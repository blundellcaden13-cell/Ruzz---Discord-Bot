import os
import re
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from html import escape

from webcommon import layout

WEB_PORT = int(os.getenv("LOGS_WEB_PORT", "8092"))
LOG_FILE = os.path.join("logs", "bot.log")
DEFAULT_LINES = 400
MAX_LINES = 3000

app = FastAPI(title="Amplified SMP — Logs")


PATH_RE = re.compile(
    r"(?:/(?:Users|home|root|var|opt|mnt|etc|srv)/[^\s\"':]+)"
    r"|(?:[A-Za-z]:\\\\?[^\s\"'\n]+)"
)
TOKEN_RE = re.compile(r"[MNOmno][A-Za-z\d_-]{23,25}\.[\w-]{6}\.[\w-]{27,40}")
LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<level>\w+)\s*\| (?P<name>[^|]+)\| (?P<msg>.*)$"
)


def sanitize(line: str) -> str:
    line = PATH_RE.sub("[path hidden]", line)
    line = TOKEN_RE.sub("[token hidden]", line)
    return line


def parse_level(line: str) -> str:
    m = LOG_LINE_RE.match(line)
    if m:
        return m.group("level").strip().upper()
    return "INFO"


def read_tail(n: int, level_filter: str = "ALL") -> list[str]:
    if not os.path.exists(LOG_FILE):
        return ["(no logs/bot.log file yet — start the bot with `python main.py` first)"]
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return [f"(could not read log file: {e})"]

    lines = [line.rstrip("\n") for line in lines if line.strip()]
    if level_filter != "ALL":
        lines = [line for line in lines if parse_level(line) == level_filter]
    return [sanitize(line) for line in lines[-n:]]


@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    return RedirectResponse("/logs", status_code=303)


@app.get("/logs/data")
async def logs_data(lines: int = DEFAULT_LINES, level: str = "ALL"):
    lines = max(10, min(lines, MAX_LINES))
    entries = read_tail(lines, level)
    return JSONResponse({
        "lines": entries,
        "count": len(entries),
        "generated_at": datetime.now().strftime("%H:%M:%S"),
    })


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(lines: int = DEFAULT_LINES, level: str = "ALL"):
    lines = max(10, min(lines, MAX_LINES))
    entries = read_tail(lines, level)

    def line_html(raw: str) -> str:
        lvl = parse_level(raw)
        return f'<div class="log-line lvl-{escape(lvl)}">{escape(raw)}</div>'

    rendered = "\n".join(line_html(l) for l in entries) or "<div class=\"log-line\">(no matching log lines)</div>"

    level_options = "".join(
        f'<option value="{lvl}"{" selected" if lvl == level else ""}>{lvl}</option>'
        for lvl in ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"]
    )
    lines_options = "".join(
        f'<option value="{n}"{" selected" if n == lines else ""}>{n} lines</option>'
        for n in [100, 400, 1000, 3000]
    )

    header = f"""
    <header class="top">
      <h1>📜 Bot Logs
        <span class="sub">Live tail of logs/bot.log — file paths &amp; tokens are redacted</span>
      </h1>
      <div class="nav">
        <select id="level-select" class="btn secondary" onchange="applyFilters()">{level_options}</select>
        <select id="lines-select" class="btn secondary" onchange="applyFilters()">{lines_options}</select>
        <span class="btn secondary" id="refresh-indicator" style="cursor:default;">⟳ auto-refreshing</span>
      </div>
    </header>
    """

    pane = f'<div class="card log-pane" id="log-pane">{rendered}</div>'

    script = """
    <script>
    let level = document.getElementById('level-select').value;
    let lines = document.getElementById('lines-select').value;

    function applyFilters() {
      level = document.getElementById('level-select').value;
      lines = document.getElementById('lines-select').value;
      refresh();
    }

    async function refresh() {
      try {
        const res = await fetch(`/logs/data?lines=${lines}&level=${level}`);
        const data = await res.json();
        const pane = document.getElementById('log-pane');
        const wasAtBottom = pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 40;
        pane.innerHTML = data.lines.map(escapeAndClassify).join('') || '<div class="log-line">(no matching log lines)</div>';
        if (wasAtBottom) pane.scrollTop = pane.scrollHeight;
        document.getElementById('refresh-indicator').textContent = '⟳ updated ' + data.generated_at;
      } catch (e) { /* bot/server unreachable — just leave the last known content */ }
    }

    function escapeAndClassify(line) {
      const div = document.createElement('div');
      div.textContent = line;
      const m = line.match(/\\| (\\w+)\\s*\\|/);
      const lvl = m ? m[1].toUpperCase() : 'INFO';
      div.className = 'log-line lvl-' + lvl;
      return div.outerHTML;
    }

    document.getElementById('log-pane').scrollTop = document.getElementById('log-pane').scrollHeight;
    setInterval(refresh, 5000);
    </script>
    """

    return layout("Bot Logs", header + pane + script, active="logs")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, log_level="info")
