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


DEFAULT_TAP_MS = 20


class BehaviorResolutionError(RuntimeError):
    pass


class EncoderClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD, _ser=None):
        if _ser is not None:
            self._ser = _ser
        else:
            target = port or rpc.find_port()
            self._ser = serial.Serial(target, baud, timeout=0.1)
        self._index: int | None = None
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "EncoderClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _next_rid(self) -> int:
        self._rid += 1
        return self._rid

    def _resolve_index(self) -> int:
        if self._index is not None:
            return self._index
        req = studio_pb2.Request()
        req.request_id = self._next_rid()
        req.custom.list_custom_subsystems.CopyFrom(custom_pb2.ListCustomSubsystemRequest())
        resp = rpc.send_recv(self._ser, req)
        css = resp.request_response.custom.list_custom_subsystems
        for sub in css.subsystems:
            if sub.identifier == SUBSYSTEM_ID:
                self._index = sub.index
                return sub.index
        raise RuntimeError(
            f"'{SUBSYSTEM_ID}' subsystem not found. "
            f"Available: {[(s.identifier, s.index) for s in css.subsystems]}"
        )

    def _call(self, rsr_req: "rsr_pb2.Request") -> "rsr_pb2.Response":
        idx = self._resolve_index()
        sreq = studio_pb2.Request()
        sreq.request_id = self._next_rid()
        sreq.custom.call.subsystem_index = idx
        sreq.custom.call.payload = rsr_req.SerializeToString()
        sresp = rpc.send_recv(self._ser, sreq)
        out = rsr_pb2.Response()
        out.ParseFromString(sresp.request_response.custom.call.payload)
        return out

    def _behavior_ids(self) -> set[int]:
        """Live behavior local_id set via the core behaviors RPC."""
        req = studio_pb2.Request()
        req.request_id = self._next_rid()
        req.behaviors.list_all_behaviors.SetInParent()
        resp = rpc.send_recv(self._ser, req)
        return set(resp.request_response.behaviors.list_all_behaviors.behaviors)

    def resolve_behavior_local_id(self, token: str) -> int:
        if token not in BEHAVIOR_DEV_NAME:
            raise BehaviorResolutionError(f"no device name known for token {token!r}")
        candidate = crc16_ansi(BEHAVIOR_DEV_NAME[token].encode())
        live = self._behavior_ids()
        if candidate in live:
            return candidate
        raise BehaviorResolutionError(
            f"crc16 id {candidate} for '{token}' ({BEHAVIOR_DEV_NAME[token]}) "
            f"not in live behavior ids {sorted(live)}. The firmware may use the "
            f"settings-table local-id mode; use 'roba encoder behaviors' to list "
            f"ids and pass 'raw <id> <param1> [param2]'."
        )

    def sensors(self) -> dict:
        return decode_response(self._call(build_get_sensors_request()))

    def get(self, sensor: int = 0) -> dict:
        return decode_response(self._call(build_get_request(sensor)))

    def behaviors(self) -> dict:
        """List live behaviors as {id, display_name} for discovery."""
        ids = sorted(self._behavior_ids())
        out = []
        for bid in ids:
            req = studio_pb2.Request()
            req.request_id = self._next_rid()
            req.behaviors.get_behavior_details.behavior_id = bid
            resp = rpc.send_recv(self._ser, req)
            d = resp.request_response.behaviors.get_behavior_details
            out.append({"id": bid, "display_name": d.display_name})
        return {"ok": True, "error": "", "behaviors": out}

    def set(self, sensor: int, layer: int, direction: str, spec: str,
            tap_ms: int | None = None) -> dict:
        token, behavior_id, param1, param2 = parse_encoder_behavior(spec)
        if token is not None:
            behavior_id = self.resolve_behavior_local_id(token)
        tms = DEFAULT_TAP_MS if tap_ms is None else tap_ms
        return decode_response(self._call(
            build_set_request(direction, sensor, layer, behavior_id, param1, param2, tms)))

    def reset(self, sensor: int, layer: int) -> dict:
        """Revert a layer: set cw and ccw behavior_id 0 -> DT-default fallback."""
        cw = decode_response(self._call(
            build_set_request("cw", sensor, layer, 0, 0, 0, DEFAULT_TAP_MS)))
        ccw = decode_response(self._call(
            build_set_request("ccw", sensor, layer, 0, 0, 0, DEFAULT_TAP_MS)))
        ok = cw.get("ok") and ccw.get("ok")
        return {"ok": bool(ok), "error": cw.get("error") or ccw.get("error", "")}
