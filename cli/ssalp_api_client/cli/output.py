from __future__ import annotations

import json
from typing import Any

import click


def print_result(result: Any, fmt: str = "pretty") -> None:
    """Print *result* to stdout in the requested format."""
    if fmt == "json":
        click.echo(json.dumps(result, indent=2, default=str))
    elif fmt == "table":
        _print_table(result)
    else:
        _print_pretty(result, indent=0)


# ── pretty ────────────────────────────────────────────────────────────────

def _print_pretty(value: Any, indent: int = 0) -> None:
    pad = "  " * indent
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                click.echo(f"{pad}{k}:")
                _print_pretty(v, indent + 1)
            else:
                click.echo(f"{pad}{k}: {v}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, (dict, list)):
                click.echo(f"{pad}[{i}]")
                _print_pretty(item, indent + 1)
            else:
                click.echo(f"{pad}- {item}")
    elif value is None:
        click.echo(f"{pad}(no data)")
    else:
        click.echo(f"{pad}{value}")


# ── table ─────────────────────────────────────────────────────────────────

def _print_table(value: Any) -> None:
    if isinstance(value, dict):
        _table_dict(value)
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        _table_list_of_dicts(value)
    else:
        _print_pretty(value)


def _table_dict(d: dict) -> None:
    if not d:
        click.echo("(empty)")
        return
    key_w = max(len(str(k)) for k in d)
    click.echo(f"{'Key':<{key_w}}  Value")
    click.echo("-" * (key_w + 2) + "-" * 20)
    for k, v in d.items():
        click.echo(f"{str(k):<{key_w}}  {v}")


def _table_list_of_dicts(rows: list[dict]) -> None:
    keys = list(rows[0].keys())
    widths = {k: max(len(str(k)), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    header = "  ".join(f"{k:<{widths[k]}}" for k in keys)
    sep = "  ".join("-" * widths[k] for k in keys)
    click.echo(header)
    click.echo(sep)
    for row in rows:
        click.echo("  ".join(f"{str(row.get(k, '')):<{widths[k]}}" for k in keys))
