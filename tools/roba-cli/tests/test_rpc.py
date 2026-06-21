import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import keymap_pb2

from roba_cli import rpc
from roba_cli.framing import encode_frame


class FakeSerial:
    """Serial stub that yields a fixed byte payload in n-sized reads."""
    def __init__(self, payload: bytes, chunk: int | None = None):
        self._payload = bytearray(payload)
        self._chunk = chunk
        self.written = bytearray()

    def write(self, b):
        self.written += b

    def flush(self):
        pass

    def read(self, n):
        if not self._payload:
            return b""
        take = n if self._chunk is None else min(n, self._chunk)
        out = bytes(self._payload[:take])
        del self._payload[:take]
        return out


def _notif_frame() -> bytes:
    r = studio_pb2.Response()
    r.notification.keymap.unsaved_changes_status_changed = True
    return encode_frame(r.SerializeToString())


def _set_layer_props_ok_frame(request_id: int) -> bytes:
    r = studio_pb2.Response()
    r.request_response.request_id = request_id
    r.request_response.keymap.set_layer_props = keymap_pb2.SET_LAYER_PROPS_RESP_OK
    return encode_frame(r.SerializeToString())


def test_send_recv_recovers_response_when_notification_precedes_it_in_one_chunk():
    blob = _notif_frame() + _set_layer_props_ok_frame(201)
    ser = FakeSerial(blob)  # both frames returned in one read
    resp = rpc.send_recv(ser, studio_pb2.Request(), timeout=1.0)
    assert resp.request_response.request_id == 201
    assert resp.request_response.keymap.set_layer_props == keymap_pb2.SET_LAYER_PROPS_RESP_OK


def test_send_recv_handles_response_split_across_reads():
    blob = _notif_frame() + _set_layer_props_ok_frame(202)
    ser = FakeSerial(blob, chunk=3)  # dribble 3 bytes per read
    resp = rpc.send_recv(ser, studio_pb2.Request(), timeout=1.0)
    assert resp.request_response.request_id == 202


def test_send_recv_returns_lone_response_without_notification():
    ser = FakeSerial(_set_layer_props_ok_frame(203))
    resp = rpc.send_recv(ser, studio_pb2.Request(), timeout=1.0)
    assert resp.request_response.request_id == 203


def test_send_recv_times_out_when_only_notifications_arrive():
    ser = FakeSerial(_notif_frame())
    import pytest
    with pytest.raises(TimeoutError):
        rpc.send_recv(ser, studio_pb2.Request(), timeout=0.3)
