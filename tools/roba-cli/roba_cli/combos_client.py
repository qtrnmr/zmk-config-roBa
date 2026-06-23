"""CombosClient: runtime combo config over the zmk__combos custom RPC.

Same 2-step custom envelope as EncoderClient / CondlayerClient:
  list_custom_subsystems -> resolve "zmk__combos" index -> call(payload=combos.Request).
Pure request builders / response decoders are unit-tested; the thin client +
live behavior-id resolution is HIL-tested.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import custom_pb2
from roba_cli.proto.zmk.combos import combos_pb2 as cb_pb2

from . import rpc
from .behavior_resolve import (
    parse_behavior_spec,
    resolve_local_id,
)
from .condlayer_client import layers_to_mask, mask_to_layers

SUBSYSTEM_ID = "zmk__combos"


# ---------------------------------------------------------------------------
# Pure request builders (unit-tested)
# ---------------------------------------------------------------------------

def build_count_request() -> cb_pb2.Request:
    req = cb_pb2.Request()
    req.count.SetInParent()
    return req


def build_get_request(index: int) -> cb_pb2.Request:
    req = cb_pb2.Request()
    req.get.index = index
    return req


def build_reset_request(index: int) -> cb_pb2.Request:
    req = cb_pb2.Request()
    req.reset.index = index
    return req


def build_set_request(index: int, field: str, value, *,
                      behavior_id: int = 0, p1: int = 0, p2: int = 0) -> cb_pb2.Request:
    """Build a SetRequest for a combo field.

    field values:
      'binding'               -> SetRequest.binding{behavior_id, param1, param2}
                                 (value ignored; use behavior_id/p1/p2 kwargs)
      'timeout-ms'            -> SetRequest.timeout_ms (int)
      'require-prior-idle-ms' -> SetRequest.require_prior_idle_ms (int)
      'layers'                -> SetRequest.layer_mask (from CSV string or int mask)
      'slow-release'          -> SetRequest.slow_release (bool; 'true'/'false'/bool)
    """
    req = cb_pb2.Request()
    s = req.set
    s.index = index

    if field == "binding":
        s.binding.behavior_id = behavior_id
        s.binding.param1 = p1
        s.binding.param2 = p2
    elif field == "timeout-ms":
        s.timeout_ms = int(value)
    elif field == "require-prior-idle-ms":
        s.require_prior_idle_ms = int(value)
    elif field == "layers":
        if isinstance(value, int):
            s.layer_mask = value
        else:
            s.layer_mask = layers_to_mask(int(p) for p in str(value).split(","))
    elif field == "slow-release":
        if isinstance(value, bool):
            s.slow_release = value
        else:
            s.slow_release = str(value).strip().lower() in ("true", "1", "yes")
    else:
        raise ValueError(
            f"unknown field {field!r}; valid: binding, timeout-ms, "
            f"require-prior-idle-ms, layers, slow-release")

    return req


# ---------------------------------------------------------------------------
# Response decoders
# ---------------------------------------------------------------------------

def info_to_dict(info: cb_pb2.ComboInfo) -> dict:
    """ComboInfo -> plain dict with both layer_mask (int) and layers (list)."""
    binding = info.binding
    return {
        "index": info.index,
        "key_positions": list(info.key_positions),
        "binding": {
            "behavior_id": binding.behavior_id,
            "param1": binding.param1,
            "param2": binding.param2,
        },
        "timeout_ms": info.timeout_ms,
        "require_prior_idle_ms": info.require_prior_idle_ms,
        "layer_mask": info.layer_mask,
        "layers": mask_to_layers(info.layer_mask),
        "slow_release": info.slow_release,
        "found": info.found,
    }


def decode_response(resp: cb_pb2.Response) -> dict:
    """Decode a combos Response into a plain dict with 'ok' and type-specific fields."""
    which = resp.WhichOneof("response_type")
    if which is None:
        return {"ok": False, "error": "empty combos response"}
    if which == "count":
        return {"ok": True, "error": "", "count": resp.count.count}
    if which == "get":
        return {"ok": True, "error": "", "info": info_to_dict(resp.get.info)}
    if which == "set":
        ok = bool(resp.set.ok)
        return {"ok": ok, "error": "" if ok else "set failed"}
    if which == "reset":
        ok = bool(resp.reset.ok)
        return {"ok": ok, "error": "" if ok else "reset failed"}
    return {"ok": False, "error": f"unknown response_type: {which}"}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class CombosClient:
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

    def __enter__(self) -> "CombosClient":
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

    def _call(self, cb_req: cb_pb2.Request) -> cb_pb2.Response:
        idx = self._resolve_index()
        sreq = studio_pb2.Request()
        sreq.request_id = self._next_rid()
        sreq.custom.call.subsystem_index = idx
        sreq.custom.call.payload = cb_req.SerializeToString()
        sresp = rpc.send_recv(self._ser, sreq)
        out = cb_pb2.Response()
        out.ParseFromString(sresp.request_response.custom.call.payload)
        return out

    def _behavior_ids(self) -> set[int]:
        """Live behavior local_id set via the core behaviors RPC."""
        req = studio_pb2.Request()
        req.request_id = self._next_rid()
        req.behaviors.list_all_behaviors = True
        resp = rpc.send_recv(self._ser, req)
        return set(resp.request_response.behaviors.list_all_behaviors.behaviors)

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

    def count(self) -> int:
        return self._call(build_count_request()).count.count

    def get(self, index: int) -> dict:
        return decode_response(self._call(build_get_request(index)))

    def list(self) -> list[dict]:
        return [self.get(i) for i in range(self.count())]

    def set(self, index: int, field: str, value) -> dict:
        """Set a combo field.

        For 'binding', value is a behavior spec string (e.g. 'kp ESC' or 'raw 14 41 0').
        For 'layers', value is a CSV of layer indices (e.g. '1,7').
        For other fields, value is the scalar value.
        """
        if field == "binding":
            token, behavior_id, p1, p2 = parse_behavior_spec(str(value))
            if token is not None:
                behavior_id = resolve_local_id(self.behaviors()["behaviors"], token)
            req = build_set_request(index, "binding", value,
                                    behavior_id=behavior_id, p1=p1, p2=p2)
        else:
            req = build_set_request(index, field, value)
        return decode_response(self._call(req))

    def reset(self, index: int) -> dict:
        return decode_response(self._call(build_reset_request(index)))
