import os
import json
import secrets
from html import escape
from datetime import datetime, timedelta, date

import uvicorn
from fastapi import FastAPI, Form, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv

from database.db import Database
from webcommon import BASE_CSS, SITE_NAME, LOGO_DATA_URI, layout as base_layout

load_dotenv()

PREFIX = "/polls"
WEB_PORT = int(os.getenv("POLL_WEB_PORT", "8090"))
WEB_USERNAME = os.getenv("POLL_WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("POLL_WEB_PASSWORD")

_generated_password = None
if not WEB_PASSWORD:
    _generated_password = secrets.token_urlsafe(9)
    WEB_PASSWORD = _generated_password

DT_FORMAT = "%Y-%m-%d %H:%M:%S"
DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

SESSION_COOKIE = "ruzz_poll_session"
SESSION_TOKEN = secrets.token_hex(32)


def u(path: str = "") -> str:
    """Build a URL under this app's /polls prefix."""
    return PREFIX + path


class NotLoggedIn(Exception):
    """Raised by require_login() when there's no valid session cookie."""


def require_login(request: Request):
    """Dependency used on every protected route — redirects to the
    login page instead of returning a bare 401 if the session cookie
    is missing or stale (e.g. after a restart)."""
    if request.cookies.get(SESSION_COOKIE) != SESSION_TOKEN:
        raise NotLoggedIn()


app = FastAPI(title="Amplified SMP — Polls")
db = Database()


@app.exception_handler(NotLoggedIn)
async def _not_logged_in_handler(request: Request, exc: NotLoggedIn):
    return RedirectResponse(u("/login"), status_code=303)


@app.on_event("startup")
async def startup():
    await db.connect()
    await db.create_tables()
    print("=" * 64)
    print(f" Amplified SMP Poll Scheduler running at http://localhost:{WEB_PORT}{PREFIX}")
    if _generated_password:
        print(" No POLL_WEB_PASSWORD set in .env — using a one-time login:")
        print(f"   Username: {WEB_USERNAME}")
        print(f"   Password: {_generated_password}")
        print(" Set POLL_WEB_USERNAME / POLL_WEB_PASSWORD in .env for a")
        print(" permanent login before exposing this on the internet.")
    print("=" * 64)


@app.on_event("shutdown")
async def shutdown():
    await db.close()


def hour_label(h: int) -> str:
    if h == 0:
        return "12am"
    if h < 12:
        return f"{h}am"
    if h == 12:
        return "12pm"
    return f"{h - 12}pm"


def time_label(dt: datetime) -> str:
    """e.g. '3:45 PM' — used anywhere we show an exact scheduled time."""
    label = dt.strftime("%I:%M %p")
    return label.lstrip("0") if not label.startswith("0:") else label


def parse_week_start(week_str: str | None) -> date:
    """Return the Monday of the requested (or current) week."""
    if week_str:
        try:
            d = datetime.strptime(week_str, "%Y-%m-%d").date()
            return d - timedelta(days=d.weekday())
        except ValueError:
            pass
    today = date.today()
    return today - timedelta(days=today.weekday())


async def get_poll_guilds() -> list[tuple[int, str]]:
    """Every guild with a poll channel configured via /poll-channel,
    joined against guild_meta so we can show a real name — and, as a
    side effect, this automatically hides any stale/orphaned config
    rows that don't correspond to a guild the bot is actually in
    (guild_meta is only ever populated by the live bot)."""
    rows = await db.fetch_all(
        "SELECT c.guild_id, g.name FROM config c "
        "INNER JOIN guild_meta g ON g.guild_id = c.guild_id "
        "WHERE c.key = 'POLL_CHANNEL_ID' "
        "ORDER BY g.name"
    )
    return [(r[0], r[1] or f"Server {r[0]}") for r in rows]


EXTRA_CSS = """
/* Week grid */
.grid-wrap{overflow-x:auto;border-radius:var(--radius);}
table.grid{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;min-width:820px;}
table.grid th{padding:12px 6px;text-align:center;font-size:12.5px;color:var(--muted);
border-bottom:1px solid var(--border);font-weight:700;text-transform:uppercase;letter-spacing:.04em;
position:sticky;top:0;background:var(--panel);z-index:1;}
table.grid th.today{color:var(--accent);}
table.grid th.today .daynum{color:
table.grid td{border-bottom:1px solid var(--border-soft);vertical-align:top;padding:3px;height:44px;}
table.grid td.time{color:var(--muted-dim);font-size:11px;text-align:right;padding-right:12px;
width:56px;white-space:nowrap;vertical-align:middle;font-weight:600;}
table.grid tr:hover td{background:rgba(255,255,255,.02);}

.slot{display:flex;flex-direction:column;gap:3px;height:100%;width:100%;}
.slot-empty{display:flex;align-items:center;justify-content:center;height:100%;width:100%;border-radius:6px;
color:transparent;font-size:16px;font-weight:700;transition:.12s;}
.slot-empty:hover{color:var(--accent);background:var(--accent-soft);}
.chip{display:flex;flex-direction:column;border-radius:6px;padding:4px 8px;font-size:11.5px;line-height:1.3;
background:var(--accent-soft);border:1px solid rgba(88,101,242,.35);transition:.12s;}
.chip:hover{background:rgba(88,101,242,.28);transform:translateY(-1px);}
.chip.posted{background:var(--success-soft);border-color:rgba(47,191,113,.35);}
.chip.posted:hover{background:rgba(47,191,113,.28);}
.chip.failed{background:var(--danger-soft);border-color:rgba(239,70,85,.35);}
.chip.failed:hover{background:rgba(239,70,85,.28);}
.chip .time{color:var(--muted);font-size:10px;font-weight:700;}
.chip .q{font-weight:700;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;color:var(--text);}

form.form textarea{min-height:120px;resize:vertical;line-height:1.6;}
.hint{color:var(--muted-dim);font-size:12px;margin-top:6px;}
.row{display:flex;gap:16px;}
.row > *{flex:1;}
"""


def layout(title: str, body: str) -> str:
    return base_layout(title, body, active="polls", extra_css=EXTRA_CSS)


def render_poll_form(
    action, guild_id, guild_name, question, options, created_by,
    day_value, time_value, week, submit_label,
    show_delete, poll_id, status, readonly=False,
):
    options_text = "\n".join(options) if options else ""
    disabled = "disabled" if readonly else ""

    status_banner = ""
    if status == "posted":
        status_banner = (
            '<div class="banner info">This poll has already been posted to Discord, so its '
            "title/options/time are locked here. Use <strong>Duplicate</strong> below to schedule "
            "a new poll with the same details, or Delete to remove it from this schedule "
            "(the live Discord message is untouched either way).</div>"
        )
    elif status == "failed":
        status_banner = (
            '<div class="banner warn">This poll failed to post — usually because no poll channel '
            "was configured yet (run <code>/poll-channel</code> in Discord). It's fully editable "
            "below; saving will re-queue it.</div>"
        )

    delete_btn = ""
    duplicate_btn = ""
    if show_delete:
        delete_btn = f"""
        <form method="post" action="{u(f'/poll/{poll_id}/delete')}?week={week}&guild={guild_id}"
              style="display:inline" onsubmit="return confirm('Delete this scheduled poll? This can\\'t be undone.');">
          <button type="submit" class="btn danger">Delete</button>
        </form>"""
    if status == "posted":
        duplicate_btn = (
            f'<a class="btn secondary" href="{u(f"/poll/{poll_id}/duplicate")}?week={week}&guild={guild_id}">Duplicate &amp; reschedule</a>'
        )

    submit_btn = "" if readonly else f'<button type="submit" class="btn">{submit_label}</button>'
    back_link = f'<a class="btn secondary" href="{u("")}?week={week}&guild={guild_id}">&larr; Back to week</a>'

    return status_banner + f"""
    <div class="card">
      <form class="form" method="post" action="{action}">
        <input type="hidden" name="guild_id" value="{guild_id}">
        <input type="hidden" name="week" value="{week}">

        <label>Title</label>
        <input type="text" name="question" value="{escape(question)}"
               placeholder="Should we do this or that?" required {disabled}>

        <label>Options (one per line, up to 5)</label>
        <textarea name="options" placeholder="Yes&#10;No" required {disabled}>{escape(options_text)}</textarea>
        <div class="hint">Only the first 5 options get a vote button — that's Discord's limit.</div>

        <label>Set up by (optional)</label>
        <input type="text" name="created_by" value="{escape(created_by or '')}"
               placeholder="Caden" {disabled}>

        <div class="row">
          <div>
            <label>Date</label>
            <input type="date" name="day" value="{day_value}" required {disabled}>
          </div>
          <div>
            <label>Time</label>
            <input type="time" name="time" value="{time_value}" required {disabled}>
          </div>
        </div>
        <div class="hint">Posts to <strong>{escape(guild_name)}</strong>'s poll channel at exactly this time (down to the minute).</div>

        <div style="margin-top:26px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          {submit_btn}
          {duplicate_btn}
          {delete_btn}
          {back_link}
        </div>
      </form>
    </div>
    """


# ─────────────────────────────────────
# Routes — auth
# ─────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    return RedirectResponse(u(""), status_code=303)


@app.get(PREFIX, response_class=HTMLResponse)
async def index_no_slash(week: str = None, guild: str = None, _: None = Depends(require_login)):
    return await index(week, guild)


@app.get(u("/login"), response_class=HTMLResponse)
async def login_form(error: str = None):
    banner = (
        '<div class="banner warn">Incorrect username or password.</div>'
        if error else ""
    )
    body = f"""
    <div class="login-shell">
      <div class="brand-lockup">
        <img class="badge" src="{LOGO_DATA_URI}" alt="">
        <h1 style="margin:0;">Poll Scheduler</h1>
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
        resp.set_cookie(
            SESSION_COOKIE, SESSION_TOKEN,
            httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
        )
        return resp
    return RedirectResponse(u("/login?error=1"), status_code=303)


@app.get(u("/logout"))
async def logout():
    resp = RedirectResponse(u("/login"), status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ─────────────────────────────────────
# Routes — schedule
# ─────────────────────────────────────

async def index(week: str = None, guild: str = None):
    guilds = await get_poll_guilds()
    if not guilds:
        body = """
        <header class="top"><h1>📊 Poll Scheduler</h1></header>
        <div class="banner warn">
          <strong>No poll channel configured yet.</strong><br>
          In Discord, run <code>/poll-channel channel:
          then refresh this page.
        </div>
        """
        return layout("Poll Scheduler", body)

    guild_ids = [g[0] for g in guilds]
    guild_names = dict(guilds)
    active_guild = int(guild) if guild and guild.isdigit() and int(guild) in guild_ids else guild_ids[0]
    active_name = guild_names[active_guild]

    week_start = parse_week_start(week)
    week_str = week_start.strftime("%Y-%m-%d")
    prev_week = (week_start - timedelta(days=7)).strftime("%Y-%m-%d")
    next_week = (week_start + timedelta(days=7)).strftime("%Y-%m-%d")
    this_week = parse_week_start(None).strftime("%Y-%m-%d")
    day_dates = [week_start + timedelta(days=i) for i in range(7)]

    rows = await db.fetch_all(
        "SELECT id, question, scheduled_for, status FROM scheduled_polls "
        "WHERE guild_id = ? AND scheduled_for >= ? AND scheduled_for < ? "
        "ORDER BY scheduled_for",
        (
            active_guild,
            day_dates[0].strftime("%Y-%m-%d 00:00:00"),
            (day_dates[-1] + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
        ),
    )

    slot_map = {}
    for pid, question, sched_for, status in rows:
        dt = datetime.strptime(sched_for, DT_FORMAT)
        idx = (dt.date() - day_dates[0]).days
        if 0 <= idx < 7:
            slot_map.setdefault((idx, dt.hour), []).append((pid, question, status, dt))

    today = date.today()

    guild_selector = ""
    if len(guilds) > 1:
        opts = "".join(
            f'<option value="{gid}"{" selected" if gid == active_guild else ""}>{escape(name)}</option>'
            for gid, name in guilds
        )
        guild_selector = f"""
        <form method="get" style="display:inline">
          <input type="hidden" name="week" value="{week_str}">
          <select name="guild" class="btn secondary" onchange="this.form.submit()">{opts}</select>
        </form>"""
    else:
        guild_selector = f'<span class="btn secondary" style="cursor:default;">{escape(active_name)}</span>'

    week_label = f"{week_start.strftime('%a')} {week_start.day} {week_start.strftime('%b')}"
    header = f"""
    <header class="top">
      <h1>📊 Poll Scheduler
        <span class="sub">{escape(active_name)} • Week beginning {week_label}</span>
      </h1>
      <div class="nav">
        {guild_selector}
        <a class="btn secondary" href="{u('')}?week={prev_week}&guild={active_guild}">&larr; Prev</a>
        <a class="btn secondary" href="{u('')}?week={this_week}&guild={active_guild}">This week</a>
        <a class="btn secondary" href="{u('')}?week={next_week}&guild={active_guild}">Next &rarr;</a>
        <a class="btn secondary small" href="{u('/logout')}">Log out</a>
      </div>
    </header>
    """

    thead_cells = "".join(
        f'<th class="{"today" if d == today else ""}">{DAY_SHORT[i]}<br>'
        f'<span class="daynum">{d.day} {d.strftime("%b")}</span></th>'
        for i, d in enumerate(day_dates)
    )

    body_rows = []
    for h in range(24):
        cells = [f'<td class="time">{hour_label(h)}</td>']
        for i in range(7):
            entries = slot_map.get((i, h))
            if entries:
                chips = []
                for pid, question, status, dt in entries:
                    css = "posted" if status == "posted" else ("failed" if status == "failed" else "")
                    short_q = question if len(question) <= 28 else question[:25] + "…"
                    chips.append(
                        f'<a class="chip {css}" href="{u(f"/poll/{pid}")}?week={week_str}&guild={active_guild}">'
                        f'<span class="time">{time_label(dt)}</span>'
                        f'<span class="q">{escape(short_q)}</span></a>'
                    )
                cells.append(f'<td><div class="slot">{"".join(chips)}</div></td>')
            else:
                day_str = day_dates[i].strftime("%Y-%m-%d")
                cells.append(
                    f'<td><a class="slot-empty" '
                    f'href="{u("/poll/new")}?day={day_str}&hour={h}&guild={active_guild}&week={week_str}">+</a></td>'
                )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table = f"""
    <div class="card grid-wrap">
      <table class="grid">
        <thead><tr><th></th>{thead_cells}</tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
    </div>
    """

    new_btn = (
        f'<div style="margin-bottom:16px">'
        f'<a class="btn" href="{u("/poll/new")}?guild={active_guild}&week={week_str}">+ New scheduled poll</a>'
        f"</div>"
    )

    return layout("Poll Scheduler", header + new_btn + table)


@app.get(u("/poll/new"), response_class=HTMLResponse)
async def new_poll_form(
    day: str = None, hour: int = 0, guild: str = None, week: str = None,
    _: None = Depends(require_login),
):
    guilds = await get_poll_guilds()
    if not guilds:
        return RedirectResponse(u(""))
    guild_ids = [g[0] for g in guilds]
    guild_names = dict(guilds)
    active_guild = int(guild) if guild and guild.isdigit() and int(guild) in guild_ids else guild_ids[0]

    try:
        day_date = datetime.strptime(day, "%Y-%m-%d").date() if day else date.today()
    except ValueError:
        day_date = date.today()

    body = "<header class=\"top\"><h1>📊 New Scheduled Poll</h1></header>" + render_poll_form(
        action=u("/poll/new"),
        guild_id=active_guild, guild_name=guild_names[active_guild],
        question="", options=["", ""], created_by="",
        day_value=day_date.strftime("%Y-%m-%d"), time_value=f"{hour:02d}:00",
        week=week or day_date.strftime("%Y-%m-%d"),
        submit_label="Schedule poll",
        show_delete=False, poll_id=None, status=None,
    )
    return layout("New Poll", body)


@app.post(u("/poll/new"))
async def create_poll(
    guild_id: int = Form(...),
    question: str = Form(...),
    options: str = Form(...),
    created_by: str = Form(""),
    day: str = Form(...),
    time: str = Form(...),
    week: str = Form(""),
    _: None = Depends(require_login),
):
    guild_names = dict(await get_poll_guilds())
    opt_list = [o.strip() for o in options.splitlines() if o.strip()][:5]
    if len(opt_list) < 2 or not question.strip():
        body = "<header class=\"top\"><h1>📊 New Scheduled Poll</h1></header>"
        body += '<div class="banner warn">Please enter a title and at least 2 options.</div>'
        body += render_poll_form(
            action=u("/poll/new"), guild_id=guild_id, guild_name=guild_names.get(guild_id, "this server"),
            question=question, options=opt_list or [options], created_by=created_by,
            day_value=day, time_value=time, week=week or day,
            submit_label="Schedule poll", show_delete=False, poll_id=None, status=None,
        )
        return HTMLResponse(layout("New Poll", body))

    scheduled_for = f"{day} {time}:00"
    await db.execute(
        "INSERT INTO scheduled_polls (guild_id, question, options, created_by, scheduled_for, status) "
        "VALUES (?, ?, ?, ?, ?, 'pending')",
        (guild_id, question.strip(), json.dumps(opt_list), created_by.strip(), scheduled_for),
    )
    return RedirectResponse(f"{u('')}?week={week or day}&guild={guild_id}", status_code=303)


@app.get(u("/poll/{poll_id}"), response_class=HTMLResponse)
async def view_poll(poll_id: int, week: str = None, guild: str = None, _: None = Depends(require_login)):
    row = await db.fetch_one(
        "SELECT guild_id, question, options, created_by, scheduled_for, status "
        "FROM scheduled_polls WHERE id = ?",
        (poll_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Poll not found")

    guild_id, question, options_json, created_by, scheduled_for, status = row
    guild_names = dict(await get_poll_guilds())
    options = json.loads(options_json)
    dt = datetime.strptime(scheduled_for, DT_FORMAT)
    readonly = status == "posted"

    pill = f'<span class="pill {status}">{status}</span>'
    summary = f"""
    <header class="top"><h1>📊 {escape(question)} {pill}</h1></header>
    <div class="card" style="margin-bottom:20px">
      <strong>Options</strong>
      <div class="opt-summary">
        {"".join(f'<div class="opt"><b>Option {i + 1}:</b> {escape(o)}</div>' for i, o in enumerate(options))}
      </div>
      <div class="hint">Scheduled for {dt.strftime('%a %d %b %Y')} at {time_label(dt)}</div>
    </div>
    """

    form = render_poll_form(
        action=u(f"/poll/{poll_id}/edit"),
        guild_id=guild_id, guild_name=guild_names.get(guild_id, "this server"),
        question=question, options=options, created_by=created_by,
        day_value=dt.strftime("%Y-%m-%d"), time_value=dt.strftime("%H:%M"),
        week=week or dt.strftime("%Y-%m-%d"),
        submit_label="Save changes", show_delete=True, poll_id=poll_id,
        status=status, readonly=readonly,
    )
    return layout("Edit Poll", summary + form)


@app.post(u("/poll/{poll_id}/edit"))
async def edit_poll(
    poll_id: int,
    guild_id: int = Form(...),
    question: str = Form(...),
    options: str = Form(...),
    created_by: str = Form(""),
    day: str = Form(...),
    time: str = Form(...),
    week: str = Form(""),
    _: None = Depends(require_login),
):
    row = await db.fetch_one("SELECT status FROM scheduled_polls WHERE id = ?", (poll_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Poll not found")

    # Posted polls are shown readonly, but guard here too in case the
    # form is submitted directly.
    if row[0] != "posted":
        opt_list = [o.strip() for o in options.splitlines() if o.strip()][:5]
        if len(opt_list) >= 2 and question.strip():
            scheduled_for = f"{day} {time}:00"
            await db.execute(
                "UPDATE scheduled_polls "
                "SET question = ?, options = ?, created_by = ?, scheduled_for = ?, status = 'pending' "
                "WHERE id = ?",
                (question.strip(), json.dumps(opt_list), created_by.strip(), scheduled_for, poll_id),
            )

    return RedirectResponse(f"{u('')}?week={week or day}&guild={guild_id}", status_code=303)


@app.get(u("/poll/{poll_id}/duplicate"), response_class=HTMLResponse)
async def duplicate_poll(poll_id: int, week: str = None, guild: str = None, _: None = Depends(require_login)):
    """Prefill a new-poll form from an existing (usually already-posted)
    poll, so 'editing' a posted poll in practice means scheduling a
    fresh copy rather than silently rewriting the live Discord message."""
    row = await db.fetch_one(
        "SELECT guild_id, question, options, created_by FROM scheduled_polls WHERE id = ?",
        (poll_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Poll not found")

    guild_id, question, options_json, created_by = row
    guild_names = dict(await get_poll_guilds())
    options = json.loads(options_json)
    today_str = date.today().strftime("%Y-%m-%d")

    body = "<header class=\"top\"><h1>📊 Duplicate &amp; Reschedule</h1></header>" + render_poll_form(
        action=u("/poll/new"),
        guild_id=guild_id, guild_name=guild_names.get(guild_id, "this server"),
        question=question, options=options, created_by=created_by,
        day_value=today_str, time_value="12:00",
        week=week or today_str,
        submit_label="Schedule poll",
        show_delete=False, poll_id=None, status=None,
    )
    return layout("Duplicate Poll", body)


@app.post(u("/poll/{poll_id}/delete"))
async def delete_poll(poll_id: int, week: str = None, guild: str = None, _: None = Depends(require_login)):
    await db.execute("DELETE FROM scheduled_polls WHERE id = ?", (poll_id,))
    return RedirectResponse(f"{u('')}?week={week or ''}&guild={guild or ''}", status_code=303)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, log_level="info")
