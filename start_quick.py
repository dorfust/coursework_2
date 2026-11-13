"""Smoke test of the whole pipeline: the same as  python start.py --quick  (revision 5; not executed).

Open THIS file in VS Code and press Run Python File (or run: python start_quick.py).
It needs nothing else: it imports start.py from its own folder and calls start.main() with
the argument --quick. The numbers of a quick run are NOT results; its duration is not measured.
Extra command-line arguments, if any, are appended (for example --dry-run).
Output folder: outputs/quick_<stamp> unless --output-root is appended. The first-time setup (venv,
pip) is done when needed. sys.dont_write_bytecode is set so that no .pyc file is written for
start.py. If this Python is outside 3.10-3.14, start.main() starts start.py again with the same
arguments when a suitable Python is found; otherwise it ends with exit code 11.
"""
import sys
from pathlib import Path

ARGS = ["--quick"]


def main():
    """Import start.py from the folder of this file (no package) and run it; return its exit code."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import start
    return start.main(ARGS + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
