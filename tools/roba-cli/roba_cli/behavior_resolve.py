"""Shared behavior-resolution helpers for encoder_client, combos_client, etc.

Provides:
  - crc16_ansi: CRC-16/ARC used by ZMK to assign behavior local IDs.
  - BEHAVIOR_DEV_NAME / BEHAVIOR_DISPLAY_CANDIDATES: token -> device/display names.
  - BehaviorResolutionError: raised when a token cannot be resolved.
  - parse_behavior_spec: parse "kp ESC" / "raw <id> <p1> [p2]" -> (token, id, p1, p2).
  - resolve_local_id: resolve a token against a behaviors list (display_name + crc16 fallback).
"""
from __future__ import annotations

import roba_cli.proto  # noqa: F401  sets sys.path

# token -> device name (crc16 fallback) and display_name candidates (primary).
BEHAVIOR_DEV_NAME = {"kp": "key_press", "msc": "mouse_scroll"}

# Studio behavior display_name candidates per token (lowercased). The firmware
# reports the friendly display-name when one is set (kp -> "Key Press") and falls
# back to the device/node name otherwise (msc -> "mouse_scroll"). Matching on
# display_name resolves the local_id in BOTH crc16 and settings-table modes,
# whereas crc16(device_name) only matches in crc16 mode. So display_name is the
# primary resolver and crc16 is the fallback.
BEHAVIOR_DISPLAY_CANDIDATES = {
    "kp": {"key press", "key_press"},
    "msc": {"mouse scroll", "mouse_scroll"},
}


class BehaviorResolutionError(RuntimeError):
    pass


def crc16_ansi(data: bytes) -> int:
    """CRC-16/ARC (reflected poly 0xA001, init 0x0000) — matches Zephyr crc16_ansi."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def _keycode_value(name: str) -> int:
    """Resolve a kp keycode name (or decimal) to its HID usage value."""
    if name.isdigit():
        return int(name)
    import zmk_studio_api as zmk
    val = getattr(zmk.Keycode, name.upper(), None)
    if val is None:
        raise ValueError(f"unknown keycode {name!r}")
    return int(val)


def parse_behavior_spec(spec: str) -> tuple[str | None, int, int, int]:
    """Parse a behavior spec into (token, behavior_id, param1, param2).

    'kp <KEYCODE>'        -> ('kp', 0, keycode, 0)    token resolved to id later
    'raw <id> <p1> [p2]'  -> (None, id, p1, p2)       explicit id, no resolution
    """
    parts = spec.split()
    if not parts:
        raise ValueError("empty behavior spec")
    head = parts[0].lower()
    rest = parts[1:]
    if head == "kp":
        if len(rest) != 1:
            raise ValueError("kp requires one keycode, e.g. 'kp ESC'")
        return ("kp", 0, _keycode_value(rest[0]), 0)
    if head == "raw":
        if len(rest) not in (2, 3):
            raise ValueError("raw requires <behavior_id> <param1> [param2]")
        return (None, int(rest[0]), int(rest[1]), int(rest[2]) if len(rest) == 3 else 0)
    raise ValueError(f"unknown behavior spec {spec!r} (use kp/raw)")


def resolve_local_id(behaviors_list: list[dict], token: str) -> int:
    """Resolve a behavior token to its local_id.

    behaviors_list: [{'id': int, 'display_name': str}]
    Matches by display_name (works in crc16 AND settings-table modes),
    then falls back to crc16(device_name).
    """
    wanted = BEHAVIOR_DISPLAY_CANDIDATES.get(token, set())
    for b in behaviors_list:
        if b["display_name"].lower() in wanted:
            return b["id"]
    if token in BEHAVIOR_DEV_NAME:
        cand = crc16_ansi(BEHAVIOR_DEV_NAME[token].encode())
        if cand in {b["id"] for b in behaviors_list}:
            return cand
    raise BehaviorResolutionError(
        f"could not resolve '{token}'. Use 'roba encoder behaviors' to list ids "
        f"and pass 'raw <id> <param1> [param2]'.")
