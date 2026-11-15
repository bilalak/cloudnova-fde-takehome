"""Entry point: `python -m app clean` and `python -m app ask "<question>"` (specs/api.md)."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("clean", help="run the cleaning pipeline and print the data-quality report")
    ask = sub.add_parser("ask", help="answer a plain-English question over the cleaned data")
    ask.add_argument("question", nargs="+", help="the question (quote it)")
    args = parser.parse_args(argv)

    if args.command == "clean":
        from app.clean import main as clean_main
        return clean_main()
    if args.command == "ask":
        from app.query import main as ask_main
        return ask_main(" ".join(args.question))
    return 2


if __name__ == "__main__":
    sys.exit(main())
