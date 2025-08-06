#!/usr/bin/env python3
"""Interactive console assistant for Arianna Core."""

from __future__ import annotations

import os
import socket
import sys
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import Deque, Iterable
import ast
import operator as op

# //: each session logs to its own file under a fixed directory
LOG_DIR = Path("/arianna_core/log")
SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
LOG_PATH = LOG_DIR / f"{SESSION_ID}.log"


def _ensure_log_dir() -> None:
    """Verify that the log directory exists and is writable."""
    if not LOG_DIR.exists():
        print(f"Log directory {LOG_DIR} does not exist", file=sys.stderr)
        raise SystemExit(1)
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


def time_now() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.utcnow().isoformat()


_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.USub: op.neg,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def calc(expr: str) -> str:
    """Evaluate a basic arithmetic expression safely."""
    try:
        node = ast.parse(expr, mode="eval").body
        return str(_eval(node))
    except Exception as exc:  # pragma: no cover - error path
        return f"error: {exc}"


def main() -> None:
    _ensure_log_dir()
    log("session_start")
    print("Arianna letsgo ready. Type 'exit' to quit.")
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
        elif user.strip() == "/time":
            reply = time_now()
        elif user.startswith("/calc"):
            expr = user.partition(" ")[2]
            reply = calc(expr)
        elif user.startswith("/summarize"):
            parts = user.split()[1:]
            limit = 5
            if parts and parts[-1].isdigit():
                limit = int(parts[-1])
                parts = parts[:-1]
            term = " ".join(parts) if parts else None
            reply = summarize(term, limit)
        else:
            reply = f"echo: {user}"
        print(reply)
        log(f"assistant:{reply}")
    log("session_end")


if __name__ == "__main__":
    main()
