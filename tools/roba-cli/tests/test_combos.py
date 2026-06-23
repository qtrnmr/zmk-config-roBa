import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.zmk.combos import combos_pb2 as cb_pb2
from roba_cli import behavior_resolve as br


def test_combos_proto_fields():
    req = cb_pb2.Request()
    assert {"count", "get", "set", "reset"} <= {f.name for f in req.DESCRIPTOR.fields}
    info = cb_pb2.ComboInfo()
    assert {"index", "key_positions", "binding", "timeout_ms",
            "require_prior_idle_ms", "layer_mask", "slow_release", "found"} \
        <= {f.name for f in info.DESCRIPTOR.fields}
    s = cb_pb2.SetRequest()
    assert {"binding", "timeout_ms", "require_prior_idle_ms",
            "layer_mask", "slow_release"} <= {f.name for f in s.DESCRIPTOR.fields}


def test_parse_behavior_spec_kp_and_raw():
    tok, bid, p1, p2 = br.parse_behavior_spec("kp ESC")
    assert tok == "kp" and bid == 0 and p2 == 0 and isinstance(p1, int)
    tok, bid, p1, p2 = br.parse_behavior_spec("raw 14 41 0")
    assert tok is None and bid == 14 and p1 == 41 and p2 == 0


# ---------- combos_client unit tests ----------

from roba_cli import combos_client as cc
import studio_pb2
import custom_pb2
from roba_cli.framing import encode_frame


class _FakeSerial:
    def __init__(self, payload: bytes):
        self._payload = bytearray(payload)
        self.written = bytearray()

    def write(self, b):
        self.written += b

    def flush(self):
        pass

    def read(self, n):
        if not self._payload:
            return b""
        out = bytes(self._payload[:n])
        del self._payload[:n]
        return out


def _custom_call_frame(cb_resp: "cb_pb2.Response") -> bytes:
    s = studio_pb2.Response()
    s.request_response.request_id = 1
    s.request_response.custom.call.payload = cb_resp.SerializeToString()
    return encode_frame(s.SerializeToString())


# --- build_* helpers ---

def test_build_count_request():
    req = cc.build_count_request()
    assert req.WhichOneof("request_type") == "count"


def test_build_get_request():
    req = cc.build_get_request(3)
    assert req.WhichOneof("request_type") == "get"
    assert req.get.index == 3


def test_build_reset_request():
    req = cc.build_reset_request(5)
    assert req.WhichOneof("request_type") == "reset"
    assert req.reset.index == 5


def test_build_set_request_binding():
    req = cc.build_set_request(0, "binding", "kp ESC", behavior_id=14, p1=41, p2=0)
    assert req.WhichOneof("request_type") == "set"
    s = req.set
    assert s.index == 0
    assert s.WhichOneof("field") == "binding"
    assert s.binding.behavior_id == 14
    assert s.binding.param1 == 41
    assert s.binding.param2 == 0


def test_build_set_request_timeout_ms():
    req = cc.build_set_request(1, "timeout-ms", "50")
    assert req.set.WhichOneof("field") == "timeout_ms"
    assert req.set.timeout_ms == 50


def test_build_set_request_require_prior_idle_ms():
    req = cc.build_set_request(1, "require-prior-idle-ms", "100")
    assert req.set.WhichOneof("field") == "require_prior_idle_ms"
    assert req.set.require_prior_idle_ms == 100


def test_build_set_request_layers():
    req = cc.build_set_request(1, "layers", "1,7")
    assert req.set.WhichOneof("field") == "layer_mask"
    assert req.set.layer_mask == (1 << 1) | (1 << 7)


def test_build_set_request_slow_release():
    req = cc.build_set_request(1, "slow-release", "true")
    assert req.set.WhichOneof("field") == "slow_release"
    assert req.set.slow_release is True


def test_build_set_request_slow_release_false():
    req = cc.build_set_request(1, "slow-release", "false")
    assert req.set.WhichOneof("field") == "slow_release"
    assert req.set.slow_release is False


# --- info_to_dict ---

def test_info_to_dict():
    info = cb_pb2.ComboInfo()
    info.index = 2
    info.key_positions.extend([0, 1])
    info.binding.behavior_id = 14
    info.binding.param1 = 41
    info.binding.param2 = 0
    info.timeout_ms = 50
    info.require_prior_idle_ms = 100
    info.layer_mask = (1 << 1) | (1 << 7)
    info.slow_release = True
    info.found = True
    d = cc.info_to_dict(info)
    assert d["index"] == 2
    assert d["key_positions"] == [0, 1]
    assert d["binding"]["behavior_id"] == 14
    assert d["binding"]["param1"] == 41
    assert d["timeout_ms"] == 50
    assert d["require_prior_idle_ms"] == 100
    assert d["layer_mask"] == (1 << 1) | (1 << 7)
    assert sorted(d["layers"]) == [1, 7]
    assert d["slow_release"] is True
    assert d["found"] is True


# --- decode_response ---

def test_decode_response_count():
    resp = cb_pb2.Response()
    resp.count.count = 3
    d = cc.decode_response(resp)
    assert d["ok"] is True
    assert d["count"] == 3


def test_decode_response_get():
    resp = cb_pb2.Response()
    resp.get.info.index = 0
    resp.get.info.binding.behavior_id = 14
    d = cc.decode_response(resp)
    assert d["ok"] is True
    assert d["info"]["binding"]["behavior_id"] == 14


def test_decode_response_set():
    resp = cb_pb2.Response()
    resp.set.ok = True
    d = cc.decode_response(resp)
    assert d["ok"] is True


def test_decode_response_set_fail():
    resp = cb_pb2.Response()
    resp.set.ok = False
    d = cc.decode_response(resp)
    assert d["ok"] is False


def test_decode_response_empty():
    resp = cb_pb2.Response()
    d = cc.decode_response(resp)
    assert d["ok"] is False


# --- FakeSerial round-trips ---

def test_get_decodes_over_custom_envelope():
    resp = cb_pb2.Response()
    resp.get.info.index = 0
    resp.get.info.binding.behavior_id = 99
    resp.get.info.found = True
    c = cc.CombosClient(_ser=_FakeSerial(_custom_call_frame(resp)))
    c._index = 0
    d = c.get(0)
    assert d["ok"] is True
    assert d["info"]["binding"]["behavior_id"] == 99
    assert d["info"]["found"] is True


def test_count_decodes_over_custom_envelope():
    resp = cb_pb2.Response()
    resp.count.count = 5
    c = cc.CombosClient(_ser=_FakeSerial(_custom_call_frame(resp)))
    c._index = 0
    n = c.count()
    assert n == 5


# --- set binding resolves via behaviors() ---

def test_set_binding_resolves_via_behaviors():
    """set(index, 'binding', 'kp ESC') should resolve kp to the stubbed behavior id."""
    set_resp = cb_pb2.Response()
    set_resp.set.ok = True
    c = cc.CombosClient(_ser=_FakeSerial(_custom_call_frame(set_resp)))
    c._index = 0
    c.behaviors = lambda: {"ok": True, "error": "", "behaviors": [
        {"id": 14, "display_name": "Key Press"},
        {"id": 5, "display_name": "mouse_scroll"},
    ]}
    # Capture the request that would be sent
    sent_reqs = []
    original_call = c._call

    def capture_call(req):
        sent_reqs.append(req)
        return original_call(req)

    c._call = capture_call
    d = c.set(0, "binding", "kp ESC")
    assert d["ok"] is True
    assert len(sent_reqs) == 1
    assert sent_reqs[0].set.binding.behavior_id == 14


from roba_cli import cli as _cli


def test_combo_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["combo", "set", "0", "binding", "kp ESC"])
    assert ns.index == 0 and ns.field == "binding" and ns.value == "kp ESC"
    assert ns.func is _cli.cmd_combo_set
    assert p.parse_args(["combo", "list"]).func is _cli.cmd_combo_list
    assert p.parse_args(["combo", "get", "2"]).index == 2
    assert p.parse_args(["combo", "reset", "1"]).func is _cli.cmd_combo_reset
    ns2 = p.parse_args(["combo", "set", "3", "timeout-ms", "40"])
    assert ns2.field == "timeout-ms" and ns2.value == "40"
