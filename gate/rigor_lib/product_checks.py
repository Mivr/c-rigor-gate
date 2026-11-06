"""Registers the product-check subcommands: `facts` and `buckfiles` (task T004)."""

from rigor_lib import buckfiles, facts_cmd


def add_parser(subparsers):
    facts_cmd.add_parser(subparsers)
    buckfiles.add_parser(subparsers)
