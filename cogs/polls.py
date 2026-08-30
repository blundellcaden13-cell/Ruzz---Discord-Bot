import json
import logging
import random
import traceback
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
from discord import ApplicationContext

from config import Config
from utils.embeds import EmbedBuilder
from utils.helpers import is_admin
from cogs.utils import PollView

logger = logging.getLogger("DevHubBot.Polls")

EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
POLL_COLORS = [
    discord.Color.blurple(), discord.Color.green(), discord.Color.gold(),
    discord.Color.fuchsia(), discord.Color.teal(), discord.Color.orange(),
]

DT_FORMAT = "%Y-%m-%d %H:%M:%S"


class PollsCog(commands.Cog, name="Polls"):
    """Delivers scheduled polls from the website to Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_scheduled_polls.start()

    def cog_unload(self):
        self.check_scheduled_polls.cancel()


    @discord.slash_command(
        name="poll-channel",
        description="Set the channel where scheduled polls (from the poll website) get posted (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def poll_channel(
        self, ctx: ApplicationContext,
        channel: discord.TextChannel,
    ):
        """Set the channel scheduled polls are delivered to."""
        await self.bot.db.set_config(ctx.guild_id, "POLL_CHANNEL_ID", str(channel.id))
        Config.set_override(ctx.guild_id, "POLL_CHANNEL_ID", channel.id)

        icon_url = ctx.guild.icon.url if ctx.guild.icon else None
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO guild_meta "
            "(guild_id, name, member_count, icon_url, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                ctx.guild_id, ctx.guild.name, ctx.guild.member_count or 0,
                icon_url, datetime.now(timezone.utc).isoformat(),
            ),
        )

        embed = EmbedBuilder.success(
            description=(
                f"Scheduled polls will now be posted in {channel.mention}.\n"
                f"Schedule them from the poll website (`python poll.py`)."
            )
        )
        await ctx.respond(embed=embed, ephemeral=True)


    @tasks.loop(seconds=30)
    async def check_scheduled_polls(self):
        if not self.bot.db:
            return

        now_str = datetime.now().strftime(DT_FORMAT)
        try:
            due = await self.bot.db.fetch_all(
                "SELECT id, guild_id, question, options, created_by "
                "FROM scheduled_polls "
                "WHERE status = 'pending' AND scheduled_for <= ?",
                (now_str,),
            )
        except Exception:
            logger.error("Failed to query scheduled_polls:\n%s", traceback.format_exc())
            return

        for poll_id, guild_id, question, options_json, created_by in due:
            await self._post_poll(poll_id, guild_id, question, options_json, created_by)

    @check_scheduled_polls.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _post_poll(self, poll_id, guild_id, question, options_json, created_by):
        try:
            options = json.loads(options_json)
        except (TypeError, ValueError):
            options = []

        if not options:
            logger.error("Scheduled poll #%s has no options — marking failed.", poll_id)
            await self.bot.db.execute(
                "UPDATE scheduled_polls SET status='failed' WHERE id=?", (poll_id,)
            )
            return

        channel_id = Config.get(guild_id, "POLL_CHANNEL_ID")
        channel = self.bot.get_channel(channel_id) if channel_id else None

        if not channel:
            logger.warning(
                "Scheduled poll #%s is due but no poll channel is set for guild %s "
                "(run /poll-channel in that server). Leaving it pending.",
                poll_id, guild_id,
            )
            return

        embed = discord.Embed(
            title=f"🗳️ {question}",
            description="**Vote below** — click a button to cast (or change) your vote.",
            color=random.choice(POLL_COLORS),
            timestamp=datetime.now(timezone.utc),
        )
        guild = self.bot.get_guild(guild_id)
        if guild and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        for idx, option in enumerate(options[:5]):
            embed.add_field(
                name=f"{EMOJIS[idx]}  {option}",
                value="`░░░░░░░░░░░░░░░░░░░░` 0.0% • 0 votes",
                inline=False,
            )
        footer = "Ruzz • Scheduled Poll"
        if created_by:
            footer += f" • Set up by {created_by}"
        embed.set_footer(
            text=footer,
            icon_url=self.bot.user.display_avatar.url if self.bot.user else None,
        )

        view = PollView(options)

        try:
            message = await channel.send(
                content="@everyone",
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    everyone=True, users=False, roles=False
                ),
            )
        except discord.Forbidden:
            logger.error(
                "Missing permission to post scheduled poll #%s in channel %s",
                poll_id, channel_id,
            )
            return
        except discord.HTTPException:
            logger.error(
                "Failed to post scheduled poll #%s:\n%s", poll_id, traceback.format_exc()
            )
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        await self.bot.db.execute(
            "UPDATE scheduled_polls "
            "SET status='posted', channel_id=?, message_id=?, posted_at=? "
            "WHERE id=?",
            (channel.id, message.id, now_iso, poll_id),
        )
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO polls "
            "(message_id, channel_id, creator_id, question, options, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message.id, channel.id, self.bot.user.id, question, options_json, now_iso),
        )
        logger.info(
            "Posted scheduled poll #%s ('%s') to #%s",
            poll_id, question, getattr(channel, "name", channel_id),
        )


def setup(bot: commands.Bot):
    """Load the Polls cog."""
    bot.add_cog(PollsCog(bot))
