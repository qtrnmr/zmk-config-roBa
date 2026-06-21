from __future__ import annotations

import argparse
import json
import sys

from . import connection


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def cmd_info(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    _emit({
        "lock_state": client.get_lock_state(),
        "behavior_count": len(client.list_all_behaviors()),
        "keymap_bytes": len(client.get_keymap_bytes()),
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roba")
    parser.add_argument("--port", default=None,
                        help="roBa USB serial port (default: auto-detect /dev/cu.usbmodem*)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="Show device/lock/keymap summary").set_defaults(func=cmd_info)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - CLI 境界で JSON エラーに変換
        _emit({"error": str(exc)})
        return 1


def run() -> None:
    sys.exit(main(sys.argv[1:]))
