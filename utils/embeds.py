import discord
from datetime import datetime, timezone


class EmbedBuilder:
    """Factory class for building consistent, beautiful embeds."""

    @staticmethod
    def _base(color: discord.Color) -> discord.Embed:
        """Create a base embed with standard footer and timestamp."""
        embed = discord.Embed(
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Ruzz")
        return embed

    @staticmethod
    def success(
        title: str = "✅ Success",
        description: str = None,
    ) -> discord.Embed:
        """Green embed for successful actions."""
        embed = EmbedBuilder._base(discord.Color.green())
        embed.title = title
        if description:
            embed.description = description
        return embed

    @staticmethod
    def error(
        title: str = "❌ Error",
        description: str = None,
    ) -> discord.Embed:
        """Red embed for errors and failures."""
        embed = EmbedBuilder._base(discord.Color.red())
        embed.title = title
        if description:
            embed.description = description
        return embed

    @staticmethod
    def info(
        title: str = "ℹ️ Info",
        description: str = None,
    ) -> discord.Embed:
        """Blue embed for informational messages."""
        embed = EmbedBuilder._base(discord.Color.blue())
        embed.title = title
        if description:
            embed.description = description
        return embed

    @staticmethod
    def warning(
        title: str = "⚠️ Warning",
        description: str = None,
    ) -> discord.Embed:
        """Orange embed for warnings."""
        embed = EmbedBuilder._base(discord.Color.orange())
        embed.title = title
        if description:
            embed.description = description
        return embed

    @staticmethod
    def loading(
        description: str = "Please wait...",
    ) -> discord.Embed:
        """Grey embed for processing states."""
        embed = EmbedBuilder._base(discord.Color.dark_grey())
        embed.title = "⏳ Processing"
        embed.description = description
        return embed