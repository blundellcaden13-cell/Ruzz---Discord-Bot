import os
from datetime import datetime, timezone
from html import escape

import aiohttp
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv

from database.db import Database
from webcommon import layout

load_dotenv()

WEB_PORT = int(os.getenv("HOME_WEB_PORT", "8091"))
BOT_API_URL = os.getenv("BOT_API_URL", "http://localhost:8080")

app = FastAPI(title="Amplified SMP — Home")
db = Database()


@app.on_event("startup")
async def startup():
    await db.connect()
    print("=" * 64)
    print(f" Amplified SMP Home running at http://localhost:{WEB_PORT}/home")
    print("=" * 64)


@app.on_event("shutdown")
async def shutdown():
    await db.close()


def fmt_duration(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


async def get_leaderboard_html(guild_rows) -> str:
    """Top inviters card — reads straight from invite_counts, no bot
    connection needed since usernames are cached at invite-time."""
    if not guild_rows:
        return ""
    guild_id = guild_rows[0][0]
    rows = await db.fetch_all(
        "SELECT username, invite_count FROM invite_counts "
        "WHERE guild_id = ? ORDER BY invite_count DESC LIMIT 5",
        (guild_id,),
    )
    if not rows:
        return ""

    medals = ["🥇", "🥈", "🥉"]
    items = []
    for i, (username, count) in enumerate(rows):
        prefix = medals[i] if i < 3 else f"#{i + 1}"
        items.append(
            f'<div class="opt" style="justify-content:space-between;">'
            f'<span>{prefix} {escape(username or "Unknown")}</span>'
            f'<b style="color:var(--accent);">{count} invite{"s" if count != 1 else ""}</b></div>'
        )

    return f"""
    <h2 style="font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:36px 0 16px;">Top Inviters</h2>
    <div class="card" style="margin-bottom:8px;">
      <div class="opt-summary">{"".join(items)}</div>
    </div>
    """


async def fetch_bot_health():
    """Best-effort fetch of the bot's own /health endpoint. Returns
    None if the bot isn't running / isn't reachable — that's treated
    as 'bot offline', not an error."""
    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{BOT_API_URL}/health") as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception:
        pass
    return None


async def get_mc_card():
    """Combine the manual /mc-status announcement with the real
    mcstatus/plugin reachability check into one (label, dot, detail)
    tuple for the status card."""
    row = await db.fetch_one(
        "SELECT guild_id, manual_status, address FROM mc_status "
        "ORDER BY updated_at DESC LIMIT 1"
    )
    if not row:
        return "Not configured", "offline", "Run /mc-server and /mc-status in Discord to enable this."

    guild_id, manual_status, address = row
    live = await db.fetch_one(
        "SELECT reachable, players_online, max_players, plugin_uptime_seconds, "
        "plugin_errors, plugin_members, checked_at FROM mc_status_live WHERE guild_id = ?",
        (guild_id,),
    )
    reachable = bool(live[0]) if live else False
    players_online, max_players, uptime_s, errors, members = (live[1:6] if live else (None,) * 5)

    if manual_status == "online":
        if reachable:
            bits = []
            if players_online is not None:
                bits.append(f"{players_online}/{max_players or '?'} players")
            if uptime_s is not None:
                bits.append(f"up {fmt_duration(uptime_s)}")
            if members is not None:
                bits.append(f"{members} members")
            if errors:
                bits.append(f"{errors} errors")
            return "Online", "online", " • ".join(bits) if bits else f"Monitoring `{address}`"
        else:
            return "Error", "error", "Error: Server is offline. Reason: Unknown"
    elif manual_status == "maintenance":
        return "Maintenance", "maintenance", f"Announced as under maintenance (`{address}`)"
    else:
        return "Offline", "offline", f"Announced as offline (`{address}`)"


@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    return RedirectResponse("/home", status_code=303)


@app.get("/home", response_class=HTMLResponse)
async def home():
    health = await fetch_bot_health()
    guild_rows = await db.fetch_all(
        "SELECT guild_id, name, member_count FROM guild_meta ORDER BY member_count DESC"
    )
    mc_label, mc_dot, mc_detail = await get_mc_card()

    if health:
        bot_dot, bot_label = "online", "Online"
        bot_detail = f"Uptime {health['uptime'].split('.')[0]} • {health['commands']} commands used"
        guild_count = health.get("guilds")
    else:
        bot_dot, bot_label = "offline", "Offline"
        bot_detail = "Bot process isn't reachable on the API port."
        guild_count = None

    if guild_rows:
        total_members = sum(r[2] or 0 for r in guild_rows)
        if len(guild_rows) == 1:
            server_value = guild_rows[0][1]
            server_detail = f"{guild_rows[0][2] or 0} members"
        else:
            server_value = f"{len(guild_rows)} servers"
            top_names = ", ".join(r[1] for r in guild_rows[:3])
            server_detail = f"{total_members} members across {top_names}"
    else:
        server_value = "No servers yet"
        server_detail = "The bot hasn't reported in — is it running?"

    open_ticket_count = await db.fetch_one("SELECT COUNT(*) FROM tickets WHERE status = 'open'")
    open_ticket_count = open_ticket_count[0] if open_ticket_count else 0
    ticket_dot = "online" if open_ticket_count == 0 else "maintenance"

    ticket_lines = []
    if guild_rows:
        primary_gid, primary_name, _ = guild_rows[0]
        primary_row = await db.fetch_one(
            "SELECT COUNT(*) FROM tickets WHERE status = 'open' AND guild_id = ?",
            (primary_gid,),
        )
        primary_count = primary_row[0] if primary_row else 0
        ticket_lines.append(f"{escape(primary_name)}: {primary_count} open")

        if len(guild_rows) > 1:
            other_gids = [g[0] for g in guild_rows[1:]]
            placeholders = ",".join("?" * len(other_gids))
            other_row = await db.fetch_one(
                f"SELECT COUNT(*) FROM tickets WHERE status = 'open' AND guild_id IN ({placeholders})",
                tuple(other_gids),
            )
            other_count = other_row[0] if other_row else 0
            ticket_lines.append(f"Other servers: {other_count} open")
    else:
        ticket_lines.append(f"{open_ticket_count} open")

    ticket_detail = "<br>".join(ticket_lines)

    stat_cards = f"""
    <div class="card-grid">
      <div class="card stat-card">
        <span class="label">Bot Status</span>
        <span class="value small"><span class="stat-dot {bot_dot}"></span>{bot_label}</span>
        <span class="hint" style="color:var(--muted);font-size:12.5px;">{bot_detail}</span>
      </div>
      <div class="card stat-card">
        <span class="label">Discord Server</span>
        <span class="value small">{server_value}</span>
        <span class="hint" style="color:var(--muted);font-size:12.5px;">{server_detail}</span>
      </div>
      <div class="card stat-card">
        <span class="label">Minecraft Server</span>
        <span class="value small"><span class="stat-dot {mc_dot}"></span>{mc_label}</span>
        <span class="hint" style="color:var(--muted);font-size:12.5px;">{mc_detail}</span>
      </div>
      <div class="card stat-card">
        <span class="label">Open Tickets</span>
        <span class="value small"><span class="stat-dot {ticket_dot}"></span>{open_ticket_count}</span>
        <span class="hint" style="color:var(--muted);font-size:12.5px;">{ticket_detail}</span>
      </div>
    </div>
    """

    tools = f"""
    <h2 style="font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:36px 0 16px;">Tools</h2>
    <div class="tool-grid">
      <div class="card tool-card">
        <h3>📊 Schedule Polls</h3>
        <div class="meta"><span class="rank-admin">Rank: Admin</span><span>Bot: Ruzz</span></div>
        <p>This website lets certain admins log in and schedule polls for the server.</p>
        <a class="btn" href="/polls">Open Poll Scheduler &rarr;</a>
      </div>
      <div class="card tool-card">
        <h3>🎫 Manage Tickets</h3>
        <div class="meta"><span class="rank-admin">Rank: Admin</span><span>Bot: Ruzz</span></div>
        <p>Set the ticket category, staff role, transcript channel, and ticket types — plus see and close open tickets.</p>
        <a class="btn" href="/tickets">Open Ticket Settings &rarr;</a>
      </div>
      <div class="card tool-card">
        <h3>📜 See Bot Logs</h3>
        <div class="meta"><span class="rank-public">Rank: Public</span><span>Bot: Ruzz</span></div>
        <p>This website lets you see the bot logs.</p>
        <a class="btn secondary" href="/logs">Open Logs &rarr;</a>
      </div>
    </div>
    """

    leaderboard_html = await get_leaderboard_html(guild_rows)

    header = """
    <header class="top">
      <h1>Dashboard</h1>
    </header>
    """

    return layout("Home", header + stat_cards + leaderboard_html + tools, active="home")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, log_level="info")
