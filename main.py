import asyncio
import logging
import os
import signal
import sys
import traceback
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import uvicorn
from fastapi import FastAPI

from config import Config
from database.db import Database
from utils.overview import OVERVIEW_CONFIG_KEYS, resolve_overview_value

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

log_format = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

file_handler = logging.FileHandler(
    os.path.join(LOG_DIR, "bot.log"), encoding="utf-8"
)
file_handler.setFormatter(log_format)
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)
console_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

for noisy in ("discord", "aiosqlite", "uvicorn", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("DevHubBot")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True
intents.presences = True


class DevHubBot(commands.Bot):
    """Custom bot class with DB and stats tracking.

    NOTE: py-cord (unlike discord.py) does NOT call `setup_hook()`
    automatically — that hook simply does not exist in py-cord's
    Client/Bot base classes. Relying on it (as the previous version
    of this file did) means the database connection, config loading,
    and cog loading NEVER run, which is exactly why the bot used to
    sit there silently after printing the PyNaCl warning: it logged
    in, but had no cogs, no DB, and a broken/dead `on_ready` (it was
    accidentally nested one indent level too deep, inside
    `_load_all_cogs`, so it was never registered as an event handler
    at all).

    The fix: do all one-time async setup (DB connect, config load,
    cog loading) in `async_setup()`, which `main()` awaits BEFORE
    calling `bot.start()`. `on_ready` is then only responsible for
    things that require an active gateway connection: syncing slash
    commands and starting background tasks.
    """

    def __init__(self):
        super().__init__(
            command_prefix=Config.BOT_PREFIX,
            intents=intents,
            owner_id=Config.OWNER_ID,
            help_command=None,
        )
        self.db: Database = None
        self.start_time = datetime.now(timezone.utc)
        self.command_count = 0
        self.message_count = 0
        self._ready_once = False

        self.api_app = FastAPI(title="Ruzz API")
        self._setup_api()

    def _setup_api(self):
        """Set up lightweight FastAPI health check."""

        @self.api_app.get("/health")
        async def health():
            return {
                "status": "online",
                "uptime": str(datetime.now(timezone.utc) - self.start_time),
                "guilds": len(self.guilds),
                "commands": self.command_count,
            }

        @self.api_app.get("/stats")
        async def stats():
            return {
                "uptime": str(datetime.now(timezone.utc) - self.start_time),
                "guilds": len(self.guilds),
                "commands_used": self.command_count,
                "messages_seen": self.message_count,
            }


    async def async_setup(self):
        """Connect the database and load every cog.

        Must be awaited BEFORE `bot.start()`. This is safe in py-cord
        because loading extensions / registering slash commands does
        not require an active gateway connection — only sending the
        actual sync request does, which happens later in `on_ready`.
        """
        self.db = Database()
        await self.db.connect()
        await self.db.create_tables()
        logger.info("Database connected and tables created.")

        rows = await self.db.fetch_all("SELECT guild_id, key, value FROM config")
        Config.load_from_db(rows)
        logger.info("Loaded %d config overrides from DB.", len(rows))

        await self._load_all_cogs()

        logger.info("Bot setup complete. Waiting for gateway connection...")

    async def _load_all_cogs(self):
        """Load every cog from the cogs/ directory."""
        cog_dir = os.path.join(os.path.dirname(__file__), "cogs")
        if not os.path.isdir(cog_dir):
            logger.warning("No cogs directory found!")
            return

        loaded = 0
        for filename in sorted(os.listdir(cog_dir)):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_name = filename[:-3]
                try:
                    self.load_extension(f"cogs.{cog_name}")
                    loaded += 1
                    logger.info("Loaded cog: %s", cog_name)
                except Exception:
                    logger.error(
                        "Failed to load cog %s:\n%s",
                        cog_name,
                        traceback.format_exc(),
                    )
        logger.info("Loaded %d cogs total.", loaded)


    async def on_ready(self):
        """Bot is online and ready."""
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        logger.info("Guilds: %d", len(self.guilds))

        if self._ready_once:
            return
        self._ready_once = True

        try:
            await self.sync_commands()
            logger.info(
                "Synced slash commands globally (can take up to ~1 hour "
                "to appear in every server on first sync)."
            )
        except Exception:
            logger.error(
                "Failed to sync commands on ready:\n%s", traceback.format_exc()
            )

        if not self.update_presence.is_running():
            self.update_presence.start()
        if not self.sync_guild_meta.is_running():
            self.sync_guild_meta.start()

    async def on_message(self, message: discord.Message):
        """Track messages and process commands."""
        if message.author.bot or message.guild is None:
            return

        self.message_count += 1

        await self.process_commands(message)

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        """Handle prefix-command errors gracefully."""
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ This command is owner-only.")
            return
        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await ctx.send(f"❌ Missing permissions: `{perms}`")
            return
        if isinstance(error, commands.MissingRole):
            await ctx.send("❌ You don't have the required role.")
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Cooldown! Try again in {error.retry_after:.1f}s.")
            return

        logger.error("Command error in %s: %s", ctx.command, str(error))
        await ctx.send("❌ An error occurred. Staff has been notified.")

    async def on_application_command_error(
        self,
        ctx: discord.ApplicationContext,
        error: discord.DiscordException,
    ):
        """Handle slash command errors gracefully.

        py-cord's event for this is `on_application_command_error`
        (with an `ApplicationContext`), not discord.py's
        `on_app_command_error` (with a raw `Interaction`).
        """
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.respond(
                f"⏳ Cooldown! Try again in {error.retry_after:.1f}s.",
                ephemeral=True,
            )
            return
        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await ctx.respond(
                f"❌ Missing permissions: `{perms}`", ephemeral=True
            )
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.respond(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        logger.error(
            "Slash command error: %s\n%s", str(error), traceback.format_exc()
        )

        try:
            if ctx.response.is_done():
                await ctx.followup.send("❌ An error occurred.", ephemeral=True)
            else:
                await ctx.respond("❌ An error occurred.", ephemeral=True)
        except discord.HTTPException:
            pass


    @tasks.loop(minutes=5)
    async def update_presence(self):
        """Update bot rich presence with total member/server counts."""
        total_members = sum(g.member_count or 0 for g in self.guilds)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"over {total_members} developers in {len(self.guilds)} servers",
            )
        )

    @update_presence.before_loop
    async def before_presence(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=5)
    async def sync_guild_meta(self):
        """Keep guild_meta (name/member count) and the channel/role
        caches fresh so poll.py, home.py, and tickets.py — which don't
        have their own Discord connection — can show real server
        names/channels/roles instead of raw IDs."""
        if not self.db:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        for guild in self.guilds:
            icon_url = guild.icon.url if guild.icon else None
            await self.db.execute(
                "INSERT OR REPLACE INTO guild_meta "
                "(guild_id, name, member_count, icon_url, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild.id, guild.name, guild.member_count or 0, icon_url, now_iso),
            )

            for channel in guild.channels:
                if isinstance(channel, (discord.TextChannel, discord.CategoryChannel)):
                    chan_type = "category" if isinstance(channel, discord.CategoryChannel) else "text"
                    await self.db.execute(
                        "INSERT OR REPLACE INTO guild_channels "
                        "(guild_id, channel_id, name, type, position) VALUES (?, ?, ?, ?, ?)",
                        (guild.id, channel.id, channel.name, chan_type, channel.position),
                    )

            for role in guild.roles:
                if role.is_default():
                    continue
                await self.db.execute(
                    "INSERT OR REPLACE INTO guild_roles "
                    "(guild_id, role_id, name, position) VALUES (?, ?, ?, ?)",
                    (guild.id, role.id, role.name, role.position),
                )

        await self._write_database_overview()

    async def _write_database_overview(self):
        """Regenerate database/DATABASE_OVERVIEW.md — a plain-text,
        human-readable snapshot of what's configured for each server.
        This is purely a *derived* read-only export: the actual .db
        file is never touched by this, and this file is fully
        rebuilt from scratch every 5 minutes, so it's always safe to
        delete/ignore/version-control however you like."""
        lines = [
            "# Database Overview",
            "",
            "_Auto-generated by the bot every 5 minutes — read-only snapshot. "
            "The actual database file (`database/devhub.db`) is unchanged by this; "
            "this is just a human-readable view into it._",
            "",
        ]

        for guild in self.guilds:
            lines.append(f"## {guild.name}")
            lines.append(f"Guild - {guild.id}")
            lines.append(f"Members - {guild.member_count or 0}")
            lines.append(f"Roles - {len(guild.roles)}")
            lines.append(f"Channels - {len(guild.channels)}")
            lines.append(f"Categories - {len(guild.categories)}")

            for key, label, kind in OVERVIEW_CONFIG_KEYS:
                value = Config.get(guild.id, key)
                if not value:
                    continue
                resolved = resolve_overview_value(guild, kind, value)
                if resolved is not None:
                    lines.append(f"{label} - {resolved}")

            mc_row = await self.db.fetch_one(
                "SELECT manual_status, address FROM mc_status WHERE guild_id = ?", (guild.id,)
            )
            if mc_row and mc_row[1]:
                lines.append(f"Minecraft Server - {mc_row[1]} (announced: {mc_row[0]})")

            lines.append("")

        try:
            os.makedirs("database", exist_ok=True)
            with open("database/DATABASE_OVERVIEW.md", "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError:
            logger.error("Failed to write database/DATABASE_OVERVIEW.md:\n%s", traceback.format_exc())

    @sync_guild_meta.before_loop
    async def before_sync_guild_meta(self):
        await self.wait_until_ready()


    async def run_api(self):
        """Run the FastAPI server in background."""
        config = uvicorn.Config(
            app=self.api_app,
            host="0.0.0.0",
            port=8080,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await server.serve()


    async def delete_all_panels(self):
        """Best-effort: delete ticket + leaderboard panel messages
        before the bot goes offline. Combined with each cog reposting
        a fresh panel on the next startup (see their on_ready
        listeners), this guarantees panels are never left behind in a
        stale/half-working state — components on the ticket panel in
        particular need a live bot process to actually work, so a
        clean delete-then-repost cycle every restart is simpler and
        more reliable than trying to keep an old message's components
        alive across restarts."""
        if not self.db:
            return

        panel_configs = [
            ("TICKET_PANEL_CHANNEL_ID", "TICKET_PANEL_MESSAGE_ID"),
            ("LEADERBOARD_CHANNEL_ID", "LEADERBOARD_MESSAGE_ID"),
        ]
        for channel_key, message_key in panel_configs:
            try:
                rows = await self.db.get_config_all_guilds(message_key)
            except Exception:
                continue
            for guild_id, msg_id in rows:
                channel_id = Config.get(guild_id, channel_key)
                if not channel_id or not msg_id:
                    continue
                channel = self.get_channel(channel_id)
                if not channel:
                    continue
                try:
                    msg = await channel.fetch_message(int(msg_id))
                    await msg.delete()
                    logger.info(
                        "Deleted panel message %s in #%s before shutdown.",
                        message_key, channel.name,
                    )
                except (discord.NotFound, discord.Forbidden, ValueError, TypeError):
                    pass
                except Exception:
                    logger.error(
                        "Error deleting panel message on shutdown:\n%s",
                        traceback.format_exc(),
                    )


async def main():
    """Start the bot and web server concurrently."""
    if not Config.TOKEN:
        logger.error(
            "No TOKEN found in your .env file! Set TOKEN=your-bot-token and try again."
        )
        return

    bot = DevHubBot()

    try:
        await bot.async_setup()
    except Exception:
        logger.error(
            "Fatal error during bot setup — aborting startup:\n%s",
            traceback.format_exc(),
        )
        return

    api_task = asyncio.create_task(bot.run_api())
    bot_task = asyncio.create_task(bot.start(Config.TOKEN))

    def _handle_sigterm():
        logger.info("Received stop signal, shutting down...")
        api_task.cancel()
        bot_task.cancel()

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, _handle_sigterm)
    except NotImplementedError:
        pass

    try:
        await asyncio.gather(api_task, bot_task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        await bot.delete_all_panels()
        if bot.db:
            await bot.db.close()
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
