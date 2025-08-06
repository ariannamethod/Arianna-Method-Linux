#!/usr/bin/env python3
"""Interactive console terminal for Arianna Core."""

from __future__ import annotations

import os
import socket
import sys
import readline
import atexit
import asyncio
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import Callable, Deque, Iterable, List
from dataclasses import dataclass
import re

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
    max_log_files: int = 100


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
                    attr = getattr(settings, key)
                    if isinstance(attr, int):
                        try:
                            value = int(value)
                        except ValueError:
                            continue
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

# Mapping between a command string and its handler function.
# Each handler accepts the argument portion of the user input and returns a
# string response.
COMMAND_MAP: dict[str, Callable[[str], str]] = {}


def _ensure_log_dir() -> None:
    """Ensure that the log directory exists and is writable."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not os.access(LOG_DIR, os.W_OK):
        print(f"No write permission for {LOG_DIR}", file=sys.stderr)
        raise SystemExit(1)
    max_files = getattr(SETTINGS, "max_log_files", 0)
    if max_files > 0:
        logs = sorted(
            LOG_DIR.glob("*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in logs[max_files:]:
            try:
                old.unlink()
            except OSError:
                pass


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


async def run_command(
    command: str, on_line: Callable[[str], None] | None = None
) -> str:
    """Execute ``command`` and return its output.

    If ``on_line`` is provided, it is called with each line of output as it
    becomes available. A 10‑second timeout is enforced and any error output is
    colored red.
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output_lines: list[str] = []
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            remaining = 10 - (loop.time() - start)
            if remaining <= 0:
                proc.kill()
                await proc.communicate()
                return color("command timed out", SETTINGS.red)
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=remaining
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return color("command timed out", SETTINGS.red)
            if not line:
                break
            decoded = line.decode().rstrip()
            output_lines.append(decoded)
            if on_line:
                on_line(decoded)
        rc = await proc.wait()
        output = "\n".join(output_lines).strip()
        if rc != 0:
            return color(output, SETTINGS.red)
        return output
    except Exception as exc:
        return color(str(exc), SETTINGS.red)


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


def summarize(
    term: str | None = None,
    limit: int = 5,
    history: bool = False,
) -> str:
    """Return the last ``limit`` lines matching ``term``.

    If ``history`` is True, search command history instead of log files.
    ``term`` is treated as a regular expression.
    """
    if history:
        try:
            with HISTORY_PATH.open() as fh:
                iterable = (line.rstrip("\n") for line in fh)
                lines = list(iterable)
        except FileNotFoundError:
            return "no history"
    else:
        if not LOG_DIR.exists():
            return "no logs"
        lines = list(_iter_log_lines())
    try:
        pattern = re.compile(term) if term else None
    except re.error:
        return "invalid pattern"
    matches: Deque[str] = deque(maxlen=limit)
    for line in lines:
        if pattern is None or pattern.search(line):
            matches.append(line)
    return "\n".join(matches) if matches else "no matches"


def search_history(pattern: str) -> str:
    """Return all history lines matching ``pattern`` as regex."""
    try:
        with HISTORY_PATH.open() as fh:
            lines = [line.rstrip("\n") for line in fh]
    except FileNotFoundError:
        return "no history"
    try:
        regex = re.compile(pattern)
    except re.error:
        return "invalid pattern"
    matches = [line for line in lines if regex.search(line)]
    return "\n".join(matches) if matches else "no matches"


# ---------------------------------------------------------------------------
# Command handlers


def _cmd_status(_: str) -> str:
    return color(status(), SETTINGS.green)


def _cmd_time(_: str) -> str:
    return current_time()


def _cmd_run(args: str) -> str:
    return asyncio.run(run_command(args))


def _cmd_summarize(args: str) -> str:
    parts = args.split()
    history_mode = False
    if "--history" in parts:
        parts.remove("--history")
        history_mode = True
    limit = 5
    if parts and parts[-1].isdigit():
        limit = int(parts[-1])
        parts = parts[:-1]
    term = " ".join(parts) if parts else None
    return summarize(term, limit, history=history_mode)


def _cmd_clear(_: str) -> str:
    return clear_screen()


def _cmd_history(arg: str) -> str:
    limit = int(arg) if arg.strip().isdigit() else 20
    return history(limit)


def _cmd_help(_: str) -> str:
    return (
        "Commands: /status, /time, /run <cmd>, "
        "/summarize [term [limit]] [--history], "
        "/clear, /history [N], /search <pattern>\n"
        "Config: ~/.letsgo/config for prompt, colors, max_log_files"
    )


def _cmd_search(pattern: str) -> str:
    return search_history(pattern)


# Register command handlers
COMMAND_MAP["/status"] = _cmd_status
COMMAND_MAP["/time"] = _cmd_time
COMMAND_MAP["/run"] = _cmd_run
COMMAND_MAP["/summarize"] = _cmd_summarize
COMMAND_MAP["/clear"] = _cmd_clear
COMMAND_MAP["/history"] = _cmd_history
COMMAND_MAP["/help"] = _cmd_help
COMMAND_MAP["/search"] = _cmd_search

# List of commands for tab completion
COMMANDS: List[str] = list(COMMAND_MAP)


def main() -> None:
    _ensure_log_dir()
    try:
        readline.read_history_file(str(HISTORY_PATH))
    except FileNotFoundError:
        pass
    readline.parse_and_bind("tab: complete")

    def completer(text: str, state: int) -> str | None:
        buffer = readline.get_line_buffer()
        if buffer.startswith("/run "):
            path = Path(text)
            directory = path.parent if path.parent != Path(".") else Path(".")
            try:
                entries = os.listdir(directory)
            except OSError:
                matches: list[str] = []
            else:
                matches = [
                    str(directory / entry) if directory != Path(".") else entry
                    for entry in entries
                    if entry.startswith(path.name)
                ]
        else:
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
        if user.startswith("/"):
            cmd, _, args = user.partition(" ")
            handler = COMMAND_MAP.get(cmd)
            if handler:
                reply = handler(args)
            else:
                reply = color(f"unknown command: {cmd}", SETTINGS.red)
        else:
            reply = f"echo: {user}"
        print(reply)
        log(f"letsgo:{reply}")
    log("session_end")


if __name__ == "__main__":
    main()
