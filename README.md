# Ruzz

Discord bot for Minecraft communities. Python + py-cord 2.x + aiosqlite + FastAPI.

Features: leveling/XP, tickets, moderation, Minecraft tools, welcome/verification, reaction roles, polls, per-server config via slash commands.

## Requirements

- Python 3.11+
- Discord bot application (https://discord.com/developers/applications)

## Setup

```bash
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env and set TOKEN and OWNER_ID
```

Enable these intents in the Developer Portal → Bot:
- Server Members Intent
- Message Content Intent
- Presence Intent

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
