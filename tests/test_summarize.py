import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant  # noqa: E402


def _write_log(log_dir, name, lines):
    path = log_dir / f"{name}.log"
    with path.open("w") as fh:
        for line in lines:
            fh.write(line + "\n")
    return path


def test_summarize_large_log(tmp_path, monkeypatch):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    # create large log file with many matching lines
    lines = [f"{i} match" for i in range(10000)]
    _write_log(log_dir, "big", lines)
    monkeypatch.setattr(assistant, "LOG_DIR", log_dir)
    result = assistant.summarize("match")
    expected = "\n".join(lines[-5:])
    assert result == expected


def test_summarize_respects_limit(tmp_path, monkeypatch):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    lines = [f"{i} match" for i in range(10)]
    _write_log(log_dir, "small", lines)
    monkeypatch.setattr(assistant, "LOG_DIR", log_dir)
    result = assistant.summarize("match", limit=3)
    expected = "\n".join(lines[-3:])
    assert result == expected
