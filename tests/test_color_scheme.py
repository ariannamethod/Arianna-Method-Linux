import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import letsgo  # noqa: E402


def test_color_scheme_env(monkeypatch):
    monkeypatch.setenv("LETSGO_COLOR_SUCCESS", "\033[35m")
    letsgo.COLOR_SCHEME = letsgo.load_color_scheme()
    try:
        assert letsgo.color("ok", "success") == "\033[35mok\033[0m"
    finally:
        monkeypatch.delenv("LETSGO_COLOR_SUCCESS", raising=False)
        letsgo.COLOR_SCHEME = letsgo.load_color_scheme()


def test_color_scheme_file(tmp_path):
    cfg = tmp_path / ".letsgo.yaml"
    cfg.write_text("prompt: '\\033[33m'\n")
    letsgo.COLOR_SCHEME = letsgo.load_color_scheme(cfg)
    try:
        assert letsgo.color(">>", "prompt") == "\033[33m>>\033[0m"
    finally:
        letsgo.COLOR_SCHEME = letsgo.load_color_scheme()
