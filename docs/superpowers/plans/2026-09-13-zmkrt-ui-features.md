# zmkrt ui feature panels (Sub-project 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six editable panels (macros, hold-tap, conditional layers, combos, encoder, trackball) to `zmkrt ui`, on top of the Sub-project 1 server and React app, reusing the existing feature clients over the shared serial session.

**Architecture:** `GET /api/features` assembles all six feature states in one document (each feature independently reports `available: false` when its custom subsystem is missing). Mutations are thin routes over the existing `MacroClient` / `HoldtapClient` / `CondlayerClient` / `CombosClient` / `EncoderClient` / `RipClient`, constructed with `_ser=session.serial` under the session lock, with the same validate → lock-check → backup → RPC pattern as Sub-project 1. The frontend gains a tab bar, a `BindingForm` extracted from `KeyEditor`, and one panel component per feature.

**Tech Stack:** unchanged (Python stdlib http.server + pyserial + protobuf; Vite 6 / React 18 / TS / Tailwind v4 / vitest; pnpm, node 24 via mise).

**Spec:** `/Volumes/Storage/ghq/github.com/qtrnmr/zmk-config-roBa/docs/superpowers/specs/2026-09-13-zmkrt-ui-features-design.md` (read it first; also skim the Sub-project 1 spec `2026-09-13-zmkrt-ui-design.md` and the shipped code under `cli/zmk_runtime_cli/ui/` and `cli/ui/src/`).

## Global Constraints

- Repo: `/Volumes/Storage/ghq/github.com/qtrnmr/zmk-module-runtime-config/cli/` (module repo, worktree branch made by `hw`). Package `zmk_runtime_cli`, command `zmkrt`. Recreate the venv in the worktree: `cd cli && python3 -m venv .venv && .venv/bin/pip install -e . pytest protobuf==7.35.1` (zmk-studio-api 0.3.1 from PyPI does not pull protobuf; the main checkout's venv has the same versions if PyPI fails).
- **Existing suite: 144 pytest + 8 vitest must stay green at every commit.** `pnpm build` output in `zmk_runtime_cli/ui/static/` is committed with every frontend task.
- No new Python runtime deps. One serial handle (`DeviceSession`); never `connection.open()` from `ui/`.
- Every mutation: validate body → `with session:` → `require_unlocked(session)` → `append_backup({...before...})` → RPC. Reuse `server._int`, `HttpError`, `require_unlocked`. Add helper `_bool`, `_list_int`, `_str_opt` as needed (defined in Task 3).
- Do not change the wire behaviour of existing CLI commands (add methods; do not alter existing signatures).
- roBa HIL facts: 8 macro slots (`CONFIG_ZMK_RUNTIME_MACRO_SLOTS=8`), 3 hold-tap slots, 3 conditional-layer entries, 6 combos, 1 encoder sensor with a `zmk,behavior-runtime-sensor-rotate` binding, 1 trackball processor (id 0). Layer names on the device: `DEFAULT APPLE ANDROID FUNCTION NUM ARROW MOUSE SCROLL SETTING APPLE_MOUSE ANDROID_MOUSE ANDROID_ARROW` (runtime-named on 2026-09-13). `CONFIG_ZMK_STUDIO_LOCKING=n` (always UNLOCKED). **Never call `/api/reset` on the device.** Leave every feature exactly as found after HIL (record before-values first).
- The UI server holds the port; never run other `zmkrt` commands while it is up.
- Commit trailer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Push `origin HEAD:main` (after `git rebase main`) only at the end (Task 9).
- Frontend rules unchanged: no UI kit / state lib / DnD lib; `min-w-0` on grid children; Japanese UI copy consistent with Sub-project 1.

## File Structure

```
cli/zmk_runtime_cli/
  combos_client.py            + set_binding(index, behavior_id, p1, p2) -> dict
  encoder_client.py           + set_raw(sensor, layer, direction, behavior_id, p1, p2, tap_ms) -> dict
  rip_client.py               + FIELD_UI (list[dict]) derived from FIELD_SPECS + info key map
  ui/session.py               + macro_client() holdtap_client() condlayer_client() combos_client() encoder_client() rip_client()
  ui/features.py              NEW: collect_* per feature + build_features(session)
  ui/server.py                + 13 routes; ROUTES entries
cli/ui/src/
  types.ts                    + Features types
  api.ts                      + getFeatures, macroParse, macroSet, holdtapSet/Reset, condlayerSet/Reset, comboSet/Reset, encoderSet/Reset, trackballSet/Reset
  macroFormat.ts              NEW: stepPreview(steps, keycodes) ; stepsToDsl not needed
  components/BindingForm.tsx  NEW (extracted from KeyEditor)
  components/KeyEditor.tsx    uses BindingForm
  components/Keyboard.tsx     + highlight?: number[] prop
  components/TopBar.tsx       + tab bar props
  components/ChangeLog.tsx    + summaries for new ops
  panels/MacroPanel.tsx HoldtapPanel.tsx CondlayerPanel.tsx ComboPanel.tsx EncoderPanel.tsx TrackballPanel.tsx  NEW
  App.tsx                     tab state + features fetch + panel switch
cli/tests/
  test_ui_features.py test_ui_server_features.py test_client_additions.py
cli/ui/src/macroFormat.test.ts
```

---

### Task 1: Client additions — `CombosClient.set_binding`, `EncoderClient.set_raw`, `rip_client.FIELD_UI`

**Files:** Modify `zmk_runtime_cli/combos_client.py` (class `CombosClient`, after `set`), `zmk_runtime_cli/encoder_client.py` (class `EncoderClient`, after `set`), `zmk_runtime_cli/rip_client.py` (after `FIELD_SPECS`). Test: `tests/test_client_additions.py`.

**Interfaces (produced):**
- `CombosClient.set_binding(self, index: int, behavior_id: int, p1: int, p2: int) -> dict` → `decode_response(self._call(build_set_request(index, "binding", None, behavior_id=behavior_id, p1=p1, p2=p2)))`
- `EncoderClient.set_raw(self, sensor: int, layer: int, direction: str, behavior_id: int, p1: int, p2: int, tap_ms: int) -> dict` → `decode_response(self._call(build_set_request(direction, sensor, layer, behavior_id, p1, p2, tap_ms)))`
- `rip_client.FIELD_UI: list[dict]` — one entry per `FIELD_SPECS` key, in this order and with these `kind`/`info_key` values:

```python
FIELD_UI = [
    {"name": "scale-multiplier", "kind": "int", "info_key": "scale_multiplier"},
    {"name": "scale-divisor", "kind": "int", "info_key": "scale_divisor"},
    {"name": "rotation", "kind": "int", "info_key": "rotation_degrees"},
    {"name": "x-invert", "kind": "bool", "info_key": "x_invert"},
    {"name": "y-invert", "kind": "bool", "info_key": "y_invert"},
    {"name": "xy-swap", "kind": "bool", "info_key": "xy_swap_enabled"},
    {"name": "xy-to-scroll", "kind": "bool", "info_key": "xy_to_scroll_enabled"},
    {"name": "axis-snap-mode", "kind": "enum", "options": ["none", "x", "y"], "info_key": "axis_snap_mode"},
    {"name": "axis-snap-threshold", "kind": "int", "info_key": "axis_snap_threshold"},
    {"name": "axis-snap-timeout", "kind": "int", "info_key": "axis_snap_timeout_ms"},
    {"name": "temp-layer-enabled", "kind": "bool", "info_key": "temp_layer_enabled"},
    {"name": "temp-layer-layer", "kind": "layer", "info_key": "temp_layer_layer"},
    {"name": "temp-layer-activation-delay", "kind": "int", "info_key": "temp_layer_activation_delay_ms"},
    {"name": "temp-layer-deactivation-delay", "kind": "int", "info_key": "temp_layer_deactivation_delay_ms"},
    {"name": "active-layers", "kind": "int", "info_key": "active_layers"},
]
```
  (`axis_snap_mode` in `info_to_dict` is the enum int 0/1/2; the UI maps it through `options`.)

- [ ] **Step 1: Failing tests**

```python
# tests/test_client_additions.py
import zmk_runtime_cli.proto  # noqa: F401
import studio_pb2
from zmk_runtime_cli.framing import encode_frame
from zmk_runtime_cli import combos_client as cc, encoder_client as ec, rip_client as rc
from zmk_runtime_cli.proto.zmk.combos import combos_pb2 as cb_pb2
from zmk_runtime_cli.proto.cormoran.rsr import custom_pb2 as rsr_pb2
from test_ui_native_client import FakeSerial  # scripted serial (one frame per write)


def _custom_frame(payload: bytes) -> bytes:
    s = studio_pb2.Response(); s.request_response.request_id = 1
    s.request_response.custom.call.payload = payload
    return encode_frame(s.SerializeToString())


def test_combos_set_binding_sends_ids_directly():
    ok = cb_pb2.Response(); ok.set.ok = True
    ser = FakeSerial([_custom_frame(ok.SerializeToString())])
    c = cc.CombosClient(_ser=ser); c._subsystem_index = 3   # skip resolve
    assert c.set_binding(2, 8, 458795, 0) == {"ok": True, "error": ""}
    req = studio_pb2.Request(); req.ParseFromString(_decode(ser.written[-1]))
    inner = cb_pb2.Request(); inner.ParseFromString(req.custom.call.payload)
    assert (inner.set.index, inner.set.binding.behavior_id, inner.set.binding.param1) == (2, 8, 458795)


def test_encoder_set_raw():
    ok = rsr_pb2.Response(); ok.set_layer_ccw_binding.success = True
    ser = FakeSerial([_custom_frame(ok.SerializeToString())])
    c = ec.EncoderClient(_ser=ser); c._subsystem_index = 4
    assert c.set_raw(0, 1, "ccw", 7, 65526, 0, 30)["ok"] is True
    req = studio_pb2.Request(); req.ParseFromString(_decode(ser.written[-1]))
    inner = rsr_pb2.Request(); inner.ParseFromString(req.custom.call.payload)
    sub = inner.set_layer_ccw_binding
    assert (sub.sensor_index, sub.layer, sub.binding.behavior_id, sub.binding.param1, sub.binding.tap_ms) == (0, 1, 7, 65526, 30)


def test_field_ui_covers_field_specs():
    assert [f["name"] for f in rc.FIELD_UI] == list(rc.FIELD_SPECS)
    assert all(f["kind"] in ("int", "bool", "enum", "layer") for f in rc.FIELD_UI)
    assert next(f for f in rc.FIELD_UI if f["name"] == "axis-snap-mode")["options"] == ["none", "x", "y"]


def _decode(frame: bytes) -> bytes:
    from zmk_runtime_cli.framing import decode_frame
    return decode_frame(frame)
```
Check how `CombosClient`/`EncoderClient` cache the subsystem index (attribute name) and adapt `_subsystem_index` accordingly; the `_resolve_index` must not be called when the cache is set.

- [ ] **Step 2: Run → FAIL. Step 3: implement the three additions. Step 4: full suite green (147). Step 5: commit** `feat(cli): id-direct combo/encoder setters and trackball field UI table`.

---

### Task 2: `session.py` factories + `features.py` (`/api/features` document)

**Files:** Modify `zmk_runtime_cli/ui/session.py`; create `zmk_runtime_cli/ui/features.py`; test `tests/test_ui_features.py`.

**Interfaces:**
- `DeviceSession.macro_client() -> MacroClient(_ser=self.serial)`, likewise `holdtap_client()`, `condlayer_client()`, `combos_client()`, `encoder_client()`, `rip_client()` (`RipClient(_ser=...)` — check its `__init__` signature accepts `_ser`; it does per the CLI source, `rip_client.py:101`).
- `features.MACRO_SLOTS_PROBE = 64` — macros: probe slots 0.. until `get_macro` raises or returns an error; **but** the firmware may return empty steps for slots ≥ configured count without error, so cap by `count_macro_slots(client)`: try `get_macro(slot)` for slot in range(64) and stop at the first exception; on roBa expect exactly 8. Record the probe result once per session (`session.macro_slot_count` cache).
- `features.collect_macros(session) -> dict`, `collect_holdtaps`, `collect_condlayers`, `collect_combos`, `collect_encoder`, `collect_trackball` — each returns the spec §4 shape, or `{"available": False, "error": str(exc)}` on any exception (RuntimeError from subsystem resolution, TimeoutError, RpcError).
- `features.build_features(session, layers_by_index: dict[int,str], behaviors: list[dict], rev: dict[int,str]) -> dict` and a convenience `features.build_features_doc(session)` that gathers layers/behaviors/rev the way `state.build_state` does (reuse `session.behaviors()`, `state.reverse_keycodes(state.keycode_table())`, `session.keymap_client().get_layers()`).
- Labels: macro steps get `"label": labels.keycode_text(keycode, rev)`; combo `binding` and encoder `cw`/`ccw` get `"label": labels.label_for(binding, behavior_by_id.get(id), layers_by_index, rev)`.

- [ ] **Step 1: Failing tests** — build scripted frames for: (a) a macros collect of a 2-slot device (slot 2 raises → count 2), (b) holdtaps count=1 + get, (c) condlayers count=1 + get, (d) combos count=1 + get with a Key Press binding → label text, (e) encoder sensors + get_all_layer_bindings, (f) trackball via the notification path (`RipClient._list_processors` reads *notification* frames: build one `studio_pb2.Response` with `notification.custom.custom_notification.payload = rip Notification(input_processor_changed)`; FakeSerial then returns `b""` so the drain condition ends the read), (g) an unavailable subsystem: `list_custom_subsystems` response without `zmk__holdtap` → `collect_holdtaps` returns `{"available": False, "error": ...}` containing `zmk__holdtap`. Use `from test_ui_native_client import FakeSerial`. Each collector test constructs `DeviceSession(_ser=FakeSerial(frames))` and pre-sets nothing else. Note the custom-subsystem clients each send `list_custom_subsystems` first (request_id 1) — include that frame first in every script: build `custom_pb2.ListCustomSubsystemResponse` with the needed `identifier`/`index` entries.
- [ ] **Step 2: Run → FAIL. Step 3: implement** `features.py`:

```python
"""Assemble the /api/features document (macros, hold-tap, condlayers, combos, encoder, trackball)."""
from __future__ import annotations

from .. import macro_dsl, rip_client
from ..holdtap_client import FLAVORS
from . import labels, state


def _unavailable(exc: Exception) -> dict:
    return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def count_macro_slots(client, probe: int = 64) -> int:
    n = 0
    for slot in range(probe):
        try:
            client.get_macro(slot)
        except Exception:  # noqa: BLE001  first failing slot ends the range
            break
        n += 1
    return n


def collect_macros(session, rev) -> dict:
    try:
        c = session.macro_client()
        if getattr(session, "macro_slot_count", None) is None:
            session.macro_slot_count = count_macro_slots(c)
        slots = []
        for slot in range(session.macro_slot_count):
            steps = c.get_macro(slot)
            for s in steps:
                s["label"] = labels.keycode_text(s["keycode"], rev)
            slots.append({"slot": slot, "steps": steps})
        return {"available": True, "max_steps": macro_dsl.MAX_STEPS, "slots": slots}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def collect_holdtaps(session) -> dict:
    try:
        return {"available": True, "flavors": list(FLAVORS), "slots": session.holdtap_client().list()}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def collect_condlayers(session) -> dict:
    try:
        return {"available": True, "entries": session.condlayer_client().list()}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def collect_combos(session, by_id, layers_by_index, rev) -> dict:
    try:
        entries = []
        for r in session.combos_client().list():
            info = r["info"]
            b = info["binding"]
            b["label"] = labels.label_for({"pos": -1, **b}, by_id.get(b["behavior_id"]), layers_by_index, rev)
            entries.append(info)
        return {"available": True, "entries": entries}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def collect_encoder(session, by_id, layers_by_index, rev) -> dict:
    try:
        c = session.encoder_client()
        sensors = c.sensors().get("sensors", [])
        bindings = []
        for s in sensors:
            got = c.get(s["index"])
            layers = got.get("bindings", [])
            for lb in layers:
                for d in ("cw", "ccw"):
                    b = lb[d]
                    b["label"] = labels.label_for({"pos": -1, **b}, by_id.get(b["behavior_id"]), layers_by_index, rev)
            bindings.append({"sensor": s["index"], "layers": layers})
        return {"available": True, "sensors": sensors, "bindings": bindings}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def collect_trackball(session) -> dict:
    try:
        procs = session.rip_client().list().get("processors", [])
        return {"available": True, "processors": procs, "fields": rip_client.FIELD_UI}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def build_features(session, layers_by_index, behaviors, rev) -> dict:
    by_id = {b["id"]: b for b in behaviors}
    with session:
        return {
            "macros": collect_macros(session, rev),
            "holdtaps": collect_holdtaps(session),
            "condlayers": collect_condlayers(session),
            "combos": collect_combos(session, by_id, layers_by_index, rev),
            "encoder": collect_encoder(session, by_id, layers_by_index, rev),
            "trackball": collect_trackball(session),
        }


def build_features_doc(session) -> dict:
    with session:
        layers_by_index = {l["index"]: l["name"] for l in session.keymap_client().get_layers()}
        behaviors = session.behaviors()
    rev = state.reverse_keycodes(state.keycode_table())
    return build_features(session, layers_by_index, behaviors, rev)
```
`label_for` requires `pos` in the binding dict only for the unknown-behavior fallback text; passing `-1` is fine (check `labels.label_for` and adjust if it indexes `pos`).

- [ ] **Step 4: tests pass; full suite green. Step 5: commit** `feat(ui): /api/features collectors over shared session`.

---

### Task 3: Server routes for the six features

**Files:** Modify `zmk_runtime_cli/ui/server.py`; test `tests/test_ui_server_features.py` (extend the `StubSession` pattern from `tests/test_ui_server.py` with stub feature clients recording calls).

**Interfaces (routes):** exactly the table in spec §4. Helpers added to `server.py`:

```python
def _bool(body, key):  v = body.get(key); if not isinstance(v, bool): raise HttpError(400, f"'{key}' must be a boolean"); return v
def _list_int(body, key): v = body.get(key); if not isinstance(v, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v): raise HttpError(400, f"'{key}' must be a list of integers"); return v
def _choice(body, key, choices): v = body.get(key); if v not in choices: raise HttpError(400, f"'{key}' must be one of {sorted(choices)}"); return v
```

Route sketches (all follow this shape; write each one out fully):

```python
def api_features(session, _):
    return 200, build_features_doc(session)


def api_macro_parse(_, body):
    dsl = body.get("dsl"); allow = bool(body.get("allow_unbalanced", False))
    if not isinstance(dsl, str): raise HttpError(400, "'dsl' must be a string")
    try:
        return 200, {"ok": True, "steps": macro_dsl.parse(dsl, allow_unbalanced=allow)}
    except ValueError as e:
        return 200, {"ok": False, "error": str(e)}


def _validate_steps(steps) -> list[dict]:
    if not isinstance(steps, list) or len(steps) > macro_dsl.MAX_STEPS:
        raise HttpError(400, f"'steps' must be a list of at most {macro_dsl.MAX_STEPS}")
    out = []
    for s in steps:
        if not isinstance(s, dict): raise HttpError(400, "each step must be an object")
        t = s.get("type"); kc = s.get("keycode"); w = s.get("wait_ms", 0); tm = s.get("tap_ms", 0)
        if t not in (0, 1, 2) or not all(isinstance(v, int) and v >= 0 for v in (kc, w, tm)):
            raise HttpError(400, "step fields: type in {0,1,2}; keycode/wait_ms/tap_ms non-negative ints")
        out.append({"type": t, "keycode": kc, "wait_ms": w, "tap_ms": tm})
    return out


def _balance_warning(steps) -> str | None:
    open_: dict[int, int] = {}
    for s in steps:
        if s["type"] == macro_dsl.STEP_PRESS: open_[s["keycode"]] = open_.get(s["keycode"], 0) + 1
        elif s["type"] == macro_dsl.STEP_RELEASE:
            if open_.get(s["keycode"], 0) == 0: return f"release of 0x{s['keycode']:X} without press"
            open_[s["keycode"]] -= 1
    left = [k for k, v in open_.items() if v > 0]
    return ("press without release: " + ", ".join(f"0x{k:X}" for k in left)) if left else None


def api_macro_set(session, body):
    slot = _int(body, "slot"); steps = _validate_steps(body.get("steps"))
    with session:
        require_unlocked(session)
        c = session.macro_client()
        try: before = c.get_macro(slot)
        except Exception: before = None  # noqa: BLE001
        append_backup({"op": "ui_macro_set", "slot": slot, "before_steps": before, "new_steps": steps})
        res = c.set_macro(slot, steps)
    return 200, {"ok": bool(res.get("ok")), "error": res.get("error") or "", "warning": _balance_warning(steps)}
```
Hold-tap: `field = _choice(body, "field", set(holdtap_client.SET_FIELDS))`; `value` may be int or str → pass `str(value)`; `before = c.get(slot)`. Reset: `before = c.get(slot)`.
Condlayer: `if_layers = _list_int(body, "if_layers")`, `then_layer = _int(body, "then_layer")`; call `c.set(index, ",".join(map(str, if_layers)), then_layer)`; `before = c.get(index)`.
Combo: `field = _choice(body, "field", {"binding","timeout-ms","require-prior-idle-ms","layers","slow-release"})`; `binding` → `_int` on the nested object's three keys → `c.set_binding(...)`; `layers` → `_list_int` → `c.set(index, "layers", ",".join(...))` (empty list → `c.set(index, "layers", 0)` int mask); `slow-release` → `_bool` → `c.set(index, "slow-release", value)`; ints → `_int`. `before = c.get(index)["info"]`.
Encoder: `direction = _choice(body, "direction", {"cw","ccw"})`, ints for sensor/layer/behavior_id/param1/param2/tap_ms → `c.set_raw(...)`; `before = c.get(sensor)`. Reset: `c.reset(sensor, layer)`.
Trackball: `field = _choice(body, "field", set(rip_client.FIELD_SPECS))`; value bool/int/str → `str(value).lower()` for bools, `str(value)` otherwise → `c.set(field, id, value_str)`; `before = c.get(id).get("processor")`. Reset: `before` same, `c.reset(id)`.

Register in `ROUTES`: `("GET","/api/features")`, `("POST","/api/macro/parse")`, `("POST","/api/macro")`, `("POST","/api/holdtap")`, `("POST","/api/holdtap/reset")`, `("POST","/api/condlayer")`, `("POST","/api/condlayer/reset")`, `("POST","/api/combo")`, `("POST","/api/combo/reset")`, `("POST","/api/encoder")`, `("POST","/api/encoder/reset")`, `("POST","/api/trackball")`, `("POST","/api/trackball/reset")`.

- [ ] **Step 1: Failing tests** covering: features GET returns the stubbed doc (monkeypatch `build_features_doc`); macro parse ok/err; macro set validates (400 on bad step), writes `ui_macro_set` backup with `before_steps`, returns `warning` for an unbalanced press; holdtap set/reset call args and backup; condlayer set joins CSV; combo binding/layers/slow-release/timeout dispatch to the right client method; encoder set_raw args; trackball set stringifies bool as `"true"`/`"false"`; all mutations 423 when locked with no client call; unknown field → 400.
- [ ] **Step 2–5:** FAIL → implement → green → commit `feat(ui): feature routes (macro/holdtap/condlayer/combo/encoder/trackball)`.

---

### Task 4: API-level HIL on roBa (before frontend work)

- [ ] Start `zmkrt ui --no-open` (background), `curl localhost:8760/api/features | python3 -m json.tool | head -150`. Expect all six `available: true`; 8 macro slots; 3 hold-taps; 3 condlayers (`[1,6]→9`, `[2,6]→10`, `[2,5]→11`); 6 combos with `key_positions` `[11,10] [0,1] [9,8] [20,21] [22,23,24] [22,23,24]`; encoder sensor(s) with 12 layer rows; trackball processor 0 with `fields` (15).
- [ ] Round-trips, recording before/after JSON each time: holdtap slot 0 `tapping-term-ms` 200→210→200; condlayer 0 re-set to its own values; combo 0 `timeout-ms` current→+10→current; encoder sensor 0 layer 0 cw re-set to its current `{behavior_id,param1,param2,tap_ms}`; trackball `x-invert` toggle and back; macro: pick the highest slot, save its `before_steps`, set `[{"type":1,"keycode":458756,"wait_ms":50,"tap_ms":0},{"type":2,"keycode":458756,"wait_ms":0,"tap_ms":0}]`, read back, then set `before_steps` again (an empty list is a valid restore).
- [ ] Fix anything that fails (commit `fix(ui): …` with the evidence in the message). Stop the server. Confirm `zmkrt macro get <slot>` / `zmkrt holdtap get 0` from the CLI show the original values.

---

### Task 5: Frontend — tabs, types, api, `BindingForm` extraction, `Keyboard.highlight`

**Files:** Modify `types.ts`, `api.ts`, `App.tsx`, `components/TopBar.tsx`, `components/KeyEditor.tsx`, `components/Keyboard.tsx`; create `components/BindingForm.tsx`, `macroFormat.ts`, `macroFormat.test.ts`.

**Interfaces:**
```ts
// types.ts (add)
export interface MacroStep { type: 0 | 1 | 2; keycode: number; wait_ms: number; tap_ms: number; label?: string }
export interface Unavailable { available: false; error: string }
export type Macros = Unavailable | { available: true; max_steps: number; slots: { slot: number; steps: MacroStep[] }[] }
export type Holdtaps = Unavailable | { available: true; flavors: string[]; slots: { slot: number; tapping_term_ms: number; quick_tap_ms: number; require_prior_idle_ms: number; flavor: string; flavor_index: number; found: boolean }[] }
export type Condlayers = Unavailable | { available: true; entries: { index: number; if_layers: number[]; then_layer: number; found: boolean }[] }
export interface RawBinding { behavior_id: number; param1: number; param2: number; label?: Label }
export type Combos = Unavailable | { available: true; entries: { index: number; key_positions: number[]; binding: RawBinding; timeout_ms: number; require_prior_idle_ms: number; layers: number[]; slow_release: boolean; found: boolean }[] }
export type EncoderBinding = RawBinding & { tap_ms: number }
export type Encoder = Unavailable | { available: true; sensors: { index: number; name: string }[]; bindings: { sensor: number; layers: { layer: number; cw: EncoderBinding; ccw: EncoderBinding }[] }[] }
export interface TrackballField { name: string; kind: "int" | "bool" | "enum" | "layer"; options?: string[]; info_key: string }
export type Trackball = Unavailable | { available: true; processors: Record<string, number | string | boolean>[]; fields: TrackballField[] }
export interface Features { macros: Macros; holdtaps: Holdtaps; condlayers: Condlayers; combos: Combos; encoder: Encoder; trackball: Trackball }
export type Tab = "keymap" | "macro" | "holdtap" | "condlayer" | "combo" | "encoder" | "trackball"
// api.ts (add) — all return OpResult unless noted
getFeatures(): Promise<Features>; macroParse(dsl, allow_unbalanced): Promise<{ok; steps?; error?}>; macroSet(slot, steps): Promise<OpResult & {warning?: string|null}>;
holdtapSet(slot, field, value); holdtapReset(slot); condlayerSet(index, if_layers, then_layer); condlayerReset(index);
comboSet(body: {index; field; value?; binding?}); comboReset(index); encoderSet(body); encoderReset(sensor, layer); trackballSet(id, field, value); trackballReset(id)
// macroFormat.ts
export function stepPreview(steps: MacroStep[]): string   // "GLOBE↓ 80ms · LEFT↓ 120ms · LEFT↑ 40ms · GLOBE↑"; tap → "A", press → "A↓", release → "A↑"; wait appended as " Nms" when > 0; uses pretty(step.label ?? String(keycode)); empty → "(空)"
// BindingForm.tsx
export interface BindingValue { behavior_id: number; param1: number; param2: number }
export default function BindingForm(props: { state: State; value: BindingValue; onChange(v: BindingValue): void; disabled?: boolean })
// Keyboard.tsx: + highlight?: number[]  (keys in the list get an amber ring + fill; independent of `selected`)
// TopBar.tsx: + tab: Tab; onTab(t: Tab): void  (renders 7 tab buttons after the device name)
```
- [ ] Failing vitest for `stepPreview` (3 cases: empty, tap+wait, press/release chord). Implement. Extract `BindingForm` from `KeyEditor` (KeyEditor keeps its slot/pos header, `適用`, `▽ にする`; the behavior select + ParamEditors move to BindingForm; behaviour identical — re-run the Sub-project 1 manual check that changing pos 0 to W and back still works). Add `highlight` to `Keyboard`. Add tabs to `TopBar` and `tab` state in `App` (keymap tab renders the existing grid; other tabs render `<FeaturePanels>` placeholder text until Task 6–8). `App` fetches `getFeatures()` in `refetch` too and keeps `features` state; refetch both after every mutation.
- [ ] `pnpm test`, `pnpm build`, start server, confirm the keymap tab is unchanged in a headless browser (agent-browser) and the tab bar renders. Commit (with `static/`) `feat(ui): tab bar, BindingForm extraction, keyboard highlight, features fetch`.

---

### Task 6: MacroPanel + HoldtapPanel + CondlayerPanel

**Files:** create `panels/MacroPanel.tsx`, `panels/HoldtapPanel.tsx`, `panels/CondlayerPanel.tsx`; wire in `App.tsx`.

Common panel props: `{ state: State; features: Features; disabled: boolean; run(fn, okMsg): Promise<void> }` where `run` is App's existing helper (it toasts, then refetches both state and features).

- [ ] **MacroPanel**: left list of slots with `stepPreview`; right: editable table (`type` select tap/press/release, key via `KeycodePicker` inside a popover/inline row expander, `wait_ms` & `tap_ms` number inputs, row ↑ ↓ ✕, `+ 行を追加` adds `{type:0, keycode: state.keycodes["A"], wait_ms:0, tap_ms:0}`); step count vs `max_steps` shown; `DSL から取込` collapsible textarea + `解析` button → `macroParse` → on ok replace rows, on error show it inline; `適用` → `macroSet` (toast includes `warning` when present); `空にする` → `macroSet(slot, [])` after a confirm dialog.
- [ ] **HoldtapPanel**: table rows per slot; each row: three `<input type=number min=0>` and flavor `<select>` bound to local edited copy; per-row `適用` sends only changed fields sequentially (one `holdtapSet` per changed field) then refetches; `既定に戻す` → `holdtapReset`. Note text: 「slot 番号は devicetree の runtime-hold-tap 定義順です (RPC は behavior 名を返しません)」.
- [ ] **CondlayerPanel**: table `index | if-layers | then-layer`; editing a row shows a checkbox per layer (`layerLabel`) for `if_layers` and a `<select>` for `then_layer`; `適用` → `condlayerSet`; `既定に戻す` → `condlayerReset`.
- [ ] Build, browser HIL (agent-browser): macro slot round-trip through the UI (set 2-step chord on the highest slot, apply, verify preview + device via `/api/features`, restore previous), holdtap 200→210→200 via the UI, condlayer re-apply. Commit (with `static/`) `feat(ui): macro, hold-tap and conditional-layer panels`.

---

### Task 7: ComboPanel + EncoderPanel

- [ ] **ComboPanel**: renders `<Keyboard layout layer={DEFAULT} base={DEFAULT} selected={null} onSelect={() => {}} highlight={hovered?.key_positions ?? []} />` above a table `index | keys | binding label | timeout | prior-idle | layers | slow-release`; hovering/focusing a row sets `hovered`; clicking opens the detail form: `BindingForm` (initial = row binding) + `timeout_ms` / `require_prior_idle_ms` numbers + layer checkboxes + slow-release toggle; `適用` sends one `comboSet` per changed field (binding first) then refetches; `既定に戻す` → `comboReset`. `keys` cell shows positions and the DEFAULT-layer labels of those positions (e.g. `11,10 → S+A`).
- [ ] **EncoderPanel**: sensor `<select>`; table rows per layer with `cw` / `ccw` label cells; clicking a cell opens `BindingForm` + `tap_ms` number; `適用` → `encoderSet`; row `既定に戻す` → `encoderReset(sensor, layer)`.
- [ ] Build, browser HIL: combo 0 timeout ±10 round-trip via UI; hover highlight visible in a screenshot; encoder layer 0 cw re-apply via UI. Commit `feat(ui): combo panel with keyboard highlight, encoder panel`.

---

### Task 8: TrackballPanel + ChangeLog summaries + docs

- [ ] **TrackballPanel**: processor `<select>` (usually one); form generated from `fields`: `int` → number input, `bool` → toggle, `enum` → select of `options` (value = index), `layer` → layer select; each control applies on change/blur via `trackballSet(id, field, value)` (enum sends the option string; bool sends boolean; int sends number) and shows a transient ✓ / error; `既定に戻す` → `ConfirmDialog` listing current values → `trackballReset(id)`.
- [ ] **ChangeLog**: summaries for `ui_macro_set` (`slot N: k steps`), `ui_holdtap_set/reset`, `ui_condlayer_set/reset`, `ui_combo_set/reset`, `ui_encoder_set/reset`, `ui_trackball_set/reset` (`field=value`).
- [ ] Docs: `cli/README.md` Browser UI section lists the tabs; `cli/ui/README.md` mentions panels dir. Build, browser HIL: `x-invert` toggle and back via UI. Commit `feat(ui): trackball panel, change-log summaries, docs`.

---

### Task 9: Final verification, restore check, push

- [ ] `pytest -q` (expect ≥ 144 + new), `pnpm test`, `pnpm build` → `git status` clean.
- [ ] With the server stopped, verify from the CLI that every HIL'd value is back to its original: `zmkrt holdtap get 0`, `zmkrt condlayer list`, `zmkrt combo get 0`, `zmkrt encoder get`, `zmkrt trackball get`, `zmkrt macro get <slot>`; compare with the before-JSON captured in Task 4/6/7/8.
- [ ] `git rebase main && git push origin HEAD:main`. Report: commit range, test counts, per-feature HIL before/after JSON, screenshots (each tab), deviations from spec/plan with reasons, any behaviour where the firmware returned `ok` without applying (as in Sub-project 1's empty-name rename).
