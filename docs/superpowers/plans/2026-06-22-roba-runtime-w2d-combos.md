# W2d — Runtime Combos Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit roBa's 6 existing combos' output binding / timeout / require-prior-idle / layers / slow-release at runtime (no reflash), key-positions fixed.

**Architecture:** New module `qtrnmr/zmk-module-runtime-combos` forks ZMK `combo.c` (W2b-style coexistence: keymap switches to `zmk,runtime-combos`, upstream `#if`'s out). The const `combos[]` (DT defaults) is kept; a parallel scalar `rt_params[]` (NVS-backed, pointer-free) holds the 5 editable fields, and the forked logic's read-sites are redirected to it via `rt_params[combo - combos]`. Host adds a `roba combo` group reusing the W2c behavior-resolution helper.

**Tech Stack:** ZMK (cormoran `v0.3-branch+dya`), Zephyr settings/NVS, nanopb; Python 3.12, pyserial, protobuf, `zmk_studio_api`, pytest.

## Global Constraints

- Self-built module, fork of `combo.c`. **No base pinning** (our module builds against the same base). Module repo `qtrnmr/zmk-module-runtime-combos`, branch `main`.
- **roBa_L unchanged.** Only roBa_R (central) config changes. Combos run on the central.
- **key-positions / key_position_len are NOT editable** — they feed `combo_lookup` and the sort, which stay built from the const array. Only `behavior`, `timeout_ms`, `require_prior_idle_ms`, `layer_mask`, `slow_release` are mutable.
- Fork fidelity: matching/lookup/sort logic stays byte-identical to upstream apart from (a) the coexistence renames and (b) the redirected read-sites listed in Task 2. opus fidelity review gates merge.
- NVS representation is pointer-free: store scalars (`behavior_local_id`, `param1`, `param2`, …), reconstruct `behavior_dev` via `zmk_behavior_find_behavior_name_from_local_id` on apply.
- Subsystem RPC identifier: **`zmk__combos`**. Proto package: **`zmk.combos`**. Behavior compatible: **`zmk,runtime-combos`**.
- Behavior local_id resolution on the host is by Studio `display_name` (roBa is SETTINGS_TABLE mode — W2c finding); reuse the W2c helper, do not reimplement crc16-only.
- Existing host tests stay green; new tests in `tools/roba-cli/tests/test_combos.py`.
- Commit trailers on every commit:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F`
- Module commits use the qtrnmr identity: `git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit …`. Module pushes use the `github.com-qtrnmr` SSH host.
- Work on branch `feat/roba-w2d-combos`; merge to `main` locally `--no-ff`; do NOT push origin unless the user asks.

## Templates (fetch verbatim, then adapt)

The W2b module `qtrnmr/zmk-module-runtime-conditional-layers` is the structural
template (listener-subsystem fork + NVS store + custom RPC + settings-reset).
Fetch files with:
`gh api -H "Accept: application/vnd.github.raw" "repos/qtrnmr/zmk-module-runtime-conditional-layers/contents/<path>?ref=main"`

Base `combo.c` to fork (tag/ref `v0.3-branch+dya`, URL-encode `+` as `%2B`):
`gh api -H "Accept: application/vnd.github.raw" "repos/cormoran/zmk/contents/app/src/combo.c?ref=v0.3-branch%2Bdya"`

## Verified facts (base `v0.3-branch+dya` combo.c)

- File body wrapped in `#if DT_HAS_COMPAT_STATUS_OKAY(DT_DRV_COMPAT)`, `DT_DRV_COMPAT = zmk_combos` (lines 7, 28). 538 lines total.
- `struct combo_cfg { int32_t key_positions[MAX_COMBO_KEYS]; int16_t key_position_len; int16_t require_prior_idle_ms; int32_t timeout_ms; uint32_t layer_mask; struct zmk_behavior_binding behavior; bool slow_release; }`.
- `struct zmk_behavior_binding { zmk_behavior_local_id_t local_id; const char *behavior_dev; uint32_t param1; uint32_t param2; }` (local_id present under `CONFIG_ZMK_BEHAVIOR_LOCAL_IDS_IN_BINDINGS`, which SETTINGS_TABLE mode selects).
- `static const struct combo_cfg combos[] = { LISTIFY(20, COMBO_CONFIGS_WITH_MATCHING_POSITIONS_LEN, (), 0) };` (line 100) — shortest-first sorted.
- File globals NOT static: `combo_lookup` (118), `active_combos` (121), `pressed_keys` (112), `pressed_keys_count` (110-ish), `candidates` (114), `fully_pressed_combo` (116).
- Read-sites of the 5 editable fields:
  - `is_quick_tap(combo, ts)` → `combo->require_prior_idle_ms` (~159)
  - `combo_active_on_layer(combo, layer)` → `combo->layer_mask` (~150-152)
  - first-timeout loop → `combos[i].timeout_ms` (~212)
  - candidate timeout check → `combos[i].timeout_ms` (~237)
  - `press_combo_behavior(combo_idx, combo, ts)` → `zmk_behavior_invoke_binding(&combo->behavior, …)` (~293, and release ~306)
  - release loop → `c = &combos[idx]; c->slow_release` (~383-384)
- Listener/init: `ZMK_LISTENER(combo, behavior_combo_listener)` (519), `ZMK_SUBSCRIPTION(combo, zmk_position_state_changed)` (520), `ZMK_SUBSCRIPTION(combo, zmk_keycode_state_changed)` (521), `SYS_INIT(combo_init, APPLICATION, CONFIG_KERNEL_INIT_PRIORITY_DEFAULT)` (536).
- roBa combos (source order; module sees sorted order): tab `&kp TAB` pos[11,10]; esc `&kp ESCAPE` pos[0,1]; backspace `&kp BACKSPACE` pos[9,8]; delete `&kp DELETE` pos[20,21]; redo_win `&kp LC(LS(Z))` pos[22,23,24] layers[DEFAULT,MOUSE]; redo_apple `&kp LG(LS(Z))` pos[22,23,24] layers[APPLE,…]. 6 combos.

## File Structure

Module `qtrnmr/zmk-module-runtime-combos` (separate repo, cloned to a temp dir):
- `src/runtime_combo.c` — forked combo.c.
- `include/zmk/runtime_combos.h` — `rt_combo_params` + store API.
- `src/runtime_combo_store.c` — NVS store.
- `src/studio/combos_rpc_handler.c` — `zmk__combos` RPC + settings-reset.
- `proto/zmk/combos/combos.proto`.
- `dts/bindings/zmk,runtime-combos.yaml`.
- `CMakeLists.txt`, `Kconfig`, `zephyr/module.yml`, `LICENSE`, `README.md`.

Config repo `zmk-config-roBa`:
- `config/west.yml`, `boards/shields/roBa/roBa_R.conf`, `config/roBa.keymap`.

Host `tools/roba-cli`:
- `roba_cli/behavior_resolve.py` (new, factored from encoder_client).
- `roba_cli/encoder_client.py` (refactor to import the shared helper).
- `proto/zmk/combos/combos.proto` + `roba_cli/proto/zmk/combos/combos_pb2.py`.
- `roba_cli/combos_client.py`, `roba_cli/cli.py`, `tests/test_combos.py`.

---

### Task 1: Module scaffold + verbatim fork (coexistence renames only) + config wiring

**Files (module repo, create):** `CMakeLists.txt`, `Kconfig`, `zephyr/module.yml`, `LICENSE`, `README.md`, `dts/bindings/zmk,runtime-combos.yaml`, `src/runtime_combo.c`.
**Files (config repo, modify):** `config/west.yml`, `boards/shields/roBa/roBa_R.conf`, `config/roBa.keymap`.

**Interfaces:**
- Produces: a firmware build where the keymap's combos run through the forked `zmk,runtime-combos` listener (still reading the const `combos[]`, behaving exactly like upstream), and upstream `combo.c` is compiled out.
- Consumes: nothing.

- [ ] **Step 1: Create the module repo locally**

```bash
mkdir -p /tmp/zmk-module-runtime-combos && cd /tmp/zmk-module-runtime-combos
git init -q
```
(The repo will be pushed to `qtrnmr/zmk-module-runtime-combos` in Task 7's verification, or earlier if the user authorizes. For now west.yml will point at it; CI needs it on GitHub — see Step 9.)

- [ ] **Step 2: Scaffold build files from the W2b template**

Fetch the W2b `CMakeLists.txt`, `Kconfig`, `zephyr/module.yml`, `LICENSE` and adapt:
- `CMakeLists.txt`: replace `ZMK_RUNTIME_CONDLAYERS`→`ZMK_RUNTIME_COMBOS`, `ZMK_RUNTIME_CONDLAYERS_STUDIO_RPC`→`ZMK_RUNTIME_COMBOS_STUDIO_RPC`, and source files `runtime_conditional_layer.c`/`runtime_condlayer_store.c`→`runtime_combo.c`/`runtime_combo_store.c`. Keep the nanopb block verbatim.
- `Kconfig`: rename configs to `ZMK_RUNTIME_COMBOS` / `ZMK_RUNTIME_COMBOS_STUDIO_RPC` / `ZMK_RUNTIME_COMBOS_MAX` (default 16); update help text to "verbatim fork of ZMK's combo subsystem; binding/timeout/layers/require-prior-idle/slow-release editable over zmk__combos, key-positions fixed".
- `zephyr/module.yml`: `name: zmk-module-runtime-combos`, keep `build: {cmake: ., kconfig: Kconfig, settings: {dts_root: .}}`.
- `LICENSE`: MIT, copy as-is.

- [ ] **Step 3: Create the DT binding**

`dts/bindings/zmk,runtime-combos.yaml` — copy ZMK's `zmk,combos` binding (fetch `app/dts/bindings/zmk,combos.yaml` and its child-binding from base zmk) and change only `compatible: "zmk,runtime-combos"`. The child properties must remain: `key-positions` (required, array), `bindings` (required, phandle-array), `layers` (array), `timeout-ms` (int), `require-prior-idle-ms` (int), `slow-release` (bool). (If `zmk,combos` uses a separate child-binding file, copy that too and reference it.)

- [ ] **Step 4: Fork combo.c → src/runtime_combo.c (coexistence renames ONLY)**

Fetch base `combo.c` verbatim into `src/runtime_combo.c`, then apply ONLY these renames (no logic/field changes yet):
- Line 7: `#define DT_DRV_COMPAT zmk_combos` → `#define DT_DRV_COMPAT zmk_runtime_combos`
- `ZMK_LISTENER(combo, behavior_combo_listener)` → `ZMK_LISTENER(runtime_combo, behavior_combo_listener)`
- `ZMK_SUBSCRIPTION(combo, zmk_position_state_changed)` → `ZMK_SUBSCRIPTION(runtime_combo, zmk_position_state_changed)`
- `ZMK_SUBSCRIPTION(combo, zmk_keycode_state_changed)` → `ZMK_SUBSCRIPTION(runtime_combo, zmk_keycode_state_changed)`
- `combo_init` → `runtime_combo_init` (both the function and the `SYS_INIT(...)` reference)
- Make these file globals `static`: `combo_lookup`, `active_combos`, `pressed_keys`, `pressed_keys_count`, `candidates`, `fully_pressed_combo` (prefix each non-static definition with `static`).

Do NOT change any field reads or add new arrays yet — the file still reads the const `combos[]`. This keeps Task 1 a pure coexistence fork (behaves identically to upstream).

- [ ] **Step 5: Wire west.yml (config repo)**

Add under `projects:` (after `zmk-behavior-runtime-sensor-rotate`):
```yaml
    - name: zmk-module-runtime-combos
      remote: qtrnmr-gh
      revision: main
```

- [ ] **Step 6: Enable in roBa_R.conf**

Append:
```conf
# runtime combos module (W2d): edit existing combos' binding/timeout/layers/
# require-prior-idle/slow-release over zmk__combos (key-positions fixed).
CONFIG_ZMK_RUNTIME_COMBOS=y
CONFIG_ZMK_RUNTIME_COMBOS_STUDIO_RPC=y
```

- [ ] **Step 7: Switch the keymap combos node**

In `config/roBa.keymap`, change the `combos` node's `compatible = "zmk,combos";` → `compatible = "zmk,runtime-combos";` (one line; children unchanged).

- [ ] **Step 8: Commit (both repos)**

Module repo (qtrnmr identity):
```bash
cd /tmp/zmk-module-runtime-combos
git add -A
git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit -m "$(printf 'feat: runtime-combos module scaffold + verbatim combo.c fork (coexistence renames)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```
Config repo:
```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add config/west.yml boards/shields/roBa/roBa_R.conf config/roBa.keymap
git commit -m "$(printf 'feat(roba-w2d): wire runtime-combos module + keymap compatible switch\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

- [ ] **Step 9: Note the CI gate**

There is no local firmware build. CI (build.yml) is the gate and requires the module to be on GitHub (`qtrnmr/zmk-module-runtime-combos`, branch `main`). The controller pushes the module repo and the feat branch to trigger CI (with user authorization). Expected: build succeeds; upstream combo.c compiled out (0 `zmk,combos` instances); combos behave as before (HIL in Task 7). This task's deliverable is "builds + structurally correct fork", verified by the Task-1 reviewer reading the diff and by CI.

---

### Task 2: Mutable params + read-site redirects + store + init registration

**Files (module repo):** Create `include/zmk/runtime_combos.h`, `src/runtime_combo_store.c`; modify `src/runtime_combo.c`.

**Interfaces:**
- Consumes: the forked `runtime_combo.c` from Task 1.
- Produces: a build where each combo's 5 editable fields are read from a parallel NVS-backed `rt_params[]`, registered at init; logic still byte-identical except the listed read-sites. Store API: `rt_combo_register(index, live, dt_default)`, `rt_combo_get/set/reset(index, …)`, `rt_combo_registered(index)`, `rt_combo_clear_all()`, `rt_combo_count()`.

- [ ] **Step 1: Create the header `include/zmk/runtime_combos.h`**

```c
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <zmk/behavior.h>

// The runtime-editable fields of one combo. Pointer-free (NVS-safe): the
// behavior is stored as local_id + params; behavior_dev is reconstructed on use.
struct rt_combo_params {
    zmk_behavior_local_id_t behavior_local_id;
    uint32_t param1;
    uint32_t param2;
    int32_t timeout_ms;
    int16_t require_prior_idle_ms;
    uint32_t layer_mask;
    bool slow_release;
};

// Register a combo's live params struct + its devicetree default. A saved NVS
// value overrides the live struct immediately or when settings load completes.
void rt_combo_register(uint8_t index, struct rt_combo_params *live,
                       const struct rt_combo_params *dt_default);

// Fill *out with the live params. 0 if registered, negative else.
int rt_combo_get(uint8_t index, struct rt_combo_params *out);

// Persist to NVS (NVS-first), then update the live struct. 0 on success.
int rt_combo_set(uint8_t index, const struct rt_combo_params *in);

// Restore the devicetree default to the live struct and delete the NVS key.
int rt_combo_reset(uint8_t index);

// True if the index has a registered combo.
bool rt_combo_registered(uint8_t index);

// Number of registered combos (contiguous from 0).
uint8_t rt_combo_count(void);

// Delete all saved combos and restore each live struct to its DT default.
void rt_combo_clear_all(void);
```

- [ ] **Step 2: Create the store `src/runtime_combo_store.c`**

Copy the W2b `src/runtime_condlayer_store.c` verbatim and apply a mechanical swap:
- `rt_condlayer_entry` → `rt_combo_params`
- `CONFIG_ZMK_RUNTIME_CONDLAYERS_MAX` → `CONFIG_ZMK_RUNTIME_COMBOS_MAX`
- `SETTINGS_PREFIX "rt_condlayer"` → `"rt_combo"`
- function/handler/mutex names `rt_condlayer_*` → `rt_combo_*`, `<zmk/runtime_condlayers.h>` → `<zmk/runtime_combos.h>`
- ADD `rt_combo_count()`:
```c
uint8_t rt_combo_count(void) {
    uint8_t n = 0;
    for (uint8_t i = 0; i < ENTRIES; i++) {
        if (entries[i].registered) n++;
    }
    return n;
}
```
Keep the NVS-first write order, the `K_MUTEX`, the both-orders (settings-load before/after register) handling, and `SETTINGS_STATIC_HANDLER_DEFINE` exactly as the template.

- [ ] **Step 3: Add `rt_params[]` + redirect read-sites in `src/runtime_combo.c`**

a) After the const `combos[]` definition (line ~101) add the parallel mutable params array and a reconstructed-binding helper:
```c
static struct rt_combo_params rt_params[ARRAY_SIZE(combos)];

// Build the (pointer-free) DT-default params for combo i from the const array.
static struct rt_combo_params rt_params_from_cfg(const struct combo_cfg *c) {
    return (struct rt_combo_params){
        .behavior_local_id = c->behavior.local_id,
        .param1 = c->behavior.param1,
        .param2 = c->behavior.param2,
        .timeout_ms = c->timeout_ms,
        .require_prior_idle_ms = c->require_prior_idle_ms,
        .layer_mask = c->layer_mask,
        .slow_release = c->slow_release,
    };
}
```

b) Redirect each editable-field read to `rt_params[<idx>]` where `<idx> = combo - combos` (pointer arithmetic into the const array) or the explicit index already in scope:
- `is_quick_tap`: `combo->require_prior_idle_ms` → `rt_params[combo - combos].require_prior_idle_ms`
- `combo_active_on_layer`: `combo->layer_mask` → `rt_params[combo - combos].layer_mask`
- first-timeout loop (`combos[i].timeout_ms`) → `rt_params[i].timeout_ms`
- candidate timeout check (`combos[i].timeout_ms`) → `rt_params[i].timeout_ms`
- release loop: where `const struct combo_cfg *c = &combos[active_combo->combo_idx];` then `c->slow_release` → `rt_params[c - combos].slow_release`

c) In `press_combo_behavior(int combo_idx, const struct combo_cfg *combo, …)`, build the binding from `rt_params[combo_idx]` instead of using `combo->behavior`:
```c
    const char *dev = zmk_behavior_find_behavior_name_from_local_id(
        rt_params[combo_idx].behavior_local_id);
    if (dev == NULL) {
        LOG_ERR("combo %d: unknown behavior local_id %d", combo_idx,
                rt_params[combo_idx].behavior_local_id);
        return -ENODEV;
    }
    struct zmk_behavior_binding binding = {
        .behavior_dev = dev,
        .local_id = rt_params[combo_idx].behavior_local_id,
        .param1 = rt_params[combo_idx].param1,
        .param2 = rt_params[combo_idx].param2,
    };
    return zmk_behavior_invoke_binding(&binding, event, true);   // press path
```
and the release path (the `false` invoke ~306) uses the same `binding` build (factor a local helper `make_binding(combo_idx)` returning the struct, used by both press and release). Leave the rest of the function untouched.

d) `key_positions`, `key_position_len`, `combo_lookup`, sort, candidate bitmask logic stay reading the const `combos[]` — unchanged.

- [ ] **Step 4: Register each combo at init**

In `runtime_combo_init`, before the `initialize_combo` loop, initialize and register the params:
```c
    for (int i = 0; i < ARRAY_SIZE(combos); i++) {
        struct rt_combo_params def = rt_params_from_cfg(&combos[i]);
        rt_params[i] = def;
        rt_combo_register(i, &rt_params[i], &def);
    }
```
Add `#include <zmk/runtime_combos.h>` to the includes.

- [ ] **Step 5: Commit (module repo)**

```bash
cd /tmp/zmk-module-runtime-combos
git add -A
git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit -m "$(printf 'feat: mutable rt_params + NVS store + read-site redirects (W2d)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

Verification: CI build (Task 7). The Task-2 reviewer checks fork fidelity (only the listed read-sites changed; matching logic untouched) and store correctness against the W2b template.

---

### Task 3: Custom Studio RPC `zmk__combos` + proto + settings-reset

**Files (module repo):** Create `proto/zmk/combos/combos.proto`, `src/studio/combos_rpc_handler.c`.

**Interfaces:**
- Consumes: the store API + `rt_params` from Task 2.
- Produces: a `zmk__combos` custom subsystem with `count`, `get`, `set` (per-field), `reset`, and a settings-reset hook. Read-only `key_positions` returned by `get`.

- [ ] **Step 1: Write the proto `proto/zmk/combos/combos.proto`**

```proto
syntax = "proto3";

package zmk.combos;

message Binding {
    uint32 behavior_id = 1;   // zmk_behavior_local_id_t
    uint32 param1 = 2;
    uint32 param2 = 3;
}

message ComboInfo {
    uint32 index = 1;
    repeated uint32 key_positions = 2;   // read-only
    Binding binding = 3;
    int32 timeout_ms = 4;
    int32 require_prior_idle_ms = 5;
    uint32 layer_mask = 6;
    bool slow_release = 7;
    bool found = 8;
}

message CountRequest {}
message CountResponse { uint32 count = 1; }

message GetRequest { uint32 index = 1; }
message GetResponse { ComboInfo info = 1; }

message SetRequest {
    uint32 index = 1;
    oneof field {
        Binding binding = 2;
        int32 timeout_ms = 3;
        int32 require_prior_idle_ms = 4;
        uint32 layer_mask = 5;
        bool slow_release = 6;
    }
}
message SetResponse { bool ok = 1; }

message ResetRequest { uint32 index = 1; }
message ResetResponse { bool ok = 1; }

message Request {
    oneof request_type {
        CountRequest count = 1;
        GetRequest get = 2;
        SetRequest set = 3;
        ResetRequest reset = 4;
    }
}
message Response {
    oneof response_type {
        CountResponse count = 1;
        GetResponse get = 2;
        SetResponse set = 3;
        ResetResponse reset = 4;
    }
}
```
Add `proto/zmk/combos/combos.options` if the W2b proto used one for `repeated`/string bounds — set `zmk.combos.ComboInfo.key_positions max_count:20` (MAX_COMBO_KEYS upper bound). (Check the W2b `condlayers` proto/options for the exact nanopb option style and mirror it.)

- [ ] **Step 2: Write the RPC handler `src/studio/combos_rpc_handler.c`**

Use the W2b `src/studio/condlayers_rpc_handler.c` as the template (fetch it). Mirror its structure: `ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__combos, &meta, handle_request)`, `ZMK_RPC_CUSTOM_SUBSYSTEM_RESPONSE_BUFFER(zmk__combos, zmk_combos_Response)`, decode the request, dispatch the oneof, encode the response. Handlers:
- `count` → `rt_combo_count()`.
- `get` → read `rt_combo_get(index, &p)`; also read `combos[index].key_positions[0..len]` for the read-only positions. **The handler needs access to the const `combos[]` key_positions** — expose a small accessor from `runtime_combo.c`: add to the header `int rt_combo_key_positions(uint8_t index, int32_t *out, uint8_t max, uint8_t *len_out);` and implement it in `runtime_combo.c` reading the const `combos[]`. Fill `ComboInfo{index, key_positions, binding{behavior_local_id,param1,param2}, timeout_ms, require_prior_idle_ms, layer_mask, slow_release, found=true}`. If not registered, `found=false`.
- `set` → `rt_combo_get(index,&p)`; apply the one oneof field that is present (binding → set behavior_local_id/param1/param2; else the scalar); `rt_combo_set(index,&p)`; `ok = (rc==0)`.
- `reset` → `rt_combo_reset(index)`; `ok = (rc==0)`.
- Add the settings-reset hook: `ZMK_RPC_SUBSYSTEM_SETTINGS_RESET(zmk__combos, on_settings_reset)` where `on_settings_reset` calls `rt_combo_clear_all()` (match the W2b hook signature exactly).

- [ ] **Step 3: Add the `rt_combo_key_positions` accessor**

In `include/zmk/runtime_combos.h` add the prototype (above), and in `src/runtime_combo.c` implement:
```c
int rt_combo_key_positions(uint8_t index, int32_t *out, uint8_t max, uint8_t *len_out) {
    if (index >= ARRAY_SIZE(combos)) return -EINVAL;
    uint8_t len = combos[index].key_position_len;
    if (len_out) *len_out = len;
    for (uint8_t i = 0; i < len && i < max; i++) out[i] = combos[index].key_positions[i];
    return 0;
}
```

- [ ] **Step 4: Commit (module repo)**

```bash
cd /tmp/zmk-module-runtime-combos
git add -A
git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit -m "$(printf 'feat: zmk__combos custom RPC (count/get/set/reset) + settings-reset (W2d)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

Verification: CI build (Task 7); Task-3 reviewer checks the RPC handler against the W2b template + proto shape + that `set` is read-modify-write (one field, others preserved).

---

### Task 4: Host — shared behavior_resolve + proto gen + combos_client

**Files (config repo, host):** Create `roba_cli/behavior_resolve.py`, `proto/zmk/combos/combos.proto`, `roba_cli/proto/zmk/combos/combos_pb2.py`, `roba_cli/proto/zmk/combos/__init__.py`, `roba_cli/combos_client.py`; modify `roba_cli/encoder_client.py`; test `tests/test_combos.py`.

**Interfaces:**
- Consumes: the proto from Task 3; the W2c resolution logic now in `behavior_resolve`.
- Produces: `CombosClient` with `count()`, `get(index)`, `list()`, `set(index, field, value)`, `reset(index)`; shared `behavior_resolve.resolve_behavior_local_id(client_call, token)` + `parse_behavior_spec(spec)`.

- [ ] **Step 1: Write the failing shared-helper + proto test**

Append to a new `tools/roba-cli/tests/test_combos.py`:
```python
import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.zmk.combos import combos_pb2 as cb_pb2
from roba_cli import behavior_resolve as br


def test_combos_proto_fields():
    req = cb_pb2.Request()
    assert {"count", "get", "set", "reset"} <= {f.name for f in req.DESCRIPTOR.fields}
    info = cb_pb2.ComboInfo()
    assert {"index", "key_positions", "binding", "timeout_ms",
            "require_prior_idle_ms", "layer_mask", "slow_release", "found"} \
        <= {f.name for f in info.DESCRIPTOR.fields}
    s = cb_pb2.SetRequest()
    assert {"binding", "timeout_ms", "require_prior_idle_ms",
            "layer_mask", "slow_release"} <= {f.name for f in s.DESCRIPTOR.fields}


def test_parse_behavior_spec_kp_and_raw():
    tok, bid, p1, p2 = br.parse_behavior_spec("kp ESC")
    assert tok == "kp" and bid == 0 and p2 == 0 and isinstance(p1, int)
    tok, bid, p1, p2 = br.parse_behavior_spec("raw 14 41 0")
    assert tok is None and bid == 14 and p1 == 41 and p2 == 0
```

- [ ] **Step 2: Run, verify failure**

`cd tools/roba-cli && .venv/bin/python -m pytest tests/test_combos.py -v` → FAIL (no combos_pb2 / behavior_resolve).

- [ ] **Step 3: Generate the proto**

```bash
cd tools/roba-cli
mkdir -p proto/zmk/combos
gh api -H "Accept: application/vnd.github.raw" 'repos/qtrnmr/zmk-module-runtime-combos/contents/proto/zmk/combos/combos.proto?ref=main' > proto/zmk/combos/combos.proto
.venv/bin/python -m grpc_tools.protoc -I proto --python_out=roba_cli/proto proto/zmk/combos/combos.proto
touch roba_cli/proto/zmk/combos/__init__.py
```
(If the module isn't pushed yet, copy the proto from the local module dir `/tmp/zmk-module-runtime-combos/proto/...` instead.)

- [ ] **Step 4: Factor the shared behavior resolver `roba_cli/behavior_resolve.py`**

Move the keycode/spec parsing + `display_name`/crc16 resolution out of `encoder_client.py` into a shared module. Concretely:
```python
from __future__ import annotations
import roba_cli.proto  # noqa: F401

# token -> device name (crc16 fallback) and display_name candidates (primary).
BEHAVIOR_DEV_NAME = {"kp": "key_press", "msc": "mouse_scroll"}
BEHAVIOR_DISPLAY_CANDIDATES = {
    "kp": {"key press", "key_press"},
    "msc": {"mouse scroll", "mouse_scroll"},
}


class BehaviorResolutionError(RuntimeError):
    pass


def crc16_ansi(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def _keycode_value(name: str) -> int:
    if name.isdigit():
        return int(name)
    import zmk_studio_api as zmk
    val = getattr(zmk.Keycode, name.upper(), None)
    if val is None:
        raise ValueError(f"unknown keycode {name!r}")
    return int(val)


def parse_behavior_spec(spec: str) -> tuple[str | None, int, int, int]:
    """'kp <KEYCODE>' -> ('kp',0,keycode,0); 'raw <id> <p1> [p2]' -> (None,id,p1,p2)."""
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
    """behaviors_list: [{'id':int,'display_name':str}]. Match by display_name
    (works in crc16 AND settings-table modes), then crc16 fallback."""
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
```
Then in `encoder_client.py`: import from `behavior_resolve` (`crc16_ansi`, `BEHAVIOR_DEV_NAME`, `BEHAVIOR_DISPLAY_CANDIDATES`, `BehaviorResolutionError`, `parse_behavior_spec` as the basis of `parse_encoder_behavior`, `resolve_local_id`). Keep `encoder_client`'s public surface (its tests must stay green) — e.g. keep `parse_encoder_behavior` (which also handles `msc`) and `EncoderClient.resolve_behavior_local_id` delegating to `behavior_resolve.resolve_local_id(self.behaviors()["behaviors"], token)`. Run the encoder tests to confirm no regression.

- [ ] **Step 5: Write `roba_cli/combos_client.py`**

Mirror `encoder_client.py`'s transport (custom-envelope 2-step via `rpc.send_recv`, `_ser` seam, `_resolve_index` for `zmk__combos`, `_call`, `_behavior_ids`/`behaviors` for resolution). Reuse `condlayer_client.layers_to_mask`/`mask_to_layers` for the `layers` field. Methods:
```python
SUBSYSTEM_ID = "zmk__combos"
# build_* request helpers (pure, unit-tested):
def build_get_request(index): ...            # Request.get.index
def build_count_request(): ...               # Request.count
def build_reset_request(index): ...          # Request.reset.index
def build_set_request(index, field, value, *, behavior_id=None, p1=0, p2=0):
    # field in {"binding","timeout-ms","require-prior-idle-ms","layers","slow-release"}
    # binding -> SetRequest.binding{behavior_id,param1,param2}; others -> scalar oneof
def info_to_dict(info): ...                  # ComboInfo -> {index,key_positions,binding,timeout_ms,...,layers}
def decode_response(resp): ...               # -> {ok, error, ...}
class CombosClient:  # count/get/list/set/reset, set resolves binding via behaviors()
```
For `set(index, "binding", "kp ESC")`: parse via `behavior_resolve.parse_behavior_spec`; if token not None resolve via `behavior_resolve.resolve_local_id(self.behaviors()["behaviors"], token)`; build SetRequest.binding. For `set(index,"layers","1,7")`: `layers_to_mask`. `info_to_dict` should also surface `layers` (mask_to_layers) alongside the raw `layer_mask`.

- [ ] **Step 6: Add unit tests (FakeSerial round-trip) to `tests/test_combos.py`**

Cover: `build_set_request` for each field (oneof selection + values); `info_to_dict` (key_positions + binding + layers from mask); `decode_response` (get/count/set/error); a FakeSerial `get`/`count` round-trip over the custom envelope (stub `_index`); a `set binding` path stubbing `behaviors()` to return `[{"id":14,"display_name":"Key Press"}]` and asserting the request carries `behavior_id=14`. (Model these on `tests/test_encoder.py`.)

- [ ] **Step 7: Run tests + full suite, commit**

`cd tools/roba-cli && .venv/bin/python -m pytest -q` (all green: existing 67 + new). Commit:
```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/roba_cli/behavior_resolve.py tools/roba-cli/roba_cli/encoder_client.py tools/roba-cli/roba_cli/combos_client.py tools/roba-cli/proto/zmk/combos tools/roba-cli/roba_cli/proto/zmk/combos tools/roba-cli/tests/test_combos.py
git commit -m "$(printf 'feat(roba-cli): combos_client + shared behavior_resolve (W2d)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 5: CLI `roba combo` group

**Files (config repo, host):** Modify `roba_cli/cli.py`; test `tests/test_combos.py`.

**Interfaces:**
- Consumes: `CombosClient`.
- Produces: `roba combo list|get <index>|set <index> <field> <value>|reset <index>` with handlers `cmd_combo_list/get/set/reset`.

- [ ] **Step 1: Failing CLI-parse test**

Append to `tests/test_combos.py`:
```python
from roba_cli import cli as _cli


def test_combo_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["combo", "set", "0", "binding", "kp ESC"])
    assert ns.index == 0 and ns.field == "binding" and ns.value == "kp ESC"
    assert ns.func is _cli.cmd_combo_set
    assert p.parse_args(["combo", "list"]).func is _cli.cmd_combo_list
    assert p.parse_args(["combo", "get", "2"]).index == 2
    assert p.parse_args(["combo", "reset", "1"]).func is _cli.cmd_combo_reset
    ns2 = p.parse_args(["combo", "set", "3", "timeout-ms", "40"])
    assert ns2.field == "timeout-ms" and ns2.value == "40"
```

- [ ] **Step 2: Run, verify failure** — `pytest tests/test_combos.py -k combo_subcommands -v` → FAIL.

- [ ] **Step 3: Implement handlers + subparser in cli.py**

Add `from .combos_client import CombosClient` near the other client imports. Handlers (use the existing `_emit`):
```python
def cmd_combo_list(args):
    with CombosClient(args.port) as c:
        _emit(c.list())
    return 0

def cmd_combo_get(args):
    with CombosClient(args.port) as c:
        _emit(c.get(args.index))
    return 0

def cmd_combo_set(args):
    with CombosClient(args.port) as c:
        res = c.set(args.index, args.field, args.value)
    _emit(res)
    return 0 if res["ok"] else 1

def cmd_combo_reset(args):
    with CombosClient(args.port) as c:
        res = c.reset(args.index)
    _emit(res)
    return 0 if res["ok"] else 1
```
Subparser group on `sub` (mirror the `condlayer` group):
```python
    cmb = sub.add_parser("combo", help="runtime combos (zmk__combos)").add_subparsers(dest="combo_cmd", required=True)
    cmb.add_parser("list", help="List all combos as JSON").set_defaults(func=cmd_combo_list)
    cg = cmb.add_parser("get", help="Show one combo")
    cg.add_argument("index", type=int)
    cg.set_defaults(func=cmd_combo_get)
    cs = cmb.add_parser("set", help="Set a combo field")
    cs.add_argument("index", type=int)
    cs.add_argument("field", choices=["binding", "timeout-ms", "require-prior-idle-ms", "layers", "slow-release"])
    cs.add_argument("value", help="behavior 'kp ESC'/'raw id p1 p2'; int; csv layers; or bool")
    cs.set_defaults(func=cmd_combo_set)
    cr = cmb.add_parser("reset", help="Revert a combo to its devicetree default")
    cr.add_argument("index", type=int)
    cr.set_defaults(func=cmd_combo_reset)
```

- [ ] **Step 4: Run full suite, commit**

`cd tools/roba-cli && .venv/bin/python -m pytest -q` (all green). Commit:
```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/roba_cli/cli.py tools/roba-cli/tests/test_combos.py
git commit -m "$(printf 'feat(roba-cli): roba combo command group (W2d)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 6: Docs

**Files (config repo):** Modify `tools/roba-cli/README.md`. (Module repo: write its `README.md`.)

- [ ] **Step 1: README — config repo**

Add a `### コンボ（zmk__combos・焼き直し不要）` section mirroring the other groups: explain `roba combo list/get/set/reset`, the editable fields (binding `kp <KEYCODE>`/`raw …`, timeout-ms, require-prior-idle-ms, layers csv, slow-release bool), that **key-positions are fixed**, combos are addressed by the module's (sorted) index — use `list` to map index→combo by `key_positions`, revert via `combo reset` (or `roba reset` which now also clears combo overrides via the settings-reset hook). Update the title phase line to append `/ W2d`.

- [ ] **Step 2: README — module repo**

Write `/tmp/zmk-module-runtime-combos/README.md`: what it is (verbatim combo.c fork, runtime-editable params, key-positions fixed), setup (west.yml + the two CONFIG flags + keymap compatible switch), the `zmk__combos` RPC surface, and the revert behavior. Commit it in the module repo (qtrnmr identity).

- [ ] **Step 3: Commit (config repo)**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add tools/roba-cli/README.md
git commit -m "$(printf 'docs(roba-w2d): document roba combo group\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

(Do NOT create a repo-tracked `memory/` dir — project memory lives in the Claude auto-memory, which the controller updates.)

---

### Task 7: CI build, HIL, opus fork-fidelity review, local merge

**Files:** none (verification + merge).

- [ ] **Step 1: Push module + feat branch to trigger CI**

With user authorization: push `qtrnmr/zmk-module-runtime-combos` `main` (qtrnmr SSH host) and the config feat branch. Expected CI: build succeeds; upstream combo.c compiled out. If build fails, fix in the module repo and re-push (it pulls module `main`).

- [ ] **Step 2: opus fork-fidelity review**

Dispatch an opus review diffing `src/runtime_combo.c` against the upstream `combo.c` (fetch both): confirm matching/lookup/sort logic is byte-identical apart from the coexistence renames and the exact read-site redirects in Task 2; confirm the behavior reconstruction (`find_behavior_name_from_local_id`) is correct and the press/release paths build the binding identically. Resolve Critical/Important before merge.

- [ ] **Step 3: User flashes roBa_R + HIL**

After flash (only roBa_R; place uf2 on Desktop):
```bash
cd tools/roba-cli
.venv/bin/roba combo list            # 6 combos with key_positions matching the keymap
.venv/bin/roba combo get 0
.venv/bin/roba combo set 0 binding "kp ESC"   # whichever index is tab (positions 11,10)
# press those two key positions -> ESC fires (was TAB)
# power-cycle, reconnect:
.venv/bin/roba combo get 0           # binding still ESC (NVS persist)
.venv/bin/roba combo reset 0         # back to TAB (live)
.venv/bin/roba combo set <i> timeout-ms 40   # sanity on a scalar field
```
Identify the tab combo by `key_positions == [11,10]` from `list` (index may differ from source order due to the shortest-first sort). Verify: set→observable (combo output changes); persist; reset→revert; device restored to defaults.

- [ ] **Step 4: Local merge to main**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git checkout main
git merge --no-ff feat/roba-w2d-combos -m "$(printf 'Merge W2d: runtime combos editing\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
.venv/bin/python -m pytest tools/roba-cli/ -q   # green on merged main
git branch -d feat/roba-w2d-combos
```
Do NOT push origin main unless the user asks. Update the Claude auto-memory + `.git/sdd/progress.md` with W2d completion and any HIL findings.

---

## Self-Review

**Spec coverage:** module fork+coexistence → Task 1; mutable params+read-site redirects+store → Task 2; RPC+proto+settings-reset → Task 3; host proto+shared resolver+client → Task 4; CLI → Task 5; docs → Task 6; CI/HIL/opus/merge → Task 7. The five editable fields, fixed key-positions, behavior_dev reconstruction, index-vs-source-order (echo key_positions), reuse of W2c resolver, and revert (per-combo + settings-reset hook) are all covered.

**Placeholder scan:** No TBD/TODO. Firmware fork tasks reference fetch-then-edit (verbatim fork — exact rename + read-site lists given) rather than inlining 538 lines; store/RPC reference the W2b template with the exact mechanical swaps. Host tasks give complete code/tests.

**Type consistency:** `rt_combo_params` fields used identically across header (Task 2), store (Task 2), RPC handler (Task 3). `build_set_request(index, field, value, …)` field names (`binding`/`timeout-ms`/`require-prior-idle-ms`/`layers`/`slow-release`) match the CLI `choices` (Task 5) and the proto oneof (Task 3, mapping `timeout-ms`→`timeout_ms` etc.). `behavior_resolve.parse_behavior_spec`/`resolve_local_id` signatures match their call sites in `combos_client` and the refactored `encoder_client` (Task 4). `zmk__combos` / `zmk.combos` / `zmk,runtime-combos` consistent throughout.
