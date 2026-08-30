import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks
from discord import ApplicationContext, Option
from mcstatus import JavaServer

from utils.embeds import EmbedBuilder
from utils.helpers import is_admin

logger = logging.getLogger("DevHubBot.MCStatus")

STATUS_CHOICES = ["online", "maintenance", "offline"]
STATUS_ICONS = {"online": "🟢", "maintenance": "🟠", "offline": "🔴"}


class MCStatusCog(commands.Cog, name="MCStatus"):
    """Minecraft server status monitoring & announcements."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.refresh_mc_status.start()

    def cog_unload(self):
        self.refresh_mc_status.cancel()


    @discord.slash_command(
        name="mc-server",
        description="Set the Minecraft server this bot monitors (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def mc_server(
        self, ctx: ApplicationContext,
        address: Option(str, "Server address to ping, e.g. play.example.com:25565"),
        stats_url: Option(
            str, "RuzzStats plugin stats URL, e.g. http://1.2.3.4:8095/stats",
            required=False, default=None,
        ),
        stats_token: Option(
            str, "Token from the plugin's config.yml (if you set one)",
            required=False, default=None,
        ),
    ):
        row = await self.bot.db.fetch_one(
            "SELECT manual_status FROM mc_status WHERE guild_id = ?", (ctx.guild_id,)
        )
        manual_status = row[0] if row else "offline"

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO mc_status "
            "(guild_id, manual_status, address, stats_url, stats_token, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.guild_id, manual_status, address, stats_url, stats_token,
                datetime.now(timezone.utc).isoformat(), str(ctx.user),
            ),
        )

        desc = f"Now monitoring `{address}`."
        if stats_url:
            desc += f"\nPlugin stats: `{stats_url}`"
        embed = EmbedBuilder.success(description=desc)
        await ctx.respond(embed=embed, ephemeral=True)

        await self._refresh_one(ctx.guild_id)


    @discord.slash_command(
        name="mc-status",
        description="Set the announced Minecraft server status (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def mc_status_cmd(
        self, ctx: ApplicationContext,
        status: Option(str, "Status to announce", choices=STATUS_CHOICES),
    ):
        row = await self.bot.db.fetch_one(
            "SELECT address, stats_url, stats_token FROM mc_status WHERE guild_id = ?",
            (ctx.guild_id,),
        )
        address, stats_url, stats_token = row if row else (None, None, None)

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO mc_status "
            "(guild_id, manual_status, address, stats_url, stats_token, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.guild_id, status, address, stats_url, stats_token,
                datetime.now(timezone.utc).isoformat(), str(ctx.user),
            ),
        )

        embed = EmbedBuilder.success(
            description=f"{STATUS_ICONS[status]} Minecraft server status set to **{status}**."
        )
        if not address:
            embed.add_field(
                name="Heads up",
                value="No server address is set yet — run `/mc-server` so the "
                      "website can also verify this against a real ping.",
                inline=False,
            )
        await ctx.respond(embed=embed, ephemeral=True)

        await self._refresh_one(ctx.guild_id)


    @tasks.loop(seconds=60)
    async def refresh_mc_status(self):
        if not self.bot.db:
            return
        try:
            rows = await self.bot.db.fetch_all("SELECT guild_id FROM mc_status")
        except Exception:
            return
        for (guild_id,) in rows:
            await self._refresh_one(guild_id)

    @refresh_mc_status.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    async def _refresh_one(self, guild_id: int):
        row = await self.bot.db.fetch_one(
            "SELECT address, stats_url, stats_token FROM mc_status WHERE guild_id = ?",
            (guild_id,),
        )
        if not row or not row[0]:
            return
        address, stats_url, stats_token = row

        reachable = False
        players_online = max_players = None
        version = None

        try:
            server = JavaServer.lookup(address)
            status = await asyncio.wait_for(server.async_status(), timeout=5)
            reachable = True
            players_online = status.players.online
            max_players = status.players.max
            version = status.version.name if status.version else None
        except Exception as e:
            logger.debug("mcstatus ping failed for %s: %s", address, e)

        plugin_uptime = plugin_errors = plugin_members = None
        if stats_url:
            try:
                headers = {"X-Ruzz-Token": stats_token} if stats_token else {}
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(stats_url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            plugin_uptime = data.get("uptime_seconds")
                            plugin_errors = data.get("errors")
                            plugin_members = data.get("members")
                            if players_online is None:
                                players_online = data.get("players_online")
                                max_players = data.get("max_players")
                            reachable = True
            except Exception as e:
                logger.debug("Plugin stats fetch failed for %s: %s", stats_url, e)

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO mc_status_live "
            "(guild_id, reachable, players_online, max_players, version, "
            "plugin_uptime_seconds, plugin_errors, plugin_members, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id, int(reachable), players_online, max_players, version,
                plugin_uptime, plugin_errors, plugin_members,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def setup(bot: commands.Bot):
    """Load the MCStatus cog."""
    bot.add_cog(MCStatusCog(bot))
