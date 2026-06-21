"""ZMK Studio framing: SOF=0xAB, ESC=0xAC, EOF=0xAD.

Escape encoding: ESC byte is prefixed before any special byte; the special
byte itself is XOR'd with 0x20 so no literal SOF/ESC/EOF appears in the
escaped payload.
"""

SOF, ESC, EOF = 0xAB, 0xAC, 0xAD
ESC_XOR = 0x20


def encode_frame(payload: bytes) -> bytes:
    """Wrap payload with SOF/EOF framing; escape any literal SOF/ESC/EOF bytes."""
    out = bytearray([SOF])
    for b in payload:
        if b in (SOF, ESC, EOF):
            out.append(ESC)
            out.append(b ^ ESC_XOR)
        else:
            out.append(b)
    out.append(EOF)
    return bytes(out)


def decode_frame(frame: bytes) -> bytes:
    """Strip SOF/EOF and unescape escaped bytes."""
    out = bytearray()
    escaped = False
    for b in frame[1:-1]:
        if escaped:
            out.append(b ^ ESC_XOR)
            escaped = False
        elif b == ESC:
            escaped = True
        else:
            out.append(b)
    return bytes(out)
