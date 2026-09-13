# zmkrt ui v2 — keyboard-first redesign

Date: 2026-09-13
Status: approved in chat (layout, integration, firmware change and the design summary below)
Builds on: `2026-09-13-zmkrt-ui-design.md` (sub-project 1) and
`2026-09-13-zmkrt-ui-features-design.md` (sub-project 2), both shipped on
`zmk-module-runtime-config` main (`3eab007`).

## 1. Goal

Make the `zmkrt ui` page modern, simple and intuitive:

- The keyboard drawing is the page. It fills the width; everything else is a chip row
  above it, a thin icon rail on the left, and an inspector that slides in from the right
  only when something is selected.
- The features that belong to a key or a spot on the board are edited *on the board*:
  combos are drawn as links between keys, the encoder is a knob, hold-tap timing is a
  section of the key inspector. Only macros, conditional layers and the trackball keep a
  page of their own (behind the rail).
- One small firmware change so the UI can do that: the hold-tap RPC reports which
  behavior each slot is, and the combo RPC reports the devicetree binding of an
  untouched combo.

## 2. Non-goals

- No light theme. No responsive/mobile layout (desktop browser only).
- No new runtime capability: slot counts, combo key-positions, sensor list stay fixed.
- No change to sub-project 1/2 safety rules (LOCKED disables all writes, every write is
  logged with `before`, `/api/reset` stays behind the typed confirm).
- The stock `&mt` / `&lt` behaviors are not runtime hold-taps; their timing is not editable
  and the inspector says so (one line) instead of showing a form.

## 3. Firmware (module `zmk-module-runtime-config`)

### 3.1 Hold-tap: `HoldTapInfo.behavior_id`

`proto/zmk/holdtap/holdtap.proto`:

```proto
message HoldTapInfo {
    uint32 slot                  = 1;
    int32  tapping_term_ms       = 2;
    int32  quick_tap_ms          = 3;
    int32  require_prior_idle_ms = 4;
    uint32 flavor                = 5;
    bool   found                 = 6;
    uint32 behavior_id           = 7; // zmk_behavior_local_id_t of the behavior owning this slot; 0 if unknown
}
```

Store (`include/zmk/runtime_holdtap.h`, `src/runtime_holdtap_store.c`): the slot keeps
the behavior's device name.

```c
void rt_holdtap_register(uint8_t slot, struct rt_holdtap_timing *live,
                         const struct rt_holdtap_timing *dt_default,
                         const char *behavior_name);   // dev->name, may be NULL
const char *rt_holdtap_behavior_name(uint8_t slot);    // NULL if not registered
```

`behavior_runtime_hold_tap.c` passes `dev->name`. The RPC `handle_get` fills
`info->behavior_id = name ? zmk_behavior_get_local_id(name) : 0`
(`zmk_behavior_get_local_id(const char *)` from `<zmk/behavior.h>`, available whenever
Studio is on because Studio requires `CONFIG_ZMK_BEHAVIOR_LOCAL_IDS`).

### 3.2 Combos: `ComboInfo.dt_binding`

`proto/zmk/combos/combos.proto`:

```proto
message ComboInfo {
    ...
    bool found = 8;
    Binding dt_binding = 9;   // the devicetree binding, resolved to a local id; valid whenever found
}
```

`runtime_combo.c` exposes the const DT binding:

```c
// include/zmk/runtime_combos.h
// Resolve combo `index`'s devicetree binding to (local_id, param1, param2).
// Returns 0, or -EINVAL if index is out of range / behavior unknown.
int rt_combo_dt_binding(uint8_t index, struct rt_combo_params *out);
```

implemented next to `rt_combo_key_positions` using `combos[idx].behavior.behavior_dev`
and `zmk_behavior_get_local_id`. `handle_get` fills `dt_binding` (`has_dt_binding = true`)
when that returns 0. The live `binding` keeps its current meaning (`behavior_id 0` = never
overridden) so the existing CLI keeps working.

### 3.3 Compatibility

Both fields are proto3 optional-by-default. The CLI treats `behavior_id == 0` /
missing `dt_binding` as "unknown" so it still works against firmware without this change.

## 4. CLI / server (module `cli/`)

- Regenerate `cli/zmk_runtime_cli/proto/holdtap/holdtap_pb2.py` and
  `cli/zmk_runtime_cli/proto/zmk/combos/combos_pb2.py` with `grpcio-tools` pinned to the
  version whose generated code matches the installed `protobuf` runtime (7.35.1).
- `holdtap_client.info_to_dict` adds `"behavior_id": info.behavior_id`.
- `combos_client.info_to_dict` adds `"dt_binding": {behavior_id, param1, param2}` when
  `info.HasField("dt_binding")`, else `None`.
- `ui/features.py`:
  - `collect_holdtaps` passes `behavior_id` through.
  - `collect_combos` labels `dt_binding` too (`binding_label`) and adds
    `"effective": <binding if behavior_id != 0 else dt_binding>` with its label, so the
    UI never has to compute "what does this combo do".
  - `build_features(session, ..., only: set[str] | None = None)`: when `only` is given,
    only those keys are collected; the others are omitted from the document.
- `GET /api/features?only=combos,holdtaps` → the query is parsed into `only`; an unknown
  name is a 400. Without `only`, unchanged.
- `GET /api/state` unchanged.

## 5. Frontend

### 5.1 Layout

```
┌──────┬──────────────────────────────────────────────────────┬──────────────┐
│ rail │ topbar: ● roBa · UNLOCKED · /dev/cu… ·        [⟳]     │  inspector   │
│ ⌨    ├──────────────────────────────────────────────────────┤  (360px,     │
│ M    │ [0 DEFAULT][1 APPLE][2 ANDROID]…[12 BOOT] [+]  ☐コンボ │   slides in  │
│ CL   │                                                      │   when       │
│ TB   │                 keyboard SVG (fills width)           │   something  │
│      │       combo links + pills, encoder knob, trackball   │   is         │
│ …    │                                                      │   selected)  │
└──────┴──────────────────────────────────────────────────────┴──────────────┘
```

- **Rail** (`components/Rail.tsx`, 56px): icon + short label for `keymap` / `macro` /
  `condlayer` / `trackball`; at the bottom a `…` menu with 変更履歴 / スナップショット /
  リセット. `Tab` type shrinks to those four ids (`holdtap`, `combo`, `encoder` are gone
  as tabs).
- **TopBar**: one line — connection dot, device name, LOCK badge, serial port (muted),
  `⟳ 再読込` on the right. No tab buttons.
- **LayerChips** (`components/LayerChips.tsx`) replaces `LayerSidebar`: horizontal,
  wrapping chip row above the keyboard. Chip = `index · name`; click selects;
  double-click edits the name inline (Enter commits, Esc cancels, blur commits);
  drag-and-drop reorders (same `onMove(start, dest)`); `+` adds (disabled at
  `available_layers == 0`); each chip has a `×` on hover that opens the existing
  ConfirmDialog; removed layers appear as dashed "復元: NAME" chips at the end.
  The right end of the row has a `コンボ表示` toggle (default on, remembered in
  localStorage).
- **Keyboard** fills the remaining area: `svg` with `preserveAspectRatio="xMidYMid meet"`
  inside a container that takes all width and height; the viewBox now also includes the
  decor (§5.3) bounds.
- **Inspector** (`components/Inspector.tsx`): `aside` 360px, mounted only when
  `selection !== null`; slides in with a 150ms transform transition; header shows what is
  selected and a `×`; `Esc` closes. Content by selection kind (§5.4).

```ts
type Selection =
  | { kind: "key"; pos: number }
  | { kind: "combo"; index: number }
  | { kind: "encoder"; sensor: number };
```

### 5.2 Key caps

- Cap: `rect` with `rx=8`, fill `zinc-800`, a 1px inner top highlight (`zinc-700`), a
  drop shadow filter; hover raises the fill to `zinc-700`.
- Tap label 16px (`zinc-100`), hold label 10px above (`zinc-400`), behavior tag 8px
  bottom-right (`sky-500/70`) — same TAG table as today.
- Transparent (`▽`): fill `zinc-900/60`, base-layer label at `zinc-500`, `▽` glyph
  top-left.
- Selected: `stroke sky-400` 3px. Keys of the hovered/selected combo: `stroke amber-400`
  2px + `fill amber-500/15`.
- Keys are clickable only where `layer.bindings[pos]` exists (unchanged).

### 5.3 On-board features

**Combos** (`components/ComboOverlay.tsx`, rendered inside the same SVG after the keys):
for every combo entry that is *active on the current layer* (`layers` empty, or contains
`layer.index`) draw

- a polyline through the rotated centres of its `key_positions` (for 2 keys a line, for
  3+ keys the keys in the given order), `stroke amber-400/70`, width 2.5, round caps;
- a pill at the centroid: rounded rect with the *effective* label
  (`entry.effective.label`: `text` or `hold/tap`), 11px, `fill zinc-900`, `stroke
  amber-400`; hovering the pill or line sets `hoverCombo`; clicking selects
  `{kind: "combo", index}`.

The overlay is hidden when the `コンボ表示` toggle is off.

**Decor** (`decor.ts`): per-layout table of non-key items; looked up by
`layout.name + ":" + layout.keys.length`. roBa (`"Default:43"`):

```ts
export interface Decor {
  encoders: { sensor: number; cx: number; cy: number; r: number }[]; // layout units (1/100 u)
  trackball?: { cx: number; cy: number; r: number };
}
export const DECOR: Record<string, Decor> = {
  "Default:43": {
    encoders: [{ sensor: 0, cx: 550, cy: 85, r: 45 }],
    trackball: { cx: 750, cy: 80, r: 55 },
  },
};
export function decorFor(layout: { name: string; keys: unknown[] }): Decor | undefined
```

- **Encoder knob** (`components/EncoderKnob.tsx`): a circle (`fill zinc-800`, `stroke
  zinc-600`), a small tick mark, and two 9px labels beside it: `↻ <cw label>` and
  `↺ <ccw label>` for the current layer (from `features.encoder.bindings[sensor].layers`
  matching `layer.index`; "—" if none). Click selects `{kind: "encoder", sensor}`.
  Selected: `stroke sky-400`. Sensor 1 (roBa right encoder) is not in the decor table and
  is therefore not drawn; a layout with no decor shows no knobs and the `…` menu gains an
  `エンコーダ一覧` item that opens the old EncoderPanel in a dialog.
- **Trackball** (`components/TrackballDecor.tsx`): circle `fill zinc-900`, `stroke
  zinc-600`, dotted inner ring; click → `setTab("trackball")`.

### 5.4 Inspector contents

**Key** (`components/KeyInspector.tsx`, replaces KeyEditor):

1. Header: `pos 12 · レイヤー 0 DEFAULT`.
2. 現在: big label (tap/hold), behavior name, raw `#id p1 p2` in mono muted.
3. `BindingForm` (unchanged) + `適用` + `▽ にする`.
4. **Hold-tap timing** section, shown when `features.holdtaps.slots` contains a slot with
   `behavior_id === current.behavior_id`: four fields (tapping-term / quick-tap /
   prior-idle number inputs, flavor select) with `適用` (one `/api/holdtap` call per
   changed field, then `refetch(["holdtaps"])`) and `既定に戻す` (`/api/holdtap/reset`).
   When the current behavior's `display_name` is `Mod-Tap` or `Layer-Tap` (stock, not
   runtime), show one muted line: `&mt / &lt のタイミングは runtime 編集できません`.
5. **他のレイヤーでのこのキー**: list of every layer except the current one with that
   position's label (`▽` shown as `▽`); clicking a row switches the layer (selection
   stays on the same pos).

**Combo** (`components/ComboInspector.tsx`): header `コンボ 4 · Z+X+C` (labels from the
base layer, as `keysText` today); `effective` label; then the existing ComboPanel form
(BindingForm, timeout, prior-idle, layer checkboxes, slow-release, 適用, 既定に戻す) moved
here. `既定に戻す` is always enabled (the RPC is idempotent).

**Encoder** (`components/EncoderInspector.tsx`): header `エンコーダ 0 · レイヤー 0 DEFAULT`;
two stacked cards CW / CCW, each with `BindingForm` + `tap_ms` and one `適用` per card
(`/api/encoder`), and `このレイヤーを既定に戻す` (`/api/encoder/reset`). Layer follows the
current chip.

### 5.5 Pages behind the rail

- `macro`: MacroPanel unchanged in behavior, restyled with the shared primitives (cards,
  same input styles) and a page header.
- `condlayer`: CondlayerPanel unchanged in behavior, restyled.
- `trackball`: TrackballPanel unchanged in behavior, restyled.
- HoldtapPanel, ComboPanel, EncoderPanel files are deleted; their form logic lives in
  the inspectors (Encoder keeps a dialog fallback for decor-less layouts, see §5.3).

### 5.6 Data flow and speed

- `App` fetches `/api/state` first and renders the board immediately; `/api/features`
  loads in the background (overlay/knob appear when it arrives; a thin progress line under
  the top bar shows while loading).
- `refetch(parts?: FeatureKey[])`: no argument = state + all features (used by 再読込 and
  layer ops); with parts = state + `GET /api/features?only=<parts>` merged into the
  cached features document. Each mutation names its parts: key → `["holdtaps"]` only if
  the hold-tap section applied, else none (state only); combo → `["combos"]`; encoder →
  `["encoder"]`; macro → `["macros"]`; condlayer → `["condlayers"]`; trackball →
  `["trackball"]`.
- `run(fn, okMsg, parts?)` keeps today's semantics (LOCKED guard, toast, busy) and calls
  `refetch(parts)`.

### 5.7 Copy

Japanese everywhere: スナップショット / リセット / 再読込 / 変更履歴 / 既定に戻す / 適用.
Toast, ConfirmDialog, ChangeLog unchanged (ChangeLog summaries already cover every op).

## 6. Safety

Unchanged from sub-projects 1/2. The inspector's write buttons are disabled when LOCKED
or busy. `/api/reset` is only reachable from the rail's `…` menu behind the typed confirm.

## 7. Testing

- **Firmware**: builds in the roBa CI (`zmk-config-roBa` workflow; module pinned to
  `main`). No local Zephyr toolchain — the implementer commits the module change, then
  the main session triggers/awaits the roBa build and flashes the right half.
- **pytest**: `holdtap_client.info_to_dict` carries `behavior_id`; `combos_client
  .info_to_dict` carries `dt_binding` / `None`; `collect_combos` produces `effective`
  (overridden vs untouched); `build_features(only=...)` collects only those; the route
  parses `only` and rejects unknown names with 400. Existing 203 stay green.
- **vitest**: `decorFor` lookup; combo overlay geometry helper (`comboPath(entry, boxes)`
  returns centres + centroid); `activeCombos(entries, layerIndex)` filter; `holdtapSlotFor
  (slots, behaviorId)`.
- **HIL on roBa** (implementer, against the *current* firmware, before the reflash):
  key set/restore, combo 0 timeout 50→60→50 via the inspector, encoder layer 0 cw same
  value re-set, layer rename round trip, `?only=combos` returns just combos. Hold-tap
  section is verified by the main session after the reflash (slot for `LAYER_TAP_TO_0`
  shows on the `英数` key; tapping-term 200→210→200).
- **Visual**: agent-browser screenshots of keymap (nothing selected / key selected /
  combo selected / encoder selected), macro, condlayer, trackball at 1280×1300, attached
  to the report.
