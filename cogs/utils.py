import discord
import logging
import random
from discord.ext import commands
from discord import ApplicationContext, Option
from datetime import datetime, timezone

from config import Config
from utils.embeds import EmbedBuilder
from utils.helpers import is_admin, is_owner, format_uptime

logger = logging.getLogger("DevHubBot.Utils")


class VerifyButton(discord.ui.Button):
    """Persistent button for verifying users."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.success,
            label="I Agree - Verify Me",
            emoji="✅",
            custom_id="verify_btn",
        )

    async def callback(self, interaction: discord.Interaction):
        """Assign the verified role when clicked."""
        role_id = Config.get(interaction.guild_id, "VERIFIED_ROLE_ID")
        role = interaction.guild.get_role(role_id)

        if not role:
            await interaction.response.send_message(
                "❌ Verification role not configured.", ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                "✅ You're already verified!", ephemeral=True,
            )
            return

        try:
            await interaction.user.add_roles(role, reason="Verified via button")
            await interaction.response.send_message(
                "🎉 You've been verified! Enjoy the server.", ephemeral=True,
            )
            cog = interaction.client.get_cog("Utils")
            if cog:
                await cog.bot.db.execute(
                    "UPDATE users SET verified = 1 WHERE user_id = ?",
                    (interaction.user.id,),
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to assign that role.", ephemeral=True,
            )


class VerifyPanelView(discord.ui.View):
    """Persistent view for the verification button — registered once
    at startup so it keeps working after a restart (see UtilsCog.on_ready)."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VerifyButton())


class ReactionRoleButton(discord.ui.Button):
    """Button used for reaction roles."""

    def __init__(self, role_id: int, label: str, emoji: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji=emoji,
            custom_id=f"rr_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        """Toggle the role on/off for the user."""
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message(
                "❌ Role no longer exists.", ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Reaction role toggle")
            await interaction.response.send_message(
                f"❌ Removed {role.mention}", ephemeral=True,
            )
        else:
            await interaction.user.add_roles(role, reason="Reaction role toggle")
            await interaction.response.send_message(
                f"✅ Added {role.mention}", ephemeral=True,
            )


class PollButton(discord.ui.Button):
    """Individual vote button for a poll option."""

    def __init__(self, index: int, label: str, emoji: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label[:25],
            emoji=emoji,
            custom_id=f"poll_{index}",
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        """Register a vote."""
        view: PollView = self.view

        for idx, voters in view.votes.items():
            if interaction.user.id in voters and idx != self.index:
                voters.remove(interaction.user.id)

        if interaction.user.id in view.votes[self.index]:
            view.votes[self.index].remove(interaction.user.id)
            action = "removed your vote from"
        else:
            view.votes[self.index].add(interaction.user.id)
            action = "voted for"

        await view.update_message(interaction)
        await interaction.response.send_message(
            f"✅ You {action} **{self.label}**!",
            ephemeral=True,
        )


class PollView(discord.ui.View):
    """Voting buttons for polls."""

    def __init__(self, options: list):
        super().__init__(timeout=None)
        self.options = options
        self.votes = {i: set() for i in range(len(options))}

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        for idx, option in enumerate(options[:5]):
            self.add_item(PollButton(idx, option, emojis[idx]))

    async def update_message(self, interaction: discord.Interaction):
        """Update the poll embed with current vote counts."""
        if not interaction.message:
            return

        embed = interaction.message.embeds[0]
        embed.clear_fields()

        total_votes = sum(len(v) for v in self.votes.values())
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

        for idx, option in enumerate(self.options[:5]):
            count = len(self.votes[idx])
            percentage = (count / total_votes * 100) if total_votes > 0 else 0
            bar_len = 20
            filled = int(percentage / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)

            embed.add_field(
                name=f"{emojis[idx]}  {option}",
                value=f"`{bar}` {percentage:.1f}% • {count} vote{'s' if count != 1 else ''}",
                inline=False,
            )

        embed.set_footer(text=f"Total votes: {total_votes} • Ruzz")
        await interaction.message.edit(embed=embed)


class UtilsCog(commands.Cog, name="Utils"):
    """Utility commands, welcome system, and community tools."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._views_registered = False

    @commands.Cog.listener()
    async def on_ready(self):
        """Re-register persistent views so the verify button and every
        reaction-role button keep working after a restart — same root
        cause and fix as the ticket panel (see cogs/tickets.py for the
        longer explanation). Guarded to only run once per process."""
        if self._views_registered:
            return
        self._views_registered = True

        self.bot.add_view(VerifyPanelView())

        try:
            rows = await self.bot.db.fetch_all(
                "SELECT message_id, role_id, emoji FROM reaction_roles"
            )
        except Exception:
            rows = []
        for message_id, role_id, emoji in rows:
            view = discord.ui.View(timeout=None)
            view.add_item(ReactionRoleButton(role_id, "Role", emoji))
            self.bot.add_view(view, message_id=message_id)

        if rows:
            logger.info("Re-registered %d reaction role button(s) after restart.", len(rows))


    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Send welcome message and DM when a member joins (works for
        any guild the bot is in, not just one hardcoded server)."""
        guild_id = member.guild.id

        welcome_ch_id = Config.get(guild_id, "WELCOME_CHANNEL_ID")
        welcome_ch = self.bot.get_channel(welcome_ch_id)

        if welcome_ch and isinstance(welcome_ch, discord.TextChannel):
            template = Config.get(guild_id, "WELCOME_MESSAGE")
            rules_mention = f"<#{Config.get(guild_id, 'RULES_CHANNEL_ID')}>"

            msg_text = template.replace(
                "{user}", member.mention
            ).replace("{rules_channel}", rules_mention)

            embed = discord.Embed(
                description=msg_text,
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(
                name=str(member),
                icon_url=member.display_avatar.url,
            )
            embed.set_footer(text=f"Member #{member.guild.member_count}")

            try:
                await welcome_ch.send(embed=embed)
            except discord.Forbidden:
                logger.error("Missing permissions to send welcome message.")

        dm_enabled = Config.get(guild_id, "WELCOME_DM_ENABLED", True)
        if dm_enabled:
            dm_template = Config.get(guild_id, "WELCOME_DM_MESSAGE")
            dm_text = dm_template.replace("{user}", member.name)

            view = discord.ui.View(timeout=None)
            view.add_item(VerifyButton())

            dm_embed = discord.Embed(
                description=dm_text,
                color=discord.Color.blue(),
            )
            try:
                await member.send(embed=dm_embed, view=view)
            except discord.Forbidden:
                logger.info(
                    "Could not send welcome DM to %s (DMs disabled).",
                    member.name,
                )

        await self._ensure_user_db(member)

    async def _ensure_user_db(self, member: discord.Member):
        """Make sure a user exists in the leveling database."""
        row = await self.bot.db.fetch_one(
            "SELECT user_id FROM users WHERE user_id = ? AND guild_id = ?",
            (member.id, member.guild.id),
        )
        if not row:
            await self.bot.db.execute(
                "INSERT INTO users (user_id, guild_id, joined_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (member.id, member.guild.id),
            )


    @discord.slash_command(
        name="verify-panel",
        description="Create a rules verification button panel (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def verify_panel(self, ctx: ApplicationContext):
        """Post the verification panel in the current channel."""
        embed = discord.Embed(
            title="✅ Server Verification",
            description=(
                "Please read the rules carefully.\n"
                "Once you understand and agree to them, click the button below "
                "to verify and gain access to the rest of the server."
            ),
            color=discord.Color.gold(),
        )
        view = VerifyPanelView()

        await ctx.channel.send(embed=embed, view=view)
        embed = EmbedBuilder.success(description="Verification panel created!")
        await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="reaction-role",
        description="Set up a reaction role panel (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def reaction_role(
        self, ctx: ApplicationContext,
        role: Option(discord.Role, "Role to assign"),
        label: Option(str, "Button label", required=False, default=""),
        emoji: Option(str, "Button emoji", required=False, default="🔘"),
    ):
        """Create a reaction role button panel."""
        if not label:
            label = role.name

        embed = discord.Embed(
            title="🎨 Role Selection",
            description="Click the button below to toggle this role!",
            color=discord.Color.blue(),
        )

        view = discord.ui.View(timeout=None)
        view.add_item(ReactionRoleButton(role.id, label, emoji))

        msg = await ctx.channel.send(embed=embed, view=view)

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO reaction_roles (message_id, channel_id, emoji, role_id) "
            "VALUES (?, ?, ?, ?)",
            (msg.id, ctx.channel.id, emoji, role.id),
        )

        embed = EmbedBuilder.success(description="Reaction role panel created!")
        await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="poll",
        description="Create an interactive poll",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def poll(
        self, ctx: ApplicationContext,
        question: Option(str, "The poll question"),
        option1: Option(str, "Option 1"),
        option2: Option(str, "Option 2"),
        option3: Option(str, "Option 3", required=False),
        option4: Option(str, "Option 4", required=False),
        option5: Option(str, "Option 5", required=False),
    ):
        """Create an interactive poll with buttons."""
        options = [o for o in [option1, option2, option3, option4, option5] if o]

        embed = discord.Embed(
            title=f"📊 {question}",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name=f"Poll by {ctx.user}",
            icon_url=ctx.user.display_avatar.url,
        )

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        for idx, option in enumerate(options):
            embed.add_field(
                name=f"{emojis[idx]} {option}",
                value="`░░░░░░░░░░░░░░░░░░░░` 0.0% (0 votes)",
                inline=False,
            )
        embed.set_footer(text="Total votes: 0 • Ruzz")

        view = PollView(options)
        await ctx.respond(embed=embed, view=view)

    @discord.slash_command(
        name="embed-builder",
        description="Build a custom embed message (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def embed_builder(
        self, ctx: ApplicationContext,
        title: Option(str, "Embed title", required=False),
        description: Option(str, "Embed description", required=False),
        color: Option(str, "Hex color (e.g. #FF0000)", required=False, default="#2F3136"),
        image_url: Option(str, "Image URL", required=False),
        thumbnail_url: Option(str, "Thumbnail URL", required=False),
    ):
        """Create a custom embed and send it to the channel."""
        if not title and not description:
            embed = EmbedBuilder.error(
                description="You must provide at least a title or description!"
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        try:
            clean_color = color.strip("#")
            embed_color = discord.Color(int(clean_color, 16))
        except ValueError:
            embed_color = discord.Color.dark_theme()

        custom_embed = discord.Embed(
            title=title,
            description=description,
            color=embed_color,
            timestamp=datetime.now(timezone.utc),
        )
        if image_url:
            custom_embed.set_image(url=image_url)
        if thumbnail_url:
            custom_embed.set_thumbnail(url=thumbnail_url)

        await ctx.channel.send(embed=custom_embed)
        embed = EmbedBuilder.success(description="Custom embed sent!")
        await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="userinfo",
        description="Get information about a user",
    )
    async def userinfo(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "Target user", required=False, default=None),
    ):
        """Display information about a server member."""
        target = user or ctx.user

        row = await self.bot.db.fetch_one(
            "SELECT level, xp, contribution_points, messages_sent, verified, joined_at "
            "FROM users WHERE user_id = ? AND guild_id = ?",
            (target.id, ctx.guild_id),
        )

        embed = discord.Embed(
            color=target.color if target.color.value != 0 else discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name=f"{target} ({target.id})",
            icon_url=target.display_avatar.url,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name="📅 Account Created",
            value=f"<t:{int(target.created_at.timestamp())}:R>",
            inline=True,
        )
        embed.add_field(
            name="📥 Joined Server",
            value=f"<t:{int(target.joined_at.timestamp())}:R>",
            inline=True,
        )

        roles = [r.mention for r in target.roles[1:]]
        if roles:
            embed.add_field(
                name=f"🏷️ Roles ({len(roles)})",
                value=" ".join(roles[:10]) + ("..." if len(roles) > 10 else ""),
                inline=False,
            )

        if row:
            level, xp, cp, msgs, verified, joined_db = row
            embed.add_field(name="📈 Level", value=str(level), inline=True)
            embed.add_field(name="✨ Total XP", value=f"{xp:,}", inline=True)
            embed.add_field(name="⭐ Contribution", value=str(cp), inline=True)
        else:
            embed.add_field(name="📈 Level", value="N/A", inline=True)

        embed.set_footer(text=f"ID: {target.id} • Ruzz")
        await ctx.respond(embed=embed)


    @discord.slash_command(
        name="botstats",
        description="View bot statistics and info",
    )
    async def botstats(self, ctx: ApplicationContext):
        """Display bot uptime, usage stats, and system info."""
        uptime = format_uptime(self.bot.start_time)

        db_count = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM users WHERE guild_id = ?",
            (ctx.guild_id,),
        )
        total_users = db_count[0] if db_count else 0

        ticket_count = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM tickets WHERE status = 'open'"
        )
        open_tickets = ticket_count[0] if ticket_count else 0

        embed = discord.Embed(
            title="🤖 Ruzz Stats",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(name="⏱️ Uptime", value=uptime, inline=True)
        embed.add_field(name="🏠 Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="👥 DB Users", value=str(total_users), inline=True)
        embed.add_field(
            name="💬 Commands Used", value=str(self.bot.command_count), inline=True
        )
        embed.add_field(
            name="📨 Messages Seen", value=str(self.bot.message_count), inline=True
        )
        embed.add_field(name="🎫 Open Tickets", value=str(open_tickets), inline=True)
        embed.add_field(
            name="🧩 Cogs Loaded", value=str(len(self.bot.cogs)), inline=True
        )

        latency = round(self.bot.latency * 1000)
        embed.add_field(name="📡 API Latency", value=f"{latency}ms", inline=True)

        embed.set_footer(text="Ruzz • /botstats")
        await ctx.respond(embed=embed)


    @discord.slash_command(
        name="help",
        description="View available commands based on your role",
    )
    async def help_command(self, ctx: ApplicationContext):
        """Display commands available to the user based on their roles."""
        embed = discord.Embed(
            title="📖 Ruzz - Help",
            description="Here are the commands available to you:",
            color=discord.Color.blue(),
        )

        public_cmds = [
            ("/rank", "View your level and XP"),
            ("/leaderboard", "View the server leaderboard"),
            ("/server-status", "Check a Minecraft server"),
            ("/skin", "View a Minecraft player's skin"),
            ("/pack-format", "Look up datapack formats"),
            ("/userinfo", "Get info about a user"),
            ("/botstats", "View bot statistics"),
            ("/help", "Show this help message"),
        ]
        embed.add_field(
            name="🌐 Public Commands",
            value="\n".join(f"`{cmd}` — {desc}" for cmd, desc in public_cmds),
            inline=False,
        )

        if is_admin(ctx.user):
            admin_cmds = [
                ("/ticket-panel [channel]", "Post the ticket panel"),
                ("/ticket add-type", "Add ticket type"),
                ("/ticket remove-type", "Remove ticket type"),
                ("/leaderboard-panel [channel]", "Post auto-updating leaderboard"),
                ("/contribution add", "Award contribution points"),
                ("/reaction-role", "Set up role buttons"),
                ("/poll", "Create interactive poll"),
                ("/embed-builder", "Build custom embeds"),
                ("/verify-panel", "Create verify button"),
                ("/ban, /kick, /timeout", "Moderation tools"),
                ("/purge, /slowmode", "Channel management"),
                ("/lock, /unlock", "Lock/unlock channels"),
                ("/log-test", "Test log channel"),
                ("/welcome-channel, /rules-channel", "Set welcome/rules channels"),
                ("/log-channel", "Set the mod-log channel"),
                ("/ticket-category", "Set where ticket channels are created"),
                ("/ticket-transcript-channel", "Set where transcripts are posted"),
                ("/admin-role, /verified-role", "Set the admin/verified roles"),
                ("/setup ...", "Welcome message, automod, view/reset config"),
            ]
            embed.add_field(
                name="🛡️ Admin Commands",
                value="\n".join(f"`{cmd}` — {desc}" for cmd, desc in admin_cmds),
                inline=False,
            )

        if is_owner(ctx.user.id):
            owner_cmds = [
                ("/restart", "Restart the bot process"),
                ("/backup", "Force a database backup"),
            ]
            embed.add_field(
                name="👑 Owner Commands",
                value="\n".join(f"`{cmd}` — {desc}" for cmd, desc in owner_cmds),
                inline=False,
            )

        embed.set_footer(text="Ruzz • /help")
        await ctx.respond(embed=embed, ephemeral=True)


    @discord.slash_command(
        name="restart",
        description="Restart the bot process (Owner only)",
        checks=[lambda ctx: is_owner(ctx.user.id)],
    )
    async def restart(self, ctx: ApplicationContext):
        """Gracefully shut down and restart the bot."""
        embed = EmbedBuilder.warning(
            description="🔄 Bot is restarting... This may take a moment."
        )
        await ctx.respond(embed=embed)

        logger.info("Restart initiated by owner (ID: %s)", ctx.user.id)

        if self.bot.db:
            await self.bot.db.close()

        await self.bot.close()


def setup(bot: commands.Bot):
    """Load the Utils cog."""
    bot.add_cog(UtilsCog(bot))
