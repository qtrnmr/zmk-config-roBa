from roba_cli.framing import encode_frame, decode_frame


def test_roundtrip_plain():
    assert decode_frame(encode_frame(b"\x01\x02")) == b"\x01\x02"


def test_escapes_special_bytes():
    enc = encode_frame(bytes([0xAB, 0xAC, 0xAD]))
    assert enc[0] == 0xAB and enc[-1] == 0xAD
    assert enc.count(0xAC) == 3  # 1 esc per special byte
    assert decode_frame(enc) == bytes([0xAB, 0xAC, 0xAD])
