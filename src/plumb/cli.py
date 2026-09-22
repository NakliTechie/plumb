"""plumb CLI — three subcommands, each emitting one table.

    plumb pull            reproduce data/*.csv from the public API
    plumb audit           rank topics whose ASJC parent disagrees with their neighbourhood
    plumb place           how far metadata-only classification gets, and at what precision
    plumb split           is a sink topic one community or a default bucket
"""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="plumb", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull", help="reproduce the input tables from the OpenAlex API")
    sub.add_parser("audit", help="hierarchy placement auditor")
    sub.add_parser("place", help="metadata-only topic classifier")
    sub.add_parser("split", help="sink-topic splitter")
    args = p.parse_args(argv)

    if args.cmd == "pull":
        from plumb import pull
        pull.by_year()
        pull.by_source_type()
        pull.topics()
        return 0

    print(f"plumb {args.cmd}: not built yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
