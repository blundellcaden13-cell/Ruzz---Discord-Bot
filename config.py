import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot configuration — env defaults, overridable via DB."""

    TOKEN = os.getenv("TOKEN", "")
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))

    ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
    VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "0"))

    WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
    RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", "0"))
    LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
    TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))
    TICKET_TRANSCRIPT_CHANNEL_ID = int(
        os.getenv("TICKET_TRANSCRIPT_CHANNEL_ID", "0")
    )
    LEADERBOARD_CHANNEL_ID = int(
        os.getenv("LEADERBOARD_CHANNEL_ID", "0")
    )

    XP_PER_MESSAGE_MIN = 5
    XP_PER_MESSAGE_MAX = 15
    XP_COOLDOWN_SECONDS = 30
    XP_MULTIPLIER = 1.0

    LEVEL_REWARDS = {
        5: None,
        10: None,
        20: None,
        30: None,
        50: None,
    }

    AUTOMOD_ENABLED = True
    AUTOMOD_BANNED_WORDS = []
    AUTOMOD_SPAM_THRESHOLD = 5
    AUTOMOD_SPAM_INTERVAL = 5

    TICKET_PANEL_TITLE = "🎫 Support Tickets"
    TICKET_PANEL_DESCRIPTION = (
        "Select a ticket type from the dropdown below"
        " to create a support ticket."
    )
    TICKET_TYPES = [
        {"label": "General Support", "value": "general",
         "emoji": "💬", "description": "General questions"},
        {"label": "Datapack Help", "value": "datapack",
         "emoji": "📦", "description": "Datapack issues"},
        {"label": "Resource Pack Help", "value": "resourcepack",
         "emoji": "🎨", "description": "Resource pack issues"},
        {"label": "Bug Report", "value": "bug",
         "emoji": "🐛", "description": "Report a bug"},
        {"label": "Staff Application", "value": "staff",
         "emoji": "📋", "description": "Apply for staff"},
    ]

    WELCOME_MESSAGE = (
        "Welcome to **the server**, {user}! 🎉\n\n"
        "Please read the rules in {rules_channel} "
        "and verify yourself to get full access!"
    )
    WELCOME_DM_ENABLED = True
    WELCOME_DM_MESSAGE = (
        "Hey {user}, welcome to **the server**! 🎉\n\n"
        "Make sure to:\n"
        "• Read the rules\n"
        "• Verify yourself\n"
        "• Pick your roles\n\n"
        "Enjoy your stay!"
    )

    BOT_PREFIX = "!"
    BACKUP_INTERVAL_HOURS = 24
    LOG_LEVEL = "INFO"

    _db_overrides: dict = {}

    @classmethod
    def get(cls, guild_id: int, key: str, default=None):
        """Get a config value for a specific guild, checking DB overrides first."""
        guild_overrides = cls._db_overrides.get(guild_id, {})
        if key in guild_overrides:
            return guild_overrides[key]
        return getattr(cls, key, default)

    @classmethod
    def set_override(cls, guild_id: int, key: str, value):
        """Set a DB override for a config key, scoped to one guild."""
        cls._db_overrides.setdefault(guild_id, {})[key] = value

    @classmethod
    def remove_override(cls, guild_id: int, key: str):
        """Remove a DB override for one guild."""
        if guild_id in cls._db_overrides:
            cls._db_overrides[guild_id].pop(key, None)

    @classmethod
    def load_from_db(cls, rows: list):
        """Load overrides from database rows of (guild_id, key, value)."""
        cls._db_overrides = {}
        for guild_id, key, value in rows:
            cls._db_overrides.setdefault(guild_id, {})[key] = cls._parse_value(value)

    @classmethod
    def _parse_value(cls, value: str):
        """Parse a string value into its proper type."""
        if value is None:
            return None
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value