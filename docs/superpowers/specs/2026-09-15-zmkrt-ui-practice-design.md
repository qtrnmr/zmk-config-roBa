# zmkrt ui — 練習モード (live key / layer monitor)

Date: 2026-09-15
Status: approved in chat (option A: firmware event stream)
Builds on: `2026-09-13-zmkrt-ui-v2-design.md` and everything on module main up to `a6cf357`.

## 1. Goal

A "練習モード" in `zmkrt ui`: while it is on, the board shows in real time which physical keys
are pressed, which layers are active (the displayed layer follows the highest active one), and
what the keyboard is sending (letters, modifiers, media keys). It works for keys that produce no
HID output (`&mo`, `&lt` holds, BT keys) because the data comes from the firmware, not from the
browser.

## 2. Non-goals

- No recording / replay, no typing-speed test, no per-key statistics.
- No BLE. USB serial only, like the rest of the UI.
- The mode does not change any device setting.

## 3. Firmware (module `zmk-module-runtime-config`)

New custom Studio RPC subsystem **`zmk__monitor`**, Kconfig `ZMK_RUNTIME_MONITOR` (`depends on
ZMK_STUDIO`, `default y` inside the module's menu; `ZMK_RUNTIME_MONITOR_STUDIO_RPC` not needed, the
subsystem *is* the feature). Sources `src/studio/monitor_rpc_handler.c` (request handler) and
`src/studio/monitor_listener.c` (event listeners), added to `CMakeLists.txt` under the new config and
to the nanopb condition.

`proto/zmk/monitor/monitor.proto`:

```proto
syntax = "proto3";
package zmk.monitor;

message Empty {}
message OkResponse { bool ok = 1; }

message LayerState {
    uint32 mask    = 1; // zmk_keymap_layer_state(): bit per layer *id*
    uint32 highest = 2; // zmk_keymap_highest_layer_active(): layer *index*
}
message KeyEvent {
    uint32 position = 1;
    bool   pressed  = 2;
    uint32 source   = 3; // ZMK_POSITION_STATE_CHANGE_SOURCE_LOCAL (255) = this half, else peripheral index
}
message KeycodeEvent {
    uint32 usage_page = 1; // 0x07 keyboard, 0x0C consumer
    uint32 keycode    = 2;
    bool   pressed    = 3;
    uint32 modifiers  = 4; // implicit | explicit, ZMK HID modifier bitmask
}

message Notification {
    oneof type {
        KeyEvent     key     = 1;
        LayerState   layers  = 2;
        KeycodeEvent keycode = 3;
    }
}

message Request {
    oneof request_type {
        Empty get_layers = 1;
        Empty enable     = 2;
        Empty disable    = 3;
    }
}
message Response {
    oneof response_type {
        LayerState layers = 1;
        OkResponse ok     = 2;
    }
}
```

- `enable` / `disable` flip a static `bool monitoring` (default false) so an idle keyboard never
  streams. `get_layers` answers the current state.
- Listeners (`ZMK_LISTENER` + `ZMK_SUBSCRIPTION`) on `zmk_position_state_changed`,
  `zmk_layer_state_changed` and `zmk_keycode_state_changed`; when `monitoring`, each raises one
  `zmk_studio_custom_notification` exactly like cormoran's
  `input_processor_listener.c` (encode callback + `find_subsystem_index("zmk__monitor")`).
  `layers` notifications carry the *whole* state (mask + highest), not the delta.
- Runs on the central (right half); peripheral positions arrive there through the split
  transport with `source` set, so the left half needs no change.

## 4. CLI / server (module `cli/`)

### 4.1 `monitor_client.py`

`MonitorClient(_ser=…)` with `enable()`, `disable()`, `get_layers() → {"mask", "highest"}`, the
usual `_resolve_index()` (subsystem `zmk__monitor`), and a pure
`decode_notification(payload: bytes) → dict` returning
`{"type": "key", "position", "pressed", "source"}` /
`{"type": "layers", "mask", "highest", "ids": [..]}` /
`{"type": "keycode", "usage_page", "keycode", "pressed", "modifiers"}`.

### 4.2 `DeviceSession` gains a reader thread (`ui/session.py`)

Today every client reads the serial handle directly and `rpc.send_recv` discards notification
frames while waiting. To stream notifications *and* keep every existing client untouched, the
session's `serial` property returns a **`MuxSerial`** wrapper (new `ui/mux_serial.py`):

- One daemon reader thread reads the real port (`timeout=0.1`), splits frames with
  `rpc._extract_frame`, parses each as `studio_pb2.Response`.
- Frames that are a `notification.custom.custom_notification` whose `subsystem_index ==
  monitor_index` are decoded with `monitor_client.decode_notification` and pushed to every
  subscriber queue (`subscribe() → queue.Queue`, `unsubscribe(q)`). `monitor_index` is set by the
  session once (`MonitorClient._resolve_index()`); until then (or if the subsystem does not exist)
  nothing is intercepted.
- **Every other frame** (request_response, core/keymap notifications, other custom notifications
  such as `cormoran_rip`) is put back, *as the original frame bytes*, into a byte queue that the
  wrapper's `read(n)` drains — so `rpc.send_recv` and `RipClient._list_processors` see exactly
  what they see today. `write()` / `flush()` pass through. `read()` blocks up to the port timeout
  and returns `b""` on nothing, like pyserial.
- Serial errors in the reader set `session.on_serial_error()` semantics (drop + reopen on next
  access); the thread exits and a new one starts with the next handle.
- Tests: a `FakeSerial` scripted with an interleaving of response and monitor-notification frames
  proves (a) `send_recv` gets its response, (b) subscribers get the decoded events in order,
  (c) a `cormoran_rip` notification still reaches `read()`.

### 4.3 Routes

- `GET /api/events` → **Server-Sent Events** (`text/event-stream`, no session lock held while
  streaming). On connect: `with session:` → `MonitorClient.enable()` when this is the first
  subscriber, then `get_layers()`; first event is `event: layers`. Then forward subscriber-queue
  items as `event: key|layers|keycode` with JSON `data`. A `: keep-alive` comment every 15 s.
  On disconnect (client closed / write error): unsubscribe; if no subscribers remain,
  `disable()` under the lock. If the subsystem is missing, respond with one
  `event: unavailable` (`data: {"error": "..."}`) and close.
- `GET /api/state` unchanged. A subscriber count is exposed as `"monitor": {"clients": n}` in
  `/api/state`? — no; keep state unchanged (YAGNI).

## 5. Frontend

- **Toggle**: a `練習モード` button in the TopBar (right of 再読込), also `P` shortcut when nothing
  is focused. On: `new EventSource("/api/events")`; off: close.
- **`src/practice.ts`** (pure, vitest): `reduce(state, event)` keeping `{ pressed: Set<pos>,
  layerMask, highest, log: Entry[] (last 30), output: string[] (current chord as texts) }`;
  `keycodeText(event, keycodes)` maps a `KeycodeEvent` to the same names the board uses
  (`rev` of `state.keycodes` for the encoded `page<<16 | keycode` … reuse `keycode_text` logic:
  implement in TS the same way `labels.keycode_text` does, modifiers from the bitmask →
  `LC/LS/LA/LG/RC/RS/RA/RG`).
- **Board**: `pressed: Set<number>` prop → pressed caps get `fill emerald-500/35`, stroke
  `emerald-400`, no transition on press, 120 ms fade on release. The displayed layer **follows
  `highest`** while practice is on (the layer card shows every active layer with a small green
  dot, the highest one selected); when the user clicks a layer manually during practice, follow
  is paused until the next `layers` event.
- **Strip** (`components/PracticeStrip.tsx`) above the board (in place of / next to the
  LayerEntry banner): left = `出力:` the chord currently held as chips (e.g. `Shift` `Z` → and the
  resulting text `Z`), middle = `レイヤー: DEFAULT + SETTING` (active names, highest bold), right =
  a scrolling one-line log of the last events (`英数↓ → SETTING` / `Q↓` / `Q↑`), plus a
  `クリア`. Encoder rotation shows as `↻ Vol-` in the output when the keycode event arrives.
- While practice is on, editing stays possible (the mode is read-only), but the inspector is
  closed when the mode starts so the board has the width.
- `unavailable` event → toast "このファームには練習モード (zmk__monitor) がありません。焼き直しが必要です"
  and the toggle turns off.

## 6. Safety

Read-only. `enable`/`disable` is the only device call and only toggles a flag in RAM.

## 7. Testing

- pytest: `monitor_client` decode + request builders; `MuxSerial` routing (4.2); `/api/events`
  with a stub session (first event is layers; unavailable path; disable on last disconnect).
- vitest: `practice.reduce` (press/release/layers/log cap), `keycodeText` (keyboard + consumer +
  modifiers).
- HIL (main session, after the right half is reflashed): press Q → highlight + log; hold 英数 →
  layer follows to SETTING; rotate the encoder → `↻`/`↺` output; release all → clean state;
  turn the mode off → `disable` sent (verify with a second `GET /api/state` still working).
