import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
from roba_cli.proto.condlayers import condlayers_pb2 as cl_pb2
from roba_cli import condlayer_client as cc
from roba_cli import cli as _cli
from roba_cli.framing import encode_frame


def test_layers_mask_roundtrip():
    assert cc.layers_to_mask([1, 7]) == (1 << 1) | (1 << 7)
    assert cc.mask_to_layers((1 << 1) | (1 << 7)) == [1, 7]
    assert cc.parse_if_csv("1,7") == (1 << 1) | (1 << 7)
    assert cc.parse_if_csv("") == 0
    assert cc.parse_if_csv(" 3 ") == (1 << 3)


def test_info_to_dict():
    info = cl_pb2.CondLayerInfo(index=2, if_layers_mask=(1 << 1) | (1 << 7),
                                then_layer=13, found=True)
    d = cc.info_to_dict(info)
    assert d["index"] == 2 and d["if_layers"] == [1, 7]
    assert d["then_layer"] == 13 and d["found"] is True


class _FakeSerial:
    def __init__(self, payload: bytes):
        self._payload = bytearray(payload)

    def write(self, b):
        pass

    def flush(self):
        pass

    def read(self, n):
        if not self._payload:
            return b""
        out = bytes(self._payload[:n])
        del self._payload[:n]
        return out


def _custom_call_frame(cl_resp: "cl_pb2.Response") -> bytes:
    sresp = studio_pb2.Response()
    sresp.request_response.request_id = 1
    sresp.request_response.custom.call.payload = cl_resp.SerializeToString()
    return encode_frame(sresp.SerializeToString())


def test_get_decodes_over_custom_envelope():
    cl_resp = cl_pb2.Response()
    cl_resp.get.index = 0
    cl_resp.get.if_layers_mask = (1 << 1) | (1 << 7)
    cl_resp.get.then_layer = 13
    cl_resp.get.found = True
    c = cc.CondlayerClient(_ser=_FakeSerial(_custom_call_frame(cl_resp)))
    c._index = 3
    d = c.get(0)
    assert d["if_layers"] == [1, 7] and d["then_layer"] == 13 and d["found"] is True


def test_count_decodes_over_custom_envelope():
    cl_resp = cl_pb2.Response()
    cl_resp.count.count = 5
    c = cc.CondlayerClient(_ser=_FakeSerial(_custom_call_frame(cl_resp)))
    c._index = 3
    assert c.count() == 5


def test_set_builds_mask_request():
    # exercise build path via a FakeSerial returning an OK set response
    cl_resp = cl_pb2.Response()
    cl_resp.set.ok = True
    c = cc.CondlayerClient(_ser=_FakeSerial(_custom_call_frame(cl_resp)))
    c._index = 3
    res = c.set(0, "1,7", 13)
    assert res["ok"] is True


def test_condlayer_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["condlayer", "set", "0", "1,7", "13"])
    assert ns.index == 0 and ns.if_csv == "1,7" and ns.then == 13
    ns2 = p.parse_args(["condlayer", "get", "2"])
    assert ns2.index == 2 and ns2.func is _cli.cmd_condlayer_get
    assert p.parse_args(["condlayer", "list"]).func is _cli.cmd_condlayer_list
    assert p.parse_args(["condlayer", "reset", "1"]).func is _cli.cmd_condlayer_reset
