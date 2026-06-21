from roba_cli.framing import encode_frame, decode_frame


def test_roundtrip_plain():
    assert decode_frame(encode_frame(b"\x01\x02")) == b"\x01\x02"


def test_escapes_special_byte_as_is():
    # ESC(0xAC) prefixes the literal 0xAB; the byte itself is emitted AS-IS
    # (no XOR), exactly as ZMK firmware rpc.c does.
    enc = encode_frame(bytes([0x01, 0xAB, 0x02]))
    assert enc == bytes([0xAB, 0x01, 0xAC, 0xAB, 0x02, 0xAD])
    assert decode_frame(enc) == bytes([0x01, 0xAB, 0x02])


def test_all_specials_escaped_in_order():
    enc = encode_frame(bytes([0xAB, 0xAC, 0xAD]))
    # SOF, ESC,0xAB, ESC,0xAC, ESC,0xAD, EOF — each special prefixed by ESC, no XOR
    assert enc == bytes([0xAB, 0xAC, 0xAB, 0xAC, 0xAC, 0xAC, 0xAD, 0xAD])
    assert decode_frame(enc) == bytes([0xAB, 0xAC, 0xAD])
