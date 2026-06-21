from __future__ import annotations

import glob

import zmk_studio_api as zmk

# roBa central exposes a USB CDC-ACM serial port when built with the
# studio-rpc-usb-uart snippet. On macOS these enumerate as /dev/cu.usbmodem*.
PORT_GLOB = "/dev/cu.usbmodem*"


def find_roba_port() -> str | None:
    """roBa の USB CDC-ACM ポートを返す。候補が一意でなければ None。"""
    ports = sorted(glob.glob(PORT_GLOB))
    if len(ports) == 1:
        return ports[0]
    return None


def open(port: str | None = None) -> "zmk.StudioClient":
    """roBa に USB serial 接続した StudioClient を返す。"""
    target = port or find_roba_port()
    if target is None:
        candidates = sorted(glob.glob(PORT_GLOB))
        raise RuntimeError(
            "roBa serial port not uniquely found. "
            f"candidates={candidates}. Pass --port explicitly."
        )
    return zmk.StudioClient.open_serial(target)
