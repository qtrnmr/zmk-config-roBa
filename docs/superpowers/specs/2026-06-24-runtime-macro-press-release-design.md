# runtime-macro press/release steps (iOS Globe chords) — Design

Date: 2026-06-24
Status: Approved (design)
Where the work lands: the module repo `qtrnmr/zmk-module-runtime-config`
(firmware `src/behaviors/behavior_runtime_macro.c` + `include/zmk/runtime_macro.h`,
and CLI `cli/zmk_runtime_cli/macro_dsl.py` + `cli/zmk_runtime_cli/cli.py`). The
spec/plan live in the config repo's `docs/superpowers/` as usual.

## Context / Goal

iOS/iPadOS exposes a family of system shortcuts on the Globe (🌐) key:
Globe+← / Globe+→ (switch app left/right), Globe+↑ (App Switcher),
Globe+C (Control Center), etc. We want these emittable from roBa **without
reflashing each new combination** — i.e. composable at runtime via `zmkrt`.

### Why this needs a firmware change

- ZMK has `GLOBE` as a *keycode* but does not treat it as a *modifier*
  (zmkfirmware/zmk issues #947, #3217). So a synthetic `GLOBE(LEFT)` is not
  possible. Globe must be an ordinary key that is **held down while the arrow
  is tapped**, so that the arrow's report overlaps in time with Globe's
  pressed state.
- `GLOBE` is a **Consumer-page** usage, not Keyboard-page:
  `GLOBE = ZMK_HID_USAGE(HID_USAGE_CONSUMER, 0x029D)` = `0x0C029D` = `787101`
  (same consumer encoding as `C_VOL_UP` = `0x0C00E9` = `786665`). The arrows
  are Keyboard-page: `LEFT`=`0x070050`, `RIGHT`=`0x07004F`, `UP`=`0x070052`,
  `DOWN`=`0x070051`. Globe and the arrow therefore live in *different* HID
  reports; "same report" is not literally achievable. What matters — and what
  iOS reads — is the **temporal overlap of pressed states**: Globe's consumer
  report shows it down while the keyboard report shows the arrow down. The
  press/release stepping below achieves exactly that.
- The current `behavior_runtime_macro.c` ignores `rt_macro_step.type` and runs
  **every** step as a press+release tap (`queue_key_tap`). So it can only
  produce sequential taps, never a held chord. A bare `&kp GLOBE` tap just
  cycles input sources / emoji — it misfires.

### What is already in place (no change needed)

The wire format and persistence already carry a per-step `type`:
- proto `zmk.macros.MacroStep.type` (field 1)
- `struct rt_macro_step { uint8_t type; ... }` (header)
- NVS blob `[count][steps...]` stores the full struct incl. `type`
- the Studio RPC handler maps `type` in both directions
  (`macros_rpc_handler.c` get line 64, set line 88)

So the only gaps are (a) the firmware behavior ignores `type`, and (b) the CLI
DSL always emits `type=0` and has no vocabulary for non-letter keys.

## Scope (this round)

**Module capability only.** This round adds the press/release capability to the
module (firmware + CLI). The roBa **keymap is left untouched** — verified with
`zmkrt snapshot` + `cmp` before flashing. After flashing, a Globe macro is
written at runtime to an existing `&rt_macro` slot and tested on-device.

**Out of scope (follow-up, roBa-config side):** bumping
`CONFIG_ZMK_RUNTIME_MACRO_SLOTS` and placing multiple `&rt_macro N` invocations
in the keymap so several Globe shortcuts can live simultaneously. With the
default `SLOTS=1` only one Globe macro is resident at a time; that is enough to
validate the capability.

## Design

### 1. Firmware — `behavior_runtime_macro.c` + `runtime_macro.h`

Step-type constants (header). Keep value `0` as tap so existing stored macros
(all `type=0`) keep their current behavior — the change is additive:

```c
#define RT_MACRO_STEP_TAP     0  // press+release (was RT_MACRO_STEP_KEY; value unchanged)
#define RT_MACRO_STEP_PRESS   1  // press only — key stays down
#define RT_MACRO_STEP_RELEASE 2  // release only
```

Dispatch in `on_rt_macro_pressed`, replacing the unconditional `queue_key_tap`:

```c
struct zmk_behavior_binding kp = { .behavior_dev = "key_press",
                                   .param1 = steps[i].keycode, .param2 = 0 };
switch (steps[i].type) {
case RT_MACRO_STEP_PRESS:
    zmk_behavior_queue_add(&event, kp, true,  steps[i].wait_ms);
    break;
case RT_MACRO_STEP_RELEASE:
    zmk_behavior_queue_add(&event, kp, false, steps[i].wait_ms);
    break;
case RT_MACRO_STEP_TAP:
default:
    zmk_behavior_queue_add(&event, kp, true,  steps[i].tap_ms);
    zmk_behavior_queue_add(&event, kp, false, steps[i].wait_ms);
    break;
}
```

Notes:
- `tap_ms` is meaningful only for TAP (hold duration). For PRESS/RELEASE,
  `wait_ms` is the post-action delay before the next step.
- Unknown `type` values fall through to TAP (defensive; the CLI never emits
  others).
- No change to proto / store / RPC handler.

### 2. CLI — `macro_dsl.py` (+ `cli.py` for the opt-out flag)

New tokens (steps still separated by `|`):
- `press <key>`   → step `type=1`
- `release <key>` → step `type=2`
- `tap <key>`     → step `type=0`, a single named/encoded key (explicit tap)
- existing `type <text>` (one tap per char), `C-S-x` modifier tokens, and
  `wait <ms>` are unchanged.

`<key>` resolution order:
1. **named table** (fully page-encoded, verbatim from ZMK `keys.h`):
   | name | value |
   |------|-------|
   | `GLOBE` | `0x0C029D` = `787101` |
   | `LEFT`  | `0x070050` = `458832` |
   | `RIGHT` | `0x07004F` = `458831` |
   | `UP`    | `0x070052` = `458834` |
   | `DOWN`  | `0x070051` = `458833` |
2. `C-S-x` modifier form (reuse existing `_parse_modified_key`)
3. single character via the existing `_HID` char table (e.g. `tap c`)
4. raw integer: `0x...` or decimal, passed through as the keycode

The named keys use **full page encoding** (consumer `0x0C…` / keyboard
`0x07…`), matching how `C_VOL_UP` is encoded elsewhere in this project — unlike
the legacy letter table which uses bare usage ids (works because `&kp` routes a
page-0 usage to the keyboard page). New names are canonical/full to be correct
for the consumer-page `GLOBE`.

**Balance validation** (the chosen stuck-key guard): after parsing, walk the
steps tracking pressed keycodes. Each `press` of keycode K must be matched by a
later `release` of the same K; a `release` with no matching open `press` is an
error; any still-open press at the end is an error. On violation raise
`ValueError` with a clear message. `macro set` gains `--allow-unbalanced` to
bypass the check (reserved for a future "hold across macro" use). The firmware
stays a dumb, trusting executor; the host enforces the semantics.

Example commands:
```bash
zmkrt macro set 0 "press GLOBE | tap LEFT | release GLOBE"   # switch app left
zmkrt macro set 0 "press GLOBE | tap RIGHT | release GLOBE"  # switch app right
zmkrt macro set 0 "press GLOBE | tap UP | release GLOBE"     # App Switcher
zmkrt macro set 0 "press GLOBE | tap c | release GLOBE"      # Control Center (Globe+C)
```

### Data flow

`zmkrt macro set <slot> "<dsl>"` → `macro_dsl.parse` → list of
`{type,keycode,wait_ms,tap_ms}` → balance check → `MacroClient` custom-envelope
RPC `SetMacro` → firmware `rt_macro_set_steps` → NVS + RAM cache. On key press,
`on_rt_macro_pressed` reads the slot and dispatches per `type` into the behavior
queue → `&kp` press/release events → HID reports.

## Testing

- **CLI (pytest, added to the existing macro_dsl test module):**
  - `press`/`release`/`tap` tokens parse to the right `type`.
  - named keycodes resolve to the exact values (`GLOBE == 787101`,
    `LEFT == 458832`, …).
  - mod form, single-char, and raw `0x…`/decimal resolution.
  - balance validation: balanced chord accepted; unmatched press rejected;
    orphan release rejected; `--allow-unbalanced` bypasses.
  - the existing 92 CLI tests stay green (additive change).
- **Firmware:** no Zephyr unit harness — validated by a successful build, then
  HIL. Before flashing, `zmkrt snapshot` + `cmp` confirms the keymap DT is
  unchanged. After flashing, set a Globe macro at runtime and confirm the iOS
  shortcut fires (manual, on-device).

## Revertibility ([[feedback_roba_always_revertible]])

- Firmware change is additive: `type=0` is still a tap, so every existing
  stored macro behaves identically. No keymap/DT change in roBa this round.
- Macro content lives in NVS — runtime-settable and resettable
  (`zmkrt macro` / settings reset) without reflashing.
- Pre-flash gate: `zmkrt snapshot` of the current keymap + `cmp` against the
  post-build artifact to prove the DT is untouched; only then flash.

## Acceptance

- Firmware dispatches per `rt_macro_step.type` (press / release / tap); build
  succeeds; existing `type=0` macros unchanged.
- CLI DSL parses `press`/`release`/`tap` and the named keycodes with the exact
  values above; balance validation rejects unbalanced input unless
  `--allow-unbalanced`; new pytest cases pass and the existing suite stays
  green.
- `zmkrt snapshot` + `cmp` shows the roBa keymap DT unchanged pre-flash.
- Module repo changes committed (qtrnmr identity) and pushed; config-repo
  spec/plan committed.
- HIL: a runtime-set `press GLOBE | tap LEFT | release GLOBE` triggers the iOS
  "switch app left" shortcut (validated by the user after flashing).
