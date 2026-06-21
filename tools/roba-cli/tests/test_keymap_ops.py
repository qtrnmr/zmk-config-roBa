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
