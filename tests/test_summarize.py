import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import letsgo  # noqa: E402


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
    monkeypatch.setattr(letsgo, "LOG_DIR", log_dir)
    result = letsgo.summarize("match")
    expected = "\n".join(lines[-5:])
    assert result == expected


def test_tail_last_lines(tmp_path, monkeypatch):
    log_file = tmp_path / "session.log"
    lines = [str(i) for i in range(30)]
    log_file.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(letsgo, "LOG_PATH", log_file)
    assert letsgo.tail().splitlines() == lines[-20:]
    assert letsgo.tail(5).splitlines() == lines[-5:]


def test_logsearch_across_files(tmp_path, monkeypatch):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    _write_log(log_dir, "one", ["foo", "bar"])
    _write_log(log_dir, "two", ["baz foo", "qux foo"])
    monkeypatch.setattr(letsgo, "LOG_DIR", log_dir)
    result = letsgo.logsearch("foo", 2)
    assert result == "baz foo\nqux foo"
