from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BehaviorSpec:
    kind: str
    args: tuple


def parse_behavior(spec: str) -> BehaviorSpec:
    parts = spec.split()
    if not parts:
        raise ValueError("empty behavior spec")
    head = parts[0].upper()
    rest = parts[1:]
    if head in ("KP", "KEYPRESS"):
        if len(rest) != 1:
            raise ValueError("KP requires exactly one keycode, e.g. 'KP A'")
        return BehaviorSpec("KeyPress", (rest[0].upper(),))
    if head in ("TRANS", "TRANSPARENT"):
        return BehaviorSpec("Transparent", ())
    if head in ("MO", "MOMENTARYLAYER"):
        if len(rest) != 1:
            raise ValueError("MO requires one layer id, e.g. 'MO 5'")
        return BehaviorSpec("MomentaryLayer", (int(rest[0]),))
    if head == "RAW":
        if len(rest) != 3:
            raise ValueError("RAW requires behavior_id param1 param2")
        return BehaviorSpec("Raw", (int(rest[0]), int(rest[1]), int(rest[2])))
    raise ValueError(f"unknown behavior: {spec!r}")


def build_behavior(spec: BehaviorSpec, zmk):
    if spec.kind == "KeyPress":
        return zmk.KeyPress(getattr(zmk.Keycode, spec.args[0]))
    if spec.kind == "Transparent":
        return zmk.Transparent()
    if spec.kind == "MomentaryLayer":
        return zmk.MomentaryLayer(spec.args[0])
    if spec.kind == "Raw":
        return zmk.Raw(*spec.args)
    raise ValueError(f"cannot build behavior of kind {spec.kind!r}")
