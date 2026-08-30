# Ruzz

**Ruzz** is an open-source Discord bot built for Minecraft communities.

Python · [py-cord](https://docs.pycord.dev/) 2.x · aiosqlite · FastAPI

One bot instance works in as many servers as you invite it to. Every server has its own settings (roles, channels, tickets, etc.) stored in the database — no hardcoded IDs.

---

## Features

| Area | What you get |
|------|----------------|
| **Leveling** | XP from messages, ranks, contribution points, auto leaderboard panel |
| **Tickets** | Dropdown panels, transcripts, claiming, priorities, web settings UI |
| **Moderation** | Warns, mutes, kicks, bans, automod hooks, log channel |
| **Minecraft** | `/server-status`, skins, pack-format lookup, optional Paper stats plugin |
| **Welcome** | Configurable welcome channel + optional DM |
| **Polls** | Schedule polls from a web UI; the bot posts them on time |
| **Setup** | All config via slash commands (`/admin-role`, `/log-channel`, …) |

---

## Requirements

- **Python 3.11+** (3.12/3.13 supported; `audioop-lts` is in `requirements.txt` for 3.12+)
- A [Discord application](https://discord.com/developers/applications) with a bot user

### Discord intents (Developer Portal → Bot)

- Server Members Intent
- Message Content Intent
- Presence Intent

### Suggested invite permissions

`Manage Roles`, `Manage Channels`, `Kick Members`, `Ban Members`, `Moderate Members`, `Manage Messages`, `Send Messages`, `Embed Links`, `Attach Files`, `Read Message History`, `Use Application Commands`

---

## Quick start

### 1. Install

```bash
git clone https://github.com/blundellcaden13-cell/Ruzz---Discord-Bot.git
cd Ruzz---Discord-Bot

python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
# venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
Invite with: Manage Roles, Manage Channels, Kick/Ban/Moderate Members, Manage Messages, Send Messages, Embed Links, Attach Files, Read Message History.

## Run

Easiest (starts bot + companion web services with a live dashboard):

```bash
# Linux / macOS
./start.sh

# Windows
start.bat
```

Or run the bot alone:

```bash
python main.py
```

Companion sites (optional, separate processes):
- `python poll.py` — poll scheduler (port 8090)
- `python home.py` — landing page (port 8091)
- `python logs.py` — log viewer (port 8092)
- `python tickets.py` — ticket settings (port 8094)

## Configuration

Only `TOKEN` and `OWNER_ID` go in `.env`. Everything else is per-server via slash commands:

| Command | Purpose |
|---------|---------|
| `/admin-role` | Admin role |
| `/verified-role` | Verified role |
| `/welcome-channel` | Welcome messages |
| `/rules-channel` | Rules channel |
| `/log-channel` | Moderation logs |
| `/ticket-category` | Ticket category |
| `/ticket-transcript-channel` | Transcript channel |
| `/ticket-panel` | Post ticket panel |
| `/leaderboard-panel` | Post leaderboard |
| `/setup view` | Show current config |
| `/setup reset` | Reset a setting |

Slash commands sync globally (first sync can take up to ~1 hour).

## Main commands

Public: `/rank`, `/leaderboard`, `/server-status`, `/skin`, `/pack-format`, `/userinfo`, `/botstats`, `/help`

Admin: moderation tools, contribution points, setup commands, ticket management, etc.

## Minecraft plugin

See `minecraft-plugin/` for an optional Paper/Spigot stats plugin.

## License

Open source. Do not commit real `.env` or database files.
