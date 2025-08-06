import os
import re
import sys
from pathlib import Path
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import letsgo  # noqa: E402


# Helper to create log files


def _write_log(log_dir: Path, name: str, lines: list[str]):
    path = log_dir / f"{name}.log"
    with path.open("w") as fh:
        for line in lines:
            fh.write(line + "\n")
    return path


def test_status_fields(monkeypatch):
    monkeypatch.setattr(letsgo, "_first_ip", lambda: "1.2.3.4")
    result = letsgo.status()
    lines = result.splitlines()
    assert len(lines) == 3
    expected_cpu = os.cpu_count()
    assert lines[0] == f"CPU cores: {expected_cpu}"
    assert re.match(r"^Uptime: \d+\.\d+s", lines[1])
    assert lines[2] == "IP: 1.2.3.4"


def test_summarize_no_logs(tmp_path, monkeypatch):
    log_dir = tmp_path / "log"
    monkeypatch.setattr(letsgo, "LOG_DIR", log_dir)
    result = letsgo.summarize("anything")
    assert result == "no logs"


def test_summarize_term_filter(tmp_path, monkeypatch):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    _write_log(log_dir, "sample", ["foo", "bar", "foo again", "baz"])
    monkeypatch.setattr(letsgo, "LOG_DIR", log_dir)
    result = letsgo.summarize("foo")
    assert result == "foo\nfoo again"


def test_current_time_format():
    stamp = letsgo.current_time()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", stamp)


def test_run_command():
    output = asyncio.run(letsgo.run_command("echo hello"))
    assert output.strip() == "hello"


def test_run_command_mock(monkeypatch):
    """Ensure run_command handles async subprocesses and emits indicator."""

    class DummyProcess:
        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(b"done\n")
            self.stdout.feed_eof()

        async def wait(self):
            return 0

        def kill(self):
            pass

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_shell(cmd, stdout=None, stderr=None):
        return DummyProcess()

    monkeypatch.setattr(
        asyncio, "create_subprocess_shell", fake_create_subprocess_shell
    )

    lines: list[str] = []

    def _cb(line: str) -> None:
        lines.append(line)

    output = asyncio.run(letsgo.run_command("whatever", _cb))
    assert output == "done"
    assert lines == ["...running", "done"]


def test_clear_screen_returns_sequence():
    assert letsgo.clear_screen() == "\033c"


def test_history_last_n(tmp_path, monkeypatch):
    hist = tmp_path / "history"
    hist.write_text("\n".join(str(i) for i in range(30)))
    monkeypatch.setattr(letsgo, "HISTORY_PATH", hist)
    assert letsgo.history().splitlines() == [str(i) for i in range(10, 30)]
    assert letsgo.history(5).splitlines() == [str(i) for i in range(25, 30)]


def test_history_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(letsgo, "HISTORY_PATH", tmp_path / "missing")
    assert letsgo.history() == "no history"


def test_log_cleanup(tmp_path, monkeypatch):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    for i in range(5):
        p = log_dir / f"{i}.log"
        p.write_text("x")
        os.utime(p, (i, i))
    monkeypatch.setattr(letsgo, "LOG_DIR", log_dir)
    monkeypatch.setattr(letsgo.SETTINGS, "max_log_files", 3)
    letsgo._ensure_log_dir()
    remaining = sorted(f.name for f in log_dir.glob("*.log"))
    assert remaining == ["2.log", "3.log", "4.log"]


def test_search_history(tmp_path, monkeypatch):
    hist = tmp_path / "history"
    hist.write_text("foo\nbar\nfoobar\n")
    monkeypatch.setattr(letsgo, "HISTORY_PATH", hist)
    result = letsgo.search_history("foo")
    assert result.splitlines() == ["foo", "foobar"]


def test_clear_command_registered(monkeypatch):
    commands = []
    handlers = {}
    letsgo.COMMAND_MAP.clear()
    letsgo.register_core(commands, handlers)
    assert "/clear" in commands

    called = {"cmd": None}

    def fake_system(cmd):
        called["cmd"] = cmd

    monkeypatch.setattr(os, "system", fake_system)
    asyncio.run(handlers["/clear"]("/clear"))
    assert called["cmd"] == "clear"


def test_help_lists_command_descriptions():
    commands = []
    handlers = {}
    letsgo.COMMAND_MAP.clear()
    letsgo.register_core(commands, handlers)
    output, _ = asyncio.run(letsgo.handle_help("/help"))
    assert "/clear" in output
    assert "clear the terminal screen" in output
    assert "usage: /clear" in output
