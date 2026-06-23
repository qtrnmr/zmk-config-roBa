# OSS Docs & Examples (Sub-project C) — Design

Date: 2026-06-24
Status: Approved (design)
Where the work lands: the module repo `qtrnmr/zmk-module-runtime-config` (docs/examples + README fixes). The spec/plan live in the config repo's `docs/superpowers/` as usual.

## Context

Sub-projects A (unified firmware module `zmk-module-runtime-config`) and B
(generalized CLI `zmk-runtime-cli` / `zmkrt`, co-located in the module's `cli/`)
are done. Each wrote its own README. Sub-project C turns the module repo into a
self-serve OSS: a ZMK user on a cormoran custom-RPC base can go from zero to
editing their keyboard with `zmkrt` without getting stuck.

The existing READMEs already cover requirement/setup/install at a high level, but:
- `cli/README.md` names the companion modules wrong:
  `zmk-cormoran-input-processor` / `zmk-cormoran-encoder` — the real ones are
  `zmk-module-runtime-input-processor` (trackball) and
  `zmk-behavior-runtime-sensor-rotate` (encoder), both from the `cormoran`
  remote, pinned to tag `zmk-v0.3.0.0`.
- There is no single end-to-end "zero → working" path, and no copyable example
  keymap fragments.

This sub-project is documentation only — **no firmware or CLI code changes**.

## Goal

Add an end-to-end install guide and example fragments to the module repo, fix
the README inaccuracies, and surface the implicit knowledge (RPC buffer sizes,
the keymap-drawer incompatibility) that the roBa build proved necessary.

## Reference values (verified from the working roBa config — use verbatim)

- Base: `zmk` from remote `cormoran`, `revision: v0.3-branch+dya` (provides the
  custom Studio RPC layer).
- Unified module: `zmk-module-runtime-config`, remote `qtrnmr` (url-base
  `https://github.com/qtrnmr`), `revision: main`.
- Companions (optional, for trackball / encoder), remote `cormoran`, **both
  pinned `revision: zmk-v0.3.0.0`** (last pre-zmk-v4 tag that keeps the 1-arg
  API + full custom-RPC surface for this base):
  - `zmk-module-runtime-input-processor` → trackball/pointer (`zmkrt trackball`)
  - `zmk-behavior-runtime-sensor-rotate` → encoder rotation (`zmkrt encoder`)
- Required conf on the central shield (`<shield>_R.conf` / single-side `.conf`):
  - `CONFIG_ZMK_STUDIO=y` (+ a Studio transport; roBa uses
    `CONFIG_ZMK_STUDIO_TRANSPORT_BLE=y` and builds the central with the
    `studio-rpc-usb-uart` snippet so the CLI can reach it over USB).
  - Per feature wanted: `CONFIG_ZMK_RUNTIME_<F>=y` and `..._STUDIO_RPC=y` for
    `MACRO` / `HOLDTAP` / `CONDLAYERS` / `COMBOS` (+ companions'
    `CONFIG_ZMK_RUNTIME_INPUT_PROCESSOR(_STUDIO_RPC)` /
    `CONFIG_ZMK_RUNTIME_SENSOR_ROTATE(_STUDIO_RPC)`).
  - **`CONFIG_ZMK_STUDIO_RPC_RX_BUF_SIZE=1024`** and
    **`CONFIG_ZMK_STUDIO_RPC_CUSTOM_SUBSYSTEM_REQUEST_PAYLOAD_MAX_BYTES=512`** —
    the default RX buffer (30) silently drops larger custom-RPC frames; these
    values cover the worst-case macro/combo payloads.
- Keymap compatibles to switch to (only for the features you enable):
  - macro behavior → `zmk,behavior-runtime-macro` (instance `&rt_macro`)
  - hold-tap behaviors → `zmk,behavior-runtime-hold-tap`
  - `conditional_layers` node → `zmk,runtime-conditional-layers`
  - `combos` node → `zmk,runtime-combos`
  - (encoder, via companion) sensor behavior → `zmk,behavior-runtime-sensor-rotate`
- **keymap-drawer caveat**: keymap-drawer (≤0.23.0) cannot parse the
  `zmk,runtime-*` compatibles and will emit nothing / drop the drawing. The DT
  positions/outputs are unchanged, so it is cosmetic, but a [Draw]-style
  workflow will remove the svg/yaml. Document it.

## Deliverables (all in `zmk-module-runtime-config`)

### 1. Fix `cli/README.md`
Correct the companion module names + remote + tag pin, and the trackball/encoder
command mapping. No other content change.

### 2. Fix `README.md` (top) — west.yml example
Make the `west.yml` snippet match the real manifest shape: a `remotes:` block
(`cormoran`, `qtrnmr`) and `projects:` entries with `remote:`/`revision:` (the
current snippet uses a bare `url:` which isn't how the working config wires it).
Add the required-conf block (the buffer sizes) and the keymap-drawer caveat.

### 3. `docs/INSTALL.md` — zero → working quickstart
A single linear path:
1. Prerequisite: a cormoran custom-RPC ZMK base (how to tell: the base provides
   `zmk/studio/custom.h`).
2. `west.yml`: add the module (+ optional companions with the tag pin), with a
   complete copyable manifest fragment using the reference values above.
3. `<shield>.conf`: the feature flags + `_STUDIO_RPC` + the two buffer-size
   lines, with one sentence each on why.
4. keymap: switch the relevant nodes/behaviors to the runtime compatibles
   (before/after fragment per feature).
5. Build & flash as usual; then `pipx install` the CLI from `cli/` and run
   `zmkrt info` to confirm the subsystems respond.
6. Caveats: keymap-drawer incompatibility; `zmk-studio-api` source-build note;
   `--port` if auto-detect is ambiguous.

### 4. `examples/` — copyable keymap fragments
One minimal, generic (non-roBa) fragment per feature, each paired with the
`zmkrt` command that edits it:
- `examples/macro.md` — `#include <behaviors/runtime-macro.dtsi>`-style instance
  + `&rt_macro` placement + `zmkrt macro set 0 "type hello"`.
- `examples/holdtap.md` — a `zmk,behavior-runtime-hold-tap` behavior + a key
  using it + `zmkrt holdtap set 0 tapping-term-ms 180`.
- `examples/conditional-layers.md` — a `zmk,runtime-conditional-layers` node +
  `zmkrt condlayer set 0 1,2 5`.
- `examples/combos.md` — a `zmk,runtime-combos` node + `zmkrt combo set 0 binding "kp ESC"`,
  noting key-positions are fixed.
Each fragment uses the exact behavior/property names the firmware bindings
define (cross-checked against `dts/bindings/` in the repo).

### 5. Link the new docs
Add a short "Getting started → see docs/INSTALL.md" pointer and an
"Examples → examples/" pointer from the top README.

## Verification

Docs-only, so verification is correctness cross-checks (no code/tests change):
- Every `CONFIG_*` name in the docs exists in the repo's `Kconfig`.
- Every compatible string in the docs/examples matches a `dts/bindings/*.yaml`
  `compatible:` in the repo.
- Every `zmkrt <group> ...` command matches a real CLI verb (cross-check against
  `cli/zmk_runtime_cli/cli.py`).
- Companion module names/remote/tag match the working `config/west.yml`.
- No dead internal links.
- opus review does this cross-check end-to-end; the existing 92 CLI tests stay
  green (untouched).

## Out of scope

- Firmware / CLI code changes (sub-projects A/B, done).
- PyPI publishing, CONTRIBUTING, CI badges, demo video (later, if ever).
- Hardware HIL (the install guide is validated by the already-working roBa build,
  which used exactly these values).
- Touching the roBa config repo beyond the spec/plan docs.

## Acceptance

- `cli/README.md` + top `README.md` corrected (companion names, west.yml shape,
  buffer-size + drawer caveat present).
- `docs/INSTALL.md` gives a complete zero→working path with copyable fragments
  using the verified reference values.
- `examples/` has one fragment+command per feature, names cross-checked against
  the repo's bindings and CLI verbs.
- Top README links the guide and examples.
- opus cross-check passes (names/compatibles/verbs all real, no dead links).
- Module repo changes committed (qtrnmr identity) and pushed; the config-repo
  spec/plan branch merged to `main` (origin push per the session's go-ahead).
