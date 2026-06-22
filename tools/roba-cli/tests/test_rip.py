import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.cormoran.rip import custom_pb2 as rip_pb2
from roba_cli import rip_client as rc


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
