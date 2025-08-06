#!/usr/bin/env python3
"""Interactive console terminal for Arianna Core."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import readline
import atexit
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import Callable, Deque, Iterable, List
from dataclasses import dataclass

_NO_COLOR_FLAG = "--no-color"
USE_COLOR = (
    os.getenv("LETSGO_NO_COLOR") is None
    and os.getenv("NO_COLOR") is None
    and _NO_COLOR_FLAG not in sys.argv
)
if _NO_COLOR_FLAG in sys.argv:
    sys.argv.remove(_NO_COLOR_FLAG)


# Configuration
CONFIG_PATH = Path.home() / ".letsgo" / "config"


@dataclass
class Settings:
    prompt: str = ">> "
    green: str = "\033[32m"
    red: str = "\033[31m"
    cyan: str = "\033[36m"
    reset: str = "\033[0m"


def _load_settings(path: Path = CONFIG_PATH) -> Settings:
    settings = Settings()
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = map(str.strip, line.split("=", 1))
                value = value.strip("\"'")
                value = bytes(value, "utf-8").decode("unicode_escape")
                if hasattr(settings, key):
                    setattr(settings, key, value)
    except FileNotFoundError:
        pass
    return settings


SETTINGS = _load_settings()


def color(text: str, code: str) -> str:
    return f"{code}{text}{SETTINGS.reset}" if USE_COLOR else text


# //: each session logs to its own file under a fixed directory
LOG_DIR = Path("/arianna_core/log")
SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
LOG_PATH = LOG_DIR / f"{SESSION_ID}.log"
HISTORY_PATH = LOG_DIR / "history"


def _ensure_log_dir() -> None:
    """Ensure that the log directory exists and is writable."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not os.access(LOG_DIR, os.W_OK):
        print(f"No write permission for {LOG_DIR}", file=sys.stderr)
        raise SystemExit(1)


def log(message: str) -> None:
    with LOG_PATH.open("a") as fh:
        fh.write(f"{datetime.utcnow().isoformat()} {message}\n")


def _first_ip() -> str:
    """Return the first non-loopback IP address or 'unknown'."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        try:
            for addr in socket.gethostbyname_ex(socket.gethostname())[2]:
                if not addr.startswith("127."):
                    return addr
        except socket.gaierror:
            pass
    return "unknown"


def status() -> str:
    """Return basic system metrics."""
    cpu = os.cpu_count()
    uptime = Path("/proc/uptime").read_text().split()[0]
    ip = _first_ip()
    return f"CPU cores: {cpu}\nUptime: {uptime}s\nIP: {ip}"


def current_time() -> str:
    """Return the current UTC time."""
    return datetime.utcnow().isoformat()


def run_command(command: str) -> str:
    """Execute a shell command and return its output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        output = exc.stdout.strip() if exc.stdout else str(exc)
        return color(output, SETTINGS.red)


def clear_screen() -> str:
    """Return the control sequence that clears the terminal."""
    return "\033c"


def history(limit: int = 20) -> str:
    """Return the last ``limit`` commands from ``HISTORY_PATH``."""
    try:
        with HISTORY_PATH.open() as fh:
            lines = [line.rstrip("\n") for line in fh]
    except FileNotFoundError:
        return "no history"
    return "\n".join(lines[-limit:])


def _iter_log_lines() -> Iterable[str]:
    """Yield log lines from all log files in order."""
    for file in sorted(LOG_DIR.glob("*.log")):
        with file.open() as fh:
            for line in fh:
                yield line.rstrip("\n")


def summarize(term: str | None = None, limit: int = 5) -> str:
    """Return the last ``limit`` log lines matching ``term``."""
    if not LOG_DIR.exists():
        return "no logs"
    matches: Deque[str] = deque(maxlen=limit)
    for line in _iter_log_lines():
        if term is None or term in line:
            matches.append(line)
    return "\n".join(matches) if matches else "no matches"


ARGS: List[str] = []


def _handle_run() -> str:
    return run_command(" ".join(ARGS))


def _handle_summarize() -> str:
    parts = ARGS[:]
    limit = 5
    if parts and parts[-1].isdigit():
        limit = int(parts[-1])
        parts = parts[:-1]
    term = " ".join(parts) if parts else None
    return summarize(term, limit)


def _handle_help() -> str:
    return (
        "Commands: /status, /time, /run <cmd>, /summarize [term [limit]], "
        "/clear, /history [N]\n"
        "Config: ~/.letsgo/config for prompt and colors"
    )


def _handle_history() -> str:
    limit = int(ARGS[0]) if ARGS and ARGS[0].isdigit() else 20
    return history(limit)


def unknown_command(user: str) -> str:
    return f"echo: {user}"


COMMAND_HANDLERS: dict[str, Callable[[], str]] = {
    "/status": status,
    "/time": current_time,
    "/run": _handle_run,
    "/summarize": _handle_summarize,
    "/help": _handle_help,
    "/clear": clear_screen,
    "/history": _handle_history,
}


COMMANDS: List[str] = list(COMMAND_HANDLERS)


def main() -> None:
    global ARGS
    _ensure_log_dir()
    try:
        readline.read_history_file(str(HISTORY_PATH))
    except FileNotFoundError:
        pass
    readline.parse_and_bind("tab: complete")

    def completer(text: str, state: int) -> str | None:
        matches = [cmd for cmd in COMMANDS if cmd.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(completer)
    atexit.register(readline.write_history_file, str(HISTORY_PATH))

    log("session_start")
    print("LetsGo terminal ready. Type 'exit' to quit.")
    while True:
        try:
            user = input(color(SETTINGS.prompt, SETTINGS.cyan))
        except EOFError:
            break
        if user.strip().lower() in {"exit", "quit"}:
            break
        log(f"user:{user}")
        parts = user.split()
        if not parts:
            continue
        cmd, *args = parts
        ARGS = args
        handler = COMMAND_HANDLERS.get(cmd)
        if handler:
            reply = handler()
            if cmd == "/status":
                colored = color(reply, SETTINGS.green)
            else:
                colored = reply
        else:
            reply = unknown_command(user)
            colored = reply
        print(colored)
        log(f"letsgo:{reply}")
    log("session_end")


if __name__ == "__main__":
    main()
