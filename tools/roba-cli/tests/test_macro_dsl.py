import pytest
from roba_cli.macro_dsl import parse


def test_type_text():
    steps = parse("type hi")
    assert [s["keycode"] for s in steps] == [0x0B, 0x0C]  # h=0x0B, i=0x0C


def test_modified_key():
    s = parse("C-c")[0]
    assert s["keycode"] == 0x01000006  # LC(c): ctrl bit (0x01<<24) | c(0x06)


def test_wait_attaches_to_prev():
    steps = parse("C-c | wait 200")
    assert steps[-1]["wait_ms"] == 200


def test_unknown_token_raises():
    with pytest.raises(ValueError):
        parse("frobnicate x")


def test_too_many_steps_raises():
    # "type " + 33 identical characters produces 33 steps, exceeding MAX_STEPS=32
    with pytest.raises(ValueError, match="max is 32"):
        parse("type " + "a" * 33)
