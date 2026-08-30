import discord
import io
import json
import logging
from discord.ext import commands, tasks
from discord import ApplicationContext, Option
from datetime import datetime, timezone

from config import Config
from utils.embeds import EmbedBuilder
from utils.helpers import is_admin

logger = logging.getLogger("DevHubBot.Tickets")


class TicketDropdown(discord.ui.Select):
    """Dropdown menu for selecting ticket type."""

    def __init__(self, ticket_types: list):
        options = []
        for t in ticket_types:
            options.append(discord.SelectOption(
                label=t.get("label", "General"),
                value=t.get("value", "general"),
                description=t.get("description", "No description"),
                emoji=t.get("emoji", "🎫"),
            ))
        super().__init__(
            placeholder="Select a ticket type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_dropdown",
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle dropdown selection — create the ticket."""
        cog = interaction.client.get_cog("Tickets")
        if not cog:
            await interaction.response.send_message(
                "❌ Ticket system is currently unavailable.",
                ephemeral=True,
            )
            return

        selected_type = self.values[0]

        await interaction.response.edit_message(view=self.view)

        await cog.create_ticket(interaction, selected_type)


class TicketPanelView(discord.ui.View):
    """Persistent view for the ticket panel."""

    def __init__(self, ticket_types: list):
        super().__init__(timeout=None)
        self.add_item(TicketDropdown(ticket_types))


class CloseTicketButton(discord.ui.Button):
    """Button added to newly created tickets to close them."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Close Ticket",
            emoji="🔒",
            custom_id="close_ticket_btn",
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle close button press."""
        cog = interaction.client.get_cog("Tickets")
        if not cog:
            await interaction.response.send_message(
                "❌ Ticket system unavailable.", ephemeral=True,
            )
            return
        await cog.close_ticket(interaction)


class TicketCloseView(discord.ui.View):
    """Persistent view for the 'Close Ticket' button shown in every
    ticket's welcome message. Every ticket channel gets its own
    message with this button — registering this once at startup
    (see TicketCog.on_ready) makes ALL of them clickable again after
    a restart, not just ones created after the restart."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CloseTicketButton())


class CloseReasonModal(discord.ui.Modal):
    """Small popup asking for an optional close reason, shown right
    after clicking 'Confirm Close'. Recorded in the DB and shown on
    the transcript."""

    def __init__(self, channel_id: int):
        super().__init__(title="Close Ticket")
        self.channel_id = channel_id
        self.reason_input = discord.ui.InputText(
            label="Reason (optional)",
            placeholder="e.g. Resolved, Duplicate, Spam...",
            required=False,
            max_length=200,
        )
        self.add_item(self.reason_input)

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.execute_close(
                interaction, self.channel_id, reason=self.reason_input.value or None
            )


class ConfirmCloseView(discord.ui.View):
    """Confirmation modal/buttons before actually closing."""

    def __init__(self, channel_id: int):
        super().__init__(timeout=60)
        self.channel_id = channel_id

    @discord.ui.button(
        label="Confirm Close",
        style=discord.ButtonStyle.danger,
        emoji="✅",
        custom_id="confirm_close_btn",
    )
    async def confirm_close(
        self, button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        """User confirmed closure — ask for an optional reason first."""
        await interaction.response.send_modal(CloseReasonModal(self.channel_id))
        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="❌",
        custom_id="cancel_close_btn",
    )
    async def cancel_close(
        self, button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        """User cancelled closure."""
        await interaction.response.edit_message(
            content="Ticket closure cancelled.",
            view=None,
        )
        self.stop()
class TicketCog(commands.Cog, name="Tickets"):
    """Ticket system with panel creation and management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reconcile_tickets.start()
        self._panels_recreated = False

    def cog_unload(self):
        self.reconcile_tickets.cancel()

    ticket = discord.SlashCommandGroup(
        name="ticket",
        description="Ticket system management (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )

    @commands.Cog.listener()
    async def on_ready(self):
        """Two things, every startup:
        1. Register persistent views for the ticket dropdown and
           close button (see the big comment below) — this is what
           actually fixes buttons not responding after a restart,
           for every ticket that already exists, not just new ones.
        2. Delete any leftover ticket panel message (in case the bot
           didn't shut down cleanly last time) and post a fresh one,
           so its ticket-type options reflect anything changed via
           the website while the bot was offline.

        Guarded to only run once per process (on_ready can fire again
        after a reconnect, and we don't want to repost the panel every
        time that happens)."""
        if self._panels_recreated:
            return
        self._panels_recreated = True

        self.bot.add_view(TicketPanelView(Config.TICKET_TYPES))
        self.bot.add_view(TicketCloseView())

        for guild in self.bot.guilds:
            channel_id = Config.get(guild.id, "TICKET_PANEL_CHANNEL_ID")
            if not channel_id:
                continue
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            old_msg_id = Config.get(guild.id, "TICKET_PANEL_MESSAGE_ID")
            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            try:
                await self._send_ticket_panel(channel, guild.id)
                logger.info("Recreated ticket panel in #%s (%s)", channel.name, guild.name)
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to repost the ticket panel in #%s (%s)",
                    channel.name, guild.name,
                )

    async def _send_ticket_panel(self, channel: discord.TextChannel, guild_id: int) -> discord.Message:
        """Build and send the ticket panel, saving its channel/message
        ID so it can be found again (for updates or the delete+repost
        cycle on the next restart). Shared by /ticket-panel and the
        on_ready recreation logic above."""
        raw = await self.bot.db.get_config(guild_id, "TICKET_TYPES")
        ticket_types = json.loads(raw) if raw else Config.TICKET_TYPES

        title = await self.bot.db.get_config(guild_id, "TICKET_PANEL_TITLE")
        title = title or Config.TICKET_PANEL_TITLE

        desc = await self.bot.db.get_config(guild_id, "TICKET_PANEL_DESCRIPTION")
        desc = desc or Config.TICKET_PANEL_DESCRIPTION

        embed = discord.Embed(title=title, description=desc, color=discord.Color.blue())
        embed.set_footer(text="Ruzz Support")

        view = TicketPanelView(ticket_types)
        msg = await channel.send(embed=embed, view=view)

        await self.bot.db.set_config(guild_id, "TICKET_PANEL_CHANNEL_ID", str(channel.id))
        Config.set_override(guild_id, "TICKET_PANEL_CHANNEL_ID", channel.id)
        await self.bot.db.set_config(guild_id, "TICKET_PANEL_MESSAGE_ID", str(msg.id))
        Config.set_override(guild_id, "TICKET_PANEL_MESSAGE_ID", msg.id)
        return msg


    @discord.slash_command(
        name="ticket-panel",
        description="Post the ticket panel (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def create_panel(
        self, ctx: ApplicationContext,
        channel: Option(
            discord.TextChannel,
            "Channel to post the panel in (defaults to this channel)",
            required=False,
            default=None,
        ),
    ):
        """Send the ticket panel with the dropdown menu."""
        target_channel = channel or ctx.channel
        await self._send_ticket_panel(target_channel, ctx.guild_id)

        embed = EmbedBuilder.success(
            description=f"Ticket panel created in {target_channel.mention}!"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @ticket.command(
        name="add-type",
        description="Add a new ticket type to the dropdown",
    )
    async def add_type(
        self, ctx: ApplicationContext,
        label: Option(str, "Display name (max 25 chars)", max_length=25),
        value: Option(str, "Value (no spaces, max 25 chars & can be anything)", max_length=25),
        emoji: Option(str, "Emoji for the dropdown", required=True, default="🎫"),
        description: Option(str, "Short description (max 50 chars)", max_length=50, required=False, default="No description"),
    ):
        """Add a new ticket type to the system."""
        raw = await self.bot.db.get_config(ctx.guild_id, "TICKET_TYPES")
        ticket_types = json.loads(raw) if raw else Config.TICKET_TYPES

        if any(t.get("value") == value for t in ticket_types):
            embed = EmbedBuilder.warning(
                description=f"Ticket type `{value}` already exists!"
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        ticket_types.append({
            "label": label,
            "value": value,
            "emoji": emoji,
            "description": description,
        })

        await self.bot.db.set_config(
            ctx.guild_id, "TICKET_TYPES", json.dumps(ticket_types)
        )
        Config.set_override(ctx.guild_id, "TICKET_TYPES", ticket_types)

        embed = EmbedBuilder.success(
            description=f"Added ticket type: {emoji} **{label}** (`{value}`)"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @ticket.command(
        name="remove-type",
        description="Remove a ticket type from the dropdown",
    )
    async def remove_type(
        self, ctx: ApplicationContext,
        value: Option(str, "Internal value of the type to remove"),
    ):
        """Remove a ticket type from the system."""
        raw = await self.bot.db.get_config(ctx.guild_id, "TICKET_TYPES")
        ticket_types = json.loads(raw) if raw else Config.TICKET_TYPES

        original_len = len(ticket_types)
        ticket_types = [t for t in ticket_types if t.get("value") != value]

        if len(ticket_types) == original_len:
            embed = EmbedBuilder.warning(
                description=f"Ticket type `{value}` not found!"
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        await self.bot.db.set_config(
            ctx.guild_id, "TICKET_TYPES", json.dumps(ticket_types)
        )
        Config.set_override(ctx.guild_id, "TICKET_TYPES", ticket_types)

        embed = EmbedBuilder.success(
            description=f"Removed ticket type: `{value}`"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    async def create_ticket(
        self, interaction: discord.Interaction, selected_type: str
    ):
        """Create a new ticket channel."""
        existing = await self.bot.db.fetch_one(
            "SELECT channel_id FROM tickets "
            "WHERE user_id = ? AND status = 'open'",
            (interaction.user.id,),
        )
        if existing:
            channel = self.bot.get_channel(existing[0])
            if channel:
                embed = EmbedBuilder.warning(
                    description=f"You already have an open ticket: {channel.mention}"
                )
                await interaction.followup.send(
                    embed=embed, ephemeral=True
                )
                return

        cat_id = Config.get(interaction.guild_id, "TICKET_CATEGORY_ID")
        category = interaction.guild.get_channel(cat_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            embed = EmbedBuilder.error(
                description="Ticket category not configured! Use `/ticket-category`."
            )
            await interaction.followup.send(
                embed=embed, ephemeral=True
            )
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                attach_files=True, read_message_history=True,
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                manage_channels=True, read_message_history=True,
            ),
        }

        admin_role_id = Config.get(interaction.guild_id, "ADMIN_ROLE_ID")
        if admin_role_id:
            admin_role = interaction.guild.get_role(admin_role_id)
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True,
                    read_message_history=True,
                )

        channel_name = f"ticket-{interaction.user.name}"
        try:
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket for {interaction.user} | Type: {selected_type}",
            )
        except discord.Forbidden:
            embed = EmbedBuilder.error(
                description="I don't have permission to create channels!"
            )
            await interaction.followup.send(
                embed=embed, ephemeral=True
            )
            return

        await self.bot.db.execute(
            "INSERT INTO tickets (channel_id, user_id, category, status, guild_id, user_name, last_activity_at) "
            "VALUES (?, ?, ?, 'open', ?, ?, ?)",
            (
                channel.id, interaction.user.id, selected_type, interaction.guild_id,
                str(interaction.user), datetime.now(timezone.utc).isoformat(),
            ),
        )

        embed = discord.Embed(
            title=f"🎫 Ticket: {selected_type.title()}",
            description=(
                f"Welcome {interaction.user.mention}!\n\n"
                f"Please describe your issue in detail.\n"
                f"A staff member will be with you shortly."
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(
            text="Click 🔒 to close this ticket when resolved"
        )
        view = TicketCloseView()
        await channel.send(
            f"{interaction.user.mention}", embed=embed, view=view
        )

        embed = EmbedBuilder.success(
            description=f"Ticket created: {channel.mention}"
        )
        await interaction.followup.send(
            embed=embed, ephemeral=True
        )

    async def close_ticket(
        self, interaction: discord.Interaction
    ):
        """Initiate the ticket closing process with confirmation."""
        row = await self.bot.db.fetch_one(
            "SELECT user_id, status FROM tickets WHERE channel_id = ?",
            (interaction.channel_id,),
        )
        if not row or row[1] == "closed":
            await interaction.response.send_message(
                "❌ This is not an active ticket channel.",
                ephemeral=True,
            )
            return

        embed = EmbedBuilder.warning(
            description="Are you sure you want to close this ticket?"
        )
        view = ConfirmCloseView(interaction.channel_id)
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )

    async def execute_close(
        self, interaction: discord.Interaction, channel_id: int, reason: str = None
    ):
        """Actually close the ticket and generate transcript."""
        await interaction.response.edit_message(
            content="🔒 Closing ticket...", view=None
        )
        await self._close_ticket_channel(channel_id, interaction.user.id, reason=reason)

    async def _close_ticket_channel(self, channel_id: int, closer_id: int | None, reason: str = None):
        """Core close logic: mark the DB row closed, post a transcript,
        delete the channel. Shared by the confirm-close button above and
        the background reconcile loop below (which has no Discord
        interaction to work with when the website requests a close)."""
        await self.bot.db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP, "
            "closer_id = ?, close_requested = 0, close_reason = ? WHERE channel_id = ?",
            (closer_id, reason, channel_id),
        )

        channel = self.bot.get_channel(channel_id)
        if channel:
            transcript_file = await self._build_transcript_file(channel)

            tc_id = Config.get(channel.guild.id, "TICKET_TRANSCRIPT_CHANNEL_ID")
            tc = self.bot.get_channel(tc_id)
            if tc:
                embed = discord.Embed(
                    title=f"📜 Ticket Transcript: {channel.name}",
                    color=discord.Color.dark_grey(),
                )
                embed.add_field(
                    name="Closed By",
                    value=(f"<@{closer_id}>" if closer_id else "Requested from the ticket website"),
                    inline=True,
                )
                if reason:
                    embed.add_field(name="Reason", value=reason, inline=True)
                await tc.send(embed=embed, file=transcript_file)

        if channel:
            try:
                await channel.delete(reason="Ticket closed")
            except discord.Forbidden:
                logger.error(
                    "Missing permission to delete ticket channel #%s (%s) in %s — "
                    "check that Ruzz's role has Manage Channels there. The ticket "
                    "is still marked closed in the database, but the channel itself "
                    "is still sitting in Discord.",
                    channel.name, channel_id, channel.guild.name,
                )
                if tc:
                    try:
                        await tc.send(
                            f"⚠️ Closed ticket **#{channel.name}** but couldn't delete the "
                            f"channel — I'm missing **Manage Channels** permission there. "
                            f"Please delete it manually."
                        )
                    except discord.Forbidden:
                        pass

    @tasks.loop(seconds=30)
    async def reconcile_tickets(self):
        """Three jobs, all defensive:
        1. Self-heal 'phantom open tickets' — if a ticket's channel no
           longer exists (deleted outside the normal close flow, or the
           bot crashed mid-close), mark it closed instead of letting it
           show up as open forever on the website.
        2. Act on close requests from the ticket website (which has no
           Discord connection of its own to close things directly).
        3. Warn, then auto-close, tickets that have gone quiet — a
           ticket with no activity for TICKET_STALE_WARN_HOURS (default
           48) gets a heads-up ping; if there's still no reply after
           another TICKET_STALE_CLOSE_HOURS (default 24, so 72 total),
           it's auto-closed with a "closed due to inactivity" reason.
        """
        if not self.bot.db:
            return
        try:
            rows = await self.bot.db.fetch_all(
                "SELECT channel_id, guild_id, close_requested, created_at, "
                "last_activity_at, warned_stale_at FROM tickets WHERE status = 'open'"
            )
        except Exception:
            return

        now = datetime.now(timezone.utc)

        for channel_id, guild_id, close_requested, created_at, last_activity_at, warned_stale_at in rows:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                await self.bot.db.execute(
                    "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP "
                    "WHERE channel_id = ?",
                    (channel_id,),
                )
                logger.info("Reconciled phantom open ticket (channel %s no longer exists).", channel_id)
                continue

            if close_requested:
                await self._close_ticket_channel(channel_id, None, reason="Closed from the ticket website")
                logger.info("Closed ticket %s via website close request.", channel_id)
                continue

            await self._check_stale_ticket(
                channel, guild_id, created_at, last_activity_at, warned_stale_at, now
            )

    async def _check_stale_ticket(self, channel, guild_id, created_at, last_activity_at, warned_stale_at, now):
        warn_hours = Config.get(guild_id, "TICKET_STALE_WARN_HOURS") or 48
        close_hours = Config.get(guild_id, "TICKET_STALE_CLOSE_HOURS") or 24

        last_activity = last_activity_at or created_at
        if not last_activity:
            return
        try:
            last_activity_dt = datetime.fromisoformat(last_activity).replace(tzinfo=timezone.utc)
        except ValueError:
            return

        if warned_stale_at:
            try:
                warned_dt = datetime.fromisoformat(warned_stale_at).replace(tzinfo=timezone.utc)
            except ValueError:
                warned_dt = None
            if warned_dt and (now - warned_dt).total_seconds() / 3600 >= close_hours:
                await self._close_ticket_channel(
                    channel.id, None, reason="Auto-closed due to inactivity"
                )
                logger.info("Auto-closed stale ticket #%s (no reply after warning).", channel.name)
            return

        hours_inactive = (now - last_activity_dt).total_seconds() / 3600
        if hours_inactive >= warn_hours:
            try:
                await channel.send(
                    f"⏰ This ticket has been quiet for {int(hours_inactive)} hours. "
                    f"It'll be automatically closed in about {close_hours} hours if there's no reply."
                )
            except discord.Forbidden:
                pass
            await self.bot.db.execute(
                "UPDATE tickets SET warned_stale_at = ? WHERE channel_id = ?",
                (now.isoformat(), channel.id),
            )

    @reconcile_tickets.before_loop
    async def before_reconcile(self):
        await self.bot.wait_until_ready()

    async def _build_transcript_file(self, channel: discord.TextChannel) -> discord.File:
        """Render a channel's message history into a plain-text
        transcript file. Used both when a ticket closes and by the
        standalone /ticket transcript command.

        Capped at the last 2000 messages — unbounded history on a
        very active ticket channel could otherwise take a long time
        to page through (each 100 messages is a separate Discord API
        call), which would stall the close flow (and the 30-second
        reconcile loop that also calls this) for everything else."""
        transcript_lines = []
        async for msg in channel.history(limit=2000, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = msg.content or "[Embed/Attachment]"
            transcript_lines.append(f"[{timestamp}] {msg.author}: {content}")
        transcript_text = "\n".join(transcript_lines) or "(no messages)"
        return discord.File(
            io.BytesIO(transcript_text.encode("utf-8")),
            filename=f"transcript-{channel.name}.txt",
        )


    async def _get_open_ticket_or_warn(self, ctx: ApplicationContext):
        """Fetch the open ticket row for the current channel, or reply
        with an error and return None."""
        row = await self.bot.db.fetch_one(
            "SELECT user_id, status, claimed_by FROM tickets WHERE channel_id = ?",
            (ctx.channel.id,),
        )
        if not row or row[1] == "closed":
            embed = EmbedBuilder.error(description="This isn't an open ticket channel.")
            await ctx.respond(embed=embed, ephemeral=True)
            return None
        return row

    @ticket.command(name="add", description="Add a user to this ticket")
    async def ticket_add(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "User to add to this ticket"),
    ):
        """Grant a user access to the current ticket channel."""
        if not await self._get_open_ticket_or_warn(ctx):
            return
        await ctx.channel.set_permissions(
            user, view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True,
            reason=f"Added to ticket by {ctx.user}",
        )
        embed = EmbedBuilder.success(description=f"Added {user.mention} to this ticket.")
        await ctx.respond(embed=embed)

    @ticket.command(name="remove", description="Remove a user from this ticket")
    async def ticket_remove(
        self, ctx: ApplicationContext,
        user: Option(discord.Member, "User to remove from this ticket"),
    ):
        """Revoke a user's access to the current ticket channel."""
        if not await self._get_open_ticket_or_warn(ctx):
            return
        await ctx.channel.set_permissions(
            user, overwrite=None, reason=f"Removed from ticket by {ctx.user}"
        )
        embed = EmbedBuilder.success(description=f"Removed {user.mention} from this ticket.")
        await ctx.respond(embed=embed)

    @ticket.command(name="claim", description="Claim this ticket as the staff member handling it")
    async def ticket_claim(self, ctx: ApplicationContext):
        """Mark yourself as the staff member handling this ticket."""
        row = await self._get_open_ticket_or_warn(ctx)
        if not row:
            return
        _, _, claimed_by = row
        if claimed_by:
            claimer = ctx.guild.get_member(claimed_by)
            embed = EmbedBuilder.warning(
                description=f"Already claimed by {claimer.mention if claimer else claimed_by}."
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE tickets SET claimed_by = ?, claimed_by_name = ? WHERE channel_id = ?",
            (ctx.user.id, str(ctx.user), ctx.channel.id),
        )
        embed = EmbedBuilder.success(description=f"🙋 {ctx.user.mention} claimed this ticket.")
        await ctx.respond(embed=embed)

    @ticket.command(name="rename", description="Rename this ticket channel")
    async def ticket_rename(
        self, ctx: ApplicationContext,
        name: Option(str, "New channel name", max_length=90),
    ):
        """Rename the current ticket channel."""
        if not await self._get_open_ticket_or_warn(ctx):
            return
        try:
            await ctx.channel.edit(name=name, reason=f"Renamed by {ctx.user}")
        except discord.Forbidden:
            embed = EmbedBuilder.error(description="I don't have permission to rename this channel.")
            await ctx.respond(embed=embed, ephemeral=True)
            return
        embed = EmbedBuilder.success(description=f"Renamed to **{name}**.")
        await ctx.respond(embed=embed)

    @ticket.command(name="transcript", description="Generate a transcript of this ticket without closing it")
    async def ticket_transcript(self, ctx: ApplicationContext):
        """Post a transcript file of this ticket so far, without closing it."""
        if not await self._get_open_ticket_or_warn(ctx):
            return
        await ctx.defer(ephemeral=True)
        transcript_file = await self._build_transcript_file(ctx.channel)
        await ctx.followup.send(file=transcript_file, ephemeral=True)

    @ticket.command(name="settings", description="Get a link to the ticket settings website")
    async def ticket_settings(self, ctx: ApplicationContext):
        """Point admins at the ticket settings website."""
        embed = EmbedBuilder.info(
            description=(
                "Ticket types, the ticket category, staff role, and transcript "
                "channel are all managed from the ticket settings website — "
                "log in with the same admin credentials as the poll scheduler."
            )
        )
        await ctx.respond(embed=embed, ephemeral=True)

    PRIORITY_EMOJI = {"low": "🟢", "normal": "🔵", "high": "🟠", "urgent": "🔴"}

    @ticket.command(name="priority", description="Set this ticket's priority")
    async def ticket_priority(
        self, ctx: ApplicationContext,
        priority: Option(str, "Priority level", choices=["low", "normal", "high", "urgent"]),
    ):
        """Tag this ticket with a priority level, shown in the channel
        topic and reflected on the ticket website."""
        if not await self._get_open_ticket_or_warn(ctx):
            return
        await self.bot.db.execute(
            "UPDATE tickets SET priority = ? WHERE channel_id = ?", (priority, ctx.channel.id)
        )
        emoji = self.PRIORITY_EMOJI[priority]
        try:
            await ctx.channel.edit(topic=f"{emoji} Priority: {priority.title()}")
        except discord.Forbidden:
            pass
        embed = EmbedBuilder.success(description=f"{emoji} Priority set to **{priority.title()}**.")
        await ctx.respond(embed=embed)

    @ticket.command(name="stats", description="See ticket stats for this server")
    async def ticket_stats(self, ctx: ApplicationContext):
        """Quick overview: open count, closed today, and average time
        to close over the last 30 days."""
        open_row = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM tickets WHERE status = 'open' AND guild_id = ?",
            (ctx.guild_id,),
        )
        closed_today_row = await self.bot.db.fetch_one(
            "SELECT COUNT(*) FROM tickets WHERE status = 'closed' AND guild_id = ? "
            "AND closed_at >= datetime('now', '-1 day')",
            (ctx.guild_id,),
        )
        avg_row = await self.bot.db.fetch_one(
            "SELECT AVG(julianday(closed_at) - julianday(created_at)) * 24 FROM tickets "
            "WHERE status = 'closed' AND guild_id = ? AND closed_at >= datetime('now', '-30 days')",
            (ctx.guild_id,),
        )
        avg_hours = avg_row[0] if avg_row and avg_row[0] is not None else None

        embed = discord.Embed(title="🎫 Ticket Stats", color=discord.Color.blurple())
        embed.add_field(name="Open now", value=str(open_row[0] if open_row else 0), inline=True)
        embed.add_field(name="Closed today", value=str(closed_today_row[0] if closed_today_row else 0), inline=True)
        embed.add_field(
            name="Avg. time to close (30d)",
            value=f"{avg_hours:.1f}h" if avg_hours is not None else "—",
            inline=True,
        )
        await ctx.respond(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Track last activity per ticket — used by the stale-ticket
        auto-close check in reconcile_tickets below. Cheap: only does
        a DB write for messages actually posted in a channel that's a
        currently-open ticket."""
        if message.author.bot or not message.guild:
            return
        await self.bot.db.execute(
            "UPDATE tickets SET last_activity_at = ?, warned_stale_at = NULL "
            "WHERE channel_id = ? AND status = 'open'",
            (datetime.now(timezone.utc).isoformat(), message.channel.id),
        )


def setup(bot: commands.Bot):
    """Load the Tickets cog."""
    bot.add_cog(TicketCog(bot))