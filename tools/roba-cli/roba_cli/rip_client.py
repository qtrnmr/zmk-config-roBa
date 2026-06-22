"""RipClient: runtime trackball/pointer config over the cormoran_rip custom RPC.

Same 2-step custom envelope as MacroClient: list_custom_subsystems -> resolve
"cormoran_rip" index -> call(payload=rip.Request). Pure request builders /
response decoders are unit-tested; the thin client is HIL-tested.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import custom_pb2
from roba_cli.proto.cormoran.rip import custom_pb2 as rip_pb2

from . import rpc

SUBSYSTEM_ID = "cormoran_rip"


def _parse_bool(s: str) -> bool:
    v = s.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected boolean, got {s!r}")


def _parse_axis_snap(s: str) -> int:
    key = "AXIS_SNAP_MODE_" + s.strip().upper()
    try:
        return rip_pb2.AxisSnapMode.Value(key)
    except ValueError:
        raise ValueError(f"unknown axis-snap-mode {s!r} (use none|x|y)")


# field name -> (request oneof attr, value sub-field, parser)
FIELD_SPECS = {
    "scale-multiplier":            ("set_scale_multiplier", "value", int),
    "scale-divisor":               ("set_scale_divisor", "value", int),
    "rotation":                    ("set_rotation", "value", int),
    "x-invert":                    ("set_x_invert", "invert", _parse_bool),
    "y-invert":                    ("set_y_invert", "invert", _parse_bool),
    "xy-swap":                     ("set_xy_swap_enabled", "enabled", _parse_bool),
    "xy-to-scroll":                ("set_xy_to_scroll_enabled", "enabled", _parse_bool),
    "axis-snap-mode":              ("set_axis_snap_mode", "mode", _parse_axis_snap),
    "axis-snap-threshold":         ("set_axis_snap_threshold", "threshold", int),
    "axis-snap-timeout":           ("set_axis_snap_timeout", "timeout_ms", int),
    "temp-layer-enabled":          ("set_temp_layer_enabled", "enabled", _parse_bool),
    "temp-layer-layer":            ("set_temp_layer_layer", "layer", int),
    "temp-layer-activation-delay": ("set_temp_layer_activation_delay", "activation_delay_ms", int),
    "temp-layer-deactivation-delay": ("set_temp_layer_deactivation_delay", "deactivation_delay_ms", int),
    "active-layers":               ("set_active_layers", "layers", int),
}


def build_set_request(field: str, id: int, raw_value: str) -> "rip_pb2.Request":
    if field not in FIELD_SPECS:
        raise ValueError(f"unknown field {field!r}. known: {sorted(FIELD_SPECS)}")
    oneof_attr, value_attr, parser = FIELD_SPECS[field]
    req = rip_pb2.Request()
    sub = getattr(req, oneof_attr)
    sub.id = id
    setattr(sub, value_attr, parser(raw_value))
    return req


def build_get_request(id: int) -> "rip_pb2.Request":
    req = rip_pb2.Request()
    req.get_input_processor.id = id
    return req


def build_reset_request(id: int) -> "rip_pb2.Request":
    req = rip_pb2.Request()
    req.reset_input_processor.id = id
    return req


def info_to_dict(info: "rip_pb2.InputProcessorInfo") -> dict:
    return {f.name: getattr(info, f.name) for f in info.DESCRIPTOR.fields}


def decode_response(resp: "rip_pb2.Response") -> dict:
    which = resp.WhichOneof("response_type")
    if which is None:
        return {"ok": False, "error": "empty rip response"}
    if which == "error":
        return {"ok": False, "error": resp.error.message}
    out = {"ok": True, "error": ""}
    if which == "get_input_processor":
        out["processor"] = info_to_dict(resp.get_input_processor.processor)
    return out


class RipClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD):
        target = port or rpc.find_port()
        self._ser = serial.Serial(target, baud, timeout=0.1)
        self._index: int | None = None
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "RipClient":
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

    def _call(self, rip_req: "rip_pb2.Request") -> "rip_pb2.Response":
        idx = self._resolve_index()
        sreq = studio_pb2.Request()
        sreq.request_id = self._next_rid()
        sreq.custom.call.subsystem_index = idx
        sreq.custom.call.payload = rip_req.SerializeToString()
        sresp = rpc.send_recv(self._ser, sreq)
        rip_resp = rip_pb2.Response()
        rip_resp.ParseFromString(sresp.request_response.custom.call.payload)
        return rip_resp

    def get(self, id: int = 0) -> dict:
        return decode_response(self._call(build_get_request(id)))

    def set(self, field: str, id: int, raw_value: str) -> dict:
        return decode_response(self._call(build_set_request(field, id, raw_value)))

    def reset(self, id: int = 0) -> dict:
        return decode_response(self._call(build_reset_request(id)))
