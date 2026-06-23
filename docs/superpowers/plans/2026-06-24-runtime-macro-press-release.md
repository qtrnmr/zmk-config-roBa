# runtime-macro press/release (iOS Globe chords) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make runtime macros emit held chords (e.g. hold Globe while tapping ←) so iOS/iPadOS Globe shortcuts are composable at runtime via `zmkrt`, without reflashing per combination.

**Architecture:** The macro wire format already carries a per-step `type`; only two gaps remain. (1) Firmware `behavior_runtime_macro.c` ignores `type` and runs every step as a press+release tap — add a per-type dispatch (press-only / release-only / tap). (2) The CLI DSL has no `press`/`release`/`tap` tokens and no vocabulary for non-letter keys (Globe is a Consumer-page key) — add them plus a named-keycode table and host-side balance validation. The roBa keymap is untouched this round.

**Tech Stack:** ZMK (C, Zephyr behavior queue) for firmware; Python 3.12 + pytest for the CLI. Work lands in the module repo `qtrnmr/zmk-module-runtime-config` (local working copy: `/tmp/zmk-module-runtime-config`).

## Global Constraints

- All firmware/CLI changes land in `qtrnmr/zmk-module-runtime-config`; commits use the `qtrnmr` git identity (`-c user.name=qtrnmr -c user.email=kt_nishimura@trust-coms.com`).
- **Additive only:** step `type=0` MUST keep meaning "tap" (press+release) so every existing stored macro behaves identically. No proto / NVS store / RPC handler changes.
- **No roBa keymap/DT change** this round (verified separately with `zmkrt snapshot` + `cmp` before flashing).
- Named keycodes use **full ZMK page encoding**, verbatim from ZMK `keys.h`:
  `GLOBE`=`0x0C029D` (=787101, Consumer), `LEFT`=`0x070050` (=458832),
  `RIGHT`=`0x07004F` (=458831), `UP`=`0x070052` (=458834), `DOWN`=`0x070051` (=458833).
- Stuck-key guard lives in the CLI (balance validation), not the firmware; `--allow-unbalanced` bypasses it.
- The existing CLI suite (92 tests) MUST stay green; new tests are additive.
- `zmk_behavior_queue_add(&event, binding, pressed, wait_ms)` — 3rd arg is the pressed bool, 4th is the post-action delay in ms.

---

### Task 1: Firmware — dispatch per step `type`

**Files:**
- Modify: `include/zmk/runtime_macro.h` (step-type constants)
- Modify: `src/behaviors/behavior_runtime_macro.c` (`queue_key_tap` → per-type dispatch)

**Interfaces:**
- Consumes: `struct rt_macro_step { uint8_t type; uint32_t keycode; uint16_t wait_ms; uint16_t tap_ms; }` (unchanged), `rt_macro_get_steps()` (unchanged), `zmk_behavior_queue_add(event, binding, pressed, wait_ms)`.
- Produces: behavior runtime that interprets `type` ∈ {0=tap,1=press,2=release}. No new public symbols.

- [ ] **Step 1: Rename the step-type constant and add press/release**

In `include/zmk/runtime_macro.h`, replace:

```c
#define RT_MACRO_STEP_KEY 0
```

with:

```c
#define RT_MACRO_STEP_TAP     0  // press+release (was RT_MACRO_STEP_KEY; value unchanged)
#define RT_MACRO_STEP_PRESS   1  // press only — key stays down
#define RT_MACRO_STEP_RELEASE 2  // release only
```

Also update the struct comment on the `type` field (line ~10) from
`// RT_MACRO_STEP_KEY` to `// RT_MACRO_STEP_TAP / _PRESS / _RELEASE`.
(`RT_MACRO_STEP_KEY` has no other references — grep-verified — so this rename
is safe.)

- [ ] **Step 2: Replace the unconditional tap with a per-type dispatch**

In `src/behaviors/behavior_runtime_macro.c`, delete the `queue_key_tap` helper
(lines 12-18) and rewrite the loop body in `on_rt_macro_pressed` so each step
dispatches on `type`:

```c
static int on_rt_macro_pressed(struct zmk_behavior_binding *binding,
                               struct zmk_behavior_binding_event event) {
    struct rt_macro_step steps[CONFIG_ZMK_RUNTIME_MACRO_MAX_STEPS];
    uint8_t count = 0;
    if (rt_macro_get_steps((uint8_t)binding->param1, steps,
                           CONFIG_ZMK_RUNTIME_MACRO_MAX_STEPS, &count) < 0) {
        return ZMK_BEHAVIOR_OPAQUE;
    }
    for (uint8_t i = 0; i < count; i++) {
        struct zmk_behavior_binding kp = { .behavior_dev = "key_press",
                                           .param1 = steps[i].keycode, .param2 = 0 };
        switch (steps[i].type) {
        case RT_MACRO_STEP_PRESS:
            zmk_behavior_queue_add(&event, kp, true, steps[i].wait_ms);
            break;
        case RT_MACRO_STEP_RELEASE:
            zmk_behavior_queue_add(&event, kp, false, steps[i].wait_ms);
            break;
        case RT_MACRO_STEP_TAP:
        default:
            zmk_behavior_queue_add(&event, kp, true, steps[i].tap_ms);
            zmk_behavior_queue_add(&event, kp, false, steps[i].wait_ms);
            break;
        }
    }
    return ZMK_BEHAVIOR_OPAQUE;
}
```

Leave `on_rt_macro_released`, the API struct, init, and the `RT_MACRO_INST`
boilerplate unchanged.

- [ ] **Step 3: Verify it compiles (no Zephyr unit harness)**

This module builds inside a ZMK/west firmware build, which is not available
locally. Verify by inspection that: the `queue_key_tap` helper and its single
caller are both gone (no dangling reference), the `switch` covers all three
constants plus `default`, and `kp` is rebuilt per step. The firmware build +
HIL is the real gate (controller runs it after the CLI tasks).

- [ ] **Step 4: Commit**

```bash
cd /tmp/zmk-module-runtime-config
git add include/zmk/runtime_macro.h src/behaviors/behavior_runtime_macro.c
git -c user.name=qtrnmr -c user.email=kt_nishimura@trust-coms.com \
  commit -m "feat(macro): dispatch macro steps by type (press/release/tap)"
```

---

### Task 2: CLI — `press`/`release`/`tap` tokens + named-keycode table

**Files:**
- Modify: `cli/zmk_runtime_cli/macro_dsl.py`
- Test: `cli/tests/test_macro_dsl.py`

**Interfaces:**
- Consumes: existing `_make_step(keycode, wait_ms=0, tap_ms=0)` → `{"type":0,...}`, `_parse_modified_key(token)`, `_char_to_keycode(ch)`, `_HID` table, `parse(s)`.
- Produces: `_resolve_key(token: str) -> int` (named table → `C-S-x` mod form → single char → raw `0x..`/decimal); `parse()` now also handles `press`/`release`/`tap` heads, emitting steps with `type` 1/2/0 respectively. Step type constants `STEP_TAP=0, STEP_PRESS=1, STEP_RELEASE=2` defined module-level.

- [ ] **Step 1: Write failing tests for tokens + named keycodes**

Append to `cli/tests/test_macro_dsl.py`:

```python
from zmk_runtime_cli.macro_dsl import _resolve_key


def test_named_keycodes_full_page_encoding():
    assert _resolve_key("GLOBE") == 0x0C029D == 787101
    assert _resolve_key("LEFT") == 0x070050
    assert _resolve_key("RIGHT") == 0x07004F
    assert _resolve_key("UP") == 0x070052
    assert _resolve_key("DOWN") == 0x070051


def test_resolve_key_fallbacks():
    assert _resolve_key("c") == 0x06           # single char via _HID
    assert _resolve_key("C-c") == 0x01000006   # mod form
    assert _resolve_key("0x1234") == 0x1234    # raw hex
    assert _resolve_key("258") == 258          # raw decimal


def test_press_release_tap_types():
    steps = parse("press GLOBE | tap LEFT | release GLOBE")
    assert [s["type"] for s in steps] == [1, 0, 2]
    assert [s["keycode"] for s in steps] == [0x0C029D, 0x070050, 0x0C029D]


def test_tap_single_char():
    s = parse("tap c")[0]
    assert s["type"] == 0 and s["keycode"] == 0x06
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /tmp/zmk-module-runtime-config/cli && python -m pytest tests/test_macro_dsl.py -q`
Expected: FAIL (`_resolve_key` not importable; `press`/`release`/`tap` raise "Unknown DSL token").

- [ ] **Step 3: Implement `_resolve_key` and the new tokens**

In `cli/zmk_runtime_cli/macro_dsl.py`, add the step-type constants and named
table near the top (after `_MOD_BITS`):

```python
# Macro step types (mirror RT_MACRO_STEP_* in firmware include/zmk/runtime_macro.h)
STEP_TAP = 0
STEP_PRESS = 1
STEP_RELEASE = 2

# Named keys — full ZMK page encoding (verbatim from ZMK keys.h).
# Consumer page = 0x0C<<16 | id; Keyboard page = 0x07<<16 | id.
_NAMED: dict[str, int] = {
    "GLOBE": 0x0C029D,
    "LEFT": 0x070050,
    "RIGHT": 0x07004F,
    "UP": 0x070052,
    "DOWN": 0x070051,
}
```

Add the resolver:

```python
def _resolve_key(token: str) -> int:
    """Resolve a single key spec to a ZMK keycode.
    Order: named table -> C-S-x mod form -> single char -> raw 0x../decimal."""
    if token in _NAMED:
        return _NAMED[token]
    if "-" in token and token[0] in _MOD_BITS:
        return _parse_modified_key(token)["keycode"]
    if len(token) == 1:
        return _char_to_keycode(token)
    try:
        return int(token, 0)  # 0x.. or decimal
    except ValueError:
        raise ValueError(f"Unknown key: {token!r}")
```

In `parse()`, add `press`/`release`/`tap` branches in the per-token `if/elif`
chain (before the `elif "-" in head ...` branch), each taking exactly one key
argument:

```python
        elif head in ("press", "release", "tap"):
            if len(parts) < 2:
                raise ValueError(f"{head!r} requires a key argument")
            keycode = _resolve_key(parts[1].strip())
            step_type = {"press": STEP_PRESS, "release": STEP_RELEASE,
                         "tap": STEP_TAP}[head]
            step = _make_step(keycode)
            step["type"] = step_type
            steps.append(step)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /tmp/zmk-module-runtime-config/cli && python -m pytest tests/test_macro_dsl.py -q`
Expected: PASS (all new + existing DSL tests).

- [ ] **Step 5: Commit**

```bash
cd /tmp/zmk-module-runtime-config
git add cli/zmk_runtime_cli/macro_dsl.py cli/tests/test_macro_dsl.py
git -c user.name=qtrnmr -c user.email=kt_nishimura@trust-coms.com \
  commit -m "feat(cli): macro DSL press/release/tap tokens + named keycodes"
```

---

### Task 3: CLI — balance validation + `--allow-unbalanced`

**Files:**
- Modify: `cli/zmk_runtime_cli/macro_dsl.py` (`parse` signature + check)
- Modify: `cli/zmk_runtime_cli/cli.py` (`cmd_macro_set` + `macro set` subparser)
- Test: `cli/tests/test_macro_dsl.py`

**Interfaces:**
- Consumes: `parse(s)` and `STEP_PRESS`/`STEP_RELEASE` from Task 2.
- Produces: `parse(s: str, allow_unbalanced: bool = False) -> list[dict]` — raises `ValueError` on an orphan release or a still-open press at end unless `allow_unbalanced`. `cmd_macro_set` calls `macro_dsl.parse(args.dsl, allow_unbalanced=args.allow_unbalanced)`.

- [ ] **Step 1: Write failing tests for balance validation**

Append to `cli/tests/test_macro_dsl.py`:

```python
def test_balanced_chord_ok():
    # no exception
    parse("press GLOBE | tap LEFT | release GLOBE")


def test_unmatched_press_raises():
    with pytest.raises(ValueError, match="unbalanced"):
        parse("press GLOBE | tap LEFT")


def test_orphan_release_raises():
    with pytest.raises(ValueError, match="unbalanced"):
        parse("release GLOBE")


def test_allow_unbalanced_bypasses():
    steps = parse("press GLOBE", allow_unbalanced=True)
    assert steps[0]["type"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /tmp/zmk-module-runtime-config/cli && python -m pytest tests/test_macro_dsl.py -k balanced -q`
Expected: FAIL (`parse` takes no `allow_unbalanced` kwarg; unbalanced input does not raise).

- [ ] **Step 3: Add the balance check to `parse`**

Change the `parse` signature and add the check just before the `MAX_STEPS`
guard / `return steps`:

```python
def parse(s: str, allow_unbalanced: bool = False) -> list[dict]:
    ...
    if not allow_unbalanced:
        open_counts: dict[int, int] = {}
        for st in steps:
            if st["type"] == STEP_PRESS:
                open_counts[st["keycode"]] = open_counts.get(st["keycode"], 0) + 1
            elif st["type"] == STEP_RELEASE:
                if open_counts.get(st["keycode"], 0) == 0:
                    raise ValueError(
                        f"unbalanced macro: release of 0x{st['keycode']:X} "
                        "with no matching press (use --allow-unbalanced to override)")
                open_counts[st["keycode"]] -= 1
        leftover = [k for k, v in open_counts.items() if v > 0]
        if leftover:
            raise ValueError(
                "unbalanced macro: press without release for "
                + ", ".join(f"0x{k:X}" for k in leftover)
                + " (use --allow-unbalanced to override)")

    if len(steps) > MAX_STEPS:
        raise ValueError(f"macro has {len(steps)} steps; max is {MAX_STEPS}")
    return steps
```

- [ ] **Step 4: Wire the flag into the CLI**

In `cli/zmk_runtime_cli/cli.py`, `cmd_macro_set` (line ~70), change:

```python
    steps = macro_dsl.parse(args.dsl)
```

to:

```python
    steps = macro_dsl.parse(args.dsl, allow_unbalanced=args.allow_unbalanced)
```

And in the `macro set` subparser (line ~367), add the flag after the `dsl`
argument:

```python
    ms_p.add_argument("--allow-unbalanced", action="store_true",
                      help="skip press/release balance validation")
```

- [ ] **Step 5: Run the full CLI suite**

Run: `cd /tmp/zmk-module-runtime-config/cli && python -m pytest -q`
Expected: PASS (existing 92 + new tests; nothing regressed).

- [ ] **Step 6: Commit**

```bash
cd /tmp/zmk-module-runtime-config
git add cli/zmk_runtime_cli/macro_dsl.py cli/zmk_runtime_cli/cli.py cli/tests/test_macro_dsl.py
git -c user.name=qtrnmr -c user.email=kt_nishimura@trust-coms.com \
  commit -m "feat(cli): balance-validate press/release macros (--allow-unbalanced to bypass)"
```

---

### Task 4: Docs — Globe chord examples

**Files:**
- Modify: `examples/macro.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Add a press/release / Globe-chord section to `examples/macro.md`**

After the existing DSL description, add:

```markdown
### Held chords (press / release)

`press <key>` holds a key down; `release <key>` lets it up; `tap <key>` is a
single press+release. Use these to build chords where one key stays held while
another is tapped — e.g. iOS/iPadOS Globe (🌐) shortcuts:

​```bash
zmkrt macro set 0 "press GLOBE | tap LEFT | release GLOBE"    # switch app left
zmkrt macro set 0 "press GLOBE | tap RIGHT | release GLOBE"   # switch app right
zmkrt macro set 0 "press GLOBE | tap UP | release GLOBE"      # App Switcher
zmkrt macro set 0 "press GLOBE | tap c | release GLOBE"       # Control Center (Globe+C)
​```

Named keys: `GLOBE`, `LEFT`, `RIGHT`, `UP`, `DOWN` (plus single characters,
`C-S-x` modifier forms, and raw `0x..`/decimal keycodes). Every `press` must
have a matching `release`; the CLI rejects an unbalanced macro unless you pass
`--allow-unbalanced`.
```

(Replace the zero-width spaces before the code fences — they are only here to
escape the nested fence in this plan.)

- [ ] **Step 2: Commit**

```bash
cd /tmp/zmk-module-runtime-config
git add examples/macro.md
git -c user.name=qtrnmr -c user.email=kt_nishimura@trust-coms.com \
  commit -m "docs: Globe-chord (press/release) examples for runtime macro"
```

---

## Post-implementation (controller, after task reviews pass)

These are not subagent tasks — the controller drives them:

1. Push the module repo (`qtrnmr` identity) to `origin main`.
2. Commit the plan to the config repo (`qtrnmr` identity).
3. **Pre-flash gate:** `zmkrt snapshot` the current roBa keymap, build the
   firmware, and `cmp` the keymap DT to prove it is unchanged
   ([[feedback_roba_always_revertible]]).
4. Hand off to the user to flash; then HIL: set
   `press GLOBE | tap LEFT | release GLOBE` on an existing `&rt_macro` slot and
   confirm the iOS "switch app left" shortcut fires.

## Self-Review

- **Spec coverage:** firmware dispatch (Task 1) ✓; DSL press/release/tap +
  named keycodes incl. GLOBE=787101 (Task 2) ✓; balance validation +
  `--allow-unbalanced` (Task 3) ✓; examples (Task 4) ✓; revertibility gate
  (post-impl step 3) ✓; additive `type=0`=tap preserved (Task 1 Step 1) ✓.
- **Placeholder scan:** none — every code step shows full code.
- **Type consistency:** `STEP_TAP/STEP_PRESS/STEP_RELEASE` (CLI) mirror
  `RT_MACRO_STEP_TAP/_PRESS/_RELEASE` (firmware), values 0/1/2 throughout;
  `_resolve_key` returns `int`; `parse(s, allow_unbalanced=False)` used
  identically in Task 3 and `cmd_macro_set`.
