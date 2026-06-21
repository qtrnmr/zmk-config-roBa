from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from . import behaviors
from . import connection


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


BACKUP_LOG = Path(__file__).resolve().parent.parent / ".roba-backup.jsonl"


def _append_backup(entry: dict) -> None:
    entry["ts"] = _dt.datetime.now().isoformat(timespec="seconds")
    with BACKUP_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_key_get(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    behavior = client.get_key_at(args.layer, args.position)
    _emit({"layer": args.layer, "position": args.position,
           "kind": behavior.kind, "repr": repr(behavior)})
    return 0


def cmd_key_set(args: argparse.Namespace) -> int:
    import zmk_studio_api as zmk
    client = connection.open(args.port)
    before = client.get_key_at(args.layer, args.position)
    _append_backup({"op": "set", "layer": args.layer, "position": args.position,
                    "before_kind": before.kind, "before_repr": repr(before),
                    "new": args.behavior})
    spec = behaviors.parse_behavior(args.behavior)
    client.set_key_at(args.layer, args.position, behaviors.build_behavior(spec, zmk))
    client.save_changes()
    _emit({"layer": args.layer, "position": args.position,
           "before": repr(before), "after_spec": args.behavior, "saved": True})
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    ok = client.reset_settings()
    _emit({"reset_settings": ok, "note": "nvs reverted to devicetree defaults"})
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    data = client.get_keymap_bytes()
    out = Path(args.path) if args.path else (
        BACKUP_LOG.parent / f"keymap-snapshot-{_dt.datetime.now():%Y%m%d-%H%M%S}.bin")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    _emit({"snapshot": str(out), "bytes": len(data),
           "note": "record only; full restore is via 'reset' (no set_keymap_bytes API)"})
    return 0


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
    key = sub.add_parser("key", help="Per-key get/set").add_subparsers(dest="key_cmd", required=True)
    kg = key.add_parser("get")
    kg.add_argument("layer", type=int)
    kg.add_argument("position", type=int)
    kg.set_defaults(func=cmd_key_get)
    ks = key.add_parser("set")
    ks.add_argument("layer", type=int)
    ks.add_argument("position", type=int)
    ks.add_argument("behavior", help="e.g. 'KP B', 'trans', 'MO 5'")
    ks.set_defaults(func=cmd_key_set)
    sub.add_parser("reset", help="Revert nvs to devicetree defaults").set_defaults(func=cmd_reset)
    snap = sub.add_parser("snapshot", help="Save raw keymap bytes for record")
    snap.add_argument("path", nargs="?", default=None)
    snap.set_defaults(func=cmd_snapshot)
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
