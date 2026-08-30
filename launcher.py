import subprocess
import sys
import threading
import time
from collections import deque
from datetime import timedelta

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

SERVICES = [
    ("Bot", "main.py", "cyan"),
    ("Polls", "poll.py", "orange3"),
    ("Home", "home.py", "green"),
    ("Logs Site", "logs.py", "magenta"),
    ("Tickets", "tickets.py", "yellow"),
]

RESTART_DELAY = 3
COMBINED_LOG_LINES = 300
STAGGER_START = 0.4


class ManagedProcess:
    def __init__(self, name: str, script: str, color: str, combined_log: deque, log_lock: threading.Lock):
        self.name = name
        self.script = script
        self.color = color
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.restarts = 0
        self.status = "starting"
        self.last_exit_code = None
        self._stop_requested = False
        self._combined_log = combined_log
        self._log_lock = log_lock

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-u", self.script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.started_at = time.time()
        self.status = "running"
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _read_output(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            with self._log_lock:
                self._combined_log.append((self.name, self.color, line))

    def _watch(self):
        assert self.proc
        self.proc.wait()
        self.last_exit_code = self.proc.returncode
        if self._stop_requested:
            self.status = "stopped"
            return

        self.status = "crashed"
        with self._log_lock:
            self._combined_log.append(
                (self.name, self.color, f"[exited with code {self.last_exit_code} — restarting in {RESTART_DELAY}s]")
            )
        time.sleep(RESTART_DELAY)
        if not self._stop_requested:
            self.restarts += 1
            self.start()

    def stop(self):
        self._stop_requested = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.status = "stopped"

    def uptime_str(self) -> str:
        if not self.started_at or self.status != "running":
            return "—"
        return str(timedelta(seconds=int(time.time() - self.started_at)))


def render_status_table(services: list[ManagedProcess]) -> Table:
    table = Table(expand=True, header_style="bold orange3", border_style="grey37")
    table.add_column("Service", ratio=2)
    table.add_column("Status", ratio=2)
    table.add_column("Uptime", ratio=2)
    table.add_column("Restarts", ratio=1, justify="right")

    dots = {"running": "🟢", "starting": "🟡", "crashed": "🔴", "stopped": "⚪"}
    for s in services:
        table.add_row(
            f"[bold]{s.name}[/bold] [dim]({s.script})[/dim]",
            f"{dots.get(s.status, '⚪')} {s.status}",
            s.uptime_str(),
            str(s.restarts),
        )
    return table


def render_logs(combined_log: deque, log_lock: threading.Lock) -> Text:
    text = Text()
    with log_lock:
        lines = list(combined_log)
    for name, color, line in lines[-60:]:
        text.append(f"[{name}] ", style=f"bold {color}")
        text.append(line + "\n")
    if not lines:
        text.append("(waiting for output...)", style="dim")
    return text


def build_layout(services: list[ManagedProcess], combined_log: deque, log_lock: threading.Lock) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="status", size=len(services) + 4),
        Layout(name="logs"),
    )

    header_text = Text("🎮  Amplified SMP — all services", style="bold white")
    layout["header"].update(
        Panel(header_text, border_style="orange3", subtitle="[dim]Ctrl+C to stop everything[/dim]")
    )
    layout["status"].update(Panel(render_status_table(services), title="Status", border_style="grey37"))
    layout["logs"].update(
        Panel(render_logs(combined_log, log_lock), title="Live logs (all services)", border_style="grey37")
    )
    return layout


def main():
    combined_log: deque = deque(maxlen=COMBINED_LOG_LINES)
    log_lock = threading.Lock()

    services = [
        ManagedProcess(name, script, color, combined_log, log_lock)
        for name, script, color in SERVICES
    ]

    for s in services:
        s.start()
        time.sleep(STAGGER_START)

    try:
        with Live(build_layout(services, combined_log, log_lock), refresh_per_second=4, screen=True) as live:
            while True:
                time.sleep(0.25)
                live.update(build_layout(services, combined_log, log_lock))
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping all services...")
        for s in services:
            s.stop()
        print("Done.")


if __name__ == "__main__":
    main()
