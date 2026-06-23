# W2d — Runtime Combos Editing — Design

Date: 2026-06-22
Status: Approved (design)
Branch: `feat/roba-w2d-combos`

## Goal

Edit roBa's existing combos **without reflashing**: change each combo's output
`binding`, `timeout-ms`, `require-prior-idle-ms`, `layers`, and `slow-release`
at runtime over USB, persisted across power cycles and revertible to the
device-tree default. **`key-positions` stay fixed** — adding/removing combos or
moving their trigger positions is explicitly out of scope (that requires
rebuilding the `combo_lookup` position→combo index, the genuinely hard part).

This is the capstone self-built feature. It is the confluence of three patterns
already proven on this project:
- **W2a** (verbatim core-behavior fork → const fields become NVS-backed data).
- **W2b** (listener-subsystem coexistence via compatible rename: upstream is
  `#if`'d out when it has zero instances).
- **W2c** (resolving a binding's `behavior_local_id` from the live device via
  Studio `display_name`, since roBa runs the SETTINGS_TABLE local-id mode).

## Why this scope is safe

`combo.c` builds, at init, a `combo_lookup[ZMK_KEYMAP_LEN][BYTES_FOR_COMBOS_MASK]`
bitmask mapping each key position to the combos that use it, plus a
shortest-first sorted `static const struct combo_cfg combos[]`. Those structures
are derived from `key_positions`/`key_position_len`. The five fields we make
mutable — `behavior`, `timeout_ms`, `require_prior_idle_ms`, `layer_mask`,
`slow_release` — are **read at match/invoke time only** and feed neither the
index nor the sort. So mutating them needs no index rebuild and leaves the
matching logic byte-identical. `key_positions`/`key_position_len` stay sourced
from the const array.

Verified read-sites in `combo.c` (base `v0.3-branch+dya`):
- `is_quick_tap` → `combo->require_prior_idle_ms` (~:159)
- candidate timeout → `combo->timeout_ms`
- `combo_active_on_layer` → `combo->layer_mask` (~:150)
- `press_combo_behavior`/release → `combo->behavior` via
  `zmk_behavior_invoke_binding(&combo->behavior, …)` (~:293, :306)
- release path → `combo->slow_release` (~:384)

`combo.c` body is wrapped entirely in
`#if DT_HAS_COMPAT_STATUS_OKAY(DT_DRV_COMPAT)` where `DT_DRV_COMPAT = zmk_combos`
(:7, :28). Changing roBa's `combos` node to `zmk,runtime-combos` drops the
upstream instance count to 0, so the whole file compiles out — no listener, no
symbol collision (same mechanism as W2b conditional-layers).

## roBa's combos (6, all `&kp`, fixed positions)

| idx | name | binding | key-positions | layers |
|----|------|---------|---------------|--------|
| 0 | tab | `&kp TAB` | 11 10 | (all) |
| 1 | esc | `&kp ESCAPE` | 0 1 | (all) |
| 2 | backspace | `&kp BACKSPACE` | 9 8 | (all) |
| 3 | delete | `&kp DELETE` | 20 21 | (all) |
| 4 | redo_win | `&kp LC(LS(Z))` | 22 23 24 | DEFAULT, MOUSE |
| 5 | redo_apple | `&kp LG(LS(Z))` | 22 23 24 | APPLE, … |

(The combo index order seen by the module is the shortest-first sorted order
that `combo.c` generates, not necessarily source order; the host `get` reports
each combo's `key_positions` so the user can identify which is which.)

## Components

### Module `qtrnmr/zmk-module-runtime-combos` (new)

- `src/runtime_combo.c` — verbatim fork of `combo.c`. Coexistence renames:
  `DT_DRV_COMPAT zmk_runtime_combos`; `ZMK_LISTENER(combo,…)`→`runtime_combo`;
  `ZMK_SUBSCRIPTION(combo,…)`→`runtime_combo`; `combo_init`→`runtime_combo_init`;
  non-static file globals made `static`. Keep `static const struct combo_cfg
  combos[]` as the DT-default source. Add a mutable
  `static struct combo_cfg rt_combos[]` initialized from the const array; redirect
  the five read-sites above to `rt_combos[idx]`. Matching/lookup code unchanged.
- `include/zmk/runtime_combos.h` — `struct rt_combo_params { int32_t timeout_ms;
  int16_t require_prior_idle_ms; uint32_t layer_mask; bool slow_release;
  zmk_behavior_local_id_t behavior_local_id; uint32_t param1; uint32_t param2; }`
  + register/get/set/reset/count/clear_all prototypes. (The behavior is stored as
  local_id + params; on apply, `behavior_dev` is reconstructed via
  `zmk_behavior_find_behavior_name_from_local_id`, exactly as the W2c rsr module
  does for its bindings.)
- `src/runtime_combo_store.c` — NVS store (key `rt_combo/<index>`, `K_MUTEX`,
  NVS-first, handles both settings-load/SYS_INIT-register orders) — same shape as
  the W2b condlayer store.
- `src/studio/combos_rpc_handler.c` — `ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__combos, …)`,
  count/get/set/reset (response-returning, per-index get; no `repeated`), plus
  `ZMK_RPC_SUBSYSTEM_SETTINGS_RESET` so `roba reset` clears `rt_combo` keys.
- `proto/zmk/combos/combos.proto` — `ComboInfo{index, key_positions (repeated),
  binding{behavior_id,param1,param2}, timeout_ms, require_prior_idle_ms,
  layer_mask, slow_release, found}`; Request/Response oneof count/get/set/reset.
  Set carries a field selector so a single field can be changed without
  clobbering the others (mirrors the W2a holdtap "set one field" approach):
  `SetRequest{index, oneof{ binding | timeout_ms | require_prior_idle_ms |
  layer_mask | slow_release }}`.
- `dts/bindings/zmk,runtime-combos.yaml` — copy of the `zmk,combos` binding
  (compatible `zmk,runtime-combos`, same child properties: `key-positions`,
  `bindings`, `layers`, `timeout-ms`, `require-prior-idle-ms`, `slow-release`).
- `Kconfig` (`ZMK_RUNTIME_COMBOS`, `ZMK_RUNTIME_COMBOS_STUDIO_RPC`),
  `CMakeLists.txt` (nanopb gen), `zephyr/module.yml`, `LICENSE`, `README.md`.

### Config repo `zmk-config-roBa`

- `config/west.yml` — add `zmk-module-runtime-combos` (remote `qtrnmr-gh`, `main`).
- `boards/shields/roBa/roBa_R.conf` — `CONFIG_ZMK_RUNTIME_COMBOS=y`,
  `CONFIG_ZMK_RUNTIME_COMBOS_STUDIO_RPC=y`. roBa_L unchanged. (Combos are
  processed on the central; only roBa_R changes.)
- `config/roBa.keymap` — `combos` node compatible `zmk,combos` →
  `zmk,runtime-combos` (one line). Children unchanged.

### Host `tools/roba-cli`

- Generate `proto/zmk/combos/combos.proto` → `roba_cli/proto/zmk/combos/combos_pb2.py`.
- `combos_client.py` — custom-envelope client for `zmk__combos`:
  `count()`, `get(index)`, `list()`, `set(index, field, value)`, `reset(index)`.
  - `binding "<spec>"`: parse `kp <KEYCODE>` / `raw <id> <p1> [p2]` and resolve
    the behavior local_id via Studio `display_name` — **reuse the resolution
    helper introduced in W2c** (factor `encoder_client`'s
    `resolve_behavior_local_id` + behavior-spec parsing into a shared module,
    e.g. `behavior_resolve.py`, imported by both clients; do not duplicate).
  - `layers <csv>`: reuse `condlayer_client.layers_to_mask` / `mask_to_layers`.
  - `timeout-ms`, `require-prior-idle-ms`: int. `slow-release`: bool.
- `cli.py` — `roba combo list | get <index> | set <index> <field> <value> |
  reset <index>`. JSON output via the existing `_emit` helper.

## Data flow (binding edit)

```
roba combo set 0 binding "kp ESC"
  → resolve "kp" -> local_id (Studio display_name "Key Press"); "ESC" -> keycode
  → zmk__combos.SetRequest{index=0, binding{behavior_id, param1, param2}}
  → firmware: rt_combos[0].behavior = {local_id, behavior_dev=find_name(local_id),
                                       param1, param2}; settings_save_one(rt_combo/0)
press key positions 11+10 → combo fires ESC (was TAB)
power-cycle → rt_combo/0 reloaded → still ESC
roba combo reset 0 → rt_combos[0] = combos[0] (DT default TAB), settings_delete
```

## Revert

- Per-combo: `roba combo reset <index>` restores that combo's params to the const
  DT default (live) and deletes its NVS key.
- Global: the module registers `ZMK_RPC_SUBSYSTEM_SETTINGS_RESET`, so `roba reset`
  also clears all `rt_combo` keys (full parity with W2a/W2b — unlike W2c, here we
  fork anyway, so adding the hook is free).
- Always-revertible: the const `combos[]` is never mutated; reset re-copies from it.

## Risks & mitigations

- **Fork fidelity**: the matching/lookup logic must stay byte-identical; only the
  five read-sites and the global-static renames change. Mitigation: opus fidelity
  review diffing the fork against upstream (as in W2a/W2b).
- **`behavior_dev` reconstruction**: invoke needs a valid `behavior_dev`; rebuild
  it from local_id on every set and on NVS load (rsr-proven approach). If
  `find_name_from_local_id` returns NULL (unknown id), reject the set.
- **Index order vs source order**: `combos[]` is sorted; the user addresses
  combos by the module's index. `get`/`list` always echo `key_positions` so the
  user maps index→combo unambiguously. Documented.
- **local-id mode**: roBa is SETTINGS_TABLE (W2c finding) — resolution is by
  display_name, not crc16. Reusing the W2c helper handles both modes.
- **CI build is the firmware gate** (new module + fork). Tag/commit pinning of
  the base is not needed (this is our own module against the same base).

## Out of scope

- Adding/removing combos; changing `key-positions`/`key_position_len`
  (needs `combo_lookup` rebuild + dynamic arrays — a separate future cycle).
- Editing roBa_L or any non-central behavior.
- Web UI.

## Acceptance

- CI build green with the module enabled and the keymap on `zmk,runtime-combos`.
- `roba combo list` shows 6 combos with correct key_positions and bindings.
- `roba combo set 0 binding "kp ESC"` → the tab combo (positions 11+10) emits ESC;
  persists across power cycle; `reset 0` restores TAB (live).
- `roba combo set <i> timeout-ms <n>` / `layers <csv>` / `require-prior-idle-ms`
  / `slow-release` round-trip via get and persist.
- opus fork-fidelity review: matching logic byte-identical apart from the five
  redirected read-sites and the coexistence renames.
- All existing host tests stay green; new `tests/test_combos.py` green.
- Merged to `main` locally (`--no-ff`), origin not pushed unless asked.
