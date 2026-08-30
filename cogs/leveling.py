import discord
import logging
from discord.ext import commands, tasks
from discord import ApplicationContext, Option
from datetime import datetime, timezone

from config import Config
from utils.embeds import EmbedBuilder
from utils.helpers import (
    calculate_level,
    xp_for_level,
    xp_progress,
    progress_bar,
    is_admin,
)

logger = logging.getLogger("DevHubBot.Leveling")

_xp_cooldowns = {}


class LevelingCog(commands.Cog, name="Leveling"):
    """Leveling, XP, and community ranking system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_leaderboard.start()
        self._panels_recreated = False

    def cog_unload(self):
        self.update_leaderboard.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """Same idea as the ticket panel: delete any leftover
        leaderboard message from a previous run and post a fresh one,
        so it's never left showing stale data (or missing entirely if
        it somehow got deleted while the bot was offline) after a
        restart. Guarded to only run once per process."""
        if self._panels_recreated:
            return
        self._panels_recreated = True

        for guild in self.bot.guilds:
            channel_id = Config.get(guild.id, "LEADERBOARD_CHANNEL_ID")
            if not channel_id:
                continue
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            old_msg_id = Config.get(guild.id, "LEADERBOARD_MESSAGE_ID")
            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            try:
                await self._send_leaderboard_panel(channel, guild)
                logger.info("Recreated leaderboard panel in #%s (%s)", channel.name, guild.name)
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to repost the leaderboard panel in #%s (%s)",
                    channel.name, guild.name,
                )

    async def _send_leaderboard_panel(self, channel: discord.TextChannel, guild: discord.Guild) -> discord.Message:
        """Build and send the leaderboard panel, saving its channel/
        message ID. Shared by /leaderboard-panel and the on_ready
        recreation logic above."""
        embed = await self._build_leaderboard_embed(guild)
        msg = await channel.send(embed=embed)

        await self.bot.db.set_config(guild.id, "LEADERBOARD_CHANNEL_ID", str(channel.id))
        Config.set_override(guild.id, "LEADERBOARD_CHANNEL_ID", channel.id)
        await self.bot.db.set_config(guild.id, "LEADERBOARD_MESSAGE_ID", str(msg.id))
        Config.set_override(guild.id, "LEADERBOARD_MESSAGE_ID", msg.id)
        return msg


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Award XP for messages with cooldown."""
        if message.author.bot or message.guild is None:
            return
        if len(message.content) < 3:
            return

        user_id = message.author.id
        guild_id = message.guild.id
        now = datetime.now(timezone.utc).timestamp()

        cooldown = Config.get(guild_id, "XP_COOLDOWN_SECONDS", 30)
        last_xp = _xp_cooldowns.get(user_id, 0)
        if now - last_xp < cooldown:
            return
        _xp_cooldowns[user_id] = now

        import random
        xp_min = Config.get(guild_id, "XP_PER_MESSAGE_MIN", 5)
        xp_max = Config.get(guild_id, "XP_PER_MESSAGE_MAX", 15)
        xp_add = random.randint(xp_min, xp_max)

        multiplier = Config.get(guild_id, "XP_MULTIPLIER", 1.0)
        xp_add = int(xp_add * multiplier)

        row = await self.bot.db.fetch_one(
            "SELECT xp, level FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )

        if row:
            current_xp, current_level = row
            new_xp = current_xp + xp_add
            new_level = calculate_level(new_xp)

            await self.bot.db.execute(
                "UPDATE users SET xp = ?, level = ?, messages_sent = messages_sent + 1 "
                "WHERE user_id = ? AND guild_id = ?",
                (new_xp, new_level, user_id, guild_id),
            )

            if new_level > current_level:
                await self._handle_level_up(
                    message.guild, message.author, message.channel, new_level
                )
        else:
            await self.bot.db.execute(
                "INSERT INTO users (user_id, guild_id, xp, level, messages_sent) "
                "VALUES (?, ?, ?, 1, 1)",
                (user_id, guild_id, xp_add),
            )

        self.bot.message_count += 1

    async def _handle_level_up(
        self, guild: discord.Guild, member: discord.Member,
        channel, new_level: int,
    ):
        """Handle level up announcements and role rewards. `channel`
        can be None (e.g. from an admin command with no natural
        channel to announce in) — in that case rewards still apply,
        just silently."""
        logger.info(
            "User %s leveled up to %d in guild %d",
            member.name, new_level, guild.id,
        )

        rewards = await self.bot.db.fetch_all(
            "SELECT level, role_id FROM level_rewards ORDER BY level ASC"
        )

        roles_to_add = []
        for reward_level, role_id in rewards:
            if new_level >= reward_level:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    roles_to_add.append(role)

        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Level up reward")
                if channel:
                    role_names = ", ".join(r.mention for r in roles_to_add)
                    await channel.send(
                        f"🎉 {member.mention} leveled up to **Level {new_level}**! "
                        f"New roles: {role_names}",
                        delete_after=10,
                    )
            except discord.Forbidden:
                logger.warning(
                    "Missing permissions to assign level roles to %s",
                    member.name,
                )
            return

        if channel:
            await channel.send(
                f"🎉 {member.mention} leveled up to **Level {new_level}**!",
                delete_after=10,
            )

    @discord.slash_command(
        name="rank",
        description="View your or another user's level and XP",
    )
    async def rank(
        self, ctx: ApplicationContext,
        user: Option(
            discord.Member,
            "Select a user",
            required=False,
            default=None,
        ),
    ):
        """Display a user's XP, level, and progress to next level."""
        target = user or ctx.user

        row = await self.bot.db.fetch_one(
            "SELECT xp, level, contribution_points, messages_sent "
            "FROM users WHERE user_id = ? AND guild_id = ?",
            (target.id, ctx.guild_id),
        )

        if not row:
            embed = EmbedBuilder.warning(
                description=f"{target.mention} hasn't sent any messages yet!"
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        current_xp, level, contribution_pts, messages = row
        progress = xp_progress(current_xp, level)
        next_level_xp = xp_for_level(level + 1)
        current_level_xp = xp_for_level(level)
        xp_needed = next_level_xp - current_level_xp
        xp_have = current_xp - current_level_xp

        rank_row = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM users WHERE guild_id = ? AND xp > ?",
            (ctx.guild_id, current_xp),
        )
        rank_pos = (rank_row[0] + 1) if rank_row else "?"

        embed = discord.Embed(
            color=discord.Color.dark_theme(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name=str(target),
            icon_url=target.display_avatar.url,
        )

        bar = progress_bar(progress, length=15)
        embed.description = (
            f"**Level {level}**\n"
            f"{bar} `{progress * 100:.1f}%`\n"
            f"**{xp_have:,}** / **{xp_needed:,}** XP"
        )

        embed.add_field(
            name="🏆 Rank", value=f"#{rank_pos}", inline=True
        )
        embed.add_field(
            name="💬 Messages", value=f"{messages:,}", inline=True
        )
        embed.add_field(
            name="⭐ Contribution", value=f"{contribution_pts:,}", inline=True
        )
        embed.add_field(
            name="✨ Total XP", value=f"{current_xp:,}", inline=True
        )

        embed.set_footer(text="Ruzz • /rank")

        await ctx.respond(embed=embed)


    contribution = discord.SlashCommandGroup(
        name="contribution",
        description="Manage contribution points (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )

    @contribution.command(
        name="add",
        description="Award contribution points to a user",
    )
    async def add_contribution(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "User to award"),
        points: Option(int, "Points to add", min_value=1, max_value=1000),
        reason: Option(str, "Reason for award", required=False),
    ):
        """Add contribution points to a user."""
        await self._ensure_user(user)

        await self.bot.db.execute(
            "UPDATE users SET contribution_points = contribution_points + ? "
            "WHERE user_id = ? AND guild_id = ?",
            (points, user.id, ctx.guild_id),
        )

        embed = EmbedBuilder.success(
            description=f"Added **{points}** contribution points to {user.mention}"
        )
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        await ctx.respond(embed=embed)

    @contribution.command(
        name="remove",
        description="Remove contribution points from a user",
    )
    async def remove_contribution(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "User to modify"),
        points: Option(int, "Points to remove", min_value=1, max_value=1000),
    ):
        """Remove contribution points from a user."""
        await self._ensure_user(user)

        await self.bot.db.execute(
            "UPDATE users SET contribution_points = MAX(0, contribution_points - ?) "
            "WHERE user_id = ? AND guild_id = ?",
            (points, user.id, ctx.guild_id),
        )

        embed = EmbedBuilder.success(
            description=f"Removed **{points}** contribution points from {user.mention}"
        )
        await ctx.respond(embed=embed)

    async def _ensure_user(self, member: discord.Member):
        """Make sure a user exists in the database."""
        row = await self.bot.db.fetch_one(
            "SELECT user_id FROM users WHERE user_id = ? AND guild_id = ?",
            (member.id, member.guild.id),
        )
        if not row:
            await self.bot.db.execute(
                "INSERT INTO users (user_id, guild_id) VALUES (?, ?)",
                (member.id, member.guild.id),
            )

    @discord.slash_command(
        name="leaderboard",
        description="View the server XP leaderboard",
    )
    async def leaderboard(
        self, ctx: ApplicationContext,
        page: Option(
            int, "Page number", required=False, default=1, min_value=1
        ),
    ):
        """Display the XP leaderboard with pagination."""
        per_page = 10
        offset = (page - 1) * per_page

        total_row = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM users WHERE guild_id = ? AND xp > 0",
            (ctx.guild_id,),
        )
        total_users = total_row[0] if total_row else 0
        max_pages = max(1, (total_users + per_page - 1) // per_page)

        if page > max_pages:
            embed = EmbedBuilder.warning(
                description=f"Page {page} doesn't exist. Max pages: {max_pages}"
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        rows = await self.bot.db.fetch_all(
            "SELECT user_id, xp, level, contribution_points "
            "FROM users WHERE guild_id = ? AND xp > 0 "
            "ORDER BY xp DESC LIMIT ? OFFSET ?",
            (ctx.guild_id, per_page, offset),
        )

        if not rows:
            embed = EmbedBuilder.info(
                description="No one has earned XP yet! Start chatting!"
            )
            await ctx.respond(embed=embed)
            return

        embed = discord.Embed(
            title="🏆 XP Leaderboard",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )

        leaderboard_text = []
        for idx, (uid, xp, lvl, cp) in enumerate(rows, start=offset + 1):
            medal = ""
            if idx == 1:
                medal = "🥇 "
            elif idx == 2:
                medal = "🥈 "
            elif idx == 3:
                medal = "🥉 "

            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"

            leaderboard_text.append(
                f"{medal}**#{idx}** {name}\n"
                f"   Level {lvl} • {xp:,} XP • ⭐ {cp} CP"
            )

        embed.description = "\n\n".join(leaderboard_text)
        embed.set_footer(
            text=f"Page {page}/{max_pages} • Ruzz"
        )

        await ctx.respond(embed=embed)

    @discord.slash_command(
        name="leaderboard-panel",
        description="Post an auto-updating leaderboard panel (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def create_leaderboard_panel(
        self, ctx: ApplicationContext,
        channel: Option(
            discord.TextChannel,
            "Channel to post the leaderboard in (defaults to this channel)",
            required=False,
            default=None,
        ),
    ):
        """Post the auto-updating leaderboard message."""
        target_channel = channel or ctx.channel
        await self._send_leaderboard_panel(target_channel, ctx.guild)

        embed = EmbedBuilder.success(
            description=f"Leaderboard panel created in {target_channel.mention}!"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    async def _build_leaderboard_embed(
        self, guild: discord.Guild
    ) -> discord.Embed:
        """Build the top-10 leaderboard embed."""
        rows = await self.bot.db.fetch_all(
            "SELECT user_id, xp, level, contribution_points "
            "FROM users WHERE guild_id = ? AND xp > 0 "
            "ORDER BY xp DESC LIMIT 10",
            (guild.id,),
        )

        embed = discord.Embed(
            title="🏆 Server Leaderboard",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )

        if not rows:
            embed.description = "No one has earned XP yet!"
            return embed

        leaderboard_text = []
        medals = ["🥇", "🥈", "🥉"]
        for idx, (uid, xp, lvl, cp) in enumerate(rows, start=1):
            medal = medals[idx - 1] if idx <= 3 else f"**#{idx}**"
            member = guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            leaderboard_text.append(
                f"{medal} **{name}** — Level {lvl} ({xp:,} XP)"
            )

        embed.description = "\n".join(leaderboard_text)
        embed.set_footer(text="Updates automatically • Ruzz")
        return embed

    @tasks.loop(minutes=10)
    async def update_leaderboard(self):
        """Auto-update the leaderboard panel every 10 minutes, for
        every guild that has one set up (not just one hardcoded
        server)."""
        msg_rows = await self.bot.db.get_config_all_guilds(
            "LEADERBOARD_MESSAGE_ID"
        )

        for guild_id, msg_id in msg_rows:
            ch_id = Config.get(guild_id, "LEADERBOARD_CHANNEL_ID")
            if not ch_id:
                continue

            channel = self.bot.get_channel(ch_id)
            if not channel:
                continue

            try:
                msg = await channel.fetch_message(int(msg_id))
                embed = await self._build_leaderboard_embed(channel.guild)
                await msg.edit(embed=embed)
            except discord.NotFound:
                await self.bot.db.delete_config(
                    guild_id, "LEADERBOARD_MESSAGE_ID"
                )
                Config.remove_override(guild_id, "LEADERBOARD_MESSAGE_ID")
                logger.info(
                    "Leaderboard panel deleted for guild %s, config cleared.",
                    guild_id,
                )
            except Exception:
                logger.error(
                    "Failed to update leaderboard panel for guild %s.",
                    guild_id,
                )

    @update_leaderboard.before_loop
    async def before_leaderboard(self):
        await self.bot.wait_until_ready()


    async def _get_or_create_user(self, user_id: int, guild_id: int):
        row = await self.bot.db.fetch_one(
            "SELECT xp, level FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        if row:
            return row
        await self.bot.db.execute(
            "INSERT INTO users (user_id, guild_id, xp, level) VALUES (?, ?, 0, 1)",
            (user_id, guild_id),
        )
        return (0, 1)

    @discord.slash_command(
        name="level-give",
        description="Set a user's level directly (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def level_give(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to level up"),
        level: Option(int, "Level to set them to", min_value=1),
    ):
        """Jump a user straight to a given level (sets XP to match)."""
        _, current_level = await self._get_or_create_user(user.id, ctx.guild_id)
        new_xp = xp_for_level(level)

        await self.bot.db.execute(
            "UPDATE users SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
            (new_xp, level, user.id, ctx.guild_id),
        )

        embed = EmbedBuilder.success(
            description=f"Set **{user}** to **Level {level}** ({new_xp} XP)."
        )
        await ctx.respond(embed=embed, ephemeral=True)

        if level > current_level:
            await self._handle_level_up(ctx.guild, user, ctx.channel, level)

    @discord.slash_command(
        name="level-remove",
        description="Lower a user's level directly (Admin only, doesn't remove reward roles)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def level_remove(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to level down"),
        level: Option(int, "Level to set them to", min_value=1),
    ):
        """Set a user back to a lower level. Doesn't strip any reward
        roles they've already earned — remove those manually if you
        want that too."""
        await self._get_or_create_user(user.id, ctx.guild_id)
        new_xp = xp_for_level(level)

        await self.bot.db.execute(
            "UPDATE users SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
            (new_xp, level, user.id, ctx.guild_id),
        )

        embed = EmbedBuilder.success(
            description=f"Set **{user}** to **Level {level}** ({new_xp} XP)."
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="xp-give",
        description="Add XP to a user (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def xp_give(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to give XP to"),
        amount: Option(int, "XP to add", min_value=1),
    ):
        """Add a specific amount of XP, applying level-ups (and their
        reward roles) the same way naturally-earned XP does."""
        current_xp, current_level = await self._get_or_create_user(user.id, ctx.guild_id)
        new_xp = current_xp + amount
        new_level = calculate_level(new_xp)

        await self.bot.db.execute(
            "UPDATE users SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
            (new_xp, new_level, user.id, ctx.guild_id),
        )

        embed = EmbedBuilder.success(
            description=f"Gave **{user}** {amount} XP (now {new_xp} XP, Level {new_level})."
        )
        await ctx.respond(embed=embed, ephemeral=True)

        if new_level > current_level:
            await self._handle_level_up(ctx.guild, user, ctx.channel, new_level)

    @discord.slash_command(
        name="xp-remove",
        description="Remove XP from a user (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def xp_remove(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to remove XP from"),
        amount: Option(int, "XP to remove", min_value=1),
    ):
        """Remove XP, recalculating their level to match (won't strip
        reward roles already earned — remove those manually if wanted)."""
        current_xp, _ = await self._get_or_create_user(user.id, ctx.guild_id)
        new_xp = max(0, current_xp - amount)
        new_level = calculate_level(new_xp)

        await self.bot.db.execute(
            "UPDATE users SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
            (new_xp, new_level, user.id, ctx.guild_id),
        )

        embed = EmbedBuilder.success(
            description=f"Removed {amount} XP from **{user}** (now {new_xp} XP, Level {new_level})."
        )
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    """Load the Leveling cog."""
    bot.add_cog(LevelingCog(bot))