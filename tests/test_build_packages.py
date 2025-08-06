import subprocess
from pathlib import Path


def _run_build(args):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "build" / "build_ariannacore.sh"
    return subprocess.check_output([str(script), *args], text=True)


def test_default_packages_exposed():
    output = _run_build(["--dry-run"])
    assert "bash" in output
    assert "curl" in output


def test_extra_packages_file(tmp_path):
    pkg_file = tmp_path / "extra.txt"
    pkg_file.write_text("git\nvim\n")
    output = _run_build(["--packages-file", str(pkg_file), "--dry-run"])
    assert "git" in output and "vim" in output
