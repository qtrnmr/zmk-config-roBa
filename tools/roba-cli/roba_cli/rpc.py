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


def send_recv(ser: "serial.Serial", studio_req: "studio_pb2.Request",
              timeout: float = READ_TIMEOUT) -> "studio_pb2.Response":
    payload = studio_req.SerializeToString()
    ser.write(encode_frame(payload))
    ser.flush()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for request_response frame")
        raw_frame = read_frame(ser, timeout=remaining)
        resp = studio_pb2.Response()
        resp.ParseFromString(decode_frame(raw_frame))
        if resp.HasField("request_response"):
            return resp
        # notification frame; discard and keep waiting
