import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.cormoran.rsr import custom_pb2 as rsr_pb2

from roba_cli import encoder_client as ec


def test_crc16_ansi_check_value_and_names():
    assert ec.crc16_ansi(b"123456789") == 0xBB3D
    assert ec.crc16_ansi(b"key_press") == 13527
    assert ec.crc16_ansi(b"mouse_scroll") == 7776


def test_scrl_table_values():
    assert ec.SCRL["SCRL_UP"] == 10
    assert ec.SCRL["SCRL_DOWN"] == 65526
    assert ec.SCRL["SCRL_LEFT"] == 4294311936
    assert ec.SCRL["SCRL_RIGHT"] == 655360


def test_parse_encoder_behavior_kp_msc_raw():
    tok, bid, p1, p2 = ec.parse_encoder_behavior("kp C_VOL_UP")
    assert tok == "kp" and bid == 0 and p1 == 786665 and p2 == 0
    tok, bid, p1, p2 = ec.parse_encoder_behavior("msc SCRL_DOWN")
    assert tok == "msc" and bid == 0 and p1 == 65526 and p2 == 0
    tok, bid, p1, p2 = ec.parse_encoder_behavior("raw 7776 65526 0")
    assert tok is None and bid == 7776 and p1 == 65526 and p2 == 0


def test_parse_encoder_behavior_rejects_unknown():
    import pytest
    with pytest.raises(ValueError):
        ec.parse_encoder_behavior("nope X")
    with pytest.raises(ValueError):
        ec.parse_encoder_behavior("msc NOT_A_SCRL")


def test_build_set_request_directions():
    cw = ec.build_set_request("cw", sensor=0, layer=2, behavior_id=13527,
                              param1=10, param2=0, tap_ms=20)
    assert cw.WhichOneof("request_type") == "set_layer_cw_binding"
    s = cw.set_layer_cw_binding
    assert s.sensor_index == 0 and s.layer == 2
    assert s.binding.behavior_id == 13527 and s.binding.param1 == 10 and s.binding.tap_ms == 20
    ccw = ec.build_set_request("ccw", 0, 2, 13527, 65526, 0, 20)
    assert ccw.WhichOneof("request_type") == "set_layer_ccw_binding"


def test_build_set_request_bad_direction():
    import pytest
    with pytest.raises(ValueError):
        ec.build_set_request("sideways", 0, 0, 1, 0, 0, 5)


def test_decode_response_get_and_error():
    resp = rsr_pb2.Response()
    lb = resp.get_all_layer_bindings.bindings.add()
    lb.layer = 0
    lb.cw_binding.behavior_id = 13527
    lb.cw_binding.param1 = 10
    lb.ccw_binding.behavior_id = 13527
    lb.ccw_binding.param1 = 786665
    d = ec.decode_response(resp)
    assert d["ok"] is True
    assert d["bindings"][0]["layer"] == 0
    assert d["bindings"][0]["cw"]["behavior_id"] == 13527
    err = rsr_pb2.Response()
    err.error.message = "bad sensor"
    de = ec.decode_response(err)
    assert de["ok"] is False and de["error"] == "bad sensor"


def test_rsr_proto_imports_and_fields_exist():
    req = rsr_pb2.Request()
    rnames = {f.name for f in req.DESCRIPTOR.fields}
    assert {"set_layer_cw_binding", "set_layer_ccw_binding",
            "get_all_layer_bindings", "get_sensors"} <= rnames
    resp = rsr_pb2.Response()
    pnames = {f.name for f in resp.DESCRIPTOR.fields}
    assert {"error", "set_layer_cw_binding", "set_layer_ccw_binding",
            "get_all_layer_bindings", "get_sensors"} <= pnames
    b = rsr_pb2.Binding()
    bnames = {f.name for f in b.DESCRIPTOR.fields}
    assert {"behavior_id", "param1", "param2", "tap_ms"} <= bnames
    lb = rsr_pb2.LayerBindings()
    lnames = {f.name for f in lb.DESCRIPTOR.fields}
    assert {"layer", "cw_binding", "ccw_binding"} <= lnames


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


def _custom_call_frame(rsr_resp: "rsr_pb2.Response") -> bytes:
    s = studio_pb2.Response()
    s.request_response.request_id = 1
    s.request_response.custom.call.payload = rsr_resp.SerializeToString()
    return encode_frame(s.SerializeToString())


def test_get_decodes_over_custom_envelope():
    r = rsr_pb2.Response()
    lb = r.get_all_layer_bindings.bindings.add()
    lb.layer = 0
    lb.cw_binding.behavior_id = 13527
    lb.cw_binding.param1 = 10
    c = ec.EncoderClient(_ser=_FakeSerial(_custom_call_frame(r)))
    c._index = 0
    d = c.get(0)
    assert d["ok"] is True and d["bindings"][0]["cw"]["behavior_id"] == 13527


def test_sensors_decodes_over_custom_envelope():
    r = rsr_pb2.Response()
    s0 = r.get_sensors.sensors.add(); s0.index = 0; s0.name = "encoder_left"
    s1 = r.get_sensors.sensors.add(); s1.index = 1; s1.name = "encoder_right"
    c = ec.EncoderClient(_ser=_FakeSerial(_custom_call_frame(r)))
    c._index = 0
    d = c.sensors()
    assert [s["name"] for s in d["sensors"]] == ["encoder_left", "encoder_right"]


def test_resolve_behavior_local_id_crc16_when_present():
    # behavior list contains the crc16 id -> resolves
    c = ec.EncoderClient(_ser=_FakeSerial(b""))
    c._index = 0
    c._behavior_ids = lambda: {13527, 7776, 99}   # stub the live id set
    assert c.resolve_behavior_local_id("kp") == 13527
    assert c.resolve_behavior_local_id("msc") == 7776


def test_resolve_behavior_local_id_raises_when_absent():
    import pytest
    c = ec.EncoderClient(_ser=_FakeSerial(b""))
    c._index = 0
    c._behavior_ids = lambda: {1, 2, 3}
    with pytest.raises(ec.BehaviorResolutionError):
        c.resolve_behavior_local_id("kp")


from roba_cli import cli as _cli


def test_encoder_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["encoder", "set", "0", "2", "cw", "msc SCRL_DOWN"])
    assert ns.sensor == 0 and ns.layer == 2 and ns.direction == "cw"
    assert ns.behavior == "msc SCRL_DOWN" and ns.func is _cli.cmd_encoder_set
    ns2 = p.parse_args(["encoder", "get", "--sensor", "1"])
    assert ns2.sensor == 1 and ns2.func is _cli.cmd_encoder_get
    assert p.parse_args(["encoder", "sensors"]).func is _cli.cmd_encoder_sensors
    assert p.parse_args(["encoder", "behaviors"]).func is _cli.cmd_encoder_behaviors
    ns3 = p.parse_args(["encoder", "reset", "0", "2"])
    assert ns3.sensor == 0 and ns3.layer == 2 and ns3.func is _cli.cmd_encoder_reset
