# Unify Runtime Modules (Sub-project A) — Design

Date: 2026-06-23
Status: Approved (design)
Branch: `feat/unify-runtime-modules` (config repo) + new module repo `zmk-module-runtime-config`

## Context & vision

The roBa project built four self-built ZMK modules that make ZMK features
runtime-editable (no reflash) over cormoran's custom Studio RPC layer:
`zmk-module-runtime-macro` (SP1), `-holdtap` (W2a), `-conditional-layers` (W2b),
`-combos` (W2d). The goal now is to turn this into a reusable OSS: a single
drop-in module that any keyboard on a **cormoran custom-RPC ZMK base** can add
to its `west.yml`, then configure macros / hold-tap / conditional-layers /
combos from the CLI (Claude Code) without reflashing.

The full OSS effort decomposes into three sub-projects:
- **A (this spec): unified firmware module** — combine the 4 self-built modules
  into one repo with per-feature Kconfig.
- **B: generalized CLI** — rename/repackage `roba-cli` as a cross-platform,
  pip-installable tool (separate spec).
- **C: OSS packaging / install docs / examples** (separate spec).

This spec covers **A only**.

### Hard constraint (carried from the project)

Everything depends on cormoran's custom Studio RPC layer
(`<zmk/studio/custom.h>`, `ZMK_RPC_CUSTOM_SUBSYSTEM`), which is **NOT in mainline
ZMK** (verified: `app/include/zmk/studio/custom.h` exists in cormoran/zmk but
404s on zmkfirmware/zmk). So the unified module targets the cormoran custom-RPC
ZMK ecosystem, not arbitrary upstream ZMK. The README states this requirement.

### Decisive de-risking fact

roBa **already runs all four self-built modules simultaneously** (all four are
enabled in `boards/shields/roBa/roBa_R.conf` today and ship in one firmware).
Coexistence is therefore already proven on real hardware and in CI. Unification
is a **mechanical relocation** of files into one repo plus a unified
Kconfig/CMake — it introduces no new runtime coexistence risk. roBa is the
dogfood: if CI stays green after switching its `west.yml` to the unified module,
the merge is correct.

## Goal

Produce a single module repo `zmk-module-runtime-config` that provides the four
runtime-editable features behind independent Kconfig options, and migrate roBa's
`west.yml` from the four separate module entries to this one — with CI green and
a HIL smoke test confirming all four RPC subsystems still respond.

Working name: **`zmk-module-runtime-config`** (changeable). The features keep
their existing Kconfig names, RPC subsystem identifiers, proto packages, DT
compatibles, and source file names (no renames — that would break the proven
coexistence and force needless host/proto regeneration).

## Source modules being merged (verbatim, no logic changes)

| Feature | Repo | Kconfig | RPC subsystem | proto pkg | DT compatible / behavior |
|---|---|---|---|---|---|
| macro | zmk-module-runtime-macro | `ZMK_RUNTIME_MACRO`(+`_STUDIO_RPC`) | `zmk__macros` | zmk.macros | `zmk,behavior-runtime-macro` |
| hold-tap | zmk-module-runtime-holdtap | `ZMK_RUNTIME_HOLDTAP`(+`_STUDIO_RPC`) | `zmk__holdtap` | zmk.holdtap | `zmk,behavior-runtime-hold-tap` |
| conditional-layers | zmk-module-runtime-conditional-layers | `ZMK_RUNTIME_CONDLAYERS`(+`_STUDIO_RPC`,`_MAX`) | `zmk__condlayers` | zmk.condlayers | `zmk,runtime-conditional-layers` |
| combos | zmk-module-runtime-combos | `ZMK_RUNTIME_COMBOS`(+`_STUDIO_RPC`,`_MAX`) | `zmk__combos` | zmk.combos | `zmk,runtime-combos` |

All identifiers are already distinct across the four — they coexist without
collision (proven on roBa). The merge preserves every identifier verbatim.

## Unified repo layout

```
zmk-module-runtime-config/
  Kconfig                      # menu "ZMK Runtime Config" sourcing/declaring the 4 feature options
  CMakeLists.txt               # per-feature guarded source/proto inclusion (one nanopb gen over enabled protos)
  zephyr/module.yml            # name: zmk-module-runtime-config; cmake: .; kconfig: Kconfig; settings.dts_root: .
  LICENSE                      # MIT
  README.md                    # what it is, the cormoran-RPC base requirement, install, per-feature config
  include/zmk/                 # the existing public headers, copied verbatim
    runtime_macro.h
    runtime_holdtap.h
    runtime_condlayers.h
    runtime_combos.h
  src/
    behaviors/                 # behavior_runtime_macro.c, behavior_runtime_hold_tap.c (verbatim)
    runtime_conditional_layer.c
    runtime_combo.c
    runtime_macro_store.c, runtime_holdtap_store.c, runtime_condlayer_store.c, runtime_combo_store.c
    studio/                    # macros_rpc_handler.c, holdtap_rpc_handler.c, condlayers_rpc_handler.c, combos_rpc_handler.c
  proto/zmk/{macros,holdtap,condlayers,combos}/*.proto (+ .options)   # verbatim
  dts/bindings/                # zmk,runtime-* yamls + behaviors/runtime-*.dtsi (verbatim)
```

Exact file names are taken from the four source repos as-is. The merge copies
each repo's `src/`, `include/`, `proto/`, `dts/` contents into the unified tree
unchanged.

## Kconfig

A `menuconfig`/menu "ZMK Runtime Config" that declares the four independent
feature options, each defaulting **off** (the user opts in per feature). Each
option's body is copied verbatim from its source module's Kconfig (same option
names, help text, `_STUDIO_RPC` sub-option `depends on ZMK_STUDIO default y`, and
`_MAX` ints for condlayers/combos). No behavioral change — only relocation into
one file (or `rsource`d fragments). Result: enabling exactly the same
`CONFIG_ZMK_RUNTIME_*` flags as today yields the same firmware.

## CMakeLists

One `CMakeLists.txt` that, per feature, conditionally adds that feature's
sources when its Kconfig is set — mirroring each source repo's existing
CMake block:
```
if(CONFIG_ZMK_RUNTIME_MACRO)
    zephyr_include_directories(include)
    target_sources(app PRIVATE src/behaviors/behavior_runtime_macro.c src/runtime_macro_store.c)
    if(CONFIG_ZMK_RUNTIME_MACRO_STUDIO_RPC) ... add src/studio/macros_rpc_handler.c ... endif()
endif()
# ... same shape for HOLDTAP / CONDLAYERS / COMBOS ...
```
The nanopb generation block (identical across the source repos) runs once and
globs `proto/**/*.proto`, so every enabled feature's proto is generated. (nanopb
generating protos for a disabled feature is harmless — only the handler .c that
references the generated header is conditionally compiled. If unused-proto
generation is undesirable, the proto glob can also be guarded per feature; the
default is the simpler single glob, matching the existing per-repo CMake.)
`zephyr_include_directories(include)` is emitted once.

## roBa migration (dogfood)

- `config/west.yml`: remove the four `zmk-module-runtime-{macro,holdtap,
  conditional-layers,combos}` projects; add one `zmk-module-runtime-config`
  (remote `qtrnmr-gh`, `revision: main`).
- `boards/shields/roBa/roBa_R.conf`: **unchanged** (the same `CONFIG_ZMK_RUNTIME_*`
  flags now resolve against the unified module's Kconfig).
- `config/roBa.keymap`: **unchanged** (same compatibles / behaviors).
- The cormoran companion modules (`zmk-module-runtime-input-processor`,
  `zmk-behavior-runtime-sensor-rotate`) stay as separate `west.yml` entries —
  out of scope for the unified module.

## Verification

- **CI build green** on roBa with the unified module (the gate). Because the
  enabled CONFIG flags and keymap are unchanged, a green build proves the
  unified Kconfig/CMake wires every feature identically.
- **HIL smoke** (after flash): one read per subsystem confirms all four RPC
  handlers respond — `roba macro get 0`, `roba holdtap list`, `roba condlayer
  list`, `roba combo list` all return data (not subsystem-not-found). No deep
  re-test of each feature (already validated in their own cycles); this only
  confirms the merge didn't drop a subsystem.
- **opus review**: confirm all four modules' files are present in the unified
  repo (nothing dropped), Kconfig declares all four options with the original
  names/sub-options, CMake guards each correctly, and no source file was
  modified during relocation (diff each merged file against its source repo).
- Existing host tests stay green (host is untouched in sub-project A).

## Old repos

The four source repos are **kept but deprecated**: each README gets a top note
pointing to `zmk-module-runtime-config`. Not deleted (avoids breaking anyone
already referencing them, and preserves history). roBa stops referencing them.

## Risks & mitigations

- **A file is dropped in the merge** → opus review diffs every merged file
  against its source repo; CI build would also fail to find missing sources.
- **CMake/Kconfig wiring error** → CI build on roBa (all four enabled) is the
  gate; a misweave fails the build.
- **nanopb double-generation / include clash** → each proto package is distinct;
  the single nanopb glob is the same pattern each repo already uses. CI confirms.
- **Behavior change from accidental edit during copy** → the merge is
  copy-only; opus diff-vs-source enforces verbatim.

## Out of scope (sub-project A)

- CLI changes (sub-project B).
- OSS naming finalization, install guide, examples (sub-project C).
- Forking/absorbing the cormoran companion modules.
- Any source-logic change to the four features.
- Renaming Kconfig options, RPC ids, proto packages, or compatibles.

## Acceptance

- `zmk-module-runtime-config` repo exists with all four features' files present
  (verbatim), a unified Kconfig (4 options, defaults off), unified CMake, and a
  README documenting the cormoran-RPC requirement + per-feature setup.
- roBa `west.yml` references the one unified module; conf/keymap unchanged.
- CI build green; HIL smoke shows all four subsystems respond.
- opus review: no file dropped, no source modified, wiring correct.
- Merged to `main` locally (`--no-ff`); origin not pushed unless asked.
