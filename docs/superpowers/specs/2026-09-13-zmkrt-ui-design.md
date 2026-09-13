# zmkrt ui — browser-based keymap viewer/editor (Sub-project 1 of 2)

Date: 2026-09-13
Status: approved (design sections 1–2 approved in chat; user asked to drive through implementation)

## 1. Goal

Make the current roBa key configuration easy to *see*, and make every runtime-editable
(hot-swappable) setting editable from a browser, by adding a `zmkrt ui` subcommand to
`zmk-runtime-cli` (repo `qtrnmr/zmk-module-runtime-config`, dir `cli/`).

`zmkrt ui` starts a local HTTP server, opens the browser, and shows the **live device
state** (NVS-applied runtime state, not the `.keymap` file) rendered on the keyboard's
real physical layout (roBa / roBaish share the same layout, fetched from the device).

Split into two sub-projects:

| Sub-project | Scope |
|---|---|
| **1 (this spec)** | server foundation, keyboard rendering, per-key binding editor, layer management, snapshot/reset, change log |
| 2 (next spec) | panels for macro / hold-tap / conditional layers / combos / encoder / trackball, reusing the same API shape |

## 2. Non-goals

- No parsing of `config/roBa.keymap` (DTS). The device is the single source of truth.
- No BLE transport (USB serial only, same as the CLI).
- No multi-device / remote access. Server binds `127.0.0.1` only.
- No compile-time changes (adding layers when `available_layers == 0`, changing combo
  key-positions, macro slot count) — the UI shows these as disabled with a reason.
- No auth. Local-only tool.

## 3. Architecture

```
zmkrt ui [--port <serial>] [--http-port 8760] [--no-open]
   │
   ├─ zmk_runtime_cli/ui/server.py     ThreadingHTTPServer + tiny router (stdlib only)
   │      GET  /            → static/index.html (Vite build, package data)
   │      GET  /assets/*    → static assets
   │      GET  /api/...     → JSON
   │      POST /api/...     → JSON
   ├─ zmk_runtime_cli/ui/session.py    DeviceSession: owns ONE pyserial handle,
   │                                   threading.Lock around every RPC, lazy open,
   │                                   reconnect on serial error
   ├─ zmk_runtime_cli/ui/native_client.py
   │      pure request builders / response decoders for Studio *native* RPCs
   │      (core / keymap / behaviors) over rpc.send_recv — same style as keymap_client.py
   ├─ zmk_runtime_cli/ui/labels.py     binding → human label ({text | hold/tap})
   ├─ zmk_runtime_cli/ui/state.py      build_state(session) → the /api/state document
   ├─ zmk_runtime_cli/backup.py        _append_backup + BACKUP_LOG moved out of cli.py
   │                                   (cli.py imports it; behaviour unchanged)
   └─ zmk_runtime_cli/ui/static/       committed Vite build output
cli/ui/                                Vite + React + TS + Tailwind source (dev only)
```

**Why one pyserial handle:** today `zmkrt key ...` uses `zmk_studio_api.StudioClient`
which opens the port itself, while every other client uses pyserial directly. Two owners
cannot share one CDC-ACM port, so the UI server talks *every* RPC through pyserial:
native keymap/behaviors/core requests are added as builders in `native_client.py`
(protos already exist: `keymap_pb2`, `behaviors_pb2`, `core_pb2`). `zmk_studio_api` is
only imported for its `Keycode` enum (no port access). `KeymapClient` and `MacroClient`
gain the same `_ser=` injection the other clients already have so Sub-project 2 can
reuse them on the shared handle; the CLI code paths are unchanged.

**Concurrency:** the browser may fire several requests; `DeviceSession.call()` takes the
lock, so RPCs are strictly serialized (request_id increments under the lock). No
WebSocket / SSE: the UI refetches `/api/state` after every mutation.

**Port exclusivity:** while `zmkrt ui` runs, other `zmkrt` commands cannot open the port.
The CLI help for `ui` says so.

## 4. API contract

All responses are JSON. Errors: HTTP 4xx/5xx with `{"error": "<message>"}`. Every
mutating endpoint appends a line to `.zmkrt-backup.jsonl` *before* sending the RPC.

### `GET /api/state`

One document with everything the UI needs:

```jsonc
{
  "device": {"name": "roBa", "lock_state": "UNLOCKED" | "LOCKED", "serial_port": "/dev/cu.usbmodem…"},
  "layout": {"name": "Default",
             "keys": [{"pos": 0, "x": 0, "y": 37, "w": 100, "h": 100, "r": 0, "rx": 0, "ry": 0}, …]},
  "keymap": {"available_layers": 0, "max_layer_name_length": 20,
             "layers": [{"index": 0, "id": 0, "name": "DEFAULT",
                         "bindings": [{"pos": 0, "behavior_id": 123, "param1": 458772, "param2": 0,
                                       "label": {"text": "Q"} },
                                      {"pos": 5, …, "label": {"hold": "LCTRL", "tap": "A"}}, …]}, …]},
  "behaviors": [{"id": 123, "display_name": "Key Press",
                 "metadata": [{"param1": [{"name": "Key", "type": "hid_usage", "keyboard_max": 255, "consumer_max": 1024}],
                               "param2": []}]}, …],
  "keycodes": {"A": 458756, "LEFT_CONTROL": 458976, …},    // from zmk_studio_api.Keycode
  "backup_log_path": "…/.zmkrt-backup.jsonl"
}
```

`metadata[].param1/param2[]` entries carry `type` ∈ `nil | constant | range | hid_usage | layer_id`
plus the type's fields (`value`, `min`/`max`, `keyboard_max`/`consumer_max`).

Layout units are the Studio/DTS units (1/100 of a key). The UI scales them.

### `POST /api/key`

`{"layer_id": 0, "position": 5, "behavior_id": 123, "param1": 458756, "param2": 0}`
→ `set_layer_binding` + `save_changes`. Response: `{"ok": true, "binding": {…with label…}}`
or `{"ok": false, "error": "SET_LAYER_BINDING_RESP_INVALID_PARAMETERS"}`.

The editor picks `behavior_id` from the live behavior list and builds params from the
behavior's metadata, exactly like ZMK Studio. This is what makes `&mt`, `&lt`, `&bt`,
`lt_to_layer_0`, `rt_macro` etc. all assignable without host-side special cases.

### `POST /api/layer/rename` `{"layer_id", "name"}` · `/add` `{}` · `/remove` `{"index"}` · `/move` `{"start", "dest"}` · `/restore` `{"layer_id", "at_index"}`

Thin wrappers over `KeymapClient` methods; each followed by `save`. Response `{ok, error[, index]}`.

### `POST /api/snapshot` → `{"path": "…/keymap-snapshot-YYYYmmdd-HHMMSS.bin", "bytes": n}`

Raw `get_keymap` bytes to file (same as `zmkrt snapshot`).

### `POST /api/reset` → `{"ok": true}`

`core.reset_settings`. The UI requires typing the layer count to confirm. The server
takes a snapshot first.

### `GET /api/backup-log?limit=50` → `{"entries": [ {…jsonl line…}, … ]}` (newest last)

## 5. Label resolution (`labels.py`)

Input: a binding, the behavior table, the layer list, and a reverse keycode map.
Output: `{"text": "…"}` or `{"hold": "…", "tap": "…"}`.

1. Determine each param's semantic from the behavior's first metadata set whose
   description matches (hid_usage → keycode, layer_id → layer name, constant → its name,
   range → number, nil → none).
2. Keycode text: strip the ZMK modifier bits (high byte, `LC/LS/LA/LG/RC/RS/RA/RG`) and
   wrap the base name like the DTS (`LG(TAB)`, `LC(LS(Z))`). Unknown value → hex.
3. Layer text: layer *name* (from the keymap) — falls back to `L<n>`.
4. Well-known display names: `Transparent` → `▽`, `None` → `∅`.
5. Two-param behaviors where both params are meaningful (`Mod-Tap`, `Layer Tap`,
   `lt_to_*`) → `{hold: <param1 text>, tap: <param2 text>}`.
6. Fallback: `<display_name> <param1> <param2>`.

Pretty-printing of long ZMK names (`LEFT_CONTROL` → `LCtrl`, `NUMBER_1` → `1`,
`KP_NUMBER_7` → `KP7`, `SEMICOLON` → `;`) is done in the **frontend** (`prettyKeycode.ts`)
so the server label stays canonical and grep-able.

## 6. Frontend (`cli/ui/`, Vite + React 18 + TypeScript + Tailwind)

Single page, dark theme, keyboard-centric.

- **Top bar**: device name, connection dot, lock badge, `Snapshot` button, `Reset` (red,
  confirm dialog). When LOCKED: yellow banner "SETTING 層の `&studio_unlock` を押して
  unlock してください" and every editing control is disabled.
- **Left sidebar — layers**: list of `index · name`. Click = select. Double-click name =
  inline rename (`/api/layer/rename`, max length from `max_layer_name_length`).
  Drag-and-drop reorder = `/api/layer/move`. `+` = `/api/layer/add`, disabled with tooltip
  "available_layers = 0 (reflash required)" when 0. Trash = `/api/layer/remove` (confirm).
  A collapsible "removed" section lists ids that disappeared since page load and offers
  `restore`.
- **Center — keyboard SVG**: one `<rect>`+`<text>` group per key from `layout.keys`,
  rotated by `r` around `(rx, ry)`, scaled to fit the pane. Label rendering:
  `text` → centered; `hold/tap` → tap large, hold small on top. Transparent keys render
  dim with the **layer-0 label ghosted** underneath (documented simplification: ZMK
  resolves ▽ to the next lower *active* layer, which depends on the active base layer).
  Selected key gets an accent ring. Hover shows raw `behavior_id/param1/param2`.
- **Right panel — key editor**: shows layer/position/current raw binding. Behavior picker
  = searchable list of `behaviors[]` (curated order: Key Press, Transparent, Momentary
  Layer, Layer Tap, Mod-Tap, To Layer, rt_macro, then the rest alphabetically). Below it,
  one param editor per metadata entry: `hid_usage` → keycode search box (from
  `keycodes`) + 8 modifier toggles; `layer_id` → layer dropdown; `range` → number input
  with min/max; `constant` → radio of named constants; `nil` → nothing. `Apply` →
  `POST /api/key` → refetch state. `Set ▽` shortcut button.
- **Bottom drawer — change log**: `/api/backup-log` rendered newest-first (time, op,
  layer/pos, before → after).

State management: one `useState<State>` + `refetch()`; no global store. Errors surface as
a toast. All fetches go through `api.ts` (typed).

Dev workflow: `pnpm dev` (Vite dev server proxies `/api` to `127.0.0.1:8760`, run
`zmkrt ui --no-open` alongside). Build: `pnpm build` → `../zmk_runtime_cli/ui/static/`.

## 7. Safety (per repo convention: every "change" ships with its "undo")

- Server start: automatic keymap snapshot to `keymap-snapshot-<ts>.bin` (logged).
- Every mutating endpoint records `before` (current binding / layer list) in
  `.zmkrt-backup.jsonl` via the shared `backup.py`.
- Reset is behind a typed confirmation and takes a snapshot first.
- LOCKED state disables all edits client-side; the server also rejects mutations with
  HTTP 423 when the last known lock state is LOCKED.
- Nothing is cached across restarts; every start re-reads the device.

## 8. Packaging

- `pyproject.toml`: `[tool.setuptools.package-data] zmk_runtime_cli = ["ui/static/**/*"]`,
  no new runtime dependencies. `zmkrt ui` is a subparser in `cli.py` calling
  `zmk_runtime_cli.ui.server.serve(...)`.
- `cli/ui/static` build output **is committed** so `pipx install .` works without node.
  `cli/ui/README.md` documents `pnpm install && pnpm build`.
- Node version pinned via `cli/ui/.node-version` (24) for mise.

## 9. Testing

- **pytest** (`cli/tests/test_ui_*.py`): request builders/decoders in `native_client.py`;
  `labels.py` table-driven cases (kp / modified kp / mt / lt / trans / none / rt_macro /
  unknown behavior / unknown keycode); `state.build_state` against `_FakeSerial`
  frames (keymap + layouts + behaviors); HTTP handler round-trips using `http.client`
  against a `DeviceSession` stub (state, key set ok/err, lock 423, backup log).
- **vitest** (`cli/ui`): `prettyKeycode`, layout geometry (rotation/bounds), label
  component selection.
- **HIL acceptance** (real roBa over USB, run by the implementer on this Mac):
  1. `zmkrt ui` opens the browser; keyboard renders 44 keys in roBa shape; 12 layers
     listed with names.
  2. Select `DEFAULT` pos 0 (Q): change to `Key Press W` → device types `w`; change log
     shows the entry; set back to `Q` → types `q`.
  3. Rename a layer and rename it back.
  4. LOCKED banner appears after pressing the physical lock (or after power-cycle) and
     editing is disabled until `&studio_unlock`.
  5. `Snapshot` writes a file; `Reset` is NOT exercised on the user's device (documented
     manual step only).

## 10. Sub-project 2 (outline, for API shape compatibility)

`/api/macro`, `/api/holdtap`, `/api/condlayer`, `/api/combo`, `/api/encoder`,
`/api/trackball` — each `GET` (list) + `POST` (set/reset), mirroring the CLI verbs and
built on the existing clients via `_ser=session.serial` under the session lock. UI adds a
tabbed side panel per feature; combos and hold-taps are also overlaid on the keyboard
(combo key-positions highlighted on hover).
