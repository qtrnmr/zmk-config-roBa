from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from . import behaviors
from . import connection
from . import macro_dsl
from .keymap_client import KeymapClient
from .rip_client import RipClient
from . import rip_client
from .holdtap_client import HoldtapClient
from . import holdtap_client
from .condlayer_client import CondlayerClient


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
    after = client.get_key_at(args.layer, args.position)
    _emit({"layer": args.layer, "position": args.position,
           "before": repr(before), "after_spec": args.behavior,
           "after_kind": after.kind, "after_repr": repr(after), "saved": True})
    return 0


def cmd_macro_get(args: argparse.Namespace) -> int:
    from .macro_client import MacroClient
    with MacroClient(args.port) as client:
        steps = client.get_macro(args.slot)
    _emit(steps)
    return 0


def cmd_macro_set(args: argparse.Namespace) -> int:
    from .macro_client import MacroClient
    steps = macro_dsl.parse(args.dsl)
    # backup: read current state first
    with MacroClient(args.port) as client:
        try:
            before = client.get_macro(args.slot)
        except Exception:  # noqa: BLE001
            before = []
        _append_backup({"op": "macro_set", "slot": args.slot,
                        "before_steps": before, "new_dsl": args.dsl})
        result = client.set_macro(args.slot, steps)
    _emit({"slot": args.slot, "steps": len(steps), "ok": result.get("ok", False),
           "error": result.get("error") or None})
    return 0 if result.get("ok") else 1


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


def cmd_layer_list(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        layers = client.get_layers()
    _emit({"layers": layers})
    return 0


def _backup_layers(client) -> None:
    """Snapshot current layers before a mutating op (for revert audit trail)."""
    try:
        layers = client.get_layers()
    except Exception:  # noqa: BLE001
        layers = None
    _append_backup({"op": "layer_mutate", "before_layers": layers})


def cmd_layer_rename(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.rename(args.layer_id, args.name)
        if res["ok"]:
            res.update(client.save())
    _emit({"op": "rename", "layer_id": args.layer_id, "name": args.name, **res})
    return 0 if res["ok"] else 1


def cmd_layer_add(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.add()
        if res["ok"]:
            res.update(client.save())
    _emit({"op": "add", **res})
    return 0 if res["ok"] else 1


def cmd_layer_remove(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.remove(args.index)
        if res["ok"]:
            res.update(client.save())
    _emit({"op": "remove", "index": args.index, **res})
    return 0 if res["ok"] else 1


def cmd_layer_move(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.move(args.start, args.dest)
        if res["ok"]:
            res.update(client.save())
    _emit({"op": "move", "start": args.start, "dest": args.dest, **res})
    return 0 if res["ok"] else 1


def cmd_layer_restore(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.restore(args.layer_id, args.at_index)
        if res["ok"]:
            res.update(client.save())
    _emit({"op": "restore", "layer_id": args.layer_id, "at_index": args.at_index, **res})
    return 0 if res["ok"] else 1


def cmd_trackball_get(args: argparse.Namespace) -> int:
    with RipClient(args.port) as client:
        res = client.get(args.id)
    _emit({"op": "trackball_get", "id": args.id, **res})
    return 0 if res["ok"] else 1


def cmd_trackball_set(args: argparse.Namespace) -> int:
    with RipClient(args.port) as client:
        before = client.get(args.id)
        _append_backup({"op": "trackball_set", "id": args.id,
                        "field": args.field, "value": args.value,
                        "before": before.get("processor")})
        res = client.set(args.field, args.id, args.value)
        after = client.get(args.id) if res["ok"] else {"processor": None}
    _emit({"op": "trackball_set", "id": args.id, "field": args.field,
           "value": args.value, "ok": res["ok"], "error": res["error"],
           "after": after.get("processor")})
    return 0 if res["ok"] else 1


def cmd_trackball_reset(args: argparse.Namespace) -> int:
    with RipClient(args.port) as client:
        before = client.get(args.id)
        _append_backup({"op": "trackball_reset", "id": args.id,
                        "before": before.get("processor")})
        res = client.reset(args.id)
        after = client.get(args.id) if res["ok"] else {"processor": None}
    _emit({"op": "trackball_reset", "id": args.id, "ok": res["ok"],
           "error": res["error"], "after": after.get("processor")})
    return 0 if res["ok"] else 1


def cmd_holdtap_list(args: argparse.Namespace) -> int:
    with HoldtapClient(args.port) as client:
        slots = client.list()
    _emit({"holdtaps": slots})
    return 0


def cmd_holdtap_get(args: argparse.Namespace) -> int:
    with HoldtapClient(args.port) as client:
        info = client.get(args.slot)
    _emit({"op": "holdtap_get", "slot": args.slot, **info})
    return 0 if info.get("found") else 1


def cmd_holdtap_set(args: argparse.Namespace) -> int:
    with HoldtapClient(args.port) as client:
        before = client.get(args.slot)
        _append_backup({"op": "holdtap_set", "slot": args.slot,
                        "field": args.field, "value": args.value, "before": before})
        res = client.set(args.slot, args.field, args.value)
        after = client.get(args.slot) if res["ok"] else {}
    _emit({"op": "holdtap_set", "slot": args.slot, "field": args.field,
           "value": args.value, "ok": res["ok"], "error": res["error"], "after": after})
    return 0 if res["ok"] else 1


def cmd_holdtap_reset(args: argparse.Namespace) -> int:
    with HoldtapClient(args.port) as client:
        before = client.get(args.slot)
        _append_backup({"op": "holdtap_reset", "slot": args.slot, "before": before})
        res = client.reset(args.slot)
        after = client.get(args.slot) if res["ok"] else {}
    _emit({"op": "holdtap_reset", "slot": args.slot, "ok": res["ok"],
           "error": res["error"], "after": after})
    return 0 if res["ok"] else 1


def cmd_condlayer_list(args: argparse.Namespace) -> int:
    with CondlayerClient(args.port) as client:
        entries = client.list()
    _emit({"condlayers": entries})
    return 0


def cmd_condlayer_get(args: argparse.Namespace) -> int:
    with CondlayerClient(args.port) as client:
        info = client.get(args.index)
    _emit({"op": "condlayer_get", "index": args.index, **info})
    return 0 if info.get("found") else 1


def cmd_condlayer_set(args: argparse.Namespace) -> int:
    with CondlayerClient(args.port) as client:
        before = client.get(args.index)
        _append_backup({"op": "condlayer_set", "index": args.index,
                        "if_csv": args.if_csv, "then": args.then, "before": before})
        res = client.set(args.index, args.if_csv, args.then)
        after = client.get(args.index) if res["ok"] else {}
    _emit({"op": "condlayer_set", "index": args.index, "if_layers": args.if_csv,
           "then_layer": args.then, "ok": res["ok"], "error": res["error"], "after": after})
    return 0 if res["ok"] else 1


def cmd_condlayer_reset(args: argparse.Namespace) -> int:
    with CondlayerClient(args.port) as client:
        before = client.get(args.index)
        _append_backup({"op": "condlayer_reset", "index": args.index, "before": before})
        res = client.reset(args.index)
        after = client.get(args.index) if res["ok"] else {}
    _emit({"op": "condlayer_reset", "index": args.index, "ok": res["ok"],
           "error": res["error"], "after": after})
    return 0 if res["ok"] else 1


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
    macro = sub.add_parser("macro", help="Runtime macro get/set").add_subparsers(
        dest="macro_cmd", required=True)
    mg = macro.add_parser("get", help="Get macro steps as JSON")
    mg.add_argument("slot", type=int)
    mg.set_defaults(func=cmd_macro_get)
    ms_p = macro.add_parser("set", help="Set macro from DSL string")
    ms_p.add_argument("slot", type=int)
    ms_p.add_argument("dsl", help='e.g. "type hello | wait 50 | C-c"')
    ms_p.set_defaults(func=cmd_macro_set)
    layer = sub.add_parser("layer", help="Layer management (Studio native)").add_subparsers(
        dest="layer_cmd", required=True)
    layer.add_parser("list", help="List layers as JSON").set_defaults(func=cmd_layer_list)
    lr = layer.add_parser("rename", help="Rename a layer by id")
    lr.add_argument("layer_id", type=int)
    lr.add_argument("name")
    lr.set_defaults(func=cmd_layer_rename)
    layer.add_parser("add", help="Add a layer (devicetree-defined free slot)").set_defaults(
        func=cmd_layer_add)
    lrm = layer.add_parser("remove", help="Remove a layer by index")
    lrm.add_argument("index", type=int)
    lrm.set_defaults(func=cmd_layer_remove)
    lm = layer.add_parser("move", help="Move a layer from start index to dest index")
    lm.add_argument("start", type=int)
    lm.add_argument("dest", type=int)
    lm.set_defaults(func=cmd_layer_move)
    lrs = layer.add_parser("restore", help="Restore a removed layer by id at index")
    lrs.add_argument("layer_id", type=int)
    lrs.add_argument("at_index", type=int)
    lrs.set_defaults(func=cmd_layer_restore)
    tb = sub.add_parser("trackball", help="Runtime trackball/pointer config (cormoran_rip)").add_subparsers(
        dest="trackball_cmd", required=True)
    tbg = tb.add_parser("get", help="Get processor state as JSON")
    tbg.add_argument("--id", type=int, default=0)
    tbg.set_defaults(func=cmd_trackball_get)
    tbs = tb.add_parser("set", help=f"Set a field. fields: {sorted(rip_client.FIELD_SPECS)}")
    tbs.add_argument("field")
    tbs.add_argument("value")
    tbs.add_argument("--id", type=int, default=0)
    tbs.set_defaults(func=cmd_trackball_set)
    tbr = tb.add_parser("reset", help="Reset processor to devicetree defaults")
    tbr.add_argument("--id", type=int, default=0)
    tbr.set_defaults(func=cmd_trackball_reset)
    ht = sub.add_parser("holdtap", help="Runtime hold-tap timing (zmk__holdtap)").add_subparsers(
        dest="holdtap_cmd", required=True)
    ht.add_parser("list", help="List all runtime hold-tap slots as JSON").set_defaults(
        func=cmd_holdtap_list)
    htg = ht.add_parser("get", help="Get one slot's timing")
    htg.add_argument("slot", type=int)
    htg.set_defaults(func=cmd_holdtap_get)
    hts = ht.add_parser("set", help=f"Set a field. fields: {sorted(holdtap_client.SET_FIELDS)}")
    hts.add_argument("slot", type=int)
    hts.add_argument("field")
    hts.add_argument("value")
    hts.set_defaults(func=cmd_holdtap_set)
    htr = ht.add_parser("reset", help="Reset a slot to devicetree defaults")
    htr.add_argument("slot", type=int)
    htr.set_defaults(func=cmd_holdtap_reset)
    cl = sub.add_parser("condlayer", help="Runtime conditional layers (zmk__condlayers)").add_subparsers(
        dest="condlayer_cmd", required=True)
    cl.add_parser("list", help="List all conditional-layer entries as JSON").set_defaults(
        func=cmd_condlayer_list)
    clg = cl.add_parser("get", help="Get one entry")
    clg.add_argument("index", type=int)
    clg.set_defaults(func=cmd_condlayer_get)
    cls = cl.add_parser("set", help="Set an entry: if-layers CSV (e.g. 1,7) + then-layer")
    cls.add_argument("index", type=int)
    cls.add_argument("if_csv", help="comma-separated layer indices, e.g. '1,7'")
    cls.add_argument("then", type=int)
    cls.set_defaults(func=cmd_condlayer_set)
    clr = cl.add_parser("reset", help="Reset an entry to devicetree defaults")
    clr.add_argument("index", type=int)
    clr.set_defaults(func=cmd_condlayer_reset)
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
