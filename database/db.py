import aiosqlite
import os
import logging
from datetime import datetime, timezone
from typing import Any, Optional, List, Tuple

logger = logging.getLogger("DevHubBot.DB")

DB_PATH = "database/devhub.db"
LOG_DIR = "logs"


class Database:
    """Manages the SQLite database connection and queries."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Establish connection to the database."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.connection = await aiosqlite.connect(self.db_path)
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA busy_timeout=5000")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        logger.info("Database connection established.")

    async def close(self):
        """Close the database connection gracefully."""
        if self.connection:
            await self.connection.close()
            logger.info("Database connection closed.")


    async def execute(
        self, query: str, params: tuple = ()
    ) -> aiosqlite.Cursor:
        """Execute a write query."""
        if not self.connection:
            raise RuntimeError("Database not connected!")
        cursor = await self.connection.execute(query, params)
        await self.connection.commit()
        return cursor

    async def fetch_one(
        self, query: str, params: tuple = ()
    ) -> Optional[Tuple]:
        """Fetch a single row."""
        if not self.connection:
            raise RuntimeError("Database not connected!")
        cursor = await self.connection.execute(query, params)
        return await cursor.fetchone()

    async def fetch_all(
        self, query: str, params: tuple = ()
    ) -> List[Tuple]:
        """Fetch all matching rows."""
        if not self.connection:
            raise RuntimeError("Database not connected!")
        cursor = await self.connection.execute(query, params)
        return await cursor.fetchall()


    async def _migrate_legacy_config_table(self):
        """
        Older versions of this bot had a single-server `config` table
        (PRIMARY KEY was just `key`, no `guild_id`) since the bot only
        ever ran in one server via a hardcoded GUILD_ID. Now that
        every setting is per-guild, that old table shape is
        incompatible. If we detect it, rename it out of the way
        instead of dropping it, so no data is silently lost — admins
        just need to re-run the setup commands (/admin-role,
        /log-channel, etc.) once per server, which they'd need to do
        for any *new* servers anyway.
        """
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='config'"
        )
        exists = await cursor.fetchone()
        if not exists:
            return

        cursor = await self.connection.execute("PRAGMA table_info(config)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "guild_id" in columns:
            return

        logger.warning(
            "Found old single-server config table — renaming to "
            "'config_legacy_backup' and starting fresh per-guild config. "
            "Re-run your /admin-role, /log-channel, etc. commands."
        )
        await self.execute(
            "ALTER TABLE config RENAME TO config_legacy_backup"
        )

    async def _add_column_if_missing(self, table: str, column: str, coltype: str):
        """SQLite has no 'ALTER TABLE ... ADD COLUMN IF NOT EXISTS', so
        this checks PRAGMA table_info first. Safe to call every startup —
        does nothing once the column already exists."""
        cursor = await self.connection.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in await cursor.fetchall()]
        if column in columns:
            return
        await self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        logger.info("Added column %s.%s (%s)", table, column, coltype)


    async def create_tables(self):
        """Create all required tables if they don't exist."""
        await self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                contribution_points INTEGER DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Bot Config (for per-guild settings like /admin-role,
        # /log-channel, etc. — one row per guild+key so every server
        # the bot is in has fully independent settings)
        await self._migrate_legacy_config_table()
        await self.execute("""
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (guild_id, key)
            )
        """)

        # Level Rewards
        await self.execute("""
            CREATE TABLE IF NOT EXISTS level_rewards (
                level INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL
            )
        """)

        # Tickets
        await self.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT,
                closer_id INTEGER
            )
        """)

        # Datapacks
        await self.execute("""
            CREATE TABLE IF NOT EXISTS datapacks (
                pack_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                version TEXT,
                download_link TEXT,
                status TEXT DEFAULT 'pending',
                upvotes INTEGER DEFAULT 0,
                downvotes INTEGER DEFAULT 0,
                message_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Datapack Votes
        await self.execute("""
            CREATE TABLE IF NOT EXISTS datapack_votes (
                pack_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                vote_type TEXT NOT NULL,
                PRIMARY KEY (pack_id, user_id),
                FOREIGN KEY (pack_id) REFERENCES datapacks(pack_id)
            )
        """)

        # Reaction Roles
        await self.execute("""
            CREATE TABLE IF NOT EXISTS reaction_roles (
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (message_id, emoji)
            )
        """)

        # Automod Violations (for logging/tracking)
        await self.execute("""
            CREATE TABLE IF NOT EXISTS automod_violations (
                violation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                violation_type TEXT NOT NULL,
                content_snippet TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Polls
        await self.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Scheduled Polls — managed by the poll.py website, delivered
        # by cogs/polls.py. This is a brand new table (IF NOT EXISTS),
        # so it's added alongside everything above without touching
        # any existing data (users/xp, tickets, datapacks, etc.).
        await self.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                created_by TEXT,
                scheduled_for TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                channel_id INTEGER,
                message_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                posted_at TEXT
            )
        """)

        # Cached guild info (name/member count) — refreshed periodically
        # by the bot — so the standalone websites (poll.py, home.py)
        # can show a real server name instead of a raw guild ID
        # without needing their own Discord connection.
        await self.execute("""
            CREATE TABLE IF NOT EXISTS guild_meta (
                guild_id INTEGER PRIMARY KEY,
                name TEXT,
                member_count INTEGER,
                icon_url TEXT,
                updated_at TEXT
            )
        """)

        # Manual Minecraft server status, set via /mc-status. This is
        # the "announced" status — separate from whether the server
        # actually responds to a ping (see mc_status_live below).
        await self.execute("""
            CREATE TABLE IF NOT EXISTS mc_status (
                guild_id INTEGER PRIMARY KEY,
                manual_status TEXT DEFAULT 'offline',
                address TEXT,
                stats_url TEXT,
                stats_token TEXT,
                updated_at TEXT,
                updated_by TEXT
            )
        """)

        # Live reachability snapshot, refreshed periodically by
        # cogs/mc_status.py (real mcstatus ping + optional plugin
        # /stats fetch). The website combines this with mc_status
        # above to decide the green/orange/red state.
        await self.execute("""
            CREATE TABLE IF NOT EXISTS mc_status_live (
                guild_id INTEGER PRIMARY KEY,
                reachable INTEGER DEFAULT 0,
                players_online INTEGER,
                max_players INTEGER,
                version TEXT,
                plugin_uptime_seconds INTEGER,
                plugin_errors INTEGER,
                plugin_members INTEGER,
                checked_at TEXT
            )
        """)

        # Warnings & Strikes (moderation)
        await self.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                created_at TEXT
            )
        """)
        await self.execute("""
            CREATE TABLE IF NOT EXISTS strikes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                created_at TEXT
            )
        """)

        # Invite tracking / rewards ladder
        await self.execute("""
            CREATE TABLE IF NOT EXISTS invite_counts (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                invite_count INTEGER DEFAULT 0,
                highest_tier INTEGER DEFAULT 0,
                updated_at TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        # Remembers who invited each member, so if that member leaves
        # we can decrement the *right* inviter's count (rather than
        # just trusting raw invite-link uses, which never go down).
        await self.execute("""
            CREATE TABLE IF NOT EXISTS invite_joins (
                guild_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                inviter_id INTEGER,
                invite_code TEXT,
                joined_at TEXT,
                PRIMARY KEY (guild_id, member_id)
            )
        """)

        # Ticket claiming (additive column on the existing tickets table)
        await self._add_column_if_missing("tickets", "claimed_by", "INTEGER")
        # Lets the website request a close without a Discord connection
        # of its own — the bot's reconcile loop picks these up.
        await self._add_column_if_missing("tickets", "close_requested", "INTEGER DEFAULT 0")
        # Lets the ticket website filter/manage tickets per-server.
        # Tickets created before this column existed will have guild_id
        # NULL — they still show in the cross-server total, just won't
        # appear on any single server's page until they're closed and a
        # new one is opened.
        await self._add_column_if_missing("tickets", "guild_id", "INTEGER")

        # Ticket feature pack: priority tagging, a recorded close
        # reason, cached display names (so the website can show real
        # names without needing a live Discord connection), and last
        # activity tracking (used by the stale-ticket auto-close check).
        await self._add_column_if_missing("tickets", "priority", "TEXT DEFAULT 'normal'")
        await self._add_column_if_missing("tickets", "close_reason", "TEXT")
        await self._add_column_if_missing("tickets", "user_name", "TEXT")
        await self._add_column_if_missing("tickets", "claimed_by_name", "TEXT")
        await self._add_column_if_missing("tickets", "last_activity_at", "TEXT")
        await self._add_column_if_missing("tickets", "warned_stale_at", "TEXT")

        # Cached channel/role lists — refreshed periodically by the bot
        # (main.py's sync loop) — so standalone websites that have no
        # Discord connection of their own (like tickets.py) can still
        # render real channel/role names in dropdowns instead of
        # asking admins to paste in raw IDs.
        await self.execute("""
            CREATE TABLE IF NOT EXISTS guild_channels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                name TEXT,
                type TEXT,
                position INTEGER,
                PRIMARY KEY (guild_id, channel_id)
            )
        """)
        await self.execute("""
            CREATE TABLE IF NOT EXISTS guild_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                name TEXT,
                position INTEGER,
                PRIMARY KEY (guild_id, role_id)
            )
        """)

        logger.info("All database tables verified/created.")

    # ─────────────────────────────────────
    # Config Overrides (for /setup commands)
    # ─────────────────────────────────────

    async def set_config(self, guild_id: int, key: str, value: str):
        """Insert or update a configuration override for a guild."""
        await self.execute(
            """
            INSERT INTO config (guild_id, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value
            """,
            (guild_id, key, str(value)),
        )
        logger.info("Config updated (guild %s): %s = %s", guild_id, key, value)

    async def get_config(self, guild_id: int, key: str) -> Optional[str]:
        """Get a configuration value for a guild from the database."""
        row = await self.fetch_one(
            "SELECT value FROM config WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        )
        return row[0] if row else None

    async def delete_config(self, guild_id: int, key: str):
        """Remove a configuration override for a guild (reverts to default)."""
        await self.execute(
            "DELETE FROM config WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        )
        logger.info("Config override removed (guild %s): %s", guild_id, key)

    async def get_config_all_guilds(self, key: str) -> List[Tuple[int, str]]:
        """Fetch a single config key's value across every guild that has it set.

        Used by background tasks (like the leaderboard auto-updater)
        that need to act on every guild, not just one.
        """
        return await self.fetch_all(
            "SELECT guild_id, value FROM config WHERE key = ?", (key,)
        )

