#!/usr/bin/env python3
"""Interactive console assistant for Arianna Core."""

from __future__ import annotations

import os
import socket
from datetime import datetime
from pathlib import Path
import argparse
import shlex
from collections import deque
from typing import Deque, Iterable, List

# //: each session logs to its own file in the repository root
ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "log"
SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
LOG_PATH = LOG_DIR / f"{SESSION_ID}.log"


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
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


def _iter_log_lines() -> Iterable[str]:
    """Yield log lines from all log files in order."""
    for file in sorted(LOG_DIR.glob("*.log")):
        with file.open() as fh:
            yield from (line.rstrip("\n") for line in fh)


def _parse_summarize_args(args: List[str]) -> tuple[str | None, int]:
    """Parse arguments for the ``/summarize`` command."""
    parser = argparse.ArgumentParser(prog="/summarize", add_help=False)
    parser.add_argument("term", nargs="*")
    parser.add_argument("--limit", type=int, default=5)
    try:
        ns = parser.parse_args(args)
    except SystemExit:
        return None, 5
    term = " ".join(ns.term) if ns.term else None
    return term, ns.limit


def summarize(term: str | None = None, limit: int = 5) -> str:
    """Return the last ``limit`` log lines matching ``term``."""
    if not LOG_DIR.exists():
        return "no logs"

    def _iter_matches() -> Iterable[str]:
        for line in _iter_log_lines():
            if term is None or term in line:
                yield line

    matches: Deque[str] = deque(_iter_matches(), maxlen=limit)
    return "\n".join(matches) if matches else "no matches"


def main() -> None:
    log("session_start")
    print("Arianna assistant ready. Type 'exit' to quit.")
    while True:
        try:
            user = input(">> ")
        except EOFError:
            break
        if user.strip().lower() in {"exit", "quit"}:
            break
        log(f"user:{user}")
        if user.strip() == "/status":
            reply = status()
        elif user.startswith("/summarize"):
            args = shlex.split(user)[1:]
            term, limit = _parse_summarize_args(args)
            reply = summarize(term, limit)
        else:
            reply = f"echo: {user}"
        print(reply)
        log(f"assistant:{reply}")
    log("session_end")


if __name__ == "__main__":
    main()
