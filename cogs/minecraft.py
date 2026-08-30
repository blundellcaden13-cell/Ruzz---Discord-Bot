import discord
import aiohttp
import logging
from discord.ext import commands
from discord import ApplicationContext, Option
from mcstatus import JavaServer

from utils.embeds import EmbedBuilder

logger = logging.getLogger("DevHubBot.Minecraft")


class MinecraftCog(commands.Cog, name="Minecraft"):
    """Minecraft-related utility commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


    @discord.slash_command(
        name="server-status",
        description="Get the status of a Minecraft Java server",
    )
    async def server_status(
        self, ctx: ApplicationContext,
        address: Option(str, "Server IP (e.g., play.hypixel.net)"),
    ):
        """Fetch and display detailed Minecraft server status."""
        await ctx.defer()

        try:
            server = JavaServer.lookup(address)
            status = server.status()
            
            version_name = status.version.name if status.version else "Unknown"
            protocol = status.version.protocol if status.version else 0
            
            online = status.players.online
            max_players = status.players.max
            
            player_list = ""
            if status.players.sample:
                names = [p.name for p in status.players.sample[:10]]
                player_list = ", ".join(names)
                if len(status.players.sample) > 10:
                    player_list += f" and {len(status.players.sample) - 10} more..."

            embed = discord.Embed(
                title=f"🟢 {address} is Online",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="👥 Players",
                value=f"{online:,} / {max_players:,}",
                inline=True,
            )
            embed.add_field(
                name="🔄 Version",
                value=version_name,
                inline=True,
            )
            embed.add_field(
                name="📡 Ping",
                value=f"{status.latency:.0f}ms",
                inline=True,
            )
            
            if player_list:
                embed.add_field(
                    name="🧑‍🤝‍🧑 Online Players",
                    value=player_list,
                    inline=False,
                )
                
            embed.set_footer(text="Ruzz • /server-status")
            embed.set_thumbnail(url=f"https://mcstatus.snowdev.com/api/ip/bot/icon/{address}")

            await ctx.respond(embed=embed)

        except Exception as e:
            logger.warning("Server ping failed for %s: %s", address, e)
            embed = EmbedBuilder.error(
                title=f"🔴 {address} is Offline or Unreachable",
                description="The server didn't respond. It might be offline, or the IP is incorrect.",
            )
            await ctx.respond(embed=embed)


    @discord.slash_command(
        name="skin",
        description="View a Minecraft player's skin and download it",
    )
    async def view_skin(
        self, ctx: ApplicationContext,
        username: Option(str, "Minecraft Java username"),
    ):
        """Fetch and display a player's skin with a download link."""
        await ctx.defer()

        async with aiohttp.ClientSession() as session:
            mojang_url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
            async with session.get(mojang_url) as resp:
                if resp.status != 200:
                    embed = EmbedBuilder.error(
                        description=f"Player `{username}` not found on Mojang."
                    )
                    await ctx.respond(embed=embed)
                    return
                data = await resp.json()
                uuid = data.get("id")
                actual_name = data.get("name", username)

            avatar_url = f"https://mc-heads.net/avatar/{uuid}/100"
            body_url = f"https://mc-heads.net/body/{uuid}/right"
            skin_download = f"https://mc-heads.net/skin/{uuid}"

            view = discord.ui.View(timeout=60)
            view.add_item(discord.ui.Button(
                label="Download Skin",
                emoji="⬇️",
                style=discord.ButtonStyle.link,
                url=skin_download,
            ))

            embed = discord.Embed(
                title=f"🎨 {actual_name}'s Skin",
                color=discord.Color.dark_green(),
            )
            embed.set_image(url=body_url)
            embed.set_thumbnail(url=avatar_url)
            embed.add_field(
                name="UUID",
                value=f"`{uuid}`",
                inline=False,
            )
            embed.set_footer(text="Ruzz • /skin")

            await ctx.respond(embed=embed, view=view)


    @discord.slash_command(
        name="pack-format",
        description="Look up Minecraft datapack/resource pack formats by version",
    )
    async def pack_format(
        self, ctx: ApplicationContext,
        version: Option(
            str,
            "Minecraft version (e.g., 1.20, 1.19.4)",
            required=False,
        ),
    ):
        """Display pack format IDs for datapacks and resource packs."""
        formats = [
    {"version": "26.3-snapshot-3", "data": 110, "resource": 91},
    {"version": "26.3-snapshot-2", "data": 109, "resource": 90},
    {"version": "26.3-snapshot-1", "data": 108, "resource": 89},
    {"version": "26.2", "data": 107.1, "resource": 88},
    {"version": "26.2-rc-2", "data": None, "resource": None},
    {"version": "26.2-rc-1", "data": None, "resource": None},
    {"version": "26.2-pre-6", "data": None, "resource": None},
    {"version": "26.2-pre-5", "data": None, "resource": None},
    {"version": "26.2-pre-4", "data": None, "resource": None},
    {"version": "26.2-pre-3", "data": 107.0, "resource": None},
    {"version": "26.2-pre-2", "data": None, "resource": None},
    {"version": "26.2-pre-1", "data": 106.1, "resource": None},
    {"version": "26.2-snapshot-8", "data": 106.0, "resource": 87},
    {"version": "26.2-snapshot-7", "data": None, "resource": 105.1},
    {"version": "26.2-snapshot-6", "data": 105.0, "resource": 86.2},
    {"version": "26.2-snapshot-5", "data": 104.0, "resource": None},
    {"version": "26.2-snapshot-4", "data": 103.0, "resource": 86.1},
    {"version": "26.2-snapshot-3", "data": 102.0, "resource": 86.0},
    {"version": "26.2-snapshot-2", "data": 101.2, "resource": 85.0},
    {"version": "26.2-snapshot-1", "data": None, "resource": None},
    {"version": "26.1.2", "data": 101.1, "resource": 84.0},
    {"version": "26.1.2-rc-1", "data": None, "resource": None},
    {"version": "26.1.1", "data": None, "resource": None},
    {"version": "26.1.1-rc-1", "data": None, "resource": None},
    {"version": "26.1", "data": None, "resource": None},
    {"version": "26.1-rc-3", "data": None, "resource": None},
    {"version": "26.1-rc-2", "data": None, "resource": None},
    {"version": "26.1-rc-1", "data": None, "resource": None},
    {"version": "26.1-pre-3", "data": None, "resource": None},
    {"version": "26.1-pre-2", "data": 101.0, "resource": None},
    {"version": "26.1-pre-1", "data": None, "resource": None},
    {"version": "26.1-snapshot-11", "data": 100.0, "resource": 83.0},
    {"version": "26.1-snapshot-10", "data": 99.3, "resource": 82.0},
    {"version": "26.1-snapshot-9", "data": 99.2, "resource": 81.1},
    {"version": "26.1-snapshot-8", "data": None, "resource": None},
    {"version": "26.1-snapshot-7", "data": 99.1, "resource": 81.0},
    {"version": "26.1-snapshot-6", "data": 99.0, "resource": 80.0},
    {"version": "26.1-snapshot-5", "data": 98.0, "resource": 79.0},
    {"version": "26.1-snapshot-4", "data": 97.1, "resource": 78.1},
    {"version": "26.1-snapshot-3", "data": 97.0, "resource": 78.0},
    {"version": "26.1-snapshot-2", "data": 96.0, "resource": 77.0},
    {"version": "26.1-snapshot-1", "data": 95.0, "resource": 76.0},
    {"version": "1.21.11", "data": 94.1, "resource": 75.0},
    {"version": "1.21.11-pre-3", "data": 94.0, "resource": None},
    {"version": "1.21.10", "data": 88.0, "resource": 69.0},
    {"version": "1.21.9", "data": None, "resource": None},
    {"version": "25w46a", "data": 93.1, "resource": 74.0},
    {"version": "25w45a", "data": 93.0, "resource": 73.0},
    {"version": "25w44a", "data": 92.0, "resource": 72.0},
    {"version": "25w43a", "data": 91.0, "resource": 71.0},
    {"version": "25w42a", "data": 90.0, "resource": 70.1},
    {"version": "25w41a", "data": 89.0, "resource": 70.0},
    {"version": "1.21", "data": 48, "resource": 34},
    {"version": "1.20.5 - 1.21", "data": 48, "resource": 34},
    {"version": "1.20.3 - 1.20.4", "data": 26, "resource": 32},
    {"version": "1.20.2", "data": 18, "resource": 18},
    {"version": "1.20 - 1.20.1", "data": 15, "resource": 15},
    {"version": "1.19.4", "data": 12, "resource": 13},
    {"version": "1.19.3", "data": None, "resource": 12},
    {"version": "1.19 - 1.19.2", "data": 10, "resource": 9},
    {"version": "1.18.2", "data": 9, "resource": 8},
    {"version": "1.18 - 1.18.1", "data": 8, "resource": None},
    {"version": "1.17 - 1.17.1", "data": 7, "resource": 7},
    {"version": "1.16.2 - 1.16.5", "data": 6, "resource": 6},
    {"version": "1.15 - 1.16.1", "data": 5, "resource": 5},
    {"version": "1.13 - 1.14.4", "data": 4, "resource": 4},
    {"version": "1.11 - 1.12.2", "data": None, "resource": 3},
    {"version": "1.9 - 1.10.2", "data": None, "resource": 2},
    {"version": "1.6.1 - 1.8.9", "data": None, "resource": 1},
    ]

        if version:
            match = None
            for f in formats:
                if version in f["version"]:
                    match = f
                    break

            if match:
                embed = discord.Embed(
                    title=f"📋 Pack Format: {match['version']}",
                    color=discord.Color.purple(),
                )
                embed.add_field(
                    name="📦 Datapack Format",
                    value=f"`pack_format = {match['data']}`",
                    inline=True,
                )
                embed.add_field(
                    name="🎨 Resource Pack Format",
                    value=f"`pack_format = {match['resource']}`",
                    inline=True,
                )
            else:
                embed = EmbedBuilder.warning(
                    description=f"Version `{version}` not found. Use `/pack-format` without a version to see all."
                )
            await ctx.respond(embed=embed)
            return

        embed = discord.Embed(
            title="📋 Pack Format Reference",
            description="Datapack (`D`) and Resource Pack (`R`) formats per version:",
            color=discord.Color.purple(),
        )

        lines = []
        for f in formats:
            lines.append(
                f"**{f['version']}**: D=`{f['data']}` | R=`{f['resource']}`"
            )

        embed.description += "\n\n" + "\n".join(lines)
        embed.set_footer(text="Ruzz • /pack-format")

        await ctx.respond(embed=embed)


def setup(bot: commands.Bot):
    """Load the Minecraft cog."""
    bot.add_cog(MinecraftCog(bot))