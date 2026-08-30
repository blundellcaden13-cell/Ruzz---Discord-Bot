import os
import json
import secrets
from html import escape
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Form, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv

from database.db import Database
from config import Config
from webcommon import BASE_CSS, SITE_NAME, LOGO_DATA_URI, layout as base_layout

load_dotenv()

PREFIX = "/tickets"
WEB_PORT = int(os.getenv("TICKETS_WEB_PORT", "8094"))
WEB_USERNAME = os.getenv("POLL_WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("POLL_WEB_PASSWORD")

_generated_password = None
if not WEB_PASSWORD:
    _generated_password = secrets.token_urlsafe(9)
    WEB_PASSWORD = _generated_password

SESSION_COOKIE = "ruzz_tickets_session"
SESSION_TOKEN = secrets.token_hex(32)


def u(path: str = "") -> str:
    return PREFIX + path


class NotLoggedIn(Exception):
    pass


def require_login(request: Request):
    if request.cookies.get(SESSION_COOKIE) != SESSION_TOKEN:
        raise NotLoggedIn()


app = FastAPI(title="Amplified SMP — Tickets")
db = Database()


@app.exception_handler(NotLoggedIn)
async def _not_logged_in_handler(request: Request, exc: NotLoggedIn):
    return RedirectResponse(u("/login"), status_code=303)


@app.on_event("startup")
async def startup():
    await db.connect()
    await db.create_tables()
    print("=" * 64)
    print(f" Amplified SMP Ticket Settings running at http://localhost:{WEB_PORT}{PREFIX}")
    if _generated_password:
        print(" No POLL_WEB_PASSWORD set in .env — using a one-time login:")
        print(f"   Username: {WEB_USERNAME}")
        print(f"   Password: {_generated_password}")
    print("=" * 64)


@app.on_event("shutdown")
async def shutdown():
    await db.close()


EXTRA_CSS = """
.stack{border:1px solid var(--border-soft);border-radius:10px;overflow:hidden;background:var(--bg-alt);}
.stack-row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 18px;}
.stack-row.empty{cursor:pointer;list-style:none;}
.stack-row.empty::-webkit-details-marker{display:none;}
.stack-row.empty:hover{background:rgba(255,140,26,.06);}
.stack-divider{height:1px;background:var(--border-soft);margin:0 18px;}
.stack-label{font-size:14.5px;font-weight:700;display:flex;flex-direction:column;gap:2px;}
.stack-label.muted{color:var(--muted-dim);font-weight:600;}
.stack-label .stack-sub{font-size:11.5px;color:var(--muted);font-weight:500;}
.stack-add{border-top:1px solid var(--border-soft);}
.stack-add summary{display:flex;}
.stack-add-form{padding:6px 18px 20px;border-top:1px dashed var(--border-soft);margin-top:2px;}
.ticket-row{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;
border-bottom:1px solid var(--border-soft);font-size:13.5px;}
.ticket-row:last-child{border-bottom:none;}
.server-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;}
.server-card{display:flex;flex-direction:column;gap:8px;border-top:2px solid var(--accent);}
.server-card h3{margin:0;font-size:16.5px;}
.server-card .count{font-size:13px;color:var(--muted);}
.server-card .count b{color:var(--text);}
"""


async def get_guilds() -> list[tuple[int, str, int]]:
    rows = await db.fetch_all(
        "SELECT guild_id, name, member_count FROM guild_meta ORDER BY name"
    )
    return [(r[0], r[1] or f"Server {r[0]}", r[2] or 0) for r in rows]


async def get_open_ticket_count(guild_id: int) -> int:
    row = await db.fetch_one(
        "SELECT COUNT(*) FROM tickets WHERE status = 'open' AND guild_id = ?",
        (guild_id,),
    )
    return row[0] if row else 0


async def get_channels(guild_id: int, type_filter: str = None) -> list[tuple[int, str]]:
    if type_filter:
        rows = await db.fetch_all(
            "SELECT channel_id, name FROM guild_channels WHERE guild_id = ? AND type = ? ORDER BY position",
            (guild_id, type_filter),
        )
    else:
        rows = await db.fetch_all(
            "SELECT channel_id, name FROM guild_channels WHERE guild_id = ? ORDER BY position",
            (guild_id,),
        )
    return [(r[0], r[1]) for r in rows]


async def get_roles(guild_id: int) -> list[tuple[int, str]]:
    rows = await db.fetch_all(
        "SELECT role_id, name FROM guild_roles WHERE guild_id = ? ORDER BY position DESC",
        (guild_id,),
    )
    return [(r[0], r[1]) for r in rows]


async def get_cfg(guild_id: int, key: str):
    row = await db.fetch_one(
        "SELECT value FROM config WHERE guild_id = ? AND key = ?", (guild_id, key)
    )
    return row[0] if row else None


async def set_cfg(guild_id: int, key: str, value: str):
    await db.execute(
        "INSERT INTO config (guild_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value",
        (guild_id, key, value),
    )


async def get_ticket_types(guild_id: int) -> list[dict]:
    raw = await get_cfg(guild_id, "TICKET_TYPES")
    if raw:
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            pass
    return Config.TICKET_TYPES


def layout(title: str, body: str) -> str:
    return base_layout(title, body, active="tickets", extra_css=EXTRA_CSS)


def select_html(name: str, options: list[tuple], selected, placeholder: str) -> str:
    opts = f'<option value="">{escape(placeholder)}</option>'
    for value, label in options:
        sel = " selected" if str(value) == str(selected) else ""
        opts += f'<option value="{value}"{sel}>{escape(label)}</option>'
    return f'<select name="{name}">{opts}</select>'


# ─────────────────────────────────────
# Auth routes
# ─────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    return RedirectResponse(u(""), status_code=303)


@app.get(u("/login"), response_class=HTMLResponse)
async def login_form(error: str = None):
    banner = '<div class="banner warn">Incorrect username or password.</div>' if error else ""
    body = f"""
    <div class="login-shell">
      <div class="brand-lockup">
        <img class="badge" src="{LOGO_DATA_URI}" alt="">
        <h1 style="margin:0;">Ticket Settings</h1>
      </div>
      {banner}
      <div class="card">
        <form class="form" method="post" action="{u('/login')}">
          <label>Username</label>
          <input type="text" name="username" required autofocus>
          <label>Password</label>
          <input type="password" name="password" required>
          <div style="margin-top:22px;">
            <button type="submit" class="btn" style="width:100%;justify-content:center;">Log in</button>
          </div>
        </form>
      </div>
    </div>
    """
    return layout("Log in", body)


@app.post(u("/login"))
async def login_submit(username: str = Form(...), password: str = Form(...)):
    if secrets.compare_digest(username, WEB_USERNAME) and secrets.compare_digest(password, WEB_PASSWORD):
        resp = RedirectResponse(u(""), status_code=303)
        resp.set_cookie(SESSION_COOKIE, SESSION_TOKEN, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return resp
    return RedirectResponse(u("/login?error=1"), status_code=303)


@app.get(u("/logout"))
async def logout():
    resp = RedirectResponse(u("/login"), status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ─────────────────────────────────────
# Server list
# ─────────────────────────────────────

@app.get(u(""), response_class=HTMLResponse)
async def server_list(_: None = Depends(require_login)):
    guilds = await get_guilds()
    if not guilds:
        body = """
        <header class="top"><h1>🎫 Ticket Settings</h1></header>
        <div class="banner warn">
          <strong>No server data yet.</strong><br>
          Make sure the bot (<code>python main.py</code>) is running and has been up for
          at least a few seconds — it caches server info here automatically.
        </div>
        """
        return layout("Ticket Settings", body)

    cards = ""
    for gid, name, members in guilds:
        open_count = await get_open_ticket_count(gid)
        cards += f"""
        <a class="card server-card" href="{u(f'/server/{gid}')}">
          <h3>{escape(name)}</h3>
          <span class="count">{members} members</span>
          <span class="count"><b>{open_count}</b> open ticket{'s' if open_count != 1 else ''}</span>
        </a>
        """

    header = """
    <header class="top">
      <h1>🎫 Ticket Settings <span class="sub">Pick a server to manage its ticket setup</span></h1>
      <div class="nav"><a class="btn secondary small" href="{}">Log out</a></div>
    </header>
    """.format(u("/logout"))

    body = header + f'<div class="server-grid">{cards}</div>'
    return layout("Ticket Settings", body)


# ─────────────────────────────────────
# Per-server detail page
# ─────────────────────────────────────

@app.get(u("/server/{guild_id}"), response_class=HTMLResponse)
async def server_detail(guild_id: int, _: None = Depends(require_login)):
    guilds = dict((g[0], g[1]) for g in await get_guilds())
    if guild_id not in guilds:
        raise HTTPException(status_code=404, detail="Server not found")
    active_name = guilds[guild_id]

    categories = await get_channels(guild_id, "category")
    text_channels = await get_channels(guild_id, "text")
    roles = await get_roles(guild_id)

    category_id = await get_cfg(guild_id, "TICKET_CATEGORY_ID")
    transcript_id = await get_cfg(guild_id, "TICKET_TRANSCRIPT_CHANNEL_ID")
    admin_role_ids = json.loads(await get_cfg(guild_id, "ADMIN_ROLE_IDS") or "[]")
    ticket_types = await get_ticket_types(guild_id)

    open_tickets = await db.fetch_all(
        "SELECT channel_id, user_id, category, claimed_by, created_at, priority, "
        "user_name, claimed_by_name FROM tickets "
        "WHERE status = 'open' AND guild_id = ? ORDER BY "
        "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
        "created_at DESC LIMIT 25",
        (guild_id,),
    )

    header = f"""
    <header class="top">
      <h1>🎫 {escape(active_name)} <span class="sub">Ticket configuration</span></h1>
      <div class="nav">
        <a class="btn secondary" href="{u('')}">&larr; All servers</a>
        <a class="btn secondary small" href="{u('/logout')}">Log out</a>
      </div>
    </header>
    """

    role_checkboxes = "".join(
        f'<label style="display:flex;align-items:center;gap:8px;font-weight:500;'
        f'text-transform:none;letter-spacing:0;font-size:13.5px;margin:6px 0;">'
        f'<input type="checkbox" name="admin_role_ids" value="{rid}" style="width:auto;"'
        f'{" checked" if rid in admin_role_ids else ""}> {escape(rname)}</label>'
        for rid, rname in roles
    ) or '<p class="hint">No roles cached yet — give the bot a minute after startup.</p>'

    settings_section = f"""
    <div class="card" style="margin-bottom:24px;">
      <form class="form" method="post" action="{u(f'/server/{guild_id}/settings')}">
        <label>Ticket category</label>
        {select_html("category_id", categories, category_id, "No category selected")}
        <div class="hint">New tickets are created as channels inside this category.</div>

        <label>Transcript channel</label>
        {select_html("transcript_id", text_channels, transcript_id, "No transcript channel selected")}
        <div class="hint">Closed-ticket transcripts get posted here.</div>

        <label>Staff / admin roles</label>
        <div style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 14px;background:var(--bg-alt);max-height:180px;overflow-y:auto;">
          {role_checkboxes}
        </div>
        <div class="hint">Any of these roles can see and manage tickets — pick as many as you want, not just one.</div>

        <div style="margin-top:20px;"><button type="submit" class="btn">Save settings</button></div>
      </form>
    </div>
    """

    type_rows = "".join(
        f"""
        <div class="stack-row">
          <span class="stack-label">{escape(t.get('emoji', '🎫'))} {escape(t.get('label', ''))}
            <span class="stack-sub">{escape(t.get('value', ''))} — {escape(t.get('description', ''))}</span>
          </span>
          <form method="post" action="{u('/types/delete')}" onsubmit="return confirm('Remove this ticket type?');">
            <input type="hidden" name="guild_id" value="{guild_id}">
            <input type="hidden" name="value" value="{escape(t.get('value', ''))}">
            <button type="submit" class="btn danger small">Remove</button>
          </form>
        </div>
        <div class="stack-divider"></div>
        """
        for t in ticket_types
    )

    types_section = f"""
    <div class="card" style="margin-bottom:24px;">
      <h3 style="margin-top:0;">🎫 Ticket Types</h3>
      <div class="hint" style="margin-bottom:14px;">These show up in the dropdown when someone opens the ticket panel. To edit one, remove it and add it again.</div>
      <div class="stack">
        {type_rows}
        <details class="stack-add">
          <summary class="stack-row empty">
            <span class="stack-label muted">Empty</span>
            <span class="btn small">Add</span>
          </summary>
          <div class="stack-add-form">
            <form class="form" method="post" action="{u('/types/add')}">
              <input type="hidden" name="guild_id" value="{guild_id}">
              <label>Label</label>
              <input type="text" name="label" maxlength="25" required placeholder="General Support">
              <label>Value (no spaces, unique)</label>
              <input type="text" name="value" maxlength="25" required placeholder="general">
              <div class="row">
                <div><label>Emoji</label><input type="text" name="emoji" maxlength="10" value="🎫"></div>
                <div><label>Description</label><input type="text" name="description" maxlength="50" placeholder="No description"></div>
              </div>
              <div style="margin-top:16px;"><button type="submit" class="btn">Add type</button></div>
            </form>
          </div>
        </details>
      </div>
    </div>
    """

    priority_emoji = {"low": "🟢", "normal": "🔵", "high": "🟠", "urgent": "🔴"}

    def ticket_row_html(cid, uid, cat, claimed, created, priority, user_name, claimed_by_name):
        opener = escape(user_name) if user_name else f"<code>{uid}</code>"
        claimed_str = ""
        if claimed:
            claimer = escape(claimed_by_name) if claimed_by_name else f"<code>{claimed}</code>"
            claimed_str = f" — claimed by {claimer}"
        p_emoji = priority_emoji.get(priority, "🔵")
        return (
            f'<div class="ticket-row"><span>{p_emoji} #{cid} — opened by {opener}{claimed_str}</span>'
            f'<span style="display:flex;align-items:center;gap:12px;">'
            f'<span style="color:var(--muted);">{escape(str(cat))} • {escape((created or "")[:16])}</span>'
            f'<form method="post" action="{u("/close-request")}" onsubmit="return confirm(\'Request this ticket be closed? The bot picks this up within ~30 seconds.\');">'
            f'<input type="hidden" name="guild_id" value="{guild_id}">'
            f'<input type="hidden" name="channel_id" value="{cid}">'
            f'<button type="submit" class="btn danger small">Close</button></form></span></div>'
        )

    ticket_rows = "".join(
        ticket_row_html(*row) for row in open_tickets
    ) or '<p style="color:var(--muted);padding:14px;">No open tickets right now.</p>'

    open_section = f"""
    <div class="card">
      <h3 style="margin-top:0;">Open tickets ({len(open_tickets)})</h3>
      <div class="hint" style="margin-bottom:10px;">Closing from here requests a close — the bot applies it (transcript + delete channel) within about 30 seconds, same as using the in-Discord close button.</div>
      {ticket_rows}
    </div>
    """

    return layout("Ticket Settings", header + settings_section + types_section + open_section)


@app.post(u("/server/{guild_id}/settings"))
async def save_settings(
    guild_id: int,
    category_id: str = Form(""),
    transcript_id: str = Form(""),
    admin_role_ids: list[str] = Form([]),
    _: None = Depends(require_login),
):
    if category_id:
        await set_cfg(guild_id, "TICKET_CATEGORY_ID", category_id)
    if transcript_id:
        await set_cfg(guild_id, "TICKET_TRANSCRIPT_CHANNEL_ID", transcript_id)
    # Always save (even if empty) — unchecking every box should clear
    # the list, not leave the old one in place.
    await set_cfg(guild_id, "ADMIN_ROLE_IDS", json.dumps([int(r) for r in admin_role_ids]))
    return RedirectResponse(u(f"/server/{guild_id}"), status_code=303)


@app.post(u("/close-request"))
async def close_request(
    guild_id: int = Form(...),
    channel_id: int = Form(...),
    _: None = Depends(require_login),
):
    await db.execute(
        "UPDATE tickets SET close_requested = 1 WHERE channel_id = ?", (channel_id,)
    )
    return RedirectResponse(u(f"/server/{guild_id}"), status_code=303)


@app.post(u("/types/add"))
async def add_type(
    guild_id: int = Form(...),
    label: str = Form(...),
    value: str = Form(...),
    emoji: str = Form("🎫"),
    description: str = Form(""),
    _: None = Depends(require_login),
):
    types = await get_ticket_types(guild_id)
    types = [t for t in types if t.get("value") != value]  # replace if same value re-added
    types.append({
        "label": label.strip()[:25],
        "value": value.strip()[:25],
        "emoji": emoji.strip()[:10] or "🎫",
        "description": (description.strip() or "No description")[:50],
    })
    await set_cfg(guild_id, "TICKET_TYPES", json.dumps(types))
    return RedirectResponse(u(f"/server/{guild_id}"), status_code=303)


@app.post(u("/types/delete"))
async def delete_type(
    guild_id: int = Form(...),
    value: str = Form(...),
    _: None = Depends(require_login),
):
    types = await get_ticket_types(guild_id)
    types = [t for t in types if t.get("value") != value]
    await set_cfg(guild_id, "TICKET_TYPES", json.dumps(types))
    return RedirectResponse(u(f"/server/{guild_id}"), status_code=303)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, log_level="info")
