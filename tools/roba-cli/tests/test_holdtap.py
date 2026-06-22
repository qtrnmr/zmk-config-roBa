import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
from roba_cli.proto.holdtap import holdtap_pb2 as ht_pb2
from roba_cli import holdtap_client as hc
from roba_cli import cli as _cli
from roba_cli.framing import encode_frame


def test_flavor_roundtrip():
    assert hc.parse_flavor("balanced") == 1
    assert hc.parse_flavor("TAP-PREFERRED") == 2
    assert hc.flavor_name(0) == "hold-preferred"
    assert hc.flavor_name(3) == "tap-unless-interrupted"
    import pytest
    with pytest.raises(ValueError):
        hc.parse_flavor("nope")


def test_build_set_request_preserves_other_fields():
    current = ht_pb2.HoldTapInfo(slot=0, tapping_term_ms=200, quick_tap_ms=-1,
                                 require_prior_idle_ms=-1, flavor=1, found=True)
    req = hc.build_set_request(0, current, "tapping-term-ms", "120")
    assert req.WhichOneof("request_type") == "set"
    assert req.set.tapping_term_ms == 120        # edited
    assert req.set.quick_tap_ms == -1            # preserved
    assert req.set.flavor == 1                   # preserved


def test_build_set_request_flavor_and_unknown():
    cur = ht_pb2.HoldTapInfo(slot=1, tapping_term_ms=200, flavor=0)
    req = hc.build_set_request(1, cur, "flavor", "tap-preferred")
    assert req.set.flavor == 2
    import pytest
    with pytest.raises(ValueError):
        hc.build_set_request(1, cur, "bogus", "1")


def test_info_to_dict():
    info = ht_pb2.HoldTapInfo(slot=2, tapping_term_ms=180, quick_tap_ms=0,
                              require_prior_idle_ms=125, flavor=1, found=True)
    d = hc.info_to_dict(info)
    assert d["slot"] == 2 and d["tapping_term_ms"] == 180
    assert d["flavor"] == "balanced" and d["found"] is True


class _FakeSerial:
    """Serial stub yielding a fixed payload, then empty reads."""
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


def _custom_call_frame(ht_resp: "ht_pb2.Response") -> bytes:
    """Wrap a holdtap.Response as a studio request_response custom call frame."""
    sresp = studio_pb2.Response()
    sresp.request_response.request_id = 1
    sresp.request_response.custom.call.payload = ht_resp.SerializeToString()
    return encode_frame(sresp.SerializeToString())


def test_get_decodes_holdtap_info_over_custom_envelope():
    ht_resp = ht_pb2.Response()
    ht_resp.get.slot = 0
    ht_resp.get.tapping_term_ms = 200
    ht_resp.get.flavor = 1
    ht_resp.get.found = True
    c = hc.HoldtapClient(_ser=_FakeSerial(_custom_call_frame(ht_resp)))
    c._index = 5  # skip subsystem resolve
    d = c.get(0)
    assert d["tapping_term_ms"] == 200 and d["flavor"] == "balanced" and d["found"] is True


def test_count_decodes_over_custom_envelope():
    ht_resp = ht_pb2.Response()
    ht_resp.count.count = 4
    c = hc.HoldtapClient(_ser=_FakeSerial(_custom_call_frame(ht_resp)))
    c._index = 5
    assert c.count() == 4


def test_holdtap_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["holdtap", "set", "0", "tapping-term-ms", "120"])
    assert ns.slot == 0 and ns.field == "tapping-term-ms" and ns.value == "120"
    ns2 = p.parse_args(["holdtap", "get", "2"])
    assert ns2.slot == 2 and ns2.func is _cli.cmd_holdtap_get
    assert p.parse_args(["holdtap", "list"]).func is _cli.cmd_holdtap_list
    assert p.parse_args(["holdtap", "reset", "1"]).func is _cli.cmd_holdtap_reset
