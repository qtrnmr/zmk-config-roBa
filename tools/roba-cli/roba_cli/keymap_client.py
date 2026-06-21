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


def req_set_layer_props(request_id: int, layer_id: int, name: str) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.set_layer_props.layer_id = layer_id
    req.keymap.set_layer_props.name = name
    return req


def req_add_layer(request_id: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.add_layer.SetInParent()  # empty AddLayerRequest selects the oneof
    return req


def req_remove_layer(request_id: int, layer_index: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.remove_layer.layer_index = layer_index
    return req


def req_move_layer(request_id: int, start_index: int, dest_index: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.move_layer.start_index = start_index
    req.keymap.move_layer.dest_index = dest_index
    return req


def req_restore_layer(request_id: int, layer_id: int, at_index: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.restore_layer.layer_id = layer_id
    req.keymap.restore_layer.at_index = at_index
    return req


def req_save_changes(request_id: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.save_changes = True
    return req


# Map the scalar-enum response fields to readable names for error reporting.
_ENUM_NAME = {
    "set_layer_binding": keymap_pb2.SetLayerBindingResponse,
    "set_layer_props": keymap_pb2.SetLayerPropsResponse,
}


def decode_status(km_resp: "keymap_pb2.Response") -> dict:
    """Normalize any keymap.Response variant to {ok, error[, index]}."""
    which = km_resp.WhichOneof("response_type")
    # Scalar enum responses (ok == 0)
    if which in _ENUM_NAME:
        val = getattr(km_resp, which)
        if val == 0:
            return {"ok": True, "error": ""}
        return {"ok": False, "error": _ENUM_NAME[which].Name(val)}
    # bool responses
    if which in ("check_unsaved_changes", "discard_changes"):
        return {"ok": bool(getattr(km_resp, which)), "error": ""}
    # oneof result{ok|err} responses
    sub = getattr(km_resp, which)
    result = sub.WhichOneof("result")
    if result == "err":
        enum_val = sub.err
        enum_desc = sub.DESCRIPTOR.fields_by_name["err"].enum_type
        return {"ok": False, "error": enum_desc.values_by_number[enum_val].name}
    out = {"ok": True, "error": ""}
    if which == "add_layer":
        out["index"] = sub.ok.index
    return out


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

    def rename(self, layer_id: int, name: str) -> dict:
        return decode_status(self._keymap_call(
            req_set_layer_props(self._next_rid(), layer_id, name)))

    def add(self) -> dict:
        return decode_status(self._keymap_call(req_add_layer(self._next_rid())))

    def remove(self, layer_index: int) -> dict:
        return decode_status(self._keymap_call(
            req_remove_layer(self._next_rid(), layer_index)))

    def move(self, start_index: int, dest_index: int) -> dict:
        return decode_status(self._keymap_call(
            req_move_layer(self._next_rid(), start_index, dest_index)))

    def restore(self, layer_id: int, at_index: int) -> dict:
        return decode_status(self._keymap_call(
            req_restore_layer(self._next_rid(), layer_id, at_index)))

    def save(self) -> dict:
        return decode_status(self._keymap_call(req_save_changes(self._next_rid())))
