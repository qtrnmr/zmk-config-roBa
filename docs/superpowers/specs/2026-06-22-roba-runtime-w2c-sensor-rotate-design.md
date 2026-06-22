# W2c — Runtime Sensor-Rotate (Encoder) Editing — Design

Date: 2026-06-22
Status: Approved (design)
Branch: `feat/roba-w2c-sensor-rotate`

## Goal

Edit the rotary-encoder rotation bindings of roBa **without reflashing**, from
Claude Code over USB. Expose a `roba encoder` command group that reads and
mutates the per-layer clockwise/counter-clockwise binding of each sensor, with
changes persisted across power cycles and instantly revertible to the
device-tree default.

This is the "light up existing OSS" pattern, identical in shape to W1b
(trackball / runtime-input-processor): reuse a complete cormoran module, pin it
to a base-compatible tag, and wire the host CLI. **No firmware fork.**

### Why this is a good unit

- The active encoder is `left_encoder` (alps,ec11, sensor index 0); `right_encoder`
  is `status = "disabled"`. The encoder is physically on the left half, but
  ZMK split processes sensor bindings on the **central** (roBa_R / USB), so only
  roBa_R changes — roBa_L stays untouched (same split topology lesson as W1b).
- Encoder edits are **directly observable** (volume changes, scroll moves), which
  makes HIL verification easier than hold-tap (W2a) or conditional layers (W2b),
  where the effect is invisible.

## Source module (reused as-is)

`cormoran/zmk-behavior-runtime-sensor-rotate`, tag **`zmk-v0.3.0.0`**.

Pin rationale: identical to `zmk-module-runtime-input-processor` (W1b). The
module's `main` migrated to zmk v4 and will not build against this
`v0.3-branch+dya` base; the `zmk-v0.3.0.0` tag is the last pre-migration release
and keeps the full custom-RPC surface. (Build-verified in CI as the gate.)

### Module surface (verified by reading source at the tag)

- Behavior `zmk,behavior-runtime-sensor-rotate` with DT properties:
  `#sensor-binding-cells = <0>`, `tap-ms`, `cw-binding` (phandle-array),
  `ccw-binding` (phandle-array). `dts/behaviors/runtime-sensor-rotate.dtsi`
  supplies a transparent `rsr_trans` instance.
- Custom Studio RPC subsystem identifier **`cormoran_rsr`**
  (`ZMK_RPC_CUSTOM_SUBSYSTEM(cormoran_rsr, ...)`), proto package `cormoran.rsr`:
  - `GetSensorsRequest` → `GetSensorsResponse{ repeated SensorInfo{index,name} }`
  - `GetAllLayerBindingsRequest{sensor_index}` →
    `GetAllLayerBindingsResponse{ repeated LayerBindings{layer, cw_binding, ccw_binding} }`
  - `SetLayerCwBindingRequest{sensor_index, layer, Binding}` → `{bool success}`
  - `SetLayerCcwBindingRequest{sensor_index, layer, Binding}` → `{bool success}`
  - `Binding { behavior_id, param1, param2, tap_ms }` where `behavior_id` **is**
    the `zmk_behavior_local_id_t` (firmware comment: "they are the same").
- Persistent storage built in: `SETTINGS_STATIC_HANDLER` key `rsr`, per
  `rsr/s<sensor>/l<layer>` via `settings_save_one`.

### Revert mechanism (decided: set-0, no fork)

The behavior falls back to the DT default binding when a stored binding's
`behavior_local_id == 0` (behavior source lines ~183-209): on read/trigger, a
zero local-id resolves to `default_cw_binding_name` / `default_ccw_binding_name`
(i.e. the keymap's `cw-binding`/`ccw-binding`). Therefore:

- **`roba encoder reset <sensor> <layer>`** = set both cw and ccw bindings to
  `behavior_id = 0`. This is a **live** revert to the device-tree default —
  satisfies the always-revertible-to-known-good constraint per binding.
- The module does **not** register `ZMK_RPC_SUBSYSTEM_SETTINGS_RESET`, so the
  global `roba reset` (settings reset) will **not** clear `rsr` keys. This is an
  accepted divergence from the other self-built modules: per-binding `reset`
  covers the revert requirement, and we keep the OSS module unmodified
  ("don't rebuild" principle). Documented as a known limitation.

## Components & changes

### 1. `config/west.yml`
Add under `qtrnmr-gh`-adjacent cormoran projects:
```yaml
    - name: zmk-behavior-runtime-sensor-rotate
      remote: cormoran
      revision: zmk-v0.3.0.0   # same compat tag as runtime-input-processor
```

### 2. `boards/shields/roBa/roBa_R.conf`
```conf
# runtime sensor-rotate module (W2c): edit encoder cw/ccw bindings over cormoran_rsr
CONFIG_ZMK_RUNTIME_SENSOR_ROTATE=y
CONFIG_ZMK_RUNTIME_SENSOR_ROTATE_STUDIO_RPC=y
```
RPC buffers already at `RX_BUF_SIZE=1024` / `PAYLOAD_MAX=512` (SP1) — sufficient.
roBa_L unchanged.

### 3. `config/roBa.keymap`
- Add `#include <behaviors/runtime-sensor-rotate.dtsi>` near the other includes.
- Convert the **bound** behavior `encoder_vol_down_up` only:
  - `compatible = "zmk,behavior-sensor-rotate"` → `"zmk,behavior-runtime-sensor-rotate"`.
  - `bindings = <&kp C_VOLUME_DOWN>, <&kp C_VOLUME_UP>` →
    `cw-binding = <&kp C_VOLUME_DOWN>; ccw-binding = <&kp C_VOLUME_UP>;`
    (preserve exact current order so physical rotation direction is unchanged).
  - keep `tap-ms = <20>`.
- The 5 `sensor-bindings = <&encoder_vol_down_up>` references are unchanged.
- `encoder_msc_down_up` (defined but unused, core sensor-rotate) is left
  untouched — scroll is achieved at runtime by assigning `msc SCRL_x` to the
  encoder, not via that instance.

### 4. host — `tools/roba-cli`
- Generate proto: copy `proto/cormoran/rsr/custom.proto` + `custom.options`,
  produce `roba_cli/proto/cormoran/rsr/custom_pb2.py` (+ `__init__.py`).
- `encoder_client.py` (mirrors `rip_client.py`): custom-envelope 2-step
  (`list_custom_subsystems` → resolve `cormoran_rsr` → `call`). Methods:
  - `sensors()` → list of `{index, name}`
  - `get(sensor)` → per-layer `[{layer, cw:{behavior,param1,param2,tap_ms}, ccw:{...}}]`
  - `set(sensor, layer, direction, behavior_str)` where direction ∈ {cw, ccw}
  - `reset(sensor, layer)` → set cw and ccw to `behavior_id=0`
- Behavior-string resolution (curated): accept `kp <KEYCODE>` and `msc <SCROLL>`.
  Resolve behavior name → `behavior_local_id` via the Studio behaviors list
  (the same list `keymap_client` already fetches for `key set`); resolve the
  keycode/param using the existing keycode parser. `param2` defaults to 0.
- `cli.py` verbs: `roba encoder sensors`, `roba encoder get <sensor>`,
  `roba encoder set <sensor> <layer> <cw|ccw> "<behavior>"`,
  `roba encoder reset <sensor> <layer>`. JSON output, consistent with other groups.

### 5. tests — `tests/test_encoder.py`
- proto round-trip over a `_FakeSerial` custom-call frame (get/set/sensors).
- behavior-string parse (`kp C_VOLUME_UP` → (behavior=kp-name, param1=keycode)).
- direction parse (`cw`/`ccw` → which set RPC), invalid direction rejected.
- CLI subcommand parse for all four verbs.
- Existing 53 tests must stay green.

## Data flow

```
roba encoder set 0 0 cw "msc SCRL_DOWN"
  → encoder_client resolves "msc" → local_id L (Studio behaviors list)
                     resolves "SCRL_DOWN" → param1 P
  → cormoran_rsr.SetLayerCwBindingRequest{sensor_index=0, layer=0,
        Binding{behavior_id=L, param1=P, param2=0, tap_ms=<keep/default>}}
  → wrapped in studio custom.call{subsystem_index, payload}
  → firmware stores rsr/s0/l0, returns success
turn encoder CW → behavior fires msc SCRL_DOWN (observable scroll)
power-cycle → rsr/s0/l0 reloaded → still scroll
roba encoder reset 0 0 → set cw & ccw behavior_id=0 → live fallback to vol up/down
```

## Risks & mitigations

- **zmk API compat at the tag**: assume `zmk-v0.3.0.0` is 1-arg-compatible like
  runtime-input-processor; **CI build is the gate**. If it fails to build,
  fall back to pinning a specific commit or (last resort) a thin fork — but
  expectation is a clean build, no fork.
- **behavior local_id stability**: the Studio behaviors list returns the
  firmware's authoritative local_ids, so host-resolved ids match what the
  firmware stores/triggers — same mechanism `key set` relies on. Low risk.
- **`tap_ms` on set**: preserve the existing per-binding `tap_ms` when only
  changing the behavior; default to the DT `tap-ms` (20) when creating fresh.
- **Global `roba reset` does not clear `rsr`**: documented limitation; per-binding
  `reset` is the supported revert path.

## Out of scope

- Modifying roBa_L or the right (disabled) encoder hardware.
- A settings-reset hook / module fork (explicitly declined).
- Arbitrary raw `local_id+param` assignment from the CLI (curated `kp`/`msc` only).
- Web UI (the module ships one; we use the CLI).

## Acceptance

- CI build green with the module enabled.
- `roba encoder sensors` lists left/right; `get 0` shows volume defaults.
- `set 0 <layer> cw "msc SCRL_DOWN"` → encoder scrolls; persists across power cycle.
- `reset 0 <layer>` → live revert to volume.
- All host tests (existing 53 + new encoder tests) green.
- opus fidelity review of the config branch: no Critical/Important findings.
- Merged to `main` locally (`--no-ff`), origin not pushed.
