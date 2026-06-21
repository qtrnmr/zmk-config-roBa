import pytest

from roba_cli.behaviors import BehaviorSpec, parse_behavior


def test_keypress():
    assert parse_behavior("KP A") == BehaviorSpec("KeyPress", ("A",))


def test_keypress_lowercase_head():
    assert parse_behavior("kp ENTER") == BehaviorSpec("KeyPress", ("ENTER",))


def test_transparent():
    assert parse_behavior("trans") == BehaviorSpec("Transparent", ())


def test_momentary_layer():
    assert parse_behavior("MO 5") == BehaviorSpec("MomentaryLayer", (5,))


def test_raw():
    assert parse_behavior("RAW 12 1 0") == BehaviorSpec("Raw", (12, 1, 0))


def test_unknown_raises():
    with pytest.raises(ValueError):
        parse_behavior("WAT 1")


def test_keypress_arity_error():
    with pytest.raises(ValueError):
        parse_behavior("KP")
