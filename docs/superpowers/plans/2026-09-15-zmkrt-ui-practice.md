# zmkrt ui 練習モード Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live key / layer / keycode monitor streamed from the firmware to the browser, shown as a 練習モード on the board.

**Architecture:** New `zmk__monitor` custom RPC subsystem (C + proto) → `MonitorClient` + a serial multiplexer thread in `DeviceSession` → `GET /api/events` SSE → `practice.ts` reducer + board overlay.

**Tech Stack:** ZMK C (cormoran fork), nanopb, Python stdlib + protobuf 7.35.1, React 18 + TS + vitest.

**Spec:** `docs/superpowers/specs/2026-09-15-zmkrt-ui-practice-design.md` (roBa repo). Read it fully first.

## Global Constraints

- Module repo worktree; firmware cannot be compiled locally — minimal, self-reviewed C, copied from the proven patterns (`src/studio/holdtap_rpc_handler.c` for the handler, cormoran `input_processor_listener.c` for the notification encoder). The main session builds via roBa CI and flashes.
- pytest (232) and vitest (227+) stay green at every commit; `pnpm build` output committed at the end.
- Existing clients (`rpc.send_recv`, `RipClient._list_processors`) must not change; the mux must be transparent to them (tests prove it).
- The user's viewer (API 8760 on the main checkout + Vite 5173) stays up; use a worktree Vite on 5174. Server-side behaviour that needs the real device is verified against **old firmware** only for the `unavailable` path; do not change device values; never `/api/reset`.
- Commit per task with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; push once at the end (`git rebase main` first).

---

### Task 1: Firmware — `zmk__monitor` subsystem

**Files:** create `proto/zmk/monitor/monitor.proto` (spec §3 verbatim), `src/studio/monitor_rpc_handler.c`, `src/studio/monitor_listener.c`, `include/zmk/runtime_monitor.h`; modify `Kconfig`, `CMakeLists.txt`.

- [ ] `include/zmk/runtime_monitor.h`: `bool rt_monitor_enabled(void); void rt_monitor_set(bool on);` (a static bool in the handler file, exported through these).
- [ ] Handler (`monitor_rpc_handler.c`), modelled on `holdtap_rpc_handler.c`: `ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__monitor, &meta, handler)`, `ZMK_RPC_CUSTOM_SUBSYSTEM_RESPONSE_BUFFER(zmk__monitor, zmk_monitor_Response)`; `get_layers` → `layers.mask = zmk_keymap_layer_state(); layers.highest = zmk_keymap_highest_layer_active();`; `enable`/`disable` → set flag, `ok.ok = true`. Security `ZMK_STUDIO_RPC_HANDLER_UNSECURED`. Includes: `<zmk/keymap.h>`.
- [ ] Listener (`monitor_listener.c`): copy the `encode_notification` + `find_subsystem_index` helpers from cormoran's listener (generic over `zmk_monitor_Notification_fields`), three listeners:
  - `zmk_position_state_changed` → `key{position, pressed=state, source}`
  - `zmk_layer_state_changed` → `layers{mask=zmk_keymap_layer_state(), highest=zmk_keymap_highest_layer_active()}` (read *after* the event, i.e. in the listener the state is already updated — ZMK raises the event after changing the mask; if unsure, read it anyway: the next event corrects it)
  - `zmk_keycode_state_changed` → `keycode{usage_page, keycode, pressed=state, modifiers=implicit|explicit}`
  Each returns `ZMK_EV_EVENT_BUBBLE` and does nothing unless `rt_monitor_enabled()`. Includes: `<zmk/events/position_state_changed.h>`, `<zmk/events/layer_state_changed.h>`, `<zmk/events/keycode_state_changed.h>`, `<zmk/keymap.h>`, `<zmk/studio/custom.h>`, `<pb_encode.h>`, `<zmk/monitor/monitor.pb.h>`.
- [ ] Kconfig: inside the menu add `config ZMK_RUNTIME_MONITOR  bool "Live key/layer monitor over Studio RPC (zmk__monitor)"  depends on ZMK_STUDIO  default y`.
- [ ] CMake: `if(CONFIG_ZMK_RUNTIME_MONITOR) zephyr_include_directories(include); target_sources(app PRIVATE src/studio/monitor_rpc_handler.c src/studio/monitor_listener.c) endif()` and add `OR CONFIG_ZMK_RUNTIME_MONITOR` to the nanopb condition (the proto glob already picks the file up).
- [ ] Self-review (includes, every symbol exists in the cormoran fork — check with `curl` on raw.githubusercontent.com as the earlier tasks did), commit.

### Task 2: CLI — `monitor_client.py` + pb2

- [ ] Generate `cli/zmk_runtime_cli/proto/zmk/monitor/monitor_pb2.py` with grpcio-tools (`-I ../proto --python_out=zmk_runtime_cli/proto zmk/monitor/monitor.proto`, descriptor name `zmk/monitor/monitor.proto`; add `__init__.py`).
- [ ] `monitor_client.py`: same skeleton as `holdtap_client.py` (`_resolve_index` for `zmk__monitor`, `_call`), methods `enable()`, `disable()`, `get_layers()`, module-level `decode_notification(payload) -> dict` and `layer_ids(mask) -> list[int]`.
- [ ] Tests `tests/test_monitor.py`: request builders (`WhichOneof`), `decode_notification` for the three types, `layer_ids(0b101) == [0, 2]`, `_resolve_index` against `_subsystems("zmk__monitor")` frames (reuse helpers from `test_ui_features.py`), and a missing-subsystem error.
- [ ] Commit.

### Task 3: `MuxSerial`

- [ ] `cli/zmk_runtime_cli/ui/mux_serial.py`: class per spec §4.2 (`__init__(real, timeout)`, `write`, `flush`, `read(n)`, `subscribe()`, `unsubscribe(q)`, `set_monitor_index(i)`, `close()`), reader thread started in `__init__`, `stop()` joins it. Use `queue.Queue` for events and a `bytearray` + `threading.Condition` for the byte stream.
- [ ] `DeviceSession.serial` wraps the opened pyserial handle in `MuxSerial`; `on_serial_error` / `close` stop the reader; injected `_ser` (tests) is wrapped too unless it already is a `MuxSerial`. Add `session.monitor_client()` and `session.ensure_monitor_index()` (resolves once, sets on the mux; returns False if unavailable).
- [ ] Tests `tests/test_mux_serial.py`: FakeSerial scripted with `[rip-notification, monitor-notification(key), request_response, monitor-notification(layers)]` → `rpc.send_recv` returns the response; a subscriber sees `[key, layers]`; a raw `read()` loop (like `_list_processors`) sees the rip notification frame bytes intact. Plus: before `set_monitor_index`, monitor frames go to `read()` (not intercepted).
- [ ] Run the *whole* suite (the session now wraps FakeSerial everywhere) — all existing tests must still pass unchanged. Commit.

### Task 4: `GET /api/events`

- [ ] `server.py`: the dispatcher special-cases `("GET", "/api/events")` before the JSON routes: `api_events(handler, session)` writes headers (`Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`), then per spec §4.3. Subscriber bookkeeping (`session.monitor_clients` int + lock). Keep-alive via `queue.get(timeout=15)` → on `Empty` write `: keep-alive\n\n`. Catch `BrokenPipeError`/`ConnectionResetError` → cleanup.
- [ ] Tests `tests/test_ui_events.py`: stub session with a scripted mux (a fake `subscribe()` queue you feed) → the HTTP client reads the first two events (`layers` then `key`) and closes; assert `enable` was called once and `disable` after disconnect; unavailable path sends `event: unavailable`.
- [ ] Commit.

### Task 5: Frontend

- [ ] `api.ts`: `openEvents(onEvent, onUnavailable) → () => void` (EventSource wrapper, parses `event`/`data`).
- [ ] `src/practice.ts` + `practice.test.ts`: `PracticeState`, `initial()`, `reduce(state, ev)`, `keycodeText(ev, keycodes)` (keyboard page 0x07 → `page<<16|keycode` lookup in the reverse table like the server; consumer 0x0C likewise; modifiers bitmask → `LC…RG` wrappers; unknown → `0x…`), `activeLayerNames(state, layers)`.
- [ ] `App.tsx`: `practice` boolean + state; TopBar toggle + `P` key; on start: close inspector, subscribe; on `layers`: set `layerIdx` to `highest` unless the user overrode since the last event; on stop: unsubscribe and reset.
- [ ] `Keyboard.tsx`: `pressed?: Set<number>` → cap styling per spec §5 (`transition: fill 120ms` only when not pressed).
- [ ] `LayerChips.tsx`: `activeIds?: Set<number>` → small green dot on active rows.
- [ ] `components/PracticeStrip.tsx` per spec §5; rendered above the board when practice is on (LayerEntry banner hidden meanwhile).
- [ ] Toast on `unavailable`. Screenshots with the strip visible (old firmware: the strip shows, then the unavailable toast — capture both).
- [ ] `pnpm build`, commit static. README: a short 練習モード paragraph + the `ZMK_RUNTIME_MONITOR` Kconfig note in `docs/INSTALL.md`.

### Task 6: Report

Commits, test counts, screenshots, the exact module SHA for the firmware build, and any deviation. HIL against the new firmware is done by the main session after the reflash.
