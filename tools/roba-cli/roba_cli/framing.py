"""ZMK Studio framing: SOF=0xAB, ESC=0xAC, EOF=0xAD.

Escape encoding (matches ZMK firmware app/src/studio/rpc.c exactly): an ESC
byte is prefixed before any literal SOF/ESC/EOF byte, and the special byte is
then emitted AS-IS (there is NO XOR). The RX state machine likewise takes the
byte after ESC literally. Do not XOR — that would break wire interop.
"""

SOF, ESC, EOF = 0xAB, 0xAC, 0xAD


def encode_frame(payload: bytes) -> bytes:
    """Wrap payload with SOF/EOF framing; ESC-prefix any literal SOF/ESC/EOF byte."""
    out = bytearray([SOF])
    for b in payload:
        if b in (SOF, ESC, EOF):
            out.append(ESC)
        out.append(b)
    out.append(EOF)
    return bytes(out)


def decode_frame(frame: bytes) -> bytes:
    """Strip SOF/EOF and unescape (ESC means: take the next byte literally)."""
    out = bytearray()
    escaped = False
    for b in frame[1:-1]:
        if escaped:
            out.append(b)
            escaped = False
        elif b == ESC:
            escaped = True
        else:
            out.append(b)
    return bytes(out)
