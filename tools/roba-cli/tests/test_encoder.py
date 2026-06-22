import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.cormoran.rsr import custom_pb2 as rsr_pb2


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
