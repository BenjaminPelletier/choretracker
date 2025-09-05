#!/usr/bin/env python
import os
import subprocess
import sys


def main(argv: list[str]) -> int:
    os.environ.setdefault("CHORETRACKER_SECRET_KEY", "test")
    os.environ.setdefault("CHORETRACKER_DISABLE_CSRF", "1")
    cmd = [
        "uv",
        "run",
        "--with",
        "pytest",
        "--with",
        "httpx",
        "-m",
        "pytest",
        *argv,
    ]
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        raise SystemExit(
            "uv is required to run tests. See DEVELOPMENT.md for installation instructions."
        )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
