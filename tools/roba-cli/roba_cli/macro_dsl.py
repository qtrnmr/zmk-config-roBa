"""Macro steps DSL parser.

Syntax: tokens separated by ' | '
  type <text>        - each ASCII char becomes one step
  <MODS->key>        - modifier-prefixed key (C-, S-, A-, G-)
  wait <ms>          - add wait_ms to the previous step

Step dict: {"type": 0, "keycode": <u32>, "wait_ms": 0, "tap_ms": 0}
Modifiers are OR'd into keycode's high byte (ZMK implicit-mod encoding):
  LCTRL  = 1<<24
  LSHIFT = 2<<24
  LALT   = 4<<24
  LGUI   = 8<<24
"""

# HID usage codes for basic keys
_HID: dict[str, int] = {}

# a-z → 0x04..0x1D
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _HID[_c] = 0x04 + _i

# 1-9 → 0x1E..0x26, 0 → 0x27
for _i, _c in enumerate("123456789"):
    _HID[_c] = 0x1E + _i
_HID["0"] = 0x27

# space
_HID[" "] = 0x2C

# ZMK implicit-mod bit positions
_MOD_BITS = {
    "C": 1 << 24,   # LCTRL
    "S": 2 << 24,   # LSHIFT
    "A": 4 << 24,   # LALT
    "G": 8 << 24,   # LGUI
}

_LSHIFT_BIT = 2 << 24


def _make_step(keycode: int, wait_ms: int = 0, tap_ms: int = 0) -> dict:
    return {"type": 0, "keycode": keycode, "wait_ms": wait_ms, "tap_ms": tap_ms}


def _char_to_keycode(ch: str) -> int:
    """Convert a single character to its ZMK keycode (with implicit LSHIFT for uppercase)."""
    if ch.isupper():
        lower = ch.lower()
        if lower not in _HID:
            raise ValueError(f"Unsupported character: {ch!r}")
        return _LSHIFT_BIT | _HID[lower]
    if ch not in _HID:
        raise ValueError(f"Unsupported character: {ch!r}")
    return _HID[ch]


def _parse_modified_key(token: str) -> dict:
    """Parse tokens like C-c, C-S-z, A-G-a into a step with modifier bits."""
    mods = 0
    s = token
    while len(s) >= 2 and s[1] == "-" and s[0] in _MOD_BITS:
        mods |= _MOD_BITS[s[0]]
        s = s[2:]
    if len(s) != 1:
        raise ValueError(f"Invalid modified key token: {token!r}")
    key = s[0]
    if key.lower() not in _HID:
        raise ValueError(f"Unsupported key in modifier token: {key!r}")
    usage = _HID[key.lower()]
    return _make_step(mods | usage)


def parse(s: str) -> list[dict]:
    """Parse a macro DSL string into a list of step dicts."""
    tokens = [t.strip() for t in s.split("|")]
    steps: list[dict] = []

    for token in tokens:
        if not token:
            continue

        parts = token.split(None, 1)
        head = parts[0]

        if head == "type":
            if len(parts) < 2:
                raise ValueError("'type' requires text argument")
            text = parts[1]
            for ch in text:
                steps.append(_make_step(_char_to_keycode(ch)))

        elif head == "wait":
            if len(parts) < 2:
                raise ValueError("'wait' requires ms argument")
            if not steps:
                raise ValueError("'wait' with no preceding step")
            ms = int(parts[1])
            steps[-1]["wait_ms"] += ms

        elif "-" in head and head[0] in _MOD_BITS:
            # modifier-prefixed key token
            steps.append(_parse_modified_key(head))

        else:
            raise ValueError(f"Unknown DSL token: {head!r}")

    return steps
