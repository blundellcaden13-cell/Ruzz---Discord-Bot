# Ruzz

**Ruzz** is an open-source Discord bot built for Minecraft or other communities.

Python · [py-cord](https://docs.pycord.dev/) 2.x · aiosqlite · FastAPI

One bot instance works in as many servers as you invite it to. Every server has its own settings (roles, channels, tickets, etc.) stored in the database — no hardcoded IDs.

---

## Features

| Area | What you get |
|------|----------------|
| **Leveling** | XP from messages, ranks, contribution points, auto leaderboard panel |
| **Tickets** | Dropdown panels, transcripts, claiming, priorities |
| **Moderation** | Warns, mutes, kicks, bans, automod hooks, log channel |
| **Minecraft** | `/server-status`, skins, pack-format lookup, optional Paper stats plugin |
| **Welcome** | Configurable welcome channel + optional DM |
| **Polls** | Scheduled polls delivered by the bot |
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
```

Edit `.env`:

```env
TOKEN=your-bot-token-here
OWNER_ID=your-discord-user-id
```

### 2. Run

**Recommended** (live terminal status dashboard):

```bash
# Linux / macOS
./start.sh

# Windows
start.bat
```

**Bot only:**

```bash
python main.py
```

The bot also exposes a small health API at `http://localhost:8080/health` and `/stats`.

### 3. Configure in Discord

| Command | Purpose |
|---------|---------|
| `/admin-role` | Role that can use admin commands |
| `/verified-role` | Role given after verification |
| `/welcome-channel` | Where welcome messages post |
| `/rules-channel` | Linked in welcome text |
| `/log-channel` | Moderation logs |
| `/ticket-category` | Category for new ticket channels |
| `/ticket-transcript-channel` | Closed-ticket transcripts |
| `/ticket-panel` | Post the ticket panel |
| `/leaderboard-panel` | Post the live XP leaderboard |
| `/setup view` | Show current config |
| `/setup reset` | Reset one setting |

Slash commands sync **globally**. First sync after install can take up to ~1 hour.

---

## Commands (overview)

**Public:** `/rank` · `/leaderboard` · `/userinfo` · `/botstats` · `/help` · `/server-status` · `/skin` · `/pack-format`

**Admin:** setup, moderation, contribution points, tickets, Minecraft status tools

Use `/help` in Discord for the full list.

---

## Minecraft plugin (Paper 1.21.11)

Optional **RuzzStats** plugin for **Paper 1.21.11** (Java 21).

Exposes live players, uptime, unique members, TPS, and errors over HTTP for the bot.

```bash
cd minecraft-plugin
mvn clean package
```

Install `target/RuzzStats-1.0.0.jar` → edit `plugins/RuzzStats/config.yml` → link with `/mc-server` in Discord.

Details: [`minecraft-plugin/README.md`](minecraft-plugin/README.md)

---

## Project layout

```
├── main.py              Bot entry point
├── launcher.py          Status dashboard (runs the bot)
├── config.py            Defaults + per-guild overrides
├── database/db.py       Async SQLite layer
├── cogs/                Discord features (leveling, tickets, mod, …)
├── utils/               Embeds & helpers
└── minecraft-plugin/    Paper 1.21.11 stats plugin
```

---

## Security

- NEVER share you bot token

---

## License

MIT — see [LICENSE](LICENSE)

---

## Releases

Pre-packaged downloads (Linux / macOS / Windows) are on the
[Releases](https://github.com/blundellcaden13-cell/Ruzz---Discord-Bot/releases) page.
