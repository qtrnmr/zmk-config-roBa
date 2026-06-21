"""Shared ZMK Studio serial transport (framing + request/response loop).

Wire format: SOF=0xAB, ESC=0xAC, EOF=0xAD, no XOR (see framing.py). Used by all
roba-cli clients that talk the Studio RPC directly over USB serial.
"""
from __future__ import annotations

import glob
import time

import serial

import roba_cli.proto  # noqa: F401  sets sys.path for proto imports
import studio_pb2

from .framing import encode_frame, decode_frame

SOF = 0xAB
ESC = 0xAC
EOF = 0xAD
PORT_GLOB = "/dev/cu.usbmodem*"
DEFAULT_BAUD = 115200
READ_TIMEOUT = 2.0
CHUNK = 256


def find_port() -> str:
    ports = sorted(glob.glob(PORT_GLOB))
    if len(ports) == 1:
        return ports[0]
    raise RuntimeError(
        f"roBa serial port not uniquely found. candidates={ports}. "
        "Pass --port explicitly."
    )


def read_frame(ser: "serial.Serial", timeout: float = READ_TIMEOUT) -> bytes:
    buf = bytearray()
    in_frame = False
    deadline = time.monotonic() + timeout
    escaped = False
    while time.monotonic() < deadline:
        chunk = ser.read(CHUNK)
        if not chunk:
            continue
        for b in chunk:
            if not in_frame:
                if b == SOF:
                    buf = bytearray([b])
                    in_frame = True
                    escaped = False
            else:
                buf.append(b)
                if escaped:
                    escaped = False
                elif b == ESC:
                    escaped = True
                elif b == EOF:
                    return bytes(buf)
    raise TimeoutError(
        f"Timed out waiting for frame (got {len(buf)} bytes so far: {buf.hex()})"
    )


def _extract_frame(buf: bytearray):
    """Extract the first complete SOF..EOF frame from buf.

    Returns (frame_bytes_including_SOF_EOF, remainder_buffer) or
    (None, kept_buffer) when no complete frame is present yet. ESC is honored
    so an escaped EOF/SOF inside the payload is not treated as a boundary.
    Leading noise before the first SOF is dropped.
    """
    start = buf.find(SOF)
    if start == -1:
        return None, bytearray()
    i = start + 1
    escaped = False
    while i < len(buf):
        b = buf[i]
        if escaped:
            escaped = False
        elif b == ESC:
            escaped = True
        elif b == EOF:
            return bytes(buf[start:i + 1]), bytearray(buf[i + 1:])
        i += 1
    return None, bytearray(buf[start:])


def send_recv(ser: "serial.Serial", studio_req: "studio_pb2.Request",
              timeout: float = READ_TIMEOUT) -> "studio_pb2.Response":
    """Send a framed request; return the first request_response Response.

    Buffers bytes across reads so that a notification frame arriving in the
    same burst as the request_response does not cause the response to be lost.
    Notification frames are discarded; the loop keeps extracting from the
    buffer (which may already hold the response) before reading more.
    """
    ser.write(encode_frame(studio_req.SerializeToString()))
    ser.flush()
    buf = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        frame, buf = _extract_frame(buf)
        if frame is not None:
            resp = studio_pb2.Response()
            resp.ParseFromString(decode_frame(frame))
            if resp.HasField("request_response"):
                return resp
            continue  # notification frame; keep extracting from the buffer
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for request_response frame")
        chunk = ser.read(CHUNK)
        if chunk:
            buf += chunk
