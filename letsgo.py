#!/usr/bin/env python3
"""Interactive console terminal for Arianna Core."""

from __future__ import annotations

import os
import socket
import sys
import readline
import atexit
import asyncio
import importlib
import pkgutil
import importlib.metadata as importlib_metadata
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import (
    Awaitable,
    Callable,
    Deque,
    Dict,
    Iterable,
    List,
    Tuple,
)
from dataclasses import dataclass, field
import re

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - fallback for older Pythons
    import tomli as tomllib

_NO_COLOR_FLAG = "--no-color"


APP_NAME = "LetsGo"
try:
    APP_VERSION = importlib_metadata.version("letsgo")
except importlib_metadata.PackageNotFoundError:
    APP_VERSION = None


# Configuration
CONFIG_PATH = Path(
    os.getenv("LETSGO_CONFIG", str(Path.home() / ".letsgo.toml"))
).expanduser()

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "green": "\033[32m",
        "red": "\033[31m",
        "cyan": "\033[36m",
        "reset": "\033[0m",
    },
    "light": {
        "green": "\033[92m",
        "red": "\033[91m",
        "cyan": "\033[94m",
        "reset": "\033[0m",
    },
}


@dataclass
class Settings:
    prompt: str = ">> "
    theme: str = "dark"
    use_color: bool = True
    max_log_files: int = 100
    colors: Dict[str, str] = field(default_factory=lambda: THEMES["dark"].copy())


def _load_settings(path: Path = CONFIG_PATH) -> Settings:
    settings = Settings()
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return settings

    if isinstance(data.get("prompt"), str):
        settings.prompt = data["prompt"]

    if isinstance(data.get("theme"), str) and data["theme"] in THEMES:
        settings.theme = data["theme"]
        settings.colors = THEMES[settings.theme].copy()

    if isinstance(data.get("use_color"), bool):
        settings.use_color = data["use_color"]

    if isinstance(data.get("max_log_files"), int):
        settings.max_log_files = data["max_log_files"]

    colors = data.get("colors")
    if isinstance(colors, dict):
        for name, value in colors.items():
            if isinstance(value, str):
                settings.colors[name] = bytes(value, "utf-8").decode("unicode_escape")

    return settings


SETTINGS = _load_settings()


def _determine_use_color(settings: Settings) -> bool:
    disabled = (
        os.getenv("LETSGO_NO_COLOR") is not None
        or os.getenv("NO_COLOR") is not None
        or not settings.use_color
        or _NO_COLOR_FLAG in sys.argv
    )
    if _NO_COLOR_FLAG in sys.argv:
        sys.argv.remove(_NO_COLOR_FLAG)
    return not disabled


USE_COLOR = _determine_use_color(SETTINGS)


def color(text: str, name: str, theme: str | None = None) -> str:
    theme_name = theme or SETTINGS.theme
    codes = THEMES.get(theme_name, THEMES["dark"]).copy()
    if theme_name == SETTINGS.theme:
        codes.update(SETTINGS.colors)
    if name.startswith("\033"):
        code = name
    else:
        code = codes.get(name, "")
    reset = codes.get("reset", "")
    return f"{code}{text}{reset}" if USE_COLOR else text


# //: each session logs to its own file under a fixed directory
LOG_DIR = Path("/arianna_core/log")
SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
LOG_PATH = LOG_DIR / f"{SESSION_ID}.log"
HISTORY_PATH = LOG_DIR / "history"

Handler = Callable[[str], Awaitable[Tuple[str, str | None]]]
COMMANDS: List[str] = []
COMMAND_HANDLERS: Dict[str, Handler] = {}
COMMAND_MAP: Dict[str, Tuple[Handler, str]] = {}


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


async def async_input(prompt: str) -> str:
    """Async wrapper around ``input``."""
    return await asyncio.to_thread(input, prompt)


async def run_command(
    command: str, on_line: Callable[[str], None] | None = None
) -> str:
    """Execute ``command`` and return its output.

    If ``on_line`` is provided, it is called with each line of output as it
    becomes available. A 10‑second timeout is enforced and any error output is
    colored red.
    """
    try:
        if on_line:
            on_line("...running")
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
                return color("command timed out", "red")
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return color("command timed out", "red")
            if not line:
                break
            decoded = line.decode().rstrip()
            output_lines.append(decoded)
            if on_line:
                on_line(decoded)
        rc = await proc.wait()
        output = "\n".join(output_lines).strip()
        if rc != 0:
            return color(output, "red")
        return output
    except Exception as exc:
        return color(str(exc), "red")


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


def show_history() -> str:
    """Return the entire command history."""
    try:
        with HISTORY_PATH.open() as fh:
            return fh.read()
    except FileNotFoundError:
        return "no history"


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


async def handle_status(_: str) -> Tuple[str, str | None]:
    reply = status()
    return reply, color(reply, "green")


async def handle_time(_: str) -> Tuple[str, str | None]:
    reply = current_time()
    return reply, reply


async def handle_run(user: str) -> Tuple[str, str | None]:
    command = user.partition(" ")[2]
    lines: list[str] = []

    def _cb(line: str) -> None:
        lines.append(line)
        print(line)

    reply = await run_command(command, _cb)
    combined = "\n".join(lines).strip()
    colored = reply if reply != combined else None
    reply = reply if colored else combined
    return reply, colored


async def handle_clear(_: str) -> Tuple[str, str | None]:
    os.system("clear")
    return "", None


async def handle_history(user: str) -> Tuple[str, str | None]:
    parts = user.split()
    if len(parts) > 1 and parts[1].isdigit():
        reply = history(int(parts[1]))
    else:
        reply = show_history()
    return reply, reply


async def handle_help(_: str) -> Tuple[str, str | None]:
    lines = [f"{cmd} - {desc}" for cmd, (_, desc) in sorted(COMMAND_MAP.items())]
    reply = "\n".join(lines)
    return reply, reply


async def handle_summarize(user: str) -> Tuple[str, str | None]:
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
    return reply, reply


async def handle_search(user: str) -> Tuple[str, str | None]:
    pattern = user.partition(" ")[2]
    reply = search_history(pattern)
    return reply, reply


def register_core(commands: List[str], handlers: Dict[str, Handler]) -> None:
    core_commands = {
        "/status": (handle_status, "show basic system metrics"),
        "/time": (handle_time, "show current UTC time"),
        "/run": (handle_run, "run a shell command"),
        "/summarize": (handle_summarize, "summarize log entries"),
        "/clear": (handle_clear, "clear the terminal screen"),
        "/history": (handle_history, "show command history"),
        "/help": (handle_help, "show this help message"),
        "/search": (handle_search, "search command history"),
    }
    commands.extend(core_commands.keys())
    handlers.update({cmd: func for cmd, (func, _) in core_commands.items()})
    COMMAND_MAP.update(core_commands)


def _load_plugins(commands: List[str], handlers: Dict[str, Handler]) -> None:
    plugin_dir = Path(__file__).with_name("plugins")
    if not plugin_dir.exists():
        return
    for module_info in pkgutil.iter_modules([str(plugin_dir)]):
        module = importlib.import_module(f"plugins.{module_info.name}")
        if hasattr(module, "register"):
            module.register(commands, handlers)


async def main() -> None:
    _ensure_log_dir()
    try:
        readline.read_history_file(str(HISTORY_PATH))
    except FileNotFoundError:
        pass

    COMMANDS.clear()
    COMMAND_HANDLERS.clear()
    register_core(COMMANDS, COMMAND_HANDLERS)
    _load_plugins(COMMANDS, COMMAND_HANDLERS)
    command_summary = " ".join(sorted(COMMAND_MAP))

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
    version = f" v{APP_VERSION}" if APP_VERSION else ""
    header = f"{APP_NAME}{version}"
    print(color(header, "green"))
    print(color("Commands:", "cyan"), command_summary)
    print("Type 'exit' to quit.")
    while True:
        try:
            user = await async_input(color(SETTINGS.prompt, "cyan"))
        except EOFError:
            break
        if user.strip().lower() in {"exit", "quit"}:
            break
        log(f"user:{user}")
        base = user.split()[0]
        handler = COMMAND_HANDLERS.get(base)
        if handler:
            reply, colored = await handler(user)
        else:
            reply = f"Unknown command: {base}. Try /help for guidance."
            colored = color(reply, "red")
        if colored is not None:
            print(colored)
        log(f"letsgo:{reply}")
    log("session_end")


if __name__ == "__main__":
    asyncio.run(main())
