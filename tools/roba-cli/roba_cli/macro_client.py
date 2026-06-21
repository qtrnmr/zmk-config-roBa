"""MacroClient: custom-envelope RPC for runtime macro get/set.

Protocol (2-step ZMK Studio custom subsystem envelope):
1. Send ListCustomSubsystemsRequest → find subsystem_index for "zmk__macros".
2. Send CallRequest{ subsystem_index, payload=macros.Request bytes } → parse macros.Response.

Wire format: ZMK Studio serial framing (SOF=0xAB, ESC=0xAC, EOF=0xAD, no XOR).
"""

from __future__ import annotations

import serial

import roba_cli.proto  # sets sys.path for proto imports
import studio_pb2
import custom_pb2
from roba_cli.proto.macros import macros_pb2
from . import rpc


class MacroClient:
    """Open the serial port and perform macro get/set over the custom-envelope RPC."""

    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD):
        target = port or rpc.find_port()
        self._ser = serial.Serial(target, baud, timeout=0.1)
        self._subsystem_index: int | None = None

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "MacroClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_index(self) -> int:
        """List custom subsystems and find the index for 'zmk__macros'."""
        if self._subsystem_index is not None:
            return self._subsystem_index

        req = studio_pb2.Request()
        req.request_id = 1
        req.custom.list_custom_subsystems.CopyFrom(custom_pb2.ListCustomSubsystemRequest())

        resp = rpc.send_recv(self._ser, req)

        rr = resp.request_response
        css_resp = rr.custom.list_custom_subsystems
        for sub in css_resp.subsystems:
            if sub.identifier == "zmk__macros":
                self._subsystem_index = sub.index
                return sub.index

        raise RuntimeError(
            f"'zmk__macros' subsystem not found. "
            f"Available: {[(s.identifier, s.index) for s in css_resp.subsystems]}"
        )

    def _call(self, macro_req: macros_pb2.Request) -> macros_pb2.Response:
        """Wrap a macros.Request in a custom CallRequest and parse the macros.Response."""
        idx = self._resolve_index()

        studio_req = studio_pb2.Request()
        studio_req.request_id = 2
        call_req = studio_req.custom.call
        call_req.subsystem_index = idx
        call_req.payload = macro_req.SerializeToString()

        resp = rpc.send_recv(self._ser, studio_req)

        call_resp = resp.request_response.custom.call
        macro_resp = macros_pb2.Response()
        macro_resp.ParseFromString(call_resp.payload)
        return macro_resp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_macro(self, slot: int) -> list[dict]:
        """Return list of step dicts for the given slot."""
        macro_req = macros_pb2.Request()
        macro_req.get_macro.slot = slot

        macro_resp = self._call(macro_req)
        steps = []
        for s in macro_resp.get_macro.steps:
            steps.append({
                "type": s.type,
                "keycode": s.keycode,
                "wait_ms": s.wait_ms,
                "tap_ms": s.tap_ms,
            })
        return steps

    def set_macro(self, slot: int, steps: list[dict]) -> dict:
        """Set steps for the given slot. Returns {ok, error}."""
        macro_req = macros_pb2.Request()
        smr = macro_req.set_macro
        smr.slot = slot
        for s in steps:
            ms = smr.steps.add()
            ms.type = s.get("type", 0)
            ms.keycode = s.get("keycode", 0)
            ms.wait_ms = s.get("wait_ms", 0)
            ms.tap_ms = s.get("tap_ms", 0)

        macro_resp = self._call(macro_req)
        sr = macro_resp.set_macro
        return {"ok": bool(sr.ok), "error": sr.error}
