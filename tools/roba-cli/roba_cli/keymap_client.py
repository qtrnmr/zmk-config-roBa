"""KeymapClient: layer management over Studio native keymap RPC (no reflash).

Pure request builders / response decoders (unit-tested) + a thin transport
client (HIL-tested) on top of rpc.send_recv. Wraps zmk.keymap.Request in
studio.Request{keymap=...}; reads studio.Response.request_response.keymap.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import keymap_pb2

from . import rpc


def req_get_keymap(request_id: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.get_keymap = True
    return req


def parse_keymap(km: "keymap_pb2.Keymap") -> list[dict]:
    return [
        {"index": i, "id": layer.id, "name": layer.name,
         "bindings": len(layer.bindings)}
        for i, layer in enumerate(km.layers)
    ]


class KeymapClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD):
        target = port or rpc.find_port()
        self._ser = serial.Serial(target, baud, timeout=0.1)
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "KeymapClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _next_rid(self) -> int:
        self._rid += 1
        return self._rid

    def _keymap_call(self, req: "studio_pb2.Request") -> "keymap_pb2.Response":
        resp = rpc.send_recv(self._ser, req)
        return resp.request_response.keymap

    def get_layers(self) -> list[dict]:
        km_resp = self._keymap_call(req_get_keymap(self._next_rid()))
        return parse_keymap(km_resp.get_keymap)
