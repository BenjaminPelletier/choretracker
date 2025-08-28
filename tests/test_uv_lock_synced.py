import subprocess
from pathlib import Path


def test_uv_lock_up_to_date():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["uv", "lock", "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "uv.lock is not in sync with pyproject.toml:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
