"""Only the optional TBR_enumeration run: the same as  python start.py --tbr-enumeration --skip-main
(revision 5; not executed).

Open THIS file in VS Code and press Run Python File (or run: python start_tbr_enumeration.py).
It needs nothing else: it imports start.py from its own folder and calls start.main() with the
arguments --tbr-enumeration --skip-main. It starts a run_all.py call with the suite
configs/suite_tbr_enumeration.json (baselines only plus TBR_enumeration, with safety budgets).
Read the WORST CASE banner before waiting for it; the budgets can be changed with
--enum-call-budget N and --enum-cell-budget N (extra arguments are appended).
Output folder: outputs/tbr_enum_<stamp> unless --output-root is appended. The first-time setup is
done when needed. After a successful run the paper-style figures post-step runs. Appended --quick,
--models or --stages are refused (exit code 2). Exit code: that of run_all.py, or 13 if only the
post-step failed.
Budget defaults are 200000 expansions per call and 20000000 per cell; both options take positive
decimal integers only.
"""
import sys
from pathlib import Path

ARGS = ["--tbr-enumeration", "--skip-main"]


def main():
    """Import start.py from the folder of this file (no package) and run it; return its exit code."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import start
    return start.main(ARGS + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
