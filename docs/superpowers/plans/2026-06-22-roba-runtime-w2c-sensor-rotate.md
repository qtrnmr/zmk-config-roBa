# W2c — Runtime Sensor-Rotate (Encoder) Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit roBa's rotary-encoder rotation bindings per layer without reflashing, via a `roba encoder` CLI group over the cormoran `cormoran_rsr` custom Studio RPC.

**Architecture:** Reuse `cormoran/zmk-behavior-runtime-sensor-rotate` (tag `zmk-v0.3.0.0`) unmodified — pin in west.yml, enable in roBa_R.conf, convert the bound encoder behavior in the keymap to the runtime variant. The host speaks the raw `cormoran.rsr` protobuf over the same pyserial transport used by `rip_client`/`macro_client` (custom-envelope 2-step). Behavior tokens (`kp`/`msc`) resolve to `behavior_local_id` via `crc16_ansi(device_name)` cross-checked against the live behavior-id list; revert is "set behavior_id 0 → live fallback to the device-tree default".

**Tech Stack:** ZMK (cormoran `v0.3-branch+dya`), Zephyr settings/NVS, nanopb; Python 3.12, pyserial, protobuf (`grpc_tools.protoc`), `zmk_studio_api` (Rust binding), pytest.

## Global Constraints

- Reuse the OSS module **unmodified**; **no fork**. Pin `zmk-behavior-runtime-sensor-rotate` to `revision: zmk-v0.3.0.0` (the base-compatible tag, same as runtime-input-processor).
- **roBa_L is unchanged.** Only roBa_R (central / USB) gets config changes.
- Revert path is per-binding **set-0** (→ DT default fallback). No module settings-reset hook is added. `roba reset` does NOT clear `rsr` keys — documented limitation.
- Curated behaviors only at the CLI: `kp <KEYCODE>` and `msc <SCRL_x>`, plus a `raw <id> <p1> [p2]` escape hatch.
- Behavior subsystem identifier string: **`cormoran_rsr`**. Proto package: **`cormoran.rsr`**.
- Existing 53 host tests must stay green; new tests live in `tests/test_encoder.py`.
- Commit messages end with the two trailers:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F`
- Work on branch `feat/roba-w2c-sensor-rotate`; merge to `main` locally `--no-ff`; **do not push origin** unless the user explicitly asks.

## Discovered constants (verified against the base zmk source)

- `cormoran.rsr` messages (tag `zmk-v0.3.0.0`):
  - `Binding { uint32 behavior_id; uint32 param1; uint32 param2; uint32 tap_ms; }`
  - `Request` oneof `request_type`: `set_layer_cw_binding` (`{sensor_index, layer, Binding binding}`),
    `set_layer_ccw_binding` (same shape), `get_all_layer_bindings` (`{sensor_index}`),
    `get_sensors` (`{}`).
  - `Response` oneof `response_type`: `error` (`{string message}`),
    `set_layer_cw_binding`/`set_layer_ccw_binding` (`{bool success}`),
    `get_all_layer_bindings` (`{repeated LayerBindings bindings}`),
    `get_sensors` (`{repeated SensorInfo sensors}`).
  - `LayerBindings { uint32 layer; Binding cw_binding; Binding ccw_binding; }`
  - `SensorInfo { uint32 index; string name; }`
- Behavior `behavior_id` **is** `zmk_behavior_local_id_t`; firmware computes it as
  `crc16_ansi(device_name)` when `CONFIG_ZMK_BEHAVIOR_LOCAL_ID_TYPE_CRC16` is active.
  CRC-16/ARC (poly 0xA001 reflected, init 0) — Python check value `crc16_ansi(b"123456789") == 0xBB3D`.
  - `crc16_ansi(b"key_press")    == 13527`  (token `kp`)
  - `crc16_ansi(b"mouse_scroll") == 7776`   (token `msc`)
- `kp` keycode param1 values come from `zmk_studio_api.Keycode` (e.g. `C_VOL_UP == 786665`,
  `C_VOL_DN == 786666`).
- `msc` SCRL param1 values (from `dt-bindings/zmk/pointing.h`, `MOVE_VAL=600`, `SCRL_VAL=10`):
  `SCRL_UP=10`, `SCRL_DOWN=65526`, `SCRL_LEFT=4294311936`, `SCRL_RIGHT=655360`.
- The bound encoder behavior is `encoder_vol_down_up` (`config/roBa.keymap:201`), referenced by
  `sensor-bindings = <&encoder_vol_down_up>` on 5 layers. Active sensor is `left_encoder`
  (index 0); `right_encoder` is disabled. `encoder_msc_down_up` is defined but unbound.

## File Structure

- `config/west.yml` — add the cormoran module project (pinned tag).
- `boards/shields/roBa/roBa_R.conf` — enable the module + its Studio RPC.
- `config/roBa.keymap` — include the dtsi; convert `encoder_vol_down_up` to the runtime variant.
- `tools/roba-cli/proto/cormoran/rsr/custom.proto` + `custom.options` — vendored proto source.
- `tools/roba-cli/roba_cli/proto/cormoran/rsr/custom_pb2.py` + `__init__.py` — generated.
- `tools/roba-cli/roba_cli/encoder_client.py` — pure builders/decoders + `EncoderClient` transport.
- `tools/roba-cli/roba_cli/cli.py` — `encoder` subcommand group.
- `tools/roba-cli/tests/test_encoder.py` — unit tests.
- `tools/roba-cli/README.md`, `memory/project_roba_studio_cli.md`, `.git/sdd/progress.md` — docs.

---

### Task 1: Firmware wiring (west.yml + conf + keymap)

**Files:**
- Modify: `config/west.yml`
- Modify: `boards/shields/roBa/roBa_R.conf`
- Modify: `config/roBa.keymap:192-208` (behaviors block) and the include section

**Interfaces:**
- Produces: a firmware build that registers the `cormoran_rsr` custom subsystem and a
  `zmk,behavior-runtime-sensor-rotate` instance `encoder_vol_down_up` with DT default
  cw=`&kp C_VOLUME_DOWN`, ccw=`&kp C_VOLUME_UP`, `tap-ms=20`, bound on the 5 layers as before.
- Consumes: nothing (first task).

- [ ] **Step 1: Pin the module in `config/west.yml`**

Add under `projects:` (after the `zmk-module-runtime-conditional-layers` entry):

```yaml
    - name: zmk-behavior-runtime-sensor-rotate
      remote: cormoran
      # Same compat tag as runtime-input-processor: zmk-v0.3.0.0 is the last
      # pre-"Migrate to zmk v4" release and keeps the full custom-RPC surface
      # against this v0.3-branch+dya base. Module `main` won't build here.
      revision: zmk-v0.3.0.0
```

- [ ] **Step 2: Enable the module in `boards/shields/roBa/roBa_R.conf`**

Append (after the W2b condlayers block):

```conf
# runtime sensor-rotate module (W2c): edit encoder cw/ccw bindings over cormoran_rsr.
# Active sensor is the left encoder (index 0); revert = set behavior id 0 -> DT default.
CONFIG_ZMK_RUNTIME_SENSOR_ROTATE=y
CONFIG_ZMK_RUNTIME_SENSOR_ROTATE_STUDIO_RPC=y
```

- [ ] **Step 3: Add the dtsi include in `config/roBa.keymap`**

Find the existing behavior/dtsi includes near the top of the file (where other
`#include` lines live) and add:

```c
#include <behaviors/runtime-sensor-rotate.dtsi>
```

(This provides the transparent `rsr_trans` instance and is required for the
`zmk,behavior-runtime-sensor-rotate` compatible to resolve.)

- [ ] **Step 4: Convert `encoder_vol_down_up` to the runtime variant**

In `config/roBa.keymap` replace the `encoder_vol_down_up` node (currently lines ~201-208):

```c
        encoder_vol_down_up: encoder_vol_down_up {
            compatible = "zmk,behavior-sensor-rotate";
            label = "ENCODER_VOL_DOWN_UP";
            #sensor-binding-cells = <0>;
            bindings = <&kp C_VOLUME_DOWN>, <&kp C_VOLUME_UP>;

            tap-ms = <20>;
        };
```

with (preserve the exact rotation direction: old `bindings[0]`→`cw-binding`, `bindings[1]`→`ccw-binding`):

```c
        encoder_vol_down_up: encoder_vol_down_up {
            compatible = "zmk,behavior-runtime-sensor-rotate";
            label = "ENCODER_VOL_DOWN_UP";
            #sensor-binding-cells = <0>;
            cw-binding = <&kp C_VOLUME_DOWN>;
            ccw-binding = <&kp C_VOLUME_UP>;

            tap-ms = <20>;
        };
```

Leave `encoder_msc_down_up` (the unused core instance) untouched and leave the 5
`sensor-bindings = <&encoder_vol_down_up>;` references unchanged.

- [ ] **Step 5: Sanity-check the device-tree edits locally**

Run: `git -C /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa diff --stat`
Expected: three files changed (`config/west.yml`, `boards/shields/roBa/roBa_R.conf`,
`config/roBa.keymap`). Visually confirm the keymap block now reads
`compatible = "zmk,behavior-runtime-sensor-rotate"` with `cw-binding`/`ccw-binding`.

(The real build gate is CI; there is no local firmware build. CI runs in Task 7's
verification once the branch is prepared for merge.)

- [ ] **Step 6: Commit**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add config/west.yml boards/shields/roBa/roBa_R.conf config/roBa.keymap
git commit -m "$(printf 'feat(roba-w2c): wire runtime sensor-rotate module + convert encoder\n\nPin cormoran zmk-behavior-runtime-sensor-rotate at tag zmk-v0.3.0.0, enable\nCONFIG_ZMK_RUNTIME_SENSOR_ROTATE(_STUDIO_RPC), include the dtsi, and convert\nencoder_vol_down_up to zmk,behavior-runtime-sensor-rotate keeping vol up/down\nas the DT default (cw=C_VOLUME_DOWN, ccw=C_VOLUME_UP).\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 2: Generate the `cormoran.rsr` proto

**Files:**
- Create: `tools/roba-cli/proto/cormoran/rsr/custom.proto`
- Create: `tools/roba-cli/proto/cormoran/rsr/custom.options`
- Create: `tools/roba-cli/roba_cli/proto/cormoran/rsr/__init__.py`
- Create: `tools/roba-cli/roba_cli/proto/cormoran/rsr/custom_pb2.py` (generated)
- Test: `tools/roba-cli/tests/test_encoder.py`

**Interfaces:**
- Produces: importable `from roba_cli.proto.cormoran.rsr import custom_pb2 as rsr_pb2` with
  messages `Request`, `Response`, `Binding`, `LayerBindings`, `SensorInfo`, `ErrorResponse`.
- Consumes: nothing.

- [ ] **Step 1: Vendor the proto source**

Fetch the two files from the tag and save them verbatim:

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa/tools/roba-cli
mkdir -p proto/cormoran/rsr
REF='v0.3-branch'  # placeholder; use the module tag below
gh api -H "Accept: application/vnd.github.raw" \
  'repos/cormoran/zmk-behavior-runtime-sensor-rotate/contents/proto/cormoran/rsr/custom.proto?ref=zmk-v0.3.0.0' \
  > proto/cormoran/rsr/custom.proto
gh api -H "Accept: application/vnd.github.raw" \
  'repos/cormoran/zmk-behavior-runtime-sensor-rotate/contents/proto/cormoran/rsr/custom.options?ref=zmk-v0.3.0.0' \
  > proto/cormoran/rsr/custom.options
```

Verify `head -3 proto/cormoran/rsr/custom.proto` shows `package cormoran.rsr;`.

- [ ] **Step 2: Generate the Python stub**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa/tools/roba-cli
.venv/bin/python -m grpc_tools.protoc -I proto --python_out=roba_cli/proto \
  proto/cormoran/rsr/custom.proto
touch roba_cli/proto/cormoran/rsr/__init__.py
```

Verify the file exists: `ls roba_cli/proto/cormoran/rsr/custom_pb2.py`.
(`roba_cli/proto/cormoran/__init__.py` already exists from the rip module.)

- [ ] **Step 3: Write the failing proto-shape test**

Create `tools/roba-cli/tests/test_encoder.py`:

```python
import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.cormoran.rsr import custom_pb2 as rsr_pb2


def test_rsr_proto_imports_and_fields_exist():
    req = rsr_pb2.Request()
    rnames = {f.name for f in req.DESCRIPTOR.fields}
    assert {"set_layer_cw_binding", "set_layer_ccw_binding",
            "get_all_layer_bindings", "get_sensors"} <= rnames
    resp = rsr_pb2.Response()
    pnames = {f.name for f in resp.DESCRIPTOR.fields}
    assert {"error", "set_layer_cw_binding", "set_layer_ccw_binding",
            "get_all_layer_bindings", "get_sensors"} <= pnames
    b = rsr_pb2.Binding()
    bnames = {f.name for f in b.DESCRIPTOR.fields}
    assert {"behavior_id", "param1", "param2", "tap_ms"} <= bnames
    lb = rsr_pb2.LayerBindings()
    lnames = {f.name for f in lb.DESCRIPTOR.fields}
    assert {"layer", "cw_binding", "ccw_binding"} <= lnames
```

- [ ] **Step 4: Run the test**

Run: `cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa/tools/roba-cli && .venv/bin/python -m pytest tests/test_encoder.py -v`
Expected: PASS (proto already generated in Step 2).

- [ ] **Step 5: Commit**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/proto/cormoran/rsr tools/roba-cli/roba_cli/proto/cormoran/rsr tools/roba-cli/tests/test_encoder.py
git commit -m "$(printf 'feat(roba-cli): vendor + generate cormoran.rsr proto (W2c)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 3: `encoder_client` pure helpers (parsing, crc16, builders, decoders)

**Files:**
- Create: `tools/roba-cli/roba_cli/encoder_client.py` (helpers only this task)
- Test: `tools/roba-cli/tests/test_encoder.py`

**Interfaces:**
- Consumes: `rsr_pb2` from Task 2.
- Produces (used by Task 4 & 5):
  - `SUBSYSTEM_ID = "cormoran_rsr"`
  - `SCRL: dict[str, int]` with keys `SCRL_UP/SCRL_DOWN/SCRL_LEFT/SCRL_RIGHT`.
  - `BEHAVIOR_DEV_NAME: dict[str, str]` = `{"kp": "key_press", "msc": "mouse_scroll"}`.
  - `crc16_ansi(data: bytes) -> int`
  - `parse_encoder_behavior(spec: str) -> tuple[str | None, int, int, int]` returning
    `(behavior_token, behavior_id, param1, param2)` — for `kp`/`msc` `behavior_id` is `0`
    (resolved later) and `behavior_token` is `"kp"`/`"msc"`; for `raw` `behavior_token` is
    `None` and `behavior_id` is explicit.
  - `build_set_request(direction: str, sensor: int, layer: int, behavior_id: int, param1: int, param2: int, tap_ms: int) -> rsr_pb2.Request`
  - `build_get_request(sensor: int) -> rsr_pb2.Request`
  - `build_get_sensors_request() -> rsr_pb2.Request`
  - `binding_to_dict(b: rsr_pb2.Binding) -> dict`
  - `decode_response(resp: rsr_pb2.Response) -> dict`

- [ ] **Step 1: Write failing tests for the pure helpers**

Append to `tools/roba-cli/tests/test_encoder.py`:

```python
from roba_cli import encoder_client as ec


def test_crc16_ansi_check_value_and_names():
    assert ec.crc16_ansi(b"123456789") == 0xBB3D
    assert ec.crc16_ansi(b"key_press") == 13527
    assert ec.crc16_ansi(b"mouse_scroll") == 7776


def test_scrl_table_values():
    assert ec.SCRL["SCRL_UP"] == 10
    assert ec.SCRL["SCRL_DOWN"] == 65526
    assert ec.SCRL["SCRL_LEFT"] == 4294311936
    assert ec.SCRL["SCRL_RIGHT"] == 655360


def test_parse_encoder_behavior_kp_msc_raw():
    tok, bid, p1, p2 = ec.parse_encoder_behavior("kp C_VOL_UP")
    assert tok == "kp" and bid == 0 and p1 == 786665 and p2 == 0
    tok, bid, p1, p2 = ec.parse_encoder_behavior("msc SCRL_DOWN")
    assert tok == "msc" and bid == 0 and p1 == 65526 and p2 == 0
    tok, bid, p1, p2 = ec.parse_encoder_behavior("raw 7776 65526 0")
    assert tok is None and bid == 7776 and p1 == 65526 and p2 == 0


def test_parse_encoder_behavior_rejects_unknown():
    import pytest
    with pytest.raises(ValueError):
        ec.parse_encoder_behavior("nope X")
    with pytest.raises(ValueError):
        ec.parse_encoder_behavior("msc NOT_A_SCRL")


def test_build_set_request_directions():
    cw = ec.build_set_request("cw", sensor=0, layer=2, behavior_id=13527,
                              param1=10, param2=0, tap_ms=20)
    assert cw.WhichOneof("request_type") == "set_layer_cw_binding"
    s = cw.set_layer_cw_binding
    assert s.sensor_index == 0 and s.layer == 2
    assert s.binding.behavior_id == 13527 and s.binding.param1 == 10 and s.binding.tap_ms == 20
    ccw = ec.build_set_request("ccw", 0, 2, 13527, 65526, 0, 20)
    assert ccw.WhichOneof("request_type") == "set_layer_ccw_binding"


def test_build_set_request_bad_direction():
    import pytest
    with pytest.raises(ValueError):
        ec.build_set_request("sideways", 0, 0, 1, 0, 0, 5)


def test_decode_response_get_and_error():
    resp = rsr_pb2.Response()
    lb = resp.get_all_layer_bindings.bindings.add()
    lb.layer = 0
    lb.cw_binding.behavior_id = 13527
    lb.cw_binding.param1 = 10
    lb.ccw_binding.behavior_id = 13527
    lb.ccw_binding.param1 = 786665
    d = ec.decode_response(resp)
    assert d["ok"] is True
    assert d["bindings"][0]["layer"] == 0
    assert d["bindings"][0]["cw"]["behavior_id"] == 13527
    err = rsr_pb2.Response()
    err.error.message = "bad sensor"
    de = ec.decode_response(err)
    assert de["ok"] is False and de["error"] == "bad sensor"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd .../tools/roba-cli && .venv/bin/python -m pytest tests/test_encoder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roba_cli.encoder_client'`.

- [ ] **Step 3: Implement the pure helpers**

Create `tools/roba-cli/roba_cli/encoder_client.py`:

```python
"""EncoderClient: runtime sensor-rotate (encoder) config over the cormoran_rsr custom RPC.

Same 2-step custom envelope as RipClient: list_custom_subsystems -> resolve
"cormoran_rsr" index -> call(payload=rsr.Request). Pure request builders /
response decoders are unit-tested; the thin client + live behavior-id resolution
is HIL-tested.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import custom_pb2
import behaviors_pb2
from roba_cli.proto.cormoran.rsr import custom_pb2 as rsr_pb2

from . import rpc

SUBSYSTEM_ID = "cormoran_rsr"

# Device names whose crc16_ansi == the firmware behavior_local_id (CRC16 mode).
BEHAVIOR_DEV_NAME = {"kp": "key_press", "msc": "mouse_scroll"}

# msc scroll params, from dt-bindings/zmk/pointing.h (MOVE_VAL=600, SCRL_VAL=10):
#   SCRL_UP=MOVE_Y(10), SCRL_DOWN=MOVE_Y(-10), SCRL_LEFT=MOVE_X(-10), SCRL_RIGHT=MOVE_X(10)
SCRL = {
    "SCRL_UP": 10,
    "SCRL_DOWN": (-10) & 0xFFFF,                 # 65526
    "SCRL_LEFT": ((-10) & 0xFFFF) << 16,         # 4294311936
    "SCRL_RIGHT": (10 & 0xFFFF) << 16,           # 655360
}


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


def parse_encoder_behavior(spec: str) -> tuple[str | None, int, int, int]:
    """Parse a curated behavior spec into (token, behavior_id, param1, param2).

    'kp <KEYCODE>'   -> ("kp", 0, keycode, 0)        token resolved to id later
    'msc <SCRL_x>'   -> ("msc", 0, scroll, 0)
    'raw <id> <p1> [p2]' -> (None, id, p1, p2)       explicit id, no resolution
    """
    parts = spec.split()
    if not parts:
        raise ValueError("empty behavior spec")
    head = parts[0].lower()
    rest = parts[1:]
    if head == "kp":
        if len(rest) != 1:
            raise ValueError("kp requires one keycode, e.g. 'kp C_VOL_UP'")
        return ("kp", 0, _keycode_value(rest[0]), 0)
    if head == "msc":
        if len(rest) != 1:
            raise ValueError("msc requires one scroll, e.g. 'msc SCRL_DOWN'")
        key = rest[0].upper()
        if key not in SCRL:
            raise ValueError(f"unknown scroll {rest[0]!r}; known: {sorted(SCRL)}")
        return ("msc", 0, SCRL[key], 0)
    if head == "raw":
        if len(rest) not in (2, 3):
            raise ValueError("raw requires <behavior_id> <param1> [param2]")
        bid = int(rest[0]); p1 = int(rest[1]); p2 = int(rest[2]) if len(rest) == 3 else 0
        return (None, bid, p1, p2)
    raise ValueError(f"unknown behavior spec {spec!r} (use kp/msc/raw)")


def _fill_binding(binding, behavior_id: int, param1: int, param2: int, tap_ms: int) -> None:
    binding.behavior_id = behavior_id
    binding.param1 = param1
    binding.param2 = param2
    binding.tap_ms = tap_ms


def build_set_request(direction: str, sensor: int, layer: int, behavior_id: int,
                      param1: int, param2: int, tap_ms: int) -> "rsr_pb2.Request":
    req = rsr_pb2.Request()
    if direction == "cw":
        sub = req.set_layer_cw_binding
    elif direction == "ccw":
        sub = req.set_layer_ccw_binding
    else:
        raise ValueError(f"direction must be 'cw' or 'ccw', got {direction!r}")
    sub.sensor_index = sensor
    sub.layer = layer
    _fill_binding(sub.binding, behavior_id, param1, param2, tap_ms)
    return req


def build_get_request(sensor: int) -> "rsr_pb2.Request":
    req = rsr_pb2.Request()
    req.get_all_layer_bindings.sensor_index = sensor
    return req


def build_get_sensors_request() -> "rsr_pb2.Request":
    req = rsr_pb2.Request()
    req.get_sensors.SetInParent()
    return req


def binding_to_dict(b: "rsr_pb2.Binding") -> dict:
    return {"behavior_id": b.behavior_id, "param1": b.param1,
            "param2": b.param2, "tap_ms": b.tap_ms}


def decode_response(resp: "rsr_pb2.Response") -> dict:
    which = resp.WhichOneof("response_type")
    if which is None:
        return {"ok": False, "error": "empty rsr response"}
    if which == "error":
        return {"ok": False, "error": resp.error.message}
    out = {"ok": True, "error": ""}
    if which == "get_all_layer_bindings":
        out["bindings"] = [
            {"layer": lb.layer,
             "cw": binding_to_dict(lb.cw_binding),
             "ccw": binding_to_dict(lb.ccw_binding)}
            for lb in resp.get_all_layer_bindings.bindings
        ]
    elif which == "get_sensors":
        out["sensors"] = [{"index": s.index, "name": s.name}
                          for s in resp.get_sensors.sensors]
    elif which in ("set_layer_cw_binding", "set_layer_ccw_binding"):
        out["ok"] = bool(getattr(resp, which).success)
    return out
```

- [ ] **Step 4: Run tests**

Run: `cd .../tools/roba-cli && .venv/bin/python -m pytest tests/test_encoder.py -v`
Expected: PASS (all helper tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/roba_cli/encoder_client.py tools/roba-cli/tests/test_encoder.py
git commit -m "$(printf 'feat(roba-cli): encoder_client pure helpers (crc16/parse/build/decode) (W2c)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 4: `EncoderClient` transport + behavior-id resolution

**Files:**
- Modify: `tools/roba-cli/roba_cli/encoder_client.py` (append the class)
- Test: `tools/roba-cli/tests/test_encoder.py`

**Interfaces:**
- Consumes: helpers from Task 3; `rpc.send_recv`, `rpc.find_port`, `rpc.DEFAULT_BAUD`;
  `studio_pb2`, `custom_pb2`, `behaviors_pb2`.
- Produces (used by Task 5): `EncoderClient` with
  `sensors() -> dict`, `get(sensor: int = 0) -> dict`,
  `set(sensor: int, layer: int, direction: str, spec: str, tap_ms: int | None = None) -> dict`,
  `reset(sensor: int, layer: int) -> dict`, `behaviors() -> dict`,
  and `resolve_behavior_local_id(token: str) -> int`.

- [ ] **Step 1: Write failing transport tests (FakeSerial round-trip)**

Append to `tools/roba-cli/tests/test_encoder.py`:

```python
import studio_pb2
import custom_pb2
from roba_cli.framing import encode_frame


class _FakeSerial:
    def __init__(self, payload: bytes):
        self._payload = bytearray(payload)
        self.written = bytearray()

    def write(self, b):
        self.written += b

    def flush(self):
        pass

    def read(self, n):
        if not self._payload:
            return b""
        out = bytes(self._payload[:n])
        del self._payload[:n]
        return out


def _custom_call_frame(rsr_resp: "rsr_pb2.Response") -> bytes:
    s = studio_pb2.Response()
    s.request_response.request_id = 1
    s.request_response.custom.call.payload = rsr_resp.SerializeToString()
    return encode_frame(s.SerializeToString())


def test_get_decodes_over_custom_envelope():
    r = rsr_pb2.Response()
    lb = r.get_all_layer_bindings.bindings.add()
    lb.layer = 0
    lb.cw_binding.behavior_id = 13527
    lb.cw_binding.param1 = 10
    c = ec.EncoderClient(_ser=_FakeSerial(_custom_call_frame(r)))
    c._index = 0
    d = c.get(0)
    assert d["ok"] is True and d["bindings"][0]["cw"]["behavior_id"] == 13527


def test_sensors_decodes_over_custom_envelope():
    r = rsr_pb2.Response()
    s0 = r.get_sensors.sensors.add(); s0.index = 0; s0.name = "encoder_left"
    s1 = r.get_sensors.sensors.add(); s1.index = 1; s1.name = "encoder_right"
    c = ec.EncoderClient(_ser=_FakeSerial(_custom_call_frame(r)))
    c._index = 0
    d = c.sensors()
    assert [s["name"] for s in d["sensors"]] == ["encoder_left", "encoder_right"]


def test_resolve_behavior_local_id_crc16_when_present():
    # behavior list contains the crc16 id -> resolves
    c = ec.EncoderClient(_ser=_FakeSerial(b""))
    c._index = 0
    c._behavior_ids = lambda: {13527, 7776, 99}   # stub the live id set
    assert c.resolve_behavior_local_id("kp") == 13527
    assert c.resolve_behavior_local_id("msc") == 7776


def test_resolve_behavior_local_id_raises_when_absent():
    import pytest
    c = ec.EncoderClient(_ser=_FakeSerial(b""))
    c._index = 0
    c._behavior_ids = lambda: {1, 2, 3}
    with pytest.raises(ec.BehaviorResolutionError):
        c.resolve_behavior_local_id("kp")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd .../tools/roba-cli && .venv/bin/python -m pytest tests/test_encoder.py -k "envelope or resolve" -v`
Expected: FAIL — `AttributeError: module 'roba_cli.encoder_client' has no attribute 'EncoderClient'`.

- [ ] **Step 3: Implement the class + resolution**

> **NOTE — Learn by Doing candidate (Learning output style):** the
> `resolve_behavior_local_id` policy (crc16 compute → cross-check against the live
> behavior-id set → raise with a helpful fallback hint) is the one meaningful design
> decision in this task. If executing inline, leave it as `TODO(human)` and request the
> contribution. If executing via subagents, implement it as written below.

Append to `tools/roba-cli/roba_cli/encoder_client.py`:

```python
DEFAULT_TAP_MS = 20


class BehaviorResolutionError(RuntimeError):
    pass


class EncoderClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD, _ser=None):
        if _ser is not None:
            self._ser = _ser
        else:
            target = port or rpc.find_port()
            self._ser = serial.Serial(target, baud, timeout=0.1)
        self._index: int | None = None
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "EncoderClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _next_rid(self) -> int:
        self._rid += 1
        return self._rid

    def _resolve_index(self) -> int:
        if self._index is not None:
            return self._index
        req = studio_pb2.Request()
        req.request_id = self._next_rid()
        req.custom.list_custom_subsystems.CopyFrom(custom_pb2.ListCustomSubsystemRequest())
        resp = rpc.send_recv(self._ser, req)
        css = resp.request_response.custom.list_custom_subsystems
        for sub in css.subsystems:
            if sub.identifier == SUBSYSTEM_ID:
                self._index = sub.index
                return sub.index
        raise RuntimeError(
            f"'{SUBSYSTEM_ID}' subsystem not found. "
            f"Available: {[(s.identifier, s.index) for s in css.subsystems]}"
        )

    def _call(self, rsr_req: "rsr_pb2.Request") -> "rsr_pb2.Response":
        idx = self._resolve_index()
        sreq = studio_pb2.Request()
        sreq.request_id = self._next_rid()
        sreq.custom.call.subsystem_index = idx
        sreq.custom.call.payload = rsr_req.SerializeToString()
        sresp = rpc.send_recv(self._ser, sreq)
        out = rsr_pb2.Response()
        out.ParseFromString(sresp.request_response.custom.call.payload)
        return out

    def _behavior_ids(self) -> set[int]:
        """Live behavior local_id set via the core behaviors RPC."""
        req = studio_pb2.Request()
        req.request_id = self._next_rid()
        req.behaviors.list_all_behaviors.SetInParent()
        resp = rpc.send_recv(self._ser, req)
        return set(resp.request_response.behaviors.list_all_behaviors.behaviors)

    def resolve_behavior_local_id(self, token: str) -> int:
        if token not in BEHAVIOR_DEV_NAME:
            raise BehaviorResolutionError(f"no device name known for token {token!r}")
        candidate = crc16_ansi(BEHAVIOR_DEV_NAME[token].encode())
        live = self._behavior_ids()
        if candidate in live:
            return candidate
        raise BehaviorResolutionError(
            f"crc16 id {candidate} for '{token}' ({BEHAVIOR_DEV_NAME[token]}) "
            f"not in live behavior ids {sorted(live)}. The firmware may use the "
            f"settings-table local-id mode; use 'roba encoder behaviors' to list "
            f"ids and pass 'raw <id> <param1> [param2]'."
        )

    def sensors(self) -> dict:
        return decode_response(self._call(build_get_sensors_request()))

    def get(self, sensor: int = 0) -> dict:
        return decode_response(self._call(build_get_request(sensor)))

    def behaviors(self) -> dict:
        """List live behaviors as {id, display_name} for discovery."""
        ids = sorted(self._behavior_ids())
        out = []
        for bid in ids:
            req = studio_pb2.Request()
            req.request_id = self._next_rid()
            req.behaviors.get_behavior_details.behavior_id = bid
            resp = rpc.send_recv(self._ser, req)
            d = resp.request_response.behaviors.get_behavior_details
            out.append({"id": bid, "display_name": d.display_name})
        return {"ok": True, "error": "", "behaviors": out}

    def set(self, sensor: int, layer: int, direction: str, spec: str,
            tap_ms: int | None = None) -> dict:
        token, behavior_id, param1, param2 = parse_encoder_behavior(spec)
        if token is not None:
            behavior_id = self.resolve_behavior_local_id(token)
        tms = DEFAULT_TAP_MS if tap_ms is None else tap_ms
        return decode_response(self._call(
            build_set_request(direction, sensor, layer, behavior_id, param1, param2, tms)))

    def reset(self, sensor: int, layer: int) -> dict:
        """Revert a layer: set cw and ccw behavior_id 0 -> DT-default fallback."""
        cw = decode_response(self._call(
            build_set_request("cw", sensor, layer, 0, 0, 0, DEFAULT_TAP_MS)))
        ccw = decode_response(self._call(
            build_set_request("ccw", sensor, layer, 0, 0, 0, DEFAULT_TAP_MS)))
        ok = cw.get("ok") and ccw.get("ok")
        return {"ok": bool(ok), "error": cw.get("error") or ccw.get("error", "")}
```

- [ ] **Step 4: Run tests**

Run: `cd .../tools/roba-cli && .venv/bin/python -m pytest tests/test_encoder.py -v`
Expected: PASS (all encoder tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/roba_cli/encoder_client.py tools/roba-cli/tests/test_encoder.py
git commit -m "$(printf 'feat(roba-cli): EncoderClient transport + crc16 behavior-id resolution (W2c)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 5: `cli.py` — `roba encoder` command group

**Files:**
- Modify: `tools/roba-cli/roba_cli/cli.py`
- Test: `tools/roba-cli/tests/test_encoder.py`

**Interfaces:**
- Consumes: `EncoderClient` from Task 4.
- Produces: argparse subcommands `encoder sensors|get|set|reset|behaviors` with handler
  functions `cmd_encoder_sensors/get/set/reset/behaviors`.

- [ ] **Step 1: Write the failing CLI-parse test**

Append to `tools/roba-cli/tests/test_encoder.py`:

```python
from roba_cli import cli as _cli


def test_encoder_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["encoder", "set", "0", "2", "cw", "msc SCRL_DOWN"])
    assert ns.sensor == 0 and ns.layer == 2 and ns.direction == "cw"
    assert ns.behavior == "msc SCRL_DOWN" and ns.func is _cli.cmd_encoder_set
    ns2 = p.parse_args(["encoder", "get", "--sensor", "1"])
    assert ns2.sensor == 1 and ns2.func is _cli.cmd_encoder_get
    assert p.parse_args(["encoder", "sensors"]).func is _cli.cmd_encoder_sensors
    assert p.parse_args(["encoder", "behaviors"]).func is _cli.cmd_encoder_behaviors
    ns3 = p.parse_args(["encoder", "reset", "0", "2"])
    assert ns3.sensor == 0 and ns3.layer == 2 and ns3.func is _cli.cmd_encoder_reset
```

- [ ] **Step 2: Run to verify failure**

Run: `cd .../tools/roba-cli && .venv/bin/python -m pytest tests/test_encoder.py -k encoder_subcommands -v`
Expected: FAIL — `AttributeError: ... cmd_encoder_set` / unknown choice `encoder`.

- [ ] **Step 3: Implement the CLI handlers + subparser**

In `tools/roba-cli/roba_cli/cli.py`:

1. Add the import near the other client imports (after the condlayer import line):

```python
from .encoder_client import EncoderClient
```

2. Add the handler functions (place them next to the trackball handlers, following the
   existing `_print` JSON convention used by the other `cmd_*` functions in this file):

```python
def cmd_encoder_sensors(args: argparse.Namespace) -> int:
    with EncoderClient(args.port) as c:
        _print(c.sensors())
    return 0


def cmd_encoder_get(args: argparse.Namespace) -> int:
    with EncoderClient(args.port) as c:
        _print(c.get(args.sensor))
    return 0


def cmd_encoder_set(args: argparse.Namespace) -> int:
    with EncoderClient(args.port) as c:
        _print(c.set(args.sensor, args.layer, args.direction, args.behavior,
                     tap_ms=args.tap_ms))
    return 0


def cmd_encoder_reset(args: argparse.Namespace) -> int:
    with EncoderClient(args.port) as c:
        _print(c.reset(args.sensor, args.layer))
    return 0


def cmd_encoder_behaviors(args: argparse.Namespace) -> int:
    with EncoderClient(args.port) as c:
        _print(c.behaviors())
    return 0
```

> If `cli.py` does not have a `_print` helper, mirror the exact output style the
> existing handlers use (they call `print(json.dumps({...}))`). Use the same idiom.

3. Register the subparser group (mirror the `trackball` group registration in `build_parser`):

```python
    enc = sub.add_parser("encoder", help="runtime sensor-rotate (encoder) bindings")
    enc_sub = enc.add_subparsers(dest="encoder_cmd", required=True)

    e_sensors = enc_sub.add_parser("sensors", help="list sensors")
    e_sensors.set_defaults(func=cmd_encoder_sensors)

    e_get = enc_sub.add_parser("get", help="show all per-layer bindings for a sensor")
    e_get.add_argument("--sensor", type=int, default=0)
    e_get.set_defaults(func=cmd_encoder_get)

    e_set = enc_sub.add_parser("set", help="set a layer's cw/ccw binding")
    e_set.add_argument("sensor", type=int)
    e_set.add_argument("layer", type=int)
    e_set.add_argument("direction", choices=["cw", "ccw"])
    e_set.add_argument("behavior", help="e.g. 'kp C_VOL_UP', 'msc SCRL_DOWN', 'raw 7776 65526 0'")
    e_set.add_argument("--tap-ms", dest="tap_ms", type=int, default=None)
    e_set.set_defaults(func=cmd_encoder_set)

    e_reset = enc_sub.add_parser("reset", help="revert a layer to the DT default (set id 0)")
    e_reset.add_argument("sensor", type=int)
    e_reset.add_argument("layer", type=int)
    e_reset.set_defaults(func=cmd_encoder_reset)

    e_beh = enc_sub.add_parser("behaviors", help="list live behaviors (id, display_name)")
    e_beh.set_defaults(func=cmd_encoder_behaviors)
```

(Use the actual name of the top-level subparsers object in `build_parser` — match
whatever variable the `trackball`/`condlayer` groups are added to.)

- [ ] **Step 4: Run the full test suite**

Run: `cd .../tools/roba-cli && .venv/bin/python -m pytest -v`
Expected: PASS — all existing 53 tests plus the new encoder tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/roba_cli/cli.py tools/roba-cli/tests/test_encoder.py
git commit -m "$(printf 'feat(roba-cli): roba encoder command group (W2c)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 6: Docs (README + memory + ledger)

**Files:**
- Modify: `tools/roba-cli/README.md`
- Modify: `memory/project_roba_studio_cli.md` (add W2c line, update "runtime editable" list)
- Modify: `.git/sdd/progress.md` (append W2c entries)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Document the command group in `tools/roba-cli/README.md`**

Add a section mirroring the other groups' style:

```markdown
### `roba encoder` (W2c — runtime sensor-rotate)

Edit the rotary-encoder rotation bindings per layer (no reflash). Active sensor is
the left encoder (index 0).

- `roba encoder sensors` — list sensors `{index, name}`.
- `roba encoder get [--sensor N]` — show every layer's `cw`/`ccw` binding.
- `roba encoder set <sensor> <layer> <cw|ccw> "<behavior>"` — set a binding.
  Behaviors: `kp <KEYCODE>` (e.g. `kp C_VOL_UP`), `msc <SCRL_x>` (e.g. `msc SCRL_DOWN`),
  or `raw <behavior_id> <param1> [param2]`. Optional `--tap-ms N`.
- `roba encoder reset <sensor> <layer>` — revert to the device-tree default
  (sets behavior id 0 → live fallback to vol up/down).
- `roba encoder behaviors` — list live behaviors `{id, display_name}` (discovery).

Notes: behavior tokens resolve via `crc16_ansi(device_name)` cross-checked against the
live behavior-id list; if the firmware uses the settings-table local-id mode, use
`behaviors` + `raw`. The global `roba reset` does NOT clear encoder bindings — use
`encoder reset` per layer.
```

Also update the README title line that enumerates phases (append `/ W2c`).

- [ ] **Step 2: Update the project memory**

In `memory/project_roba_studio_cli.md`, add a `**W2c 完了**` line in the same style as the
W2a/W2b lines and extend the "現状 runtime 編集可能" enumeration with
`エンコーダ(W2c)`. Reference `[[reference_runtime_input_processor_w1b]]` (same reuse pattern).

- [ ] **Step 3: Append to the progress ledger**

Add W2c task lines to `.git/sdd/progress.md` mirroring the W2b block format.

- [ ] **Step 4: Commit**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/README.md memory/project_roba_studio_cli.md
git commit -m "$(printf 'docs(roba-w2c): document roba encoder group + update project state\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

(`.git/sdd/progress.md` is inside `.git` and not tracked; update it but it is not committed.)

---

### Task 7: Build verification, HIL, opus review, local merge

**Files:** none (verification + merge).

**Interfaces:** consumes the full branch.

- [ ] **Step 1: Trigger the CI firmware build**

The build runs via the repo's `build.yml` on push. Since origin is not pushed during the
feature work, build verification happens by the user (or by pushing the branch only if the
user approves). Ask the user to confirm the CI build is green, OR push the feature branch if
the user authorizes it. **Do not push without explicit approval.**

Expected: CI builds roBa_R with the module enabled (no `dtsi`/link errors). If the build
fails on the tag, fall back to pinning a specific commit of the module (note in the ledger);
do not fork.

- [ ] **Step 2: User flashes and HIL-verifies**

Provide the flashing instruction and the HIL script. After flash:

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa/tools/roba-cli
.venv/bin/roba encoder sensors            # expect index 0 encoder_left (+ disabled right)
.venv/bin/roba encoder behaviors          # confirm key_press id == 13527, mouse_scroll == 7776
.venv/bin/roba encoder get --sensor 0     # DEFAULT layer cw/ccw show the vol defaults
.venv/bin/roba encoder set 0 0 cw "msc SCRL_DOWN"   # change CW on the DEFAULT layer
# turn the encoder CW -> page should SCROLL (observable)
# power-cycle the board, reconnect:
.venv/bin/roba encoder get --sensor 0     # cw still msc (NVS persisted)
.venv/bin/roba encoder reset 0 0          # revert layer 0
# turn encoder CW -> volume changes again (live DT-default fallback)
```

Verification gates:
- `behaviors` confirms the crc16 ids are present (validates the resolution mode). If they
  are NOT present, record it and switch the HIL to the `raw <id> ...` path using the ids
  `behaviors` reports.
- set → observable scroll; power-cycle persists; `reset` → observable volume.

- [ ] **Step 3: opus fidelity review of the config branch**

Dispatch an opus review of the branch diff (config + host only; module is unmodified).
Resolve any Critical/Important findings before merge.

- [ ] **Step 4: Local merge to main**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git checkout main
git merge --no-ff feat/roba-w2c-sensor-rotate -m "$(printf 'Merge W2c: runtime sensor-rotate (encoder) editing\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
.venv/bin/python -m pytest tools/roba-cli/ -q   # 53 + encoder tests green on merged main
git branch -d feat/roba-w2c-sensor-rotate
```

Do **not** push origin unless the user explicitly asks.

- [ ] **Step 5: Update memory + ledger with completion**

Mark W2c done in `memory/project_roba_studio_cli.md` and `.git/sdd/progress.md`,
including the resolved local-id mode (crc16 vs settings-table) learned at HIL.

---

## Self-Review

**Spec coverage:**
- west.yml pin → Task 1.1. conf flags → Task 1.2. keymap convert + dtsi → Task 1.3-1.4.
- proto gen → Task 2. encoder_client (sensors/get/set/reset, curated kp/msc, raw escape)
  → Tasks 3-4. CLI verbs → Task 5. tests → Tasks 2-5. README/memory/ledger → Task 6.
- revert via set-0 → Task 4 `reset`. behavior local_id resolution (crc16 + cross-check)
  → Task 4. HIL/opus/merge → Task 7. All spec sections mapped.

**Placeholder scan:** No TBD/TODO except the deliberate `TODO(human)` note in Task 4
(Learning-style contribution candidate, with the full implementation also provided so a
subagent can proceed). No "add error handling"/"similar to" placeholders; all code shown.

**Type consistency:** `parse_encoder_behavior` returns `(token, behavior_id, param1, param2)`
used identically in Task 4 `set`. `build_set_request(direction, sensor, layer, behavior_id,
param1, param2, tap_ms)` signature matches its call sites in Task 3 tests and Task 4 `set`/
`reset`. `decode_response` keys (`ok`, `error`, `bindings`, `sensors`) match CLI usage.
`SUBSYSTEM_ID`, `SCRL`, `BEHAVIOR_DEV_NAME`, `crc16_ansi`, `BehaviorResolutionError`
referenced consistently across tasks.
