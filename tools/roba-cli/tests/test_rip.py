import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.cormoran.rip import custom_pb2 as rip_pb2


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
