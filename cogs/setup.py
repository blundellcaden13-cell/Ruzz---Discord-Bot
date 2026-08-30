import json
import discord
from discord.ext import commands
from discord import ApplicationContext

from config import Config
from utils.embeds import EmbedBuilder
from utils.helpers import is_admin
from utils.overview import OVERVIEW_CONFIG_KEYS, resolve_overview_value


class SetupCog(commands.Cog, name="Setup"):
    """Configuration commands for server administrators."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


    @discord.slash_command(
        name="welcome-channel",
        description="Set the channel where welcome messages are posted (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def welcome_channel(
        self, ctx: ApplicationContext,
        channel: discord.TextChannel,
    ):
        """Set the welcome channel."""
        await self.bot.db.set_config(ctx.guild_id, "WELCOME_CHANNEL_ID", str(channel.id))
        Config.set_override(ctx.guild_id, "WELCOME_CHANNEL_ID", channel.id)

        embed = EmbedBuilder.success(
            description=f"Welcome channel set to {channel.mention}"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="rules-channel",
        description="Set the rules channel (used in welcome messages) (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def rules_channel(
        self, ctx: ApplicationContext,
        channel: discord.TextChannel,
    ):
        """Set the rules channel."""
        await self.bot.db.set_config(ctx.guild_id, "RULES_CHANNEL_ID", str(channel.id))
        Config.set_override(ctx.guild_id, "RULES_CHANNEL_ID", channel.id)

        embed = EmbedBuilder.success(
            description=f"Rules channel set to {channel.mention}"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="log-channel",
        description="Set the channel for moderation logs (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def log_channel(
        self, ctx: ApplicationContext,
        channel: discord.TextChannel,
    ):
        """Set the log channel."""
        await self.bot.db.set_config(ctx.guild_id, "LOG_CHANNEL_ID", str(channel.id))
        Config.set_override(ctx.guild_id, "LOG_CHANNEL_ID", channel.id)

        embed = EmbedBuilder.success(
            description=f"Log channel set to {channel.mention}"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="ticket-category",
        description="Set the category where new ticket channels are created (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def ticket_category(
        self, ctx: ApplicationContext,
        category: discord.CategoryChannel,
    ):
        """Set the ticket creation category."""
        bot_perms = category.permissions_for(ctx.guild.me)
        if not bot_perms.manage_channels:
            embed = EmbedBuilder.error(
                description="I don't have `Manage Channels` permission in that category!"
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        await self.bot.db.set_config(ctx.guild_id, "TICKET_CATEGORY_ID", str(category.id))
        Config.set_override(ctx.guild_id, "TICKET_CATEGORY_ID", category.id)

        embed = EmbedBuilder.success(
            description=f"Ticket category set to **{category.name}**"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="ticket-transcript-channel",
        description="Set the channel where closed-ticket transcripts are posted (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def ticket_transcript_channel(
        self, ctx: ApplicationContext,
        channel: discord.TextChannel,
    ):
        """Set the ticket transcript channel."""
        await self.bot.db.set_config(
            ctx.guild_id, "TICKET_TRANSCRIPT_CHANNEL_ID", str(channel.id)
        )
        Config.set_override(ctx.guild_id, "TICKET_TRANSCRIPT_CHANNEL_ID", channel.id)

        embed = EmbedBuilder.success(
            description=f"Transcripts will be sent to {channel.mention}"
        )
        await ctx.respond(embed=embed, ephemeral=True)


    admin_role = discord.SlashCommandGroup(
        name="admin-role",
        description="Manage which roles count as bot admin (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )

    async def _get_admin_role_ids(self, guild_id: int) -> list:
        raw = await self.bot.db.get_config(guild_id, "ADMIN_ROLE_IDS")
        if raw:
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                pass
        return []

    async def _save_admin_role_ids(self, guild_id: int, role_ids: list):
        value = json.dumps(role_ids)
        await self.bot.db.set_config(guild_id, "ADMIN_ROLE_IDS", value)
        Config.set_override(guild_id, "ADMIN_ROLE_IDS", value)

    @admin_role.command(name="add", description="Add a role that counts as bot admin")
    async def admin_role_add(self, ctx: ApplicationContext, role: discord.Role):
        """Add a role to the list of roles treated as bot admins."""
        role_ids = await self._get_admin_role_ids(ctx.guild_id)
        if role.id in role_ids:
            embed = EmbedBuilder.warning(description=f"{role.mention} is already an admin role.")
            await ctx.respond(embed=embed, ephemeral=True)
            return
        role_ids.append(role.id)
        await self._save_admin_role_ids(ctx.guild_id, role_ids)
        embed = EmbedBuilder.success(
            description=f"Added {role.mention} as an admin role. ({len(role_ids)} total now)"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @admin_role.command(name="remove", description="Remove a role from counting as bot admin")
    async def admin_role_remove(self, ctx: ApplicationContext, role: discord.Role):
        """Remove a role from the admin list."""
        role_ids = await self._get_admin_role_ids(ctx.guild_id)
        if role.id not in role_ids:
            embed = EmbedBuilder.warning(description=f"{role.mention} wasn't set as an admin role.")
            await ctx.respond(embed=embed, ephemeral=True)
            return
        role_ids.remove(role.id)
        await self._save_admin_role_ids(ctx.guild_id, role_ids)
        embed = EmbedBuilder.success(description=f"Removed {role.mention} from admin roles.")
        await ctx.respond(embed=embed, ephemeral=True)

    @admin_role.command(name="list", description="See which roles currently count as bot admin")
    async def admin_role_list(self, ctx: ApplicationContext):
        """Show every role currently treated as bot admin."""
        role_ids = await self._get_admin_role_ids(ctx.guild_id)
        legacy_id = Config.get(ctx.guild_id, "ADMIN_ROLE_ID")

        lines = []
        for rid in role_ids:
            role = ctx.guild.get_role(rid)
            lines.append(f"• {role.mention if role else f'`{rid}` (role not found)'}")
        if legacy_id and legacy_id not in role_ids:
            role = ctx.guild.get_role(legacy_id)
            lines.append(f"• {role.mention if role else f'`{legacy_id}`'} *(set via the old single-role `/admin-role`)*")

        if not lines:
            lines = ["*None set — only members with the real Discord **Administrator** permission count right now.*"]

        embed = discord.Embed(
            title="🛡️ Admin Roles",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="config",
        description="See everything currently configured for this server (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def config_view(self, ctx: ApplicationContext):
        """One place to see every setting that's actually configured,
        resolved to real channel/role names — instead of hunting
        through each individual /command or the raw database."""
        guild = ctx.guild
        lines = []

        for key, label, kind in OVERVIEW_CONFIG_KEYS:
            value = Config.get(guild.id, key)
            if not value:
                continue
            resolved = resolve_overview_value(guild, kind, value)
            if resolved is not None:
                lines.append(f"**{label}:** {resolved}")

        if not lines:
            lines = ["*Nothing configured yet — run any of the setup commands "
                      "(`/admin-role add`, `/ticket-category`, `/poll-channel`, etc.) to get started.*"]

        embed = discord.Embed(
            title=f"⚙️ Configuration — {guild.name}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text="This is also written to database/DATABASE_OVERVIEW.md every 5 minutes, for all servers at once."
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="verified-role",
        description="Set the role given to members who verify (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )
    async def verified_role(
        self, ctx: ApplicationContext,
        role: discord.Role,
    ):
        """Set the verified role."""
        await self.bot.db.set_config(ctx.guild_id, "VERIFIED_ROLE_ID", str(role.id))
        Config.set_override(ctx.guild_id, "VERIFIED_ROLE_ID", role.id)

        embed = EmbedBuilder.success(
            description=f"Verified role set to {role.mention}"
        )
        await ctx.respond(embed=embed, ephemeral=True)


    setup = discord.SlashCommandGroup(
        name="setup",
        description="Additional bot settings (Admin only)",
        checks=[lambda ctx: is_admin(ctx.user)],
    )

    @setup.command(
        name="welcome-message",
        description="Set the welcome message. Use {user} and {rules_channel} as placeholders.",
    )
    async def set_welcome_message(
        self, ctx: ApplicationContext,
        message: str,
    ):
        """Set the welcome message text."""
        await self.bot.db.set_config(ctx.guild_id, "WELCOME_MESSAGE", message)
        Config.set_override(ctx.guild_id, "WELCOME_MESSAGE", message)

        rules_mention = f"<#{Config.get(ctx.guild_id, 'RULES_CHANNEL_ID')}>"
        preview = message.replace(
            "{user}", ctx.user.mention
        ).replace("{rules_channel}", rules_mention)

        embed = EmbedBuilder.success(
            description="Welcome message updated! Preview below:"
        )
        embed.add_field(
            name="Preview", value=preview, inline=False
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @setup.command(
        name="view",
        description="View the current bot configuration",
    )
    async def view_config(self, ctx: ApplicationContext):
        """Display all current configuration overrides."""
        rows = await self.bot.db.fetch_all(
            "SELECT key, value FROM config WHERE guild_id = ?", (ctx.guild_id,)
        )

        embed = EmbedBuilder.info(title="⚙️ Current Configuration")

        if not rows:
            embed.description = (
                "No custom settings found yet. Use commands like "
                "`/admin-role`, `/log-channel`, `/welcome-channel` etc. "
                "to configure the bot."
            )
        else:
            config_text = []
            for key, value in rows:
                if "CHANNEL_ID" in key:
                    config_text.append(
                        f"• `{key}`: <#{value}>"
                    )
                elif "ROLE_ID" in key:
                    config_text.append(
                        f"• `{key}`: <@&{value}>"
                    )
                elif "CATEGORY_ID" in key:
                    config_text.append(
                        f"• `{key}`: <#{value}>"
                    )
                else:
                    display_val = (
                        value[:50] + "..."
                        if len(value) > 50 else value
                    )
                    config_text.append(
                        f"• `{key}`: {display_val}"
                    )

            embed.description = "\n".join(config_text)

        await ctx.respond(embed=embed, ephemeral=True)

    @setup.command(
        name="reset",
        description="Reset a config key back to its default",
    )
    async def reset_config(
        self, ctx: ApplicationContext,
        key: str,
    ):
        """Remove a DB override to revert to default."""
        current = await self.bot.db.get_config(ctx.guild_id, key)
        if current is None:
            embed = EmbedBuilder.warning(
                description=f"Key `{key}` has no custom override."
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        await self.bot.db.delete_config(ctx.guild_id, key)
        Config.remove_override(ctx.guild_id, key)

        embed = EmbedBuilder.success(
            description=f"Key `{key}` has been reset to default."
        )
        await ctx.respond(embed=embed, ephemeral=True)


    @setup.command(
        name="automod-toggle",
        description="Enable or disable the automod system",
    )
    async def toggle_automod(
        self, ctx: ApplicationContext,
        enabled: bool,
    ):
        """Toggle automod on or off."""
        await self.bot.db.set_config(ctx.guild_id, "AUTOMOD_ENABLED", str(enabled))
        Config.set_override(ctx.guild_id, "AUTOMOD_ENABLED", enabled)

        status = "Enabled ✅" if enabled else "Disabled ❌"
        embed = EmbedBuilder.success(
            description=f"Automod has been {status}"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @setup.command(
        name="automod-add-word",
        description="Add a word to the automod banned words list",
    )
    async def add_banned_word(
        self, ctx: ApplicationContext,
        word: str,
    ):
        """Add a word to the banned list."""
        raw = await self.bot.db.get_config(ctx.guild_id, "AUTOMOD_BANNED_WORDS")
        banned_words = json.loads(raw) if raw else []

        if word.lower() in [w.lower() for w in banned_words]:
            embed = EmbedBuilder.warning(
                description=f"Word `{word}` is already banned."
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        banned_words.append(word.lower())

        await self.bot.db.set_config(
            ctx.guild_id, "AUTOMOD_BANNED_WORDS", json.dumps(banned_words)
        )
        Config.set_override(ctx.guild_id, "AUTOMOD_BANNED_WORDS", banned_words)

        embed = EmbedBuilder.success(
            description=f"Added `{word}` to banned words.\n"
            f"Total banned words: {len(banned_words)}"
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @setup.command(
        name="automod-remove-word",
        description="Remove a word from the automod banned words list",
    )
    async def remove_banned_word(
        self, ctx: ApplicationContext,
        word: str,
    ):
        """Remove a word from the banned list."""
        raw = await self.bot.db.get_config(ctx.guild_id, "AUTOMOD_BANNED_WORDS")
        banned_words = json.loads(raw) if raw else []

        if word.lower() not in [w.lower() for w in banned_words]:
            embed = EmbedBuilder.warning(
                description=f"Word `{word}` is not in the banned list."
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return

        banned_words.remove(word.lower())
        await self.bot.db.set_config(
            ctx.guild_id, "AUTOMOD_BANNED_WORDS", json.dumps(banned_words)
        )
        Config.set_override(ctx.guild_id, "AUTOMOD_BANNED_WORDS", banned_words)

        embed = EmbedBuilder.success(
            description=f"Removed `{word}` from banned words."
        )
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    """Load the Setup cog."""
    bot.add_cog(SetupCog(bot))
