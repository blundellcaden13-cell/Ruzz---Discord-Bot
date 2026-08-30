import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import ApplicationContext, Option

from config import Config
from utils.embeds import EmbedBuilder
from utils.helpers import is_admin

logger = logging.getLogger("DevHubBot.Invites")

TIERS = [
    (3, "INVITE_BASIC_ROLE_ID", "Basic Inviter", 0, "Access to the exclusive chat"),
    (5, "INVITE_COPPER_ROLE_ID", "Copper Inviter", 1, "Access to the exclusive chat + 1 Diamond Block"),
    (10, "INVITE_IRON_ROLE_ID", "Iron Inviter", 3, "Access to the exclusive chat + 3 Diamond Blocks"),
    (25, "INVITE_GOLD_ROLE_ID", "Gold Inviter", 5, "Access to the exclusive chat + 5 Diamond Blocks"),
    (50, "INVITE_VIP_ROLE_ID", "VIP", 0, "A VIP Perk + the VIP role"),
]


class InvitesCog(commands.Cog, name="Invites"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}


    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._refresh_cache(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._refresh_cache(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    async def _refresh_cache(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites}
        except discord.Forbidden:
            logger.warning(
                "Missing 'Manage Server' permission in %s — can't track invites there.",
                guild.name,
            )


    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        inviter = await self._find_inviter(guild)
        await self._refresh_cache(guild)

        now_iso = datetime.now(timezone.utc).isoformat()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO invite_joins (guild_id, member_id, inviter_id, invite_code, joined_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild.id, member.id, inviter.id if inviter else None, None, now_iso),
        )

        if inviter is None or inviter.bot:
            return

        await self._add_invite(guild, inviter, delta=1)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        row = await self.bot.db.fetch_one(
            "SELECT inviter_id FROM invite_joins WHERE guild_id = ? AND member_id = ?",
            (guild.id, member.id),
        )
        await self.bot.db.execute(
            "DELETE FROM invite_joins WHERE guild_id = ? AND member_id = ?",
            (guild.id, member.id),
        )
        if not row or not row[0]:
            return
        inviter = guild.get_member(row[0])
        if inviter:
            await self._add_invite(guild, inviter, delta=-1, announce=False)
        else:
            await self.bot.db.execute(
                "UPDATE invite_counts SET invite_count = MAX(0, invite_count - 1) "
                "WHERE guild_id = ? AND user_id = ?",
                (guild.id, row[0]),
            )

    async def _find_inviter(self, guild: discord.Guild) -> discord.Member | None:
        """Diff current invite uses against the cached snapshot to find
        which invite just got used, and by whom it was created."""
        before = self.invite_cache.get(guild.id, {})
        try:
            after = await guild.invites()
        except discord.Forbidden:
            return None

        for inv in after:
            if inv.uses and inv.uses > before.get(inv.code, 0):
                return inv.inviter
        return None


    async def _add_invite(self, guild: discord.Guild, member: discord.Member, delta: int, announce: bool = True):
        row = await self.bot.db.fetch_one(
            "SELECT invite_count, highest_tier FROM invite_counts WHERE guild_id = ? AND user_id = ?",
            (guild.id, member.id),
        )
        current, highest_tier = row if row else (0, 0)
        new_count = max(0, current + delta)

        await self.bot.db.execute(
            "INSERT INTO invite_counts (guild_id, user_id, username, invite_count, highest_tier, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "username=excluded.username, invite_count=excluded.invite_count, updated_at=excluded.updated_at",
            (guild.id, member.id, str(member), new_count, highest_tier, datetime.now(timezone.utc).isoformat()),
        )

        if announce and delta > 0:
            await self._check_tiers(guild, member, new_count, highest_tier)

    async def _check_tiers(self, guild: discord.Guild, member: discord.Member, count: int, highest_tier: int):
        """Grant every tier the member has now reached that they weren't
        already credited for, lowest to highest (in case of a big jump)."""
        newly_reached = [t for t in TIERS if t[0] > highest_tier and count >= t[0]]
        if not newly_reached:
            return

        new_highest = max(t[0] for t in newly_reached)
        await self.bot.db.execute(
            "UPDATE invite_counts SET highest_tier = ? WHERE guild_id = ? AND user_id = ?",
            (new_highest, guild.id, member.id),
        )

        exclusive_channel_id = Config.get(guild.id, "INVITE_EXCLUSIVE_CHANNEL_ID")
        exclusive_channel = guild.get_channel(exclusive_channel_id) if exclusive_channel_id else None

        for threshold, role_key, label, blocks, blurb in newly_reached:
            role_id = Config.get(guild.id, role_key)
            role = guild.get_role(role_id) if role_id else None
            if role:
                try:
                    await member.add_roles(role, reason=f"Reached {threshold} invites")
                except discord.Forbidden:
                    logger.warning("Missing permission to grant %s to %s", label, member)

            if exclusive_channel:
                try:
                    await exclusive_channel.set_permissions(
                        member, read_messages=True, send_messages=True,
                        reason="Invite reward — exclusive chat access",
                    )
                except discord.Forbidden:
                    logger.warning("Missing permission to update exclusive chat access for %s", member)

            await self._announce_reward(guild, member, threshold, label, blocks, blurb)

    async def _announce_reward(self, guild, member, threshold, label, blocks, blurb):
        embed = discord.Embed(
            title=f"🎉 {member.display_name} just hit {threshold} invites!",
            description=f"**{label}** — {blurb}",
            color=discord.Color.gold(),
        )
        if blocks:
            embed.add_field(
                name="Diamond Blocks owed",
                value=f"{blocks} — an admin will hand these out in-game.",
                inline=False,
            )

        rewards_channel_id = Config.get(guild.id, "INVITE_REWARDS_CHANNEL_ID")
        rewards_channel = guild.get_channel(rewards_channel_id) if rewards_channel_id else None
        if rewards_channel:
            try:
                await rewards_channel.send(content=member.mention, embed=embed)
            except discord.Forbidden:
                pass

        try:
            await member.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass


    async def _set_role_config(self, ctx: ApplicationContext, key: str, role: discord.Role, label: str):
        await self.bot.db.set_config(ctx.guild_id, key, str(role.id))
        Config.set_override(ctx.guild_id, key, role.id)
        embed = EmbedBuilder.success(description=f"{label} set to {role.mention}.")
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="basic-role", description="Set the role given at 3 invites (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def basic_role(self, ctx: ApplicationContext, role: Option(discord.Role, "Basic Inviter role")):
        await self._set_role_config(ctx, "INVITE_BASIC_ROLE_ID", role, "Basic Inviter role (3 invites)")

    @discord.slash_command(name="copper-role", description="Set the role given at 5 invites (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def copper_role(self, ctx: ApplicationContext, role: Option(discord.Role, "Copper Inviter role")):
        await self._set_role_config(ctx, "INVITE_COPPER_ROLE_ID", role, "Copper Inviter role (5 invites)")

    @discord.slash_command(name="iron-role", description="Set the role given at 10 invites (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def iron_role(self, ctx: ApplicationContext, role: Option(discord.Role, "Iron Inviter role")):
        await self._set_role_config(ctx, "INVITE_IRON_ROLE_ID", role, "Iron Inviter role (10 invites)")

    @discord.slash_command(name="gold-role", description="Set the role given at 25 invites (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def gold_role(self, ctx: ApplicationContext, role: Option(discord.Role, "Gold Inviter role")):
        await self._set_role_config(ctx, "INVITE_GOLD_ROLE_ID", role, "Gold Inviter role (25 invites)")

    @discord.slash_command(name="vip", description="Set the VIP role given at 50 invites (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def vip(self, ctx: ApplicationContext, role: Option(discord.Role, "VIP role")):
        await self._set_role_config(ctx, "INVITE_VIP_ROLE_ID", role, "VIP role (50 invites)")

    @discord.slash_command(name="invite-chat", description="Set the exclusive chat channel granted to inviters (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def invite_chat(self, ctx: ApplicationContext, channel: Option(discord.TextChannel, "Exclusive chat channel")):
        await self.bot.db.set_config(ctx.guild_id, "INVITE_EXCLUSIVE_CHANNEL_ID", str(channel.id))
        Config.set_override(ctx.guild_id, "INVITE_EXCLUSIVE_CHANNEL_ID", channel.id)
        embed = EmbedBuilder.success(description=f"Exclusive chat set to {channel.mention}.")
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="invite-rewards-channel", description="Set where invite-reward announcements post (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def invite_rewards_channel(self, ctx: ApplicationContext, channel: Option(discord.TextChannel, "Announcement channel")):
        await self.bot.db.set_config(ctx.guild_id, "INVITE_REWARDS_CHANNEL_ID", str(channel.id))
        Config.set_override(ctx.guild_id, "INVITE_REWARDS_CHANNEL_ID", channel.id)
        embed = EmbedBuilder.success(description=f"Invite rewards will be announced in {channel.mention}.")
        await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(name="invites", description="Check invite count and reward progress")
    async def invites_cmd(self, ctx: ApplicationContext, user: Option(discord.Member, "Member to check", required=False, default=None)):
        target = user or ctx.user
        row = await self.bot.db.fetch_one(
            "SELECT invite_count, highest_tier FROM invite_counts WHERE guild_id = ? AND user_id = ?",
            (ctx.guild_id, target.id),
        )
        count, highest_tier = row if row else (0, 0)

        next_tier = next((t for t in TIERS if t[0] > highest_tier), None)
        embed = discord.Embed(title=f"📨 {target.display_name}'s Invites", color=discord.Color.blurple())
        embed.add_field(name="Total invites", value=str(count), inline=True)
        current_label = next((t[2] for t in reversed(TIERS) if t[0] == highest_tier), "None yet")
        embed.add_field(name="Current tier", value=current_label, inline=True)
        if next_tier:
            remaining = max(0, next_tier[0] - count)
            embed.add_field(
                name="Next reward",
                value=f"**{next_tier[2]}** at {next_tier[0]} invites ({remaining} more to go) — {next_tier[4]}",
                inline=False,
            )
        else:
            embed.add_field(name="Next reward", value="You've hit every tier — nice work! 🏆", inline=False)
        await ctx.respond(embed=embed)

    @discord.slash_command(name="invite-leaderboard", description="See the top inviters in this server")
    async def invite_leaderboard(self, ctx: ApplicationContext):
        rows = await self.bot.db.fetch_all(
            "SELECT user_id, username, invite_count FROM invite_counts "
            "WHERE guild_id = ? ORDER BY invite_count DESC LIMIT 10",
            (ctx.guild_id,),
        )
        if not rows:
            embed = EmbedBuilder.info(description="No invites tracked yet.")
            await ctx.respond(embed=embed)
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, username, count) in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{prefix} <@{user_id}> — **{count}** invite{'s' if count != 1 else ''}")

        embed = discord.Embed(
            title="🏆 Invite Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await ctx.respond(embed=embed)


    @discord.slash_command(name="set-invites", description="Manually set a member's invite count (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def set_invites(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Member to update"),
        count: Option(int, "New invite count", min_value=0),
    ):
        row = await self.bot.db.fetch_one(
            "SELECT highest_tier FROM invite_counts WHERE guild_id = ? AND user_id = ?",
            (ctx.guild_id, user.id),
        )
        highest_tier = row[0] if row else 0
        await self.bot.db.execute(
            "INSERT INTO invite_counts (guild_id, user_id, username, invite_count, highest_tier, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "username=excluded.username, invite_count=excluded.invite_count, updated_at=excluded.updated_at",
            (ctx.guild_id, user.id, str(user), count, highest_tier, datetime.now(timezone.utc).isoformat()),
        )
        await self._check_tiers(ctx.guild, user, count, highest_tier)
        embed = EmbedBuilder.success(description=f"Set **{user}**'s invite count to **{count}** (tiers re-checked, roles/rewards applied if newly earned).")
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="sync-invites", description="Re-read current invite link uses from Discord (Admin only)", checks=[lambda ctx: is_admin(ctx.user)])
    async def sync_invites(self, ctx: ApplicationContext):
        await self._refresh_cache(ctx.guild)
        embed = EmbedBuilder.success(description="Invite cache refreshed from Discord.")
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(InvitesCog(bot))
