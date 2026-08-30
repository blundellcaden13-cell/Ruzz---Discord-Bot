import json
import math
import discord
from datetime import datetime, timezone
from config import Config


def calculate_level(xp: int) -> int:
    """
    Calculate level from XP using an increasing curve.
    Formula: level = floor(sqrt(xp / 50))
    Level 1 = 0 XP, Level 2 = 100 XP, Level 3 = 200 XP, etc.
    """
    if xp <= 0:
        return 1
    return int(math.sqrt(xp / 50)) + 1


def xp_for_level(level: int) -> int:
    """Calculate total XP required to reach a given level."""
    if level <= 1:
        return 0
    return (level - 1) ** 2 * 50


def xp_progress(xp: int, level: int) -> float:
    """
    Calculate progress percentage towards the next level.
    Returns a float between 0.0 and 1.0.
    """
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    xp_needed = next_level_xp - current_level_xp
    xp_have = xp - current_level_xp

    if xp_needed <= 0:
        return 1.0
    return max(0.0, min(1.0, xp_have / xp_needed))


def progress_bar(
    progress: float, length: int = 20, fill: str = "█", empty: str = "░"
) -> str:
    """Generate a text-based progress bar."""
    filled = int(progress * length)
    bar = fill * filled + empty * (length - filled)
    return f"[{bar}]"


def truncate(text: str, max_length: int = 1024) -> str:
    """Truncate text to fit Discord embed field limits."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def clean_codeblock(text: str) -> str:
    """Remove markdown codeblock wrappers if present."""
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3]
        if text and text[0] != "\n":
            text = text.split("\n", 1)[-1]
    return text.strip()


def discord_timestamp(
    dt: datetime, style: str = "R"
) -> str:
    """
    Format a datetime into a Discord timestamp.
    Styles: t (short time), T (long time), d (short date),
            D (long date), f (short date/time), F (long date/time),
            R (relative time)
    """
    timestamp = int(dt.timestamp())
    return f"<t:{timestamp}:{style}>"


def format_uptime(start_time: datetime) -> str:
    """Format uptime from a start datetime into a readable string."""
    delta = datetime.now(timezone.utc) - start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def is_admin(member: discord.Member) -> bool:
    """Check if a member has any configured admin role, the legacy
    single ADMIN_ROLE_ID (kept for backwards compatibility), or real
    server Administrator permission."""
    if member.guild_permissions.administrator:
        return True

    member_role_ids = {r.id for r in member.roles}

    admin_role_ids_raw = Config.get(member.guild.id, "ADMIN_ROLE_IDS")
    if admin_role_ids_raw:
        try:
            admin_role_ids = json.loads(admin_role_ids_raw)
        except (TypeError, ValueError):
            admin_role_ids = []
        if member_role_ids.intersection(admin_role_ids):
            return True

    legacy_role_id = Config.get(member.guild.id, "ADMIN_ROLE_ID")
    if legacy_role_id and legacy_role_id in member_role_ids:
        return True

    return False


def is_owner(user_id: int) -> bool:
    """Check if a user is the bot owner."""
    return user_id == Config.OWNER_ID