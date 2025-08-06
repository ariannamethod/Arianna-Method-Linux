import os
import re
import sys
import time
from pathlib import Path

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
    output = letsgo.run_command("echo hello")
    assert output.strip() == "hello"


def test_run_background_output():
    pid = letsgo.run_background("echo background")
    assert pid in letsgo.TASKS
    lines = []
    for _ in range(20):
        lines.extend(letsgo.poll_tasks())
        if not letsgo.TASKS:
            break
        time.sleep(0.05)
    assert any(line == "background" for _pid, line in lines)
