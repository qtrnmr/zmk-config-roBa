import pytest

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import keymap_pb2

from roba_cli import keymap_client as kc


def test_req_get_keymap_wraps_in_studio_request():
    req = kc.req_get_keymap(7)
    assert req.request_id == 7
    assert req.WhichOneof("subsystem") == "keymap"
    assert req.keymap.WhichOneof("request_type") == "get_keymap"
    assert req.keymap.get_keymap is True


def test_parse_keymap_lists_layers_with_index_id_name_and_binding_count():
    km = keymap_pb2.Keymap()
    l0 = km.layers.add(); l0.id = 0; l0.name = "DEFAULT"
    l0.bindings.add(); l0.bindings.add()  # 2 bindings
    l1 = km.layers.add(); l1.id = 9; l1.name = "SETTING"
    l1.bindings.add()  # 1 binding
    out = kc.parse_keymap(km)
    assert out == [
        {"index": 0, "id": 0, "name": "DEFAULT", "bindings": 2},
        {"index": 1, "id": 9, "name": "SETTING", "bindings": 1},
    ]


def test_req_set_layer_props_fields():
    req = kc.req_set_layer_props(3, layer_id=9, name="GAME")
    assert req.request_id == 3
    assert req.keymap.WhichOneof("request_type") == "set_layer_props"
    assert req.keymap.set_layer_props.layer_id == 9
    assert req.keymap.set_layer_props.name == "GAME"


def test_req_move_and_remove_and_restore_fields():
    m = kc.req_move_layer(1, 2, 5).keymap.move_layer
    assert (m.start_index, m.dest_index) == (2, 5)
    r = kc.req_remove_layer(1, 4).keymap.remove_layer
    assert r.layer_index == 4
    rs = kc.req_restore_layer(1, 9, 3).keymap.restore_layer
    assert (rs.layer_id, rs.at_index) == (9, 3)


def test_req_add_layer_and_save_changes():
    assert kc.req_add_layer(1).keymap.WhichOneof("request_type") == "add_layer"
    sc = kc.req_save_changes(1)
    assert sc.keymap.WhichOneof("request_type") == "save_changes"
    assert sc.keymap.save_changes is True


def test_decode_status_set_layer_props_ok_and_err():
    ok = keymap_pb2.Response()
    ok.set_layer_props = keymap_pb2.SET_LAYER_PROPS_RESP_OK
    assert kc.decode_status(ok) == {"ok": True, "error": ""}
    err = keymap_pb2.Response()
    err.set_layer_props = keymap_pb2.SET_LAYER_PROPS_RESP_ERR_INVALID_ID
    d = kc.decode_status(err)
    assert d["ok"] is False and "INVALID_ID" in d["error"]


def test_decode_status_add_layer_ok_returns_index():
    resp = keymap_pb2.Response()
    resp.add_layer.ok.index = 12
    d = kc.decode_status(resp)
    assert d["ok"] is True and d.get("index") == 12


def test_decode_status_save_changes_err():
    resp = keymap_pb2.Response()
    resp.save_changes.err = keymap_pb2.SAVE_CHANGES_ERR_NO_SPACE
    d = kc.decode_status(resp)
    assert d["ok"] is False and "NO_SPACE" in d["error"]


def test_decode_status_save_changes_ok_false():
    """save_changes.ok is a bool; False should report failure."""
    resp = keymap_pb2.Response()
    resp.save_changes.ok = False
    d = kc.decode_status(resp)
    assert d["ok"] is False and d["error"] == "SAVE_CHANGES_ERR_GENERIC"


def test_decode_status_empty_response_raises():
    """Empty Response (no response_type set) should raise ValueError."""
    resp = keymap_pb2.Response()
    with pytest.raises(ValueError, match="empty keymap response"):
        kc.decode_status(resp)
