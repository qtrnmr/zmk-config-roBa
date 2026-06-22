import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
from roba_cli.proto.cormoran.rip import custom_pb2 as rip_pb2
from roba_cli import rip_client as rc
from roba_cli import cli as _cli
from roba_cli.framing import encode_frame


class _FakeSerial:
    """Serial stub yielding a fixed byte payload, then empty reads."""
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


def _list_notif_frame(**fields) -> bytes:
    """A studio.Response notification carrying one InputProcessorChangedNotification."""
    notif = studio_pb2.Response()
    rn = rip_pb2.Notification()
    p = rn.input_processor_changed.processor
    for k, v in fields.items():
        setattr(p, k, v)
    cn = notif.notification.custom.custom_notification
    cn.subsystem_index = 0
    cn.payload = rn.SerializeToString()
    return encode_frame(notif.SerializeToString())


def test_get_uses_list_notification_path():
    ser = _FakeSerial(_list_notif_frame(id=0, name="mouse", scale_multiplier=1, scale_divisor=2))
    c = rc.RipClient(_ser=ser)
    c._index = 0  # skip subsystem resolve (no IO for it)
    res = c.get(0)
    assert res["ok"] is True
    assert res["processor"]["name"] == "mouse"
    assert res["processor"]["scale_divisor"] == 2


def test_get_missing_id_returns_not_found():
    ser = _FakeSerial(_list_notif_frame(id=0, name="mouse"))
    c = rc.RipClient(_ser=ser)
    c._index = 0
    res = c.get(7)
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_rip_proto_imports_and_oneof_fields_exist():
    req = rip_pb2.Request()
    names = {f.name for f in req.DESCRIPTOR.fields}
    assert {"get_input_processor", "set_scale_divisor", "set_rotation",
            "reset_input_processor", "set_x_invert"} <= names
    info = rip_pb2.InputProcessorInfo()
    inames = {f.name for f in info.DESCRIPTOR.fields}
    assert {"scale_multiplier", "scale_divisor", "rotation_degrees",
            "x_invert", "y_invert", "xy_to_scroll_enabled"} <= inames
    assert rip_pb2.AxisSnapMode.Value("AXIS_SNAP_MODE_X") == 1


def test_build_set_request_scale_divisor():
    req = rc.build_set_request("scale-divisor", id=0, raw_value="4")
    assert req.WhichOneof("request_type") == "set_scale_divisor"
    assert req.set_scale_divisor.id == 0
    assert req.set_scale_divisor.value == 4


def test_build_set_request_bool_and_rotation_and_enum():
    r1 = rc.build_set_request("x-invert", 0, "true")
    assert r1.set_x_invert.invert is True
    r2 = rc.build_set_request("rotation", 0, "-90")
    assert r2.set_rotation.value == -90
    r3 = rc.build_set_request("axis-snap-mode", 0, "x")
    assert r3.set_axis_snap_mode.mode == rip_pb2.AxisSnapMode.Value("AXIS_SNAP_MODE_X")


def test_build_get_and_reset_requests():
    assert rc.build_get_request(0).WhichOneof("request_type") == "get_input_processor"
    assert rc.build_get_request(0).get_input_processor.id == 0
    assert rc.build_reset_request(2).reset_input_processor.id == 2


def test_build_set_request_unknown_field_raises():
    import pytest
    with pytest.raises(ValueError):
        rc.build_set_request("nope", 0, "1")


def test_trackball_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["trackball", "set", "scale-divisor", "4"])
    assert ns.field == "scale-divisor" and ns.value == "4" and ns.id == 0
    ns2 = p.parse_args(["trackball", "get", "--id", "1"])
    assert ns2.id == 1 and ns2.func is _cli.cmd_trackball_get
    ns3 = p.parse_args(["trackball", "reset"])
    assert ns3.func is _cli.cmd_trackball_reset


def test_info_to_dict_and_decode_response():
    resp = rip_pb2.Response()
    resp.get_input_processor.processor.id = 0
    resp.get_input_processor.processor.scale_divisor = 3
    resp.get_input_processor.processor.x_invert = True
    d = rc.decode_response(resp)
    assert d["ok"] is True
    assert d["processor"]["scale_divisor"] == 3 and d["processor"]["x_invert"] is True
    err = rip_pb2.Response()
    err.error.message = "bad id"
    de = rc.decode_response(err)
    assert de["ok"] is False and de["error"] == "bad id"
