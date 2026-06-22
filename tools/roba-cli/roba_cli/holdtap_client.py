"""HoldtapClient: runtime hold-tap timing over the cormoran custom RPC `zmk__holdtap`.

Same 2-step custom envelope as MacroClient/RipClient: list_custom_subsystems ->
resolve "zmk__holdtap" index -> call(payload=holdtap.Request). All results are
returned in the response (no notifications). Pure builders/decoders are
unit-tested; the thin client is HIL-tested.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import custom_pb2
from roba_cli.proto.holdtap import holdtap_pb2 as ht_pb2

from . import rpc

SUBSYSTEM_ID = "zmk__holdtap"

# flavor enum index <-> name (must match firmware enum flavor order)
FLAVORS = ["hold-preferred", "balanced", "tap-preferred", "tap-unless-interrupted"]

# settable field name -> HoldTapInfo/SetRequest attr + parser
_INT = int


def parse_flavor(s: str) -> int:
    key = s.strip().lower()
    if key in FLAVORS:
        return FLAVORS.index(key)
    raise ValueError(f"unknown flavor {s!r} (use one of {FLAVORS})")


def flavor_name(idx: int) -> str:
    return FLAVORS[idx] if 0 <= idx < len(FLAVORS) else f"unknown({idx})"


SET_FIELDS = {
    "tapping-term-ms": ("tapping_term_ms", _INT),
    "quick-tap-ms": ("quick_tap_ms", _INT),
    "require-prior-idle-ms": ("require_prior_idle_ms", _INT),
    "flavor": ("flavor", parse_flavor),
}


def info_to_dict(info: "ht_pb2.HoldTapInfo") -> dict:
    return {
        "slot": info.slot,
        "tapping_term_ms": info.tapping_term_ms,
        "quick_tap_ms": info.quick_tap_ms,
        "require_prior_idle_ms": info.require_prior_idle_ms,
        "flavor": flavor_name(info.flavor),
        "flavor_index": info.flavor,
        "found": info.found,
    }


def build_set_request(slot: int, current: "ht_pb2.HoldTapInfo", field: str, raw_value: str) \
        -> "ht_pb2.Request":
    """Build a SetRequest carrying all four fields: the edited one plus the
    current values for the rest (firmware set replaces the whole timing)."""
    if field not in SET_FIELDS:
        raise ValueError(f"unknown field {field!r}. known: {sorted(SET_FIELDS)}")
    req = ht_pb2.Request()
    s = req.set
    s.slot = slot
    s.tapping_term_ms = current.tapping_term_ms
    s.quick_tap_ms = current.quick_tap_ms
    s.require_prior_idle_ms = current.require_prior_idle_ms
    s.flavor = current.flavor
    attr, parser = SET_FIELDS[field]
    setattr(s, attr, parser(raw_value))
    return req


class HoldtapClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD, _ser=None):
        if _ser is not None:
            self._ser = _ser
        else:
            self._ser = serial.Serial(port or rpc.find_port(), baud, timeout=0.1)
        self._index: int | None = None
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "HoldtapClient":
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

    def _call(self, ht_req: "ht_pb2.Request") -> "ht_pb2.Response":
        idx = self._resolve_index()
        sreq = studio_pb2.Request()
        sreq.request_id = self._next_rid()
        sreq.custom.call.subsystem_index = idx
        sreq.custom.call.payload = ht_req.SerializeToString()
        sresp = rpc.send_recv(self._ser, sreq)
        ht_resp = ht_pb2.Response()
        ht_resp.ParseFromString(sresp.request_response.custom.call.payload)
        return ht_resp

    def count(self) -> int:
        req = ht_pb2.Request()
        req.count.SetInParent()
        return self._call(req).count.count

    def get(self, slot: int) -> dict:
        req = ht_pb2.Request()
        req.get.slot = slot
        info = self._call(req).get
        return info_to_dict(info)

    def list(self) -> list[dict]:
        return [self.get(s) for s in range(self.count())]

    def set(self, slot: int, field: str, raw_value: str) -> dict:
        req = ht_pb2.Request()
        req.get.slot = slot
        current = self._call(req).get  # read current to preserve other fields
        resp = self._call(build_set_request(slot, current, field, raw_value)).set
        return {"ok": bool(resp.ok), "error": resp.error}

    def reset(self, slot: int) -> dict:
        req = ht_pb2.Request()
        req.reset.slot = slot
        resp = self._call(req).reset
        return {"ok": bool(resp.ok), "error": resp.error}
