"""Command-line entry point: python -m ssn_hops <command>.

The module imports main from cli (a relative import) and calls it when the module is run as a
script. The return value of main is not used here and this file sets no exit code.
"""
from .cli import main

if __name__ == "__main__":
    main()
