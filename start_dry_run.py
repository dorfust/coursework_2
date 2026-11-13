"""Check only, nothing heavy starts: the same as  python start.py --dry-run  (revision 5; not executed).

Open THIS file in VS Code and press Run Python File (or run: python start_dry_run.py).
It needs nothing else: it imports start.py from its own folder and calls start.main() with
the argument --dry-run. The first-time setup (venv, pip, torch) is still done when it is needed;
run_all.py then only checks the configuration and prints its commands.
Extra command-line arguments, if any, are appended (for example --quick).
The generated config file is still written under outputs/_start (a second one if --tbr-enumeration
is appended and the second call is reached), and the first-time setup still runs when it is needed;
run_all.py is called with --dry-run.
"""
import sys
from pathlib import Path

ARGS = ["--dry-run"]


def main():
    """Import start.py from the folder of this file (no package) and run it; return its exit code."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import start
    return start.main(ARGS + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
