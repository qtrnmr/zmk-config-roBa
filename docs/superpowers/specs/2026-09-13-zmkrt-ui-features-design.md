# zmkrt ui — feature panels (Sub-project 2 of 2)

Date: 2026-09-13
Status: approved in chat (design summary approved; user asked to drive through implementation)
Builds on: `2026-09-13-zmkrt-ui-design.md` (Sub-project 1, shipped as module `bb658b7..8658ce7`)

## 1. Goal

Make every remaining runtime-editable feature editable from the `zmkrt ui` browser page,
using the same one-document state model, the same safety rules, and the same form
components as Sub-project 1:

| Feature | Firmware RPC | Existing client |
|---|---|---|
| Macros (8 slots on roBa) | `zmk__macros` | `MacroClient` |
| Hold-tap timing | `zmk__holdtap` | `HoldtapClient` |
| Conditional layers | `zmk__condlayers` | `CondlayerClient` |
| Combos | `zmk__combos` | `CombosClient` |
| Encoder (sensor-rotate) | `cormoran_rsr` | `EncoderClient` |
| Trackball (input processor) | `cormoran_rip` | `RipClient` |

## 2. Non-goals

- No compile-time changes: macro slot count, combo key-positions, condlayer/holdtap
  slot counts stay read-only (shown with the reason).
- No new firmware RPCs. Everything uses the existing custom subsystems.
- No BLE. No multi-device. No auth (unchanged).

## 3. Architecture (delta over Sub-project 1)

```
zmk_runtime_cli/ui/
  features.py     build_features(session) -> /api/features document; per-feature
                  collectors that return {available: false, error} when the custom
                  subsystem is missing (other keyboards) instead of failing the whole doc
  server.py       + routes below; same HttpError / require_unlocked / append_backup pattern
  session.py      + macro_client() / holdtap_client() / condlayer_client() /
                  combos_client() / encoder_client() / rip_client() factories, all
                  `Client(_ser=self.serial)` under the session lock
zmk_runtime_cli/
  combos_client.py   + set_binding(index, behavior_id, p1, p2) (id-direct, no spec string)
  encoder_client.py  + set_raw(sensor, layer, direction, behavior_id, p1, p2, tap_ms)
  rip_client.py      + FIELD_UI: list of {name, kind: int|bool|enum, options?, info_key}
                       so the UI form is generated from one table (mirrors FIELD_SPECS)
cli/ui/src/
  App.tsx            top tab bar: キーマップ | マクロ | Hold-tap | 条件レイヤー | コンボ | エンコーダ | トラックボール
  components/BindingForm.tsx   extracted from KeyEditor: behavior picker + metadata-driven
                               param editors, value = {behavior_id, param1, param2}
  panels/MacroPanel.tsx  HoldtapPanel.tsx  CondlayerPanel.tsx  ComboPanel.tsx
         EncoderPanel.tsx  TrackballPanel.tsx
```

Every mutating route: validate body → `with session:` → `require_unlocked` →
`append_backup({op, ..., before})` → RPC → return `{ok, error}`; the page refetches
`/api/features` (and `/api/state` when layer names may matter) after every mutation.

## 4. API contract

### `GET /api/features`

```jsonc
{
  "macros":    {"available": true, "slots": [{"slot": 0, "steps": [{"type": 1, "keycode": 787101, "wait_ms": 80, "tap_ms": 0, "label": "GLOBE"}, …]}, …]},
  "holdtaps":  {"available": true, "flavors": ["hold-preferred","balanced","tap-preferred","tap-unless-interrupted"],
                "slots": [{"slot": 0, "tapping_term_ms": 200, "quick_tap_ms": 0, "require_prior_idle_ms": 0, "flavor": "balanced", "flavor_index": 1, "found": true}, …]},
  "condlayers": {"available": true, "entries": [{"index": 0, "if_layers": [1, 6], "then_layer": 9, "found": true}, …]},
  "combos":    {"available": true, "entries": [{"index": 0, "key_positions": [11, 10], "binding": {"behavior_id": 8, "param1": 458795, "param2": 0, "label": {…}}, "timeout_ms": 50, "require_prior_idle_ms": 0, "layers": [], "slow_release": false, "found": true}, …]},
  "encoder":   {"available": true, "sensors": [{"index": 0, "name": "…"}],
                "bindings": [{"sensor": 0, "layers": [{"layer": 0, "cw": {"behavior_id": …, "param1": …, "param2": …, "tap_ms": 20, "label": {…}}, "ccw": {…}}, …]}]},
  "trackball": {"available": true, "processors": [{"id": 0, "name": "…", "scale_multiplier": 1, …all InputProcessorInfo fields…}],
                "fields": [{"name": "scale-multiplier", "kind": "int", "info_key": "scale_multiplier"},
                           {"name": "x-invert", "kind": "bool", "info_key": "x_invert"},
                           {"name": "axis-snap-mode", "kind": "enum", "options": ["none","x","y"], "info_key": "axis_snap_mode"},
                           {"name": "temp-layer-layer", "kind": "layer", "info_key": "temp_layer_layer"}, …]}
}
```

A feature whose custom subsystem is not present reports `{"available": false, "error": "<message>"}`
and the tab shows that message instead of a form. Macro step `label` and combo/encoder
binding `label` reuse Sub-project 1's `labels.py` (`keycode_text` for macro keycodes;
`label_for` for bindings). `layers` values are layer **indices**; the UI maps them to names.

### Mutations (all `POST`, JSON in/out `{ok, error}`)

| Path | Body | Backs onto |
|---|---|---|
| `/api/macro/parse` | `{"dsl": "press GLOBE \| wait 80 \| …", "allow_unbalanced": false}` | `macro_dsl.parse` → `{"ok", "steps": [...]}` or `{"ok": false, "error"}` (no device I/O, no backup entry) |
| `/api/macro` | `{"slot": 0, "steps": [{"type", "keycode", "wait_ms", "tap_ms"}, …]}` | `MacroClient.set_macro`; server validates `len(steps) <= macro_dsl.MAX_STEPS`, each field int ≥ 0, `type` ∈ {0,1,2}; press/release balance is checked and returned as a **warning** field, not a rejection (the UI shows it and lets the user apply) |
| `/api/holdtap` | `{"slot", "field": "tapping-term-ms"\|"quick-tap-ms"\|"require-prior-idle-ms"\|"flavor", "value"}` | `HoldtapClient.set(slot, field, str(value))` |
| `/api/holdtap/reset` | `{"slot"}` | `HoldtapClient.reset` |
| `/api/condlayer` | `{"index", "if_layers": [1, 6], "then_layer": 9}` | `CondlayerClient.set(index, ",".join(...), then_layer)` |
| `/api/condlayer/reset` | `{"index"}` | `CondlayerClient.reset` |
| `/api/combo` | `{"index", "field": "binding", "binding": {"behavior_id","param1","param2"}}` or `{"index", "field": "timeout-ms"\|"require-prior-idle-ms"\|"slow-release", "value"}` or `{"index", "field": "layers", "value": [1, 7]}` | `CombosClient.set_binding` / `CombosClient.set` |
| `/api/combo/reset` | `{"index"}` | `CombosClient.reset` |
| `/api/encoder` | `{"sensor", "layer", "direction": "cw"\|"ccw", "behavior_id", "param1", "param2", "tap_ms"}` | `EncoderClient.set_raw` |
| `/api/encoder/reset` | `{"sensor", "layer"}` | `EncoderClient.reset` |
| `/api/trackball` | `{"id", "field": "<FIELD_SPECS name>", "value"}` (bool/int/enum-string) | `RipClient.set(field, id, str(value))` |
| `/api/trackball/reset` | `{"id"}` | `RipClient.reset` (server records the full processor dict in the backup entry first) |

Backup entries: `op` = `ui_macro_set` / `ui_holdtap_set` / `ui_holdtap_reset` /
`ui_condlayer_set` / `ui_condlayer_reset` / `ui_combo_set` / `ui_combo_reset` /
`ui_encoder_set` / `ui_encoder_reset` / `ui_trackball_set` / `ui_trackball_reset`, each with
the request body and the `before` value read just before the RPC.

## 5. Frontend

- **Tab bar** in the top bar. The キーマップ tab is Sub-project 1 unchanged. Each other tab is
  a panel with the same shape: list on the left (or a table), detail form on the right,
  `適用` / `既定に戻す` buttons, disabled when LOCKED or `available: false`.
- **BindingForm** is extracted from `KeyEditor` (behavior `<select>` in curated order +
  metadata-driven param editors) and reused by KeyEditor, ComboPanel (binding field) and
  EncoderPanel (cw/ccw).
- **MacroPanel**: slot list (0–7) with a one-line preview (`GLOBE↓ 80ms LEFT↓ 120ms LEFT↑ …`);
  detail = editable step table: columns `type` (tap/press/release select), `key`
  (KeycodePicker popover; shows canonical text), `wait_ms`, `tap_ms`, row `↑ ↓ ✕`, `+ 行を追加`.
  A collapsible `DSL から取込` textarea → `POST /api/macro/parse` → replaces the table.
  `適用` → `POST /api/macro`. Unbalanced press/release shows an amber warning line.
- **HoldtapPanel**: table of slots; each row editable inline (three number inputs + flavor
  select), `既定に戻す` per row. Slot numbers only (the RPC does not expose which behavior
  a slot belongs to; a note says so).
- **CondlayerPanel**: table `index | if-layers | then-layer`; edit = checkbox list of layer
  names + then-layer select. `既定に戻す` per row.
- **ComboPanel**: table `index | keys | binding | timeout | prior-idle | layers | slow-release`.
  **Hovering a row highlights its key positions on the keyboard SVG** (the Keyboard component
  gains a `highlight: number[]` prop; the combo tab renders the keyboard above the table with
  the DEFAULT layer's labels). Detail form: BindingForm + numbers + layer checkboxes + toggle.
- **EncoderPanel**: sensor select; table of layers × (cw, ccw) with labels; click a cell →
  BindingForm + tap_ms; `既定に戻す` per layer.
- **TrackballPanel**: form generated from `fields` (int → number, bool → toggle, enum →
  select, layer → layer select); each field applies individually on blur/change with a
  small ✓; `既定に戻す` for the processor behind a confirm dialog listing the current values.

## 6. Safety

Same as Sub-project 1: LOCKED disables everything; every mutation is logged with `before`;
resets exist for every feature; the ChangeLog drawer understands the new `op`s.

## 7. Testing

- pytest: `features.build_features` with scripted `FakeSerial` frames per feature, including
  an "unavailable subsystem" case; every route via the `StubSession` pattern (validation
  400s, lock 423, backup entry written, client called with the right args);
  `combos_client.set_binding` / `encoder_client.set_raw` / `rip_client.FIELD_UI` units.
- vitest: macro preview formatting; BindingForm value round-trip.
- HIL on roBa (implementer): for each feature, get → set → read back → restore (holdtap:
  bump tapping-term 200→210→200; condlayer: entry 0 same value re-set; combo 0:
  timeout 50→60→50; encoder: layer 0 cw same value re-set; trackball: `x-invert` toggle and
  back; macro: slot 7 (highest, expected empty or backup first) set a 2-step macro then
  clear to the previous steps). Record before/after JSON. No `/api/reset`.
