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

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

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
SCHEME_PATH = Path.home() / ".letsgo.yaml"


@dataclass
class Settings:
    prompt: str = ">> "
    max_log_files: int = 100


@dataclass
class ColorScheme:
    prompt: str = "\033[36m"
    success: str = "\033[32m"
    error: str = "\033[31m"
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


def load_color_scheme(path: Path = SCHEME_PATH) -> ColorScheme:
    scheme = ColorScheme()
    data: dict[str, str] = {}
    if yaml and path.exists():
        try:
            with path.open() as fh:
                loaded = yaml.safe_load(fh) or {}
                if isinstance(loaded, dict):
                    data = {k: str(v) for k, v in loaded.items()}
        except Exception:
            data = {}
    for key in ("prompt", "success", "error"):
        env_key = f"LETSGO_COLOR_{key.upper()}"
        value = os.getenv(env_key, data.get(key))
        if value is not None:
            value = bytes(str(value), "utf-8").decode("unicode_escape")
            setattr(scheme, key, value)
    return scheme


COLOR_SCHEME = load_color_scheme()


def color(text: str, key: str) -> str:
    code = getattr(COLOR_SCHEME, key, key)
    return f"{code}{text}{COLOR_SCHEME.reset}" if USE_COLOR and code else text


# //: each session logs to its own file under a fixed directory
LOG_DIR = Path("/arianna_core/log")
SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
LOG_PATH = LOG_DIR / f"{SESSION_ID}.log"
HISTORY_PATH = LOG_DIR / "history"

COMMANDS: List[str] = [
    "/status",
    "/time",
    "/run",
    "/summarize",
    "/clear",
    "/history",
    "/help",
    "/search",
]


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
                return color("command timed out", "error")
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=remaining
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return color("command timed out", "error")
            if not line:
                break
            decoded = line.decode().rstrip()
            output_lines.append(decoded)
            if on_line:
                on_line(decoded)
        rc = await proc.wait()
        output = "\n".join(output_lines).strip()
        if rc != 0:
            return color(output, "error")
        return output
    except Exception as exc:
        return color(str(exc), "error")


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


async def main() -> None:
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
            user = await asyncio.to_thread(
                input, color(SETTINGS.prompt, "prompt")
            )
        except EOFError:
            break
        if user.strip().lower() in {"exit", "quit"}:
            break
        log(f"user:{user}")
        if user.strip() == "/status":
            reply = status()
            colored = color(reply, "success")
        elif user.strip() == "/time":
            reply = current_time()
            colored = reply
        elif user.startswith("/run "):
            lines: list[str] = []

            def _cb(line: str) -> None:
                lines.append(line)
                print(line)

            reply = await run_command(user.partition(" ")[2], _cb)
            combined = "\n".join(lines).strip()
            colored = reply if reply != combined else None
            reply = reply if colored else combined
        elif user.strip() == "/clear":
            reply = clear_screen()
            colored = reply
        elif user.startswith("/history"):
            parts = user.split()
            limit = (
                int(parts[1])
                if len(parts) > 1 and parts[1].isdigit()
                else 20
            )
            reply = history(limit)
            colored = reply
        elif user.strip() == "/help":
            reply = (
                "Commands: /status, /time, /run <cmd>, "
                "/summarize [term [limit]] [--history], "
                "/clear, /history [N], /search <pattern>\n"
                "Config: ~/.letsgo/config for prompt, max_log_files; "
                "colors via ~/.letsgo.yaml or environment"
            )
            colored = reply
        elif user.startswith("/summarize"):
            parts = user.split()[1:]
            history_mode = False
            if "--history" in parts:
                parts.remove("--history")
                history_mode = True
            limit = 5
            if parts and parts[-1].isdigit():
                limit = int(parts[-1])
                parts = parts[:-1]
            term = " ".join(parts) if parts else None
            reply = summarize(term, limit, history=history_mode)
            colored = reply
        elif user.startswith("/search "):
            pattern = user.partition(" ")[2]
            reply = search_history(pattern)
            colored = reply
        else:
            reply = f"echo: {user}"
            colored = reply
        if colored is not None:
            print(colored)
        log(f"letsgo:{reply}")
    log("session_end")


if __name__ == "__main__":
    asyncio.run(main())
