"""CondlayerClient: runtime conditional-layers over the custom RPC `zmk__condlayers`.

2-step custom envelope (list_custom_subsystems -> resolve index -> call). All
results returned in the response. if_layers are exchanged with the host as a
list of layer indices; on the wire they are a bitmask.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import custom_pb2
from roba_cli.proto.condlayers import condlayers_pb2 as cl_pb2

from . import rpc

SUBSYSTEM_ID = "zmk__condlayers"


def layers_to_mask(layers) -> int:
    """[1, 7] -> (1<<1)|(1<<7). Accepts an iterable of layer indices."""
    mask = 0
    for layer in layers:
        mask |= (1 << int(layer))
    return mask


def mask_to_layers(mask: int) -> list[int]:
    """Bitmask -> sorted list of layer indices."""
    return [i for i in range(32) if mask & (1 << i)]


def parse_if_csv(s: str) -> int:
    """'1,7' -> mask. Empty string -> 0."""
    s = s.strip()
    if not s:
        return 0
    return layers_to_mask(int(p) for p in s.split(","))


def info_to_dict(info: "cl_pb2.CondLayerInfo") -> dict:
    return {
        "index": info.index,
        "if_layers": mask_to_layers(info.if_layers_mask),
        "if_layers_mask": info.if_layers_mask,
        "then_layer": info.then_layer,
        "found": info.found,
    }


class CondlayerClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD, _ser=None):
        if _ser is not None:
            self._ser = _ser
        else:
            self._ser = serial.Serial(port or rpc.find_port(), baud, timeout=0.1)
        self._index: int | None = None
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "CondlayerClient":
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

    def _call(self, cl_req: "cl_pb2.Request") -> "cl_pb2.Response":
        idx = self._resolve_index()
        sreq = studio_pb2.Request()
        sreq.request_id = self._next_rid()
        sreq.custom.call.subsystem_index = idx
        sreq.custom.call.payload = cl_req.SerializeToString()
        sresp = rpc.send_recv(self._ser, sreq)
        cl_resp = cl_pb2.Response()
        cl_resp.ParseFromString(sresp.request_response.custom.call.payload)
        return cl_resp

    def count(self) -> int:
        req = cl_pb2.Request()
        req.count.SetInParent()
        return self._call(req).count.count

    def get(self, index: int) -> dict:
        req = cl_pb2.Request()
        req.get.index = index
        return info_to_dict(self._call(req).get)

    def list(self) -> list[dict]:
        return [self.get(i) for i in range(self.count())]

    def set(self, index: int, if_csv: str, then_layer: int) -> dict:
        req = cl_pb2.Request()
        req.set.index = index
        req.set.if_layers_mask = parse_if_csv(if_csv)
        req.set.then_layer = then_layer
        resp = self._call(req).set
        return {"ok": bool(resp.ok), "error": resp.error}

    def reset(self, index: int) -> dict:
        req = cl_pb2.Request()
        req.reset.index = index
        resp = self._call(req).reset
        return {"ok": bool(resp.ok), "error": resp.error}
