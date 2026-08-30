import discord
import logging
from discord.ext import commands
from discord import ApplicationContext, Option
from datetime import datetime, timezone, timedelta

from config import Config
from utils.embeds import EmbedBuilder
from utils.helpers import is_admin

logger = logging.getLogger("DevHubBot.Moderation")


class ModerationCog(commands.Cog, name="Moderation"):
    """Server moderation and management commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _log_action(
        self, guild: discord.Guild, action: str, moderator: discord.Member,
        target: discord.User, reason: str = "No reason provided"
    ):
        """Log a moderation action to the designated log channel."""
        log_channel_id = Config.get(guild.id, "LOG_CHANNEL_ID")
        log_channel = self.bot.get_channel(log_channel_id)

        if not log_channel or not isinstance(log_channel, discord.TextChannel):
            logger.warning("Log channel not found for action: %s", action)
            return

        embed = discord.Embed(
            title=f"🔨 {action}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Target", value=f"{target} (`{target.id}`)", inline=True)
        embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            logger.error("Missing permissions to send in log channel.")


    @discord.slash_command(
        name="ban",
        description="Ban a user from the server",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def ban(
        self, ctx: ApplicationContext,
        user: Option(discord.User, "User to ban"),
        reason: Option(str, "Reason for ban", required=False, default="No reason provided"),
        delete_days: Option(int, "Days of messages to delete (0-7)", required=False, default=1, min_value=0, max_value=7),
    ):
        """Ban a user from the server."""
        try:
            await ctx.guild.ban(
                user,
                reason=reason,
                delete_message_seconds=delete_days * 86400,
            )
            embed = EmbedBuilder.success(
                description=f"✈️ **{user}** has been banned.\n**Reason:** {reason}"
            )
            await ctx.respond(embed=embed)
            await self._log_action(ctx.guild, "Ban", ctx.user, user, reason)
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to ban that user!")
            await ctx.respond(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("Ban failed: %s", e)
            embed = EmbedBuilder.error(description="An error occurred while trying to ban.")
            await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="kick",
        description="Kick a user from the server",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def kick(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to kick"),
        reason: Option(str, "Reason for kick", required=False, default="No reason provided"),
    ):
        """Kick a user from the server."""
        try:
            await user.kick(reason=reason)
            embed = EmbedBuilder.success(
                description=f"👢 **{user}** has been kicked.\n**Reason:** {reason}"
            )
            await ctx.respond(embed=embed)
            await self._log_action(ctx.guild, "Kick", ctx.user, user, reason)
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to kick that user!")
            await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="timeout",
        description="Temporarily timeout a user",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def timeout(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to timeout"),
        duration: Option(int, "Duration in minutes", min_value=1, max_value=40320),
        reason: Option(str, "Reason for timeout", required=False, default="No reason provided"),
    ):
        """Put a user in timeout."""
        delta = timedelta(minutes=duration)
        try:
            await user.timeout(delta, reason=reason)
            embed = EmbedBuilder.success(
                description=f"⏱️ **{user}** has been timed out for **{duration}m**.\n**Reason:** {reason}"
            )
            await ctx.respond(embed=embed)
            await self._log_action(ctx.guild, "Timeout", ctx.user, user, f"{duration}m - {reason}")
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to timeout that user!")
            await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="warn",
        description="Warn a user (recorded, but doesn't trigger any automatic action)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def warn(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to warn"),
        reason: Option(str, "Reason for the warning", required=False, default="No reason provided"),
    ):
        """Log a warning against a user."""
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ctx.guild_id, user.id, ctx.user.id, reason, now_iso),
        )
        count_row = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?",
            (ctx.guild_id, user.id),
        )
        total = count_row[0] if count_row else 1

        embed = EmbedBuilder.success(
            description=f"⚠️ **{user}** has been warned. (**{total}** total warning{'s' if total != 1 else ''})\n**Reason:** {reason}"
        )
        await ctx.respond(embed=embed)
        await self._log_action(ctx.guild, "Warn", ctx.user, user, reason)

        try:
            dm_embed = EmbedBuilder.warning(
                title=f"You were warned in {ctx.guild.name}",
                description=f"**Reason:** {reason}",
            )
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @discord.slash_command(
        name="warnings",
        description="View a user's warning history",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def warnings_cmd(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to look up"),
    ):
        """List a user's warnings."""
        rows = await self.bot.db.fetch_all(
            "SELECT moderator_id, reason, created_at FROM warnings "
            "WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 15",
            (ctx.guild_id, user.id),
        )
        if not rows:
            embed = EmbedBuilder.info(description=f"**{user}** has no warnings on record.")
            await ctx.respond(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"⚠️ Warnings for {user}",
            color=discord.Color.orange(),
        )
        for moderator_id, reason, created_at in rows:
            date_str = created_at.split("T")[0] if created_at else "unknown"
            embed.add_field(
                name=date_str,
                value=f"{reason}\n*by <@{moderator_id}>*",
                inline=False,
            )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="clear-warnings",
        description="Clear all warnings for a user (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def clear_warnings(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to clear warnings for"),
    ):
        """Wipe a user's warning history."""
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (ctx.guild_id, user.id),
        )
        embed = EmbedBuilder.success(description=f"🧹 Cleared all warnings for **{user}**.")
        await ctx.respond(embed=embed, ephemeral=True)
        await self._log_action(ctx.guild, "Clear Warnings", ctx.user, user, "—")


    STRIKE_ESCALATION = [
        (3, "timeout_1h"),
        (5, "kick"),
        (7, "ban"),
    ]

    @discord.slash_command(
        name="strike",
        description="Give a user a strike — auto-escalates at 3/5/7 strikes (timeout/kick/ban)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def strike(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to strike"),
        reason: Option(str, "Reason for the strike", required=False, default="No reason provided"),
    ):
        """Log a strike against a user, auto-escalating at set thresholds."""
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.bot.db.execute(
            "INSERT INTO strikes (guild_id, user_id, moderator_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ctx.guild_id, user.id, ctx.user.id, reason, now_iso),
        )
        count_row = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM strikes WHERE guild_id = ? AND user_id = ?",
            (ctx.guild_id, user.id),
        )
        total = count_row[0] if count_row else 1

        embed = EmbedBuilder.success(
            description=f"🚨 **{user}** received a strike. (**{total}** total strike{'s' if total != 1 else ''})\n**Reason:** {reason}"
        )

        action_taken = None
        for threshold, action in self.STRIKE_ESCALATION:
            if total == threshold:
                action_taken = action
                break

        if action_taken:
            try:
                if action_taken == "timeout_1h":
                    await user.timeout(timedelta(hours=1), reason=f"Auto: reached {total} strikes")
                    embed.add_field(name="Auto-action", value="⏱️ Timed out for 1 hour (3 strikes reached)", inline=False)
                    await self._log_action(ctx.guild, "Strike Auto-Timeout", ctx.user, user, f"{total} strikes")
                elif action_taken == "kick":
                    await user.kick(reason=f"Auto: reached {total} strikes")
                    embed.add_field(name="Auto-action", value="👢 Kicked (5 strikes reached)", inline=False)
                    await self._log_action(ctx.guild, "Strike Auto-Kick", ctx.user, user, f"{total} strikes")
                elif action_taken == "ban":
                    await ctx.guild.ban(user, reason=f"Auto: reached {total} strikes")
                    embed.add_field(name="Auto-action", value="✈️ Banned (7 strikes reached)", inline=False)
                    await self._log_action(ctx.guild, "Strike Auto-Ban", ctx.user, user, f"{total} strikes")
            except discord.Forbidden:
                embed.add_field(
                    name="Auto-action failed",
                    value=f"Reached {total} strikes, but I don't have permission to apply the automatic action.",
                    inline=False,
                )

        await ctx.respond(embed=embed)
        if not action_taken:
            await self._log_action(ctx.guild, "Strike", ctx.user, user, reason)

        try:
            dm_embed = EmbedBuilder.warning(
                title=f"You received a strike in {ctx.guild.name}",
                description=f"**Reason:** {reason}\n**Total strikes:** {total}\n\n"
                            f"Strikes auto-escalate: 3 = 1h timeout, 5 = kick, 7 = ban.",
            )
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @discord.slash_command(
        name="strikes",
        description="View a user's strike history",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def strikes_cmd(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to look up"),
    ):
        """List a user's strikes."""
        rows = await self.bot.db.fetch_all(
            "SELECT moderator_id, reason, created_at FROM strikes "
            "WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 15",
            (ctx.guild_id, user.id),
        )
        if not rows:
            embed = EmbedBuilder.info(description=f"**{user}** has no strikes on record.")
            await ctx.respond(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🚨 Strikes for {user} ({len(rows)} shown)",
            description="Auto-escalation: 3 = 1h timeout, 5 = kick, 7 = ban.",
            color=discord.Color.red(),
        )
        for moderator_id, reason, created_at in rows:
            date_str = created_at.split("T")[0] if created_at else "unknown"
            embed.add_field(
                name=date_str,
                value=f"{reason}\n*by <@{moderator_id}>*",
                inline=False,
            )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="clear-strikes",
        description="Clear all strikes for a user (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def clear_strikes(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to clear strikes for"),
    ):
        """Wipe a user's strike history."""
        await self.bot.db.execute(
            "DELETE FROM strikes WHERE guild_id = ? AND user_id = ?",
            (ctx.guild_id, user.id),
        )
        embed = EmbedBuilder.success(description=f"🧹 Cleared all strikes for **{user}**.")
        await ctx.respond(embed=embed, ephemeral=True)
        await self._log_action(ctx.guild, "Clear Strikes", ctx.user, user, "—")


    @discord.slash_command(
        name="purge",
        description="Delete a number of messages from this channel",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def purge(
        self, ctx: ApplicationContext,
        amount: Option(int, "Number of messages to delete (1-100)", min_value=1, max_value=100),
    ):
        """Bulk delete messages in the current channel."""
        await ctx.defer(ephemeral=True)

        try:
            deleted = await ctx.channel.purge(limit=amount)
            embed = EmbedBuilder.success(
                description=f"🗑️ Deleted **{len(deleted)}** messages."
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
            await self._log_action(
                ctx.guild, "Purge", ctx.user, ctx.guild.me,
                f"{len(deleted)} messages in #{ctx.channel.name}"
            )
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to manage messages!")
            await ctx.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("Purge failed: %s", e)
            embed = EmbedBuilder.error(description="Failed to purge messages.")
            await ctx.followup.send(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="slowmode",
        description="Set the slowmode delay for this channel",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def slowmode(
        self, ctx: ApplicationContext,
        seconds: Option(int, "Delay in seconds (0 to disable)", min_value=0, max_value=21600),
    ):
        """Set channel slowmode."""
        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                embed = EmbedBuilder.success(description="🐢 Slowmode has been disabled.")
            else:
                embed = EmbedBuilder.success(
                    description=f"🐢 Slowmode set to **{seconds} seconds**."
                )
            await ctx.respond(embed=embed)
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to manage channels!")
            await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="lock",
        description="Lock the current channel (prevent messages)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def lock(self, ctx: ApplicationContext):
        """Lock the current channel for @everyone."""
        try:
            overwrites = ctx.channel.overwrites_for(ctx.guild.default_role)
            overwrites.send_messages = False
            await ctx.channel.set_permissions(
                ctx.guild.default_role, overwrite=overwrites
            )
            embed = EmbedBuilder.success(
                description=f"🔒 {ctx.channel.mention} has been locked."
            )
            await ctx.respond(embed=embed)
            await self._log_action(
                ctx.guild, "Lock Channel", ctx.user, ctx.guild.me,
                f"Locked #{ctx.channel.name}"
            )
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to manage channels!")
            await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="unlock",
        description="Unlock the current channel",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def unlock(self, ctx: ApplicationContext):
        """Unlock the current channel for @everyone."""
        try:
            overwrites = ctx.channel.overwrites_for(ctx.guild.default_role)
            overwrites.send_messages = None
            await ctx.channel.set_permissions(
                ctx.guild.default_role, overwrite=overwrites
            )
            embed = EmbedBuilder.success(
                description=f"🔓 {ctx.channel.mention} has been unlocked."
            )
            await ctx.respond(embed=embed)
            await self._log_action(
                ctx.guild, "Unlock Channel", ctx.user, ctx.guild.me,
                f"Unlocked #{ctx.channel.name}"
            )
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to manage channels!")
            await ctx.respond(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Automod: Filter banned words and prevent spam."""
        if message.author.bot or message.guild is None:
            return
        if is_admin(message.author):
            return

        enabled = Config.get(message.guild.id, "AUTOMOD_ENABLED", True)
        if not enabled:
            return

        import json
        raw = await self.bot.db.get_config(message.guild.id, "AUTOMOD_BANNED_WORDS")
        banned_words = json.loads(raw) if raw else Config.AUTOMOD_BANNED_WORDS

        if banned_words:
            content_lower = message.content.lower()
            for word in banned_words:
                if word in content_lower:
                    try:
                        await message.delete()
                        warn = await message.channel.send(
                            f"⚠️ {message.author.mention}, that word is not allowed here!",
                            delete_after=5,
                        )
                        await self.bot.db.execute(
                            "INSERT INTO automod_violations (user_id, guild_id, violation_type, content_snippet) "
                            "VALUES (?, ?, 'banned_word', ?)",
                            (message.author.id, message.guild.id, message.content[:100]),
                        )
                        return
                    except discord.Forbidden:
                        logger.warning("Missing permissions to delete message for automod.")
                    except Exception as e:
                        logger.error("Automod word filter error: %s", e)
                    return

        spam_threshold = Config.get(message.guild.id, "AUTOMOD_SPAM_THRESHOLD", 5)
        spam_interval = Config.get(message.guild.id, "AUTOMOD_SPAM_INTERVAL", 5)

        try:
            recent = []
            async for msg in message.channel.history(limit=spam_threshold):
                if msg.author.id == message.author.id:
                    recent.append(msg.content)

            if (
                len(recent) >= spam_threshold
                and len(set(recent)) == 1
                and recent[0] != ""
            ):
                try:
                    await message.delete()
                    await message.author.timeout(
                        timedelta(seconds=30), reason="Automod: Spam detected"
                    )
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, stop spamming! You've been timed out for 30s.",
                        delete_after=10,
                    )
                    await self.bot.db.execute(
                        "INSERT INTO automod_violations (user_id, guild_id, violation_type, content_snippet) "
                        "VALUES (?, ?, 'spam', ?)",
                        (message.author.id, message.guild.id, message.content[:50]),
                    )
                except discord.Forbidden:
                    logger.warning("Missing permissions for spam action.")
                except Exception as e:
                    logger.error("Automod spam filter error: %s", e)
        except Exception:
            pass


    @discord.slash_command(
        name="log-test",
        description="Send a test message to the log channel (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def log_test(self, ctx: ApplicationContext):
        """Test if logging is working correctly."""
        log_channel_id = Config.get(ctx.guild_id, "LOG_CHANNEL_ID")
        log_channel = self.bot.get_channel(log_channel_id)

        if not log_channel:
            embed = EmbedBuilder.error(
                description="Log channel not found! Use `/log-channel` first."
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        try:
            test_embed = EmbedBuilder.info(
                title="📢 Log Test",
                description="This is a test message to verify logging works!",
            )
            await log_channel.send(embed=test_embed)
            embed = EmbedBuilder.success(
                description=f"Test log sent to {log_channel.mention}!"
            )
            await ctx.respond(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = EmbedBuilder.error(
                description="I don't have permission to send messages in the log channel!"
            )
            await ctx.respond(embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    """Load the Moderation cog."""
    bot.add_cog(ModerationCog(bot))