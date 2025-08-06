import os
import re
import sys
from pathlib import Path
import asyncio
import pytest

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


def test_build_prompt_uses_prompt_toolkit(monkeypatch, tmp_path):
    if not getattr(letsgo, "PT_AVAILABLE", False):
        pytest.skip("prompt_toolkit not available")
    monkeypatch.setattr(letsgo, "HISTORY_PATH", tmp_path / "history")

    class DummySession:
        def __init__(self, **kwargs):
            pass

        def prompt(self, msg):
            return "done"

    monkeypatch.setattr(letsgo, "PromptSession", lambda **kw: DummySession())
    monkeypatch.setattr(letsgo, "FileHistory", lambda path: object())
    func = letsgo._build_prompt()
    assert func() == "done"


def test_build_prompt_fallback(monkeypatch):
    monkeypatch.setattr(letsgo, "PT_AVAILABLE", False)
    monkeypatch.setattr(letsgo.readline, "read_history_file", lambda *a, **k: None)
    monkeypatch.setattr(letsgo.readline, "parse_and_bind", lambda *a, **k: None)
    monkeypatch.setattr(letsgo.readline, "set_completer", lambda *a, **k: None)
    monkeypatch.setattr(letsgo.readline, "write_history_file", lambda *a, **k: None)
    called = {}

    def fake_input(prompt):
        called["prompt"] = prompt
        return "x"

    monkeypatch.setattr("builtins.input", fake_input)
    func = letsgo._build_prompt()
    assert func() == "x"
    assert "prompt" in called
