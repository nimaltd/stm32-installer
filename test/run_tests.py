#!/usr/bin/env python3
"""
Build and run the tests, then print the result.

Usage:
    python test/run_tests.py            run everything
    python test/run_tests.py -k manifest  run the tests whose name matches

Named to match the runner in the C library repositories, so the same command
works everywhere: python test/run_tests.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    try:
        import pytest  # noqa: F401
    except ImportError:
        print("pytest is not installed. Installing it now ...", flush=True)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", "pytest", "PyYAML"]
            )
        except subprocess.CalledProcessError:
            print(f"\nInstall it yourself:\n\n    {sys.executable} -m pip install pytest\n")
            return 2

    command = [sys.executable, "-m", "pytest", str(ROOT / "test"), "-v"] + sys.argv[1:]

    print(f">>> {' '.join(command)}\n", flush=True)
    code = subprocess.run(command, cwd=ROOT).returncode

    print()
    print("PASS: every test succeeded." if code == 0 else "FAIL: see the failures above.")

    return code


if __name__ == "__main__":
    sys.exit(main())
