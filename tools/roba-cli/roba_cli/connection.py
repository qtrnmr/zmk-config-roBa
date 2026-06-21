from __future__ import annotations

import zmk_studio_api as zmk

ROBA_NAME = "roBa"


def find_roba_device_id() -> str | None:
    """ペア済み BLE から roBa の device_id を返す。無ければ None。"""
    for device_id, local_name in zmk.StudioClient.list_ble_devices():
        if (local_name or "") == ROBA_NAME:
            return device_id
    return None


def open(device_id: str | None = None) -> "zmk.StudioClient":
    """roBa に BLE 接続した StudioClient を返す。"""
    target = device_id or find_roba_device_id()
    if target is None:
        raise RuntimeError("roBa not found over BLE. Pair/connect the keyboard first.")
    return zmk.StudioClient.open_ble(target)
