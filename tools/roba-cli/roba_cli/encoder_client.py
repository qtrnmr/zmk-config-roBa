"""EncoderClient: runtime sensor-rotate (encoder) config over the cormoran_rsr custom RPC.

Same 2-step custom envelope as RipClient: list_custom_subsystems -> resolve
"cormoran_rsr" index -> call(payload=rsr.Request). Pure request builders /
response decoders are unit-tested; the thin client + live behavior-id resolution
is HIL-tested.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import custom_pb2
import behaviors_pb2
from roba_cli.proto.cormoran.rsr import custom_pb2 as rsr_pb2

from . import rpc

SUBSYSTEM_ID = "cormoran_rsr"

# Device names whose crc16_ansi == the firmware behavior_local_id (CRC16 mode).
BEHAVIOR_DEV_NAME = {"kp": "key_press", "msc": "mouse_scroll"}

# msc scroll params, from dt-bindings/zmk/pointing.h (MOVE_VAL=600, SCRL_VAL=10):
#   SCRL_UP=MOVE_Y(10), SCRL_DOWN=MOVE_Y(-10), SCRL_LEFT=MOVE_X(-10), SCRL_RIGHT=MOVE_X(10)
SCRL = {
    "SCRL_UP": 10,
    "SCRL_DOWN": (-10) & 0xFFFF,                 # 65526
    "SCRL_LEFT": ((-10) & 0xFFFF) << 16,         # 4294311936
    "SCRL_RIGHT": (10 & 0xFFFF) << 16,           # 655360
}


def crc16_ansi(data: bytes) -> int:
    """CRC-16/ARC (reflected poly 0xA001, init 0x0000) — matches Zephyr crc16_ansi."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def _keycode_value(name: str) -> int:
    """Resolve a kp keycode name (or decimal) to its HID usage value."""
    if name.isdigit():
        return int(name)
    import zmk_studio_api as zmk
    val = getattr(zmk.Keycode, name.upper(), None)
    if val is None:
        raise ValueError(f"unknown keycode {name!r}")
    return int(val)


def parse_encoder_behavior(spec: str) -> tuple[str | None, int, int, int]:
    """Parse a curated behavior spec into (token, behavior_id, param1, param2).

    'kp <KEYCODE>'   -> ("kp", 0, keycode, 0)        token resolved to id later
    'msc <SCRL_x>'   -> ("msc", 0, scroll, 0)
    'raw <id> <p1> [p2]' -> (None, id, p1, p2)       explicit id, no resolution
    """
    parts = spec.split()
    if not parts:
        raise ValueError("empty behavior spec")
    head = parts[0].lower()
    rest = parts[1:]
    if head == "kp":
        if len(rest) != 1:
            raise ValueError("kp requires one keycode, e.g. 'kp C_VOL_UP'")
        return ("kp", 0, _keycode_value(rest[0]), 0)
    if head == "msc":
        if len(rest) != 1:
            raise ValueError("msc requires one scroll, e.g. 'msc SCRL_DOWN'")
        key = rest[0].upper()
        if key not in SCRL:
            raise ValueError(f"unknown scroll {rest[0]!r}; known: {sorted(SCRL)}")
        return ("msc", 0, SCRL[key], 0)
    if head == "raw":
        if len(rest) not in (2, 3):
            raise ValueError("raw requires <behavior_id> <param1> [param2]")
        bid = int(rest[0]); p1 = int(rest[1]); p2 = int(rest[2]) if len(rest) == 3 else 0
        return (None, bid, p1, p2)
    raise ValueError(f"unknown behavior spec {spec!r} (use kp/msc/raw)")


def _fill_binding(binding, behavior_id: int, param1: int, param2: int, tap_ms: int) -> None:
    binding.behavior_id = behavior_id
    binding.param1 = param1
    binding.param2 = param2
    binding.tap_ms = tap_ms


def build_set_request(direction: str, sensor: int, layer: int, behavior_id: int,
                      param1: int, param2: int, tap_ms: int) -> "rsr_pb2.Request":
    req = rsr_pb2.Request()
    if direction == "cw":
        sub = req.set_layer_cw_binding
    elif direction == "ccw":
        sub = req.set_layer_ccw_binding
    else:
        raise ValueError(f"direction must be 'cw' or 'ccw', got {direction!r}")
    sub.sensor_index = sensor
    sub.layer = layer
    _fill_binding(sub.binding, behavior_id, param1, param2, tap_ms)
    return req


def build_get_request(sensor: int) -> "rsr_pb2.Request":
    req = rsr_pb2.Request()
    req.get_all_layer_bindings.sensor_index = sensor
    return req


def build_get_sensors_request() -> "rsr_pb2.Request":
    req = rsr_pb2.Request()
    req.get_sensors.SetInParent()
    return req


def binding_to_dict(b: "rsr_pb2.Binding") -> dict:
    return {"behavior_id": b.behavior_id, "param1": b.param1,
            "param2": b.param2, "tap_ms": b.tap_ms}


def decode_response(resp: "rsr_pb2.Response") -> dict:
    which = resp.WhichOneof("response_type")
    if which is None:
        return {"ok": False, "error": "empty rsr response"}
    if which == "error":
        return {"ok": False, "error": resp.error.message}
    out = {"ok": True, "error": ""}
    if which == "get_all_layer_bindings":
        out["bindings"] = [
            {"layer": lb.layer,
             "cw": binding_to_dict(lb.cw_binding),
             "ccw": binding_to_dict(lb.ccw_binding)}
            for lb in resp.get_all_layer_bindings.bindings
        ]
    elif which == "get_sensors":
        out["sensors"] = [{"index": s.index, "name": s.name}
                          for s in resp.get_sensors.sensors]
    elif which in ("set_layer_cw_binding", "set_layer_ccw_binding"):
        out["ok"] = bool(getattr(resp, which).success)
    return out
