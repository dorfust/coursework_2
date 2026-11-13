"""Commands only execute when the user explicitly runs them."""
# Subcommands: environment, generate, train, evaluate; their options are defined in build_parser.
import argparse
import json
import re
from .config import load_config
from .data import generate_dataset
from .provenance import environment
# Import chain: .training imports torch itself and, through .model, torch_geometric. These
# imports are executed when this module is imported, so every subcommand, "environment"
# included, is reached only after they have been executed.
from .training import train, evaluate


# Format check only: exactly 40 hexadecimal characters (re.fullmatch); the value is returned
# in lower case. It is not compared with git here.
def revision(value):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise argparse.ArgumentTypeError("record a complete 40-character git checkout SHA")
    return value.lower()


def build_parser():
    parser = argparse.ArgumentParser(description="Independent fixed-N satellite hop reconstruction")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("environment", help="print dependency/device information, no installation")
    generate = commands.add_parser("generate", help="write a new dataset directory; refuses existing path")
    generate.add_argument("--config", required=True)
    generate.add_argument("--out", required=True)
    generate.add_argument("--revision", required=True, type=revision)
    training = commands.add_parser("train", help="write a new run directory; refuses existing path")
    training.add_argument("--config", required=True)
    training.add_argument("--data", required=True)
    training.add_argument("--out", required=True)
    training.add_argument("--revision", required=True, type=revision)
    # The two commands differ in the device: train has no --device option (train() in
    # training.py takes the device from the config's train section); evaluate has --device
    # (default "cpu") and --split (default "test"). evaluate() also creates the parent
    # folders of its --out path.
    evaluation = commands.add_parser("evaluate", help="write metrics to a new JSON file")
    evaluation.add_argument("--run", required=True)
    evaluation.add_argument("--data", required=True)
    evaluation.add_argument("--split", choices=("train", "val", "test"), default="test")
    evaluation.add_argument("--device", default="cpu")
    evaluation.add_argument("--out", required=True)
    evaluation.add_argument("--revision", required=True, type=revision)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "environment":
        result = environment()
    elif args.command == "generate":
        result = generate_dataset(load_config(args.config), args.out, args.revision)
    elif args.command == "train":
        result = train(load_config(args.config), args.data, args.out, args.revision)
    else:
        result = evaluate(args.run, args.data, args.split, args.out, args.revision, args.device)
    # The whole result dict of the command is printed as JSON (indent=2, sorted keys,
    # allow_nan=False), and only after the command has returned. main returns None; this
    # function has no sys.exit and no try/except, so exceptions raised by a command are not
    # handled here.
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
