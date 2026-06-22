# W1b: トラックボール/ポインタ設定の runtime 編集 — 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cormoran `zmk-module-runtime-input-processor`（subsystem `cormoran_rip`）を roBa_R で有効化し、`roba trackball get/set/reset` でトラックボールの感度(scale)・回転・invert・scroll・axis-snap・temp-layer・active-layers を焼き直し無しで runtime 編集できるようにする。

**Architecture:** ファーム側は「既存モジュールの有効化」（overlay の include 順序修正＋conf フラグ）。host 側は SP1 の custom 封筒2段（list_custom_subsystems→index→call）と W1a で堅牢化した `rpc.send_recv`（notification＋応答バースト対応済）を再利用し、`cormoran_rip` 用の `rip_client.py`＋`roba trackball` verb を足す。

**Tech Stack:** ZMK (cormoran fork `v0.3-branch+dya`, custom-RPC レイヤは SP1 で実証済み)、Python 3.12 venv、grpc_tools.protoc、pyserial、pytest。

## Global Constraints

- 横断制約「常時 known-good へ即 revert」: known-good = **main `04fabef`＋現在 flash 済みファーム**。W1b は**新ファームの flash を1回伴う**（runtime-input-processor をファームに入れるため。SP1 と同じ。以後 trackball 設定変更は焼き直し不要）。flash 前に「現行 uf2 / `settings_reset.uf2` でいつでも戻せる」ことを担保。各 trackball 設定は `cormoran_rip` の `ResetInputProcessor`（reset-to-defaults）＋ `roba reset`＋電源再投入で revert（実機で revert 経路を確定する）。
- transport は USB serial（`studio-rpc-usb-uart` snippet, 現状維持）。roBa_L 不変。ble-management/settings-rpc/battery-history は**無効のまま**（multi-endpoint link error 回避、W1a と同条件）。
- host 出力は1行 JSON。mutating は変更前状態を `.roba-backup.jsonl` に記録。
- 既存 31 テスト緑を維持。
- proto は `import roba_cli.proto`（sys.path 通し）後に `import studio_pb2`/`import custom_pb2`、rip は `from roba_cli.proto.cormoran.rip import custom_pb2 as rip_pb2`。
- pytest/CLI は `tools/roba-cli` で `.venv/bin/python` 実行。

## ビルド前提（source 確認済み・2026-06-22）

- `dtsi:17` エラーの真因は **include 順序**：`<input/processors/runtime-input-processor.dtsi>` は `INPUT_EV_REL`/`INPUT_REL_*`（Zephyr `<zephyr/dt-bindings/input/input-event-codes.h>`）を使うが、roBa overlay はこの header を include せず dtsi を include していた（commit 5ce16fc で除去）。**dtsi の前に input-event-codes.h を include すれば解消**（ZMK base 非互換ではない）。
- `CONFIG_ZMK_RUNTIME_INPUT_PROCESSOR_STUDIO_RPC=y` は `<zmk/studio/custom.h>`/`ZMK_RPC_CUSTOM_SUBSYSTEM` を要求するが、これは **SP1 のマクロモジュールが同じ base でビルド成功している**＝利用可能。
- node label `mouse_runtime_input_processor`、compatible `zmk,input-processor-runtime`。subsystem id 文字列 `cormoran_rip`。`west.yml` は既に `zmk-module-runtime-input-processor`(remote cormoran, revision main) を配線済み。

---

## File Structure

- Modify `boards/shields/roBa/roBa_R.overlay` — input-event-codes.h を含む include 順序を修正し、dtsi include と `input-processors = <&mouse_runtime_input_processor>` を復活。
- Modify `boards/shields/roBa/roBa_R.conf` — `CONFIG_ZMK_RUNTIME_INPUT_PROCESSOR=y` / `_STUDIO_RPC=y`。
- Create `proto/cormoran/rip/custom.proto` — `cormoran.rip` proto（host 用、firmware とは独立コピー）。
- Create `roba_cli/proto/cormoran/__init__.py`, `roba_cli/proto/cormoran/rip/__init__.py`（空）, 生成物 `roba_cli/proto/cormoran/rip/custom_pb2.py`。
- Create `roba_cli/rip_client.py` — `cormoran_rip` custom 封筒クライアント＋純粋 builder/decoder。
- Modify `roba_cli/cli.py` — `roba trackball get/set/reset`。
- Create `tests/test_rip.py` — 純粋 builder/decoder の単体テスト。
- Modify `tools/roba-cli/README.md`。

---

## Task 1: ファーム有効化（ビルド go/no-go・GATE）

**Files:**
- Modify: `boards/shields/roBa/roBa_R.overlay`
- Modify: `boards/shields/roBa/roBa_R.conf`

**Interfaces:** Produces: `mouse_runtime_input_processor` を含む roBa_R ファーム（CI でビルド成功）。

- [ ] **Step 1: overlay の include 順序を修正し dtsi/property を復活**

`roBa_R.overlay` の先頭 include を次のようにする（`roBa.dtsi` の後、Zephyr input-event-codes を dtsi の前に置く）:

```dts
#include "roBa.dtsi"
#include <zephyr/dt-bindings/input/input-event-codes.h>
#include <input/processors/runtime-input-processor.dtsi>
```

`trackball_listener` ノードに `input-processors` を復活:

```dts
    trackball_listener {
        status = "okay";
        compatible = "zmk,input-listener";
        device = <&trackball>;
        input-processors = <&mouse_runtime_input_processor>;
    };
```

- [ ] **Step 2: conf にフラグを追加**

`roBa_R.conf` の SP1 マクロ設定群の近く（DYA Studio modules のコメント群の前）に追加:

```
# runtime input processor module (W1b): trackball runtime config over cormoran_rip
CONFIG_ZMK_RUNTIME_INPUT_PROCESSOR=y
CONFIG_ZMK_RUNTIME_INPUT_PROCESSOR_STUDIO_RPC=y
```

- [ ] **Step 3: コミットしてブランチを push、CI ビルドを起動**

```bash
git add boards/shields/roBa/roBa_R.overlay boards/shields/roBa/roBa_R.conf
git commit -m "feat(roBa_R): enable runtime-input-processor + cormoran_rip Studio RPC (W1b Task1)"
git push -u origin feat/roba-w1b-trackball
```

- [ ] **Step 4: CI 結果を確認（go/no-go）**

```bash
gh run list --branch feat/roba-w1b-trackball --limit 1
gh run watch <run-id>   # または gh run view <run-id> --log-failed
```
Expected（GO）: roBa_R / roBa_L / settings_reset の全ターゲットが green。`runtime-input-processor.dtsi:17` エラーが消えていること。
NO-GO 時: ログの devicetree/コンパイルエラーを特定。`INPUT_EV_REL` 系がまだ未定義なら include 順序/パスを再調整（`<dt-bindings/zmk/pointing.h>` の併用、dtsi の後に `<dt-bindings/zmk/matrix_transform.h>` が必要かを確認）。`<zmk/studio/custom.h>` 系の link error が出た場合は base の custom-RPC レイヤ非互換を意味するので**ここで停止し、結果をユーザーへ報告**（known-good へは main 04fabef で即復帰可能）。

- [ ] **Step 5: ビルド成果物(uf2)を取得しユーザーへ flash 依頼**

```bash
gh run download <run-id> -n <roBa_R artifact name>
```
roBa_R-...-zmk.uf2 をユーザーに渡し、roBa_R を flash してもらう（roBa_L は不変＝flash 不要）。flash 前に known-good 復帰手段（現行 uf2 / settings_reset.uf2）を明示。

---

## Task 2: host proto（`cormoran.rip`）追加と生成

**Files:**
- Create: `proto/cormoran/rip/custom.proto`
- Create: `roba_cli/proto/cormoran/__init__.py`, `roba_cli/proto/cormoran/rip/__init__.py`
- Generate: `roba_cli/proto/cormoran/rip/custom_pb2.py`
- Test: `tests/test_rip.py`（import サニティ）

**Interfaces:** Produces: `rip_pb2.Request` / `rip_pb2.Response` / `rip_pb2.InputProcessorInfo` / `rip_pb2.AxisSnapMode`。

- [ ] **Step 1: `proto/cormoran/rip/custom.proto` を作成**（firmware と同一定義のホスト用コピー）

```proto
syntax = "proto3";

package cormoran.rip;

enum AxisSnapMode {
    AXIS_SNAP_MODE_NONE = 0;
    AXIS_SNAP_MODE_X = 1;
    AXIS_SNAP_MODE_Y = 2;
}

message InputProcessorInfo {
    uint32 id = 1;
    string name = 2;
    uint32 scale_multiplier = 3;
    uint32 scale_divisor = 4;
    int32  rotation_degrees = 5;
    bool   temp_layer_enabled = 6;
    uint32 temp_layer_layer = 7;
    uint32 temp_layer_activation_delay_ms = 8;
    uint32 temp_layer_deactivation_delay_ms = 9;
    uint32 active_layers = 10;
    AxisSnapMode axis_snap_mode = 11;
    uint32 axis_snap_threshold = 12;
    uint32 axis_snap_timeout_ms = 13;
    bool   xy_to_scroll_enabled = 14;
    bool   xy_swap_enabled = 15;
    bool   x_invert = 16;
    bool   y_invert = 17;
}

message LayerInfo {
    uint32 index = 1;
    string name = 2;
}

message ListInputProcessorsRequest {}
message ListInputProcessorsResponse {}
message GetInputProcessorRequest { uint32 id = 1; }
message GetInputProcessorResponse { InputProcessorInfo processor = 1; }
message GetLayerInfoRequest {}
message GetLayerInfoResponse { repeated LayerInfo layers = 1; }
message SetScaleMultiplierRequest { uint32 id = 1; uint32 value = 2; }
message SetScaleMultiplierResponse {}
message SetScaleDivisorRequest { uint32 id = 1; uint32 value = 2; }
message SetScaleDivisorResponse {}
message SetRotationRequest { uint32 id = 1; int32 value = 2; }
message SetRotationResponse {}
message ResetInputProcessorRequest { uint32 id = 1; }
message ResetInputProcessorResponse {}
message SetTempLayerEnabledRequest { uint32 id = 1; bool enabled = 2; }
message SetTempLayerEnabledResponse {}
message SetTempLayerLayerRequest { uint32 id = 1; uint32 layer = 2; }
message SetTempLayerLayerResponse {}
message SetTempLayerActivationDelayRequest { uint32 id = 1; uint32 activation_delay_ms = 2; }
message SetTempLayerActivationDelayResponse {}
message SetTempLayerDeactivationDelayRequest { uint32 id = 1; uint32 deactivation_delay_ms = 2; }
message SetTempLayerDeactivationDelayResponse {}
message SetActiveLayersRequest { uint32 id = 1; uint32 layers = 2; }
message SetActiveLayersResponse {}
message SetAxisSnapModeRequest { uint32 id = 1; AxisSnapMode mode = 2; }
message SetAxisSnapModeResponse {}
message SetAxisSnapThresholdRequest { uint32 id = 1; uint32 threshold = 2; }
message SetAxisSnapThresholdResponse {}
message SetAxisSnapTimeoutRequest { uint32 id = 1; uint32 timeout_ms = 2; }
message SetAxisSnapTimeoutResponse {}
message SetXyToScrollEnabledRequest { uint32 id = 1; bool enabled = 2; }
message SetXyToScrollEnabledResponse {}
message SetXySwapEnabledRequest { uint32 id = 1; bool enabled = 2; }
message SetXySwapEnabledResponse {}
message SetXInvertRequest { uint32 id = 1; bool invert = 2; }
message SetXInvertResponse {}
message SetYInvertRequest { uint32 id = 1; bool invert = 2; }
message SetYInvertResponse {}
message ErrorResponse { string message = 1; }

message Request {
    oneof request_type {
        ListInputProcessorsRequest           list_input_processors = 1;
        GetInputProcessorRequest             get_input_processor = 2;
        SetScaleMultiplierRequest            set_scale_multiplier = 3;
        SetScaleDivisorRequest               set_scale_divisor = 4;
        SetRotationRequest                   set_rotation = 5;
        ResetInputProcessorRequest           reset_input_processor = 6;
        SetTempLayerEnabledRequest           set_temp_layer_enabled = 7;
        SetTempLayerLayerRequest             set_temp_layer_layer = 8;
        SetTempLayerActivationDelayRequest   set_temp_layer_activation_delay = 9;
        SetTempLayerDeactivationDelayRequest set_temp_layer_deactivation_delay = 10;
        SetActiveLayersRequest               set_active_layers = 11;
        GetLayerInfoRequest                  get_layer_info = 12;
        SetAxisSnapModeRequest               set_axis_snap_mode = 13;
        SetAxisSnapThresholdRequest          set_axis_snap_threshold = 14;
        SetAxisSnapTimeoutRequest            set_axis_snap_timeout = 15;
        SetXyToScrollEnabledRequest          set_xy_to_scroll_enabled = 16;
        SetXySwapEnabledRequest              set_xy_swap_enabled = 17;
        SetXInvertRequest                    set_x_invert = 18;
        SetYInvertRequest                    set_y_invert = 19;
    }
}

message Response {
    oneof response_type {
        ErrorResponse                         error = 1;
        ListInputProcessorsResponse           list_input_processors = 2;
        GetInputProcessorResponse             get_input_processor = 3;
        SetScaleMultiplierResponse            set_scale_multiplier = 4;
        SetScaleDivisorResponse               set_scale_divisor = 5;
        SetRotationResponse                   set_rotation = 6;
        ResetInputProcessorResponse           reset_input_processor = 7;
        SetTempLayerEnabledResponse           set_temp_layer_enabled = 8;
        SetTempLayerLayerResponse             set_temp_layer_layer = 9;
        SetTempLayerActivationDelayResponse   set_temp_layer_activation_delay = 10;
        SetTempLayerDeactivationDelayResponse set_temp_layer_deactivation_delay = 11;
        SetActiveLayersResponse               set_active_layers = 12;
        GetLayerInfoResponse                  get_layer_info = 13;
        SetAxisSnapModeResponse               set_axis_snap_mode = 14;
        SetAxisSnapThresholdResponse          set_axis_snap_threshold = 15;
        SetAxisSnapTimeoutResponse            set_axis_snap_timeout = 16;
        SetXyToScrollEnabledResponse          set_xy_to_scroll_enabled = 17;
        SetXySwapEnabledResponse              set_xy_swap_enabled = 18;
        SetXInvertResponse                    set_x_invert = 19;
        SetYInvertResponse                    set_y_invert = 20;
    }
}

message InputProcessorChangedNotification { InputProcessorInfo processor = 1; }
message Notification {
    oneof notification_type {
        InputProcessorChangedNotification input_processor_changed = 1;
    }
}
```

- [ ] **Step 2: パッケージ `__init__.py` を作成**

```bash
cd tools/roba-cli
mkdir -p roba_cli/proto/cormoran/rip
touch roba_cli/proto/cormoran/__init__.py roba_cli/proto/cormoran/rip/__init__.py
```

- [ ] **Step 3: protobuf Python を生成**

```bash
cd tools/roba-cli
.venv/bin/python -m grpc_tools.protoc -I proto --python_out=roba_cli/proto proto/cormoran/rip/custom.proto
```
Expected: `roba_cli/proto/cormoran/rip/custom_pb2.py` が生成される（source 行 `cormoran/rip/custom.proto`）。

- [ ] **Step 4: import サニティテストを作成して実行**（`tests/test_rip.py`）

```python
import roba_cli.proto  # noqa: F401  sets sys.path
from roba_cli.proto.cormoran.rip import custom_pb2 as rip_pb2


def test_rip_proto_imports_and_oneof_fields_exist():
    req = rip_pb2.Request()
    names = {f.name for f in req.DESCRIPTOR.fields}
    assert {"get_input_processor", "set_scale_divisor", "set_rotation",
            "reset_input_processor", "set_x_invert"} <= names
    info = rip_pb2.InputProcessorInfo()
    inames = {f.name for f in info.DESCRIPTOR.fields}
    assert {"scale_multiplier", "scale_divisor", "rotation_degrees",
            "x_invert", "y_invert", "xy_to_scroll_enabled"} <= inames
    assert rip_pb2.AxisSnapMode.Value("AXIS_SNAP_MODE_X") == 1
```

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_rip.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tools/roba-cli/proto/cormoran tools/roba-cli/roba_cli/proto/cormoran tools/roba-cli/tests/test_rip.py
git commit -m "feat(roba-cli): add cormoran.rip proto + generated bindings (W1b)"
```

---

## Task 3: `rip_client.py`（builder/decoder＋custom 封筒クライアント）

**Files:**
- Create: `tools/roba-cli/roba_cli/rip_client.py`
- Test: `tools/roba-cli/tests/test_rip.py`

**Interfaces:**
- Produces（純粋関数）:
  - `FIELD_SPECS: dict[str, tuple]` — set 可能なフィールド名 → `(request_oneof_attr, value_attr, parser)`。
  - `build_set_request(field: str, id: int, raw_value: str) -> rip_pb2.Request`
  - `build_get_request(id: int) -> rip_pb2.Request`
  - `build_reset_request(id: int) -> rip_pb2.Request`
  - `info_to_dict(info: rip_pb2.InputProcessorInfo) -> dict`
  - `decode_response(resp: rip_pb2.Response) -> dict` — `{ok, error[, processor]}`
- Produces（クライアント）: `RipClient(port=None)` with `.get(id) -> dict` / `.set(field, id, raw_value) -> dict` / `.reset(id) -> dict`。
- Consumes: `rpc.send_recv`/`rpc.find_port`/`rpc.DEFAULT_BAUD`, `studio_pb2`, `custom_pb2`(zmk.custom)。

- [ ] **Step 1: 失敗するテストを追記**（`tests/test_rip.py`）

```python
from roba_cli import rip_client as rc


def test_build_set_request_scale_divisor():
    req = rc.build_set_request("scale-divisor", id=0, raw_value="4")
    assert req.WhichOneof("request_type") == "set_scale_divisor"
    assert req.set_scale_divisor.id == 0
    assert req.set_scale_divisor.value == 4


def test_build_set_request_bool_and_rotation_and_enum():
    r1 = rc.build_set_request("x-invert", 0, "true")
    assert r1.set_x_invert.invert is True
    r2 = rc.build_set_request("rotation", 0, "-90")
    assert r2.set_rotation.value == -90
    r3 = rc.build_set_request("axis-snap-mode", 0, "x")
    assert r3.set_axis_snap_mode.mode == rip_pb2.AxisSnapMode.Value("AXIS_SNAP_MODE_X")


def test_build_get_and_reset_requests():
    assert rc.build_get_request(0).WhichOneof("request_type") == "get_input_processor"
    assert rc.build_get_request(0).get_input_processor.id == 0
    assert rc.build_reset_request(2).reset_input_processor.id == 2


def test_build_set_request_unknown_field_raises():
    import pytest
    with pytest.raises(ValueError):
        rc.build_set_request("nope", 0, "1")


def test_info_to_dict_and_decode_response():
    resp = rip_pb2.Response()
    resp.get_input_processor.processor.id = 0
    resp.get_input_processor.processor.scale_divisor = 3
    resp.get_input_processor.processor.x_invert = True
    d = rc.decode_response(resp)
    assert d["ok"] is True
    assert d["processor"]["scale_divisor"] == 3 and d["processor"]["x_invert"] is True
    err = rip_pb2.Response()
    err.error.message = "bad id"
    de = rc.decode_response(err)
    assert de["ok"] is False and de["error"] == "bad id"
```

- [ ] **Step 2: テストが落ちるのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_rip.py -q`
Expected: FAIL（`rip_client` 未作成）。

- [ ] **Step 3: `rip_client.py` を実装**

```python
"""RipClient: runtime trackball/pointer config over the cormoran_rip custom RPC.

Same 2-step custom envelope as MacroClient: list_custom_subsystems -> resolve
"cormoran_rip" index -> call(payload=rip.Request). Pure request builders /
response decoders are unit-tested; the thin client is HIL-tested.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import custom_pb2
from roba_cli.proto.cormoran.rip import custom_pb2 as rip_pb2

from . import rpc

SUBSYSTEM_ID = "cormoran_rip"


def _parse_bool(s: str) -> bool:
    v = s.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected boolean, got {s!r}")


def _parse_axis_snap(s: str) -> int:
    key = "AXIS_SNAP_MODE_" + s.strip().upper()
    try:
        return rip_pb2.AxisSnapMode.Value(key)
    except ValueError:
        raise ValueError(f"unknown axis-snap-mode {s!r} (use none|x|y)")


# field name -> (request oneof attr, value sub-field, parser)
FIELD_SPECS = {
    "scale-multiplier":            ("set_scale_multiplier", "value", int),
    "scale-divisor":               ("set_scale_divisor", "value", int),
    "rotation":                    ("set_rotation", "value", int),
    "x-invert":                    ("set_x_invert", "invert", _parse_bool),
    "y-invert":                    ("set_y_invert", "invert", _parse_bool),
    "xy-swap":                     ("set_xy_swap_enabled", "enabled", _parse_bool),
    "xy-to-scroll":                ("set_xy_to_scroll_enabled", "enabled", _parse_bool),
    "axis-snap-mode":              ("set_axis_snap_mode", "mode", _parse_axis_snap),
    "axis-snap-threshold":         ("set_axis_snap_threshold", "threshold", int),
    "axis-snap-timeout":           ("set_axis_snap_timeout", "timeout_ms", int),
    "temp-layer-enabled":          ("set_temp_layer_enabled", "enabled", _parse_bool),
    "temp-layer-layer":            ("set_temp_layer_layer", "layer", int),
    "temp-layer-activation-delay": ("set_temp_layer_activation_delay", "activation_delay_ms", int),
    "temp-layer-deactivation-delay": ("set_temp_layer_deactivation_delay", "deactivation_delay_ms", int),
    "active-layers":               ("set_active_layers", "layers", int),
}


def build_set_request(field: str, id: int, raw_value: str) -> "rip_pb2.Request":
    if field not in FIELD_SPECS:
        raise ValueError(f"unknown field {field!r}. known: {sorted(FIELD_SPECS)}")
    oneof_attr, value_attr, parser = FIELD_SPECS[field]
    req = rip_pb2.Request()
    sub = getattr(req, oneof_attr)
    sub.id = id
    setattr(sub, value_attr, parser(raw_value))
    return req


def build_get_request(id: int) -> "rip_pb2.Request":
    req = rip_pb2.Request()
    req.get_input_processor.id = id
    return req


def build_reset_request(id: int) -> "rip_pb2.Request":
    req = rip_pb2.Request()
    req.reset_input_processor.id = id
    return req


def info_to_dict(info: "rip_pb2.InputProcessorInfo") -> dict:
    return {f.name: getattr(info, f.name) for f in info.DESCRIPTOR.fields}


def decode_response(resp: "rip_pb2.Response") -> dict:
    which = resp.WhichOneof("response_type")
    if which is None:
        return {"ok": False, "error": "empty rip response"}
    if which == "error":
        return {"ok": False, "error": resp.error.message}
    out = {"ok": True, "error": ""}
    if which == "get_input_processor":
        out["processor"] = info_to_dict(resp.get_input_processor.processor)
    return out


class RipClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD):
        target = port or rpc.find_port()
        self._ser = serial.Serial(target, baud, timeout=0.1)
        self._index: int | None = None
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "RipClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _next_rid(self) -> int:
        self._rid += 1
        return self._rid

    def _resolve_index(self) -> int:
        if self._index is not None:
            return self._index
        req = studio_pb2.Request()
        req.request_id = self._next_rid()
        req.custom.list_custom_subsystems.CopyFrom(custom_pb2.ListCustomSubsystemRequest())
        resp = rpc.send_recv(self._ser, req)
        css = resp.request_response.custom.list_custom_subsystems
        for sub in css.subsystems:
            if sub.identifier == SUBSYSTEM_ID:
                self._index = sub.index
                return sub.index
        raise RuntimeError(
            f"'{SUBSYSTEM_ID}' subsystem not found. "
            f"Available: {[(s.identifier, s.index) for s in css.subsystems]}"
        )

    def _call(self, rip_req: "rip_pb2.Request") -> "rip_pb2.Response":
        idx = self._resolve_index()
        sreq = studio_pb2.Request()
        sreq.request_id = self._next_rid()
        sreq.custom.call.subsystem_index = idx
        sreq.custom.call.payload = rip_req.SerializeToString()
        sresp = rpc.send_recv(self._ser, sreq)
        rip_resp = rip_pb2.Response()
        rip_resp.ParseFromString(sresp.request_response.custom.call.payload)
        return rip_resp

    def get(self, id: int = 0) -> dict:
        return decode_response(self._call(build_get_request(id)))

    def set(self, field: str, id: int, raw_value: str) -> dict:
        return decode_response(self._call(build_set_request(field, id, raw_value)))

    def reset(self, id: int = 0) -> dict:
        return decode_response(self._call(build_reset_request(id)))
```

- [ ] **Step 4: テストが通るのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_rip.py -q`
Expected: PASS（全件）。

- [ ] **Step 5: 全スイート緑か確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest -q`
Expected: 既存 31 ＋新規が全 PASS。

- [ ] **Step 6: Commit**

```bash
git add tools/roba-cli/roba_cli/rip_client.py tools/roba-cli/tests/test_rip.py
git commit -m "feat(roba-cli): rip_client for cormoran_rip trackball RPC (W1b)"
```

---

## Task 4: `cli.py` に `roba trackball` verb

**Files:**
- Modify: `tools/roba-cli/roba_cli/cli.py`
- Test: `tools/roba-cli/tests/test_rip.py`（parser スモーク）

**Interfaces:**
- Consumes: `RipClient`、`rip_client.FIELD_SPECS`、既存 `_emit`/`_append_backup`。
- Produces（CLI verb）: `roba trackball get [--id N]` / `roba trackball set <field> <value> [--id N]` / `roba trackball reset [--id N]`。

- [ ] **Step 1: parser スモークテストを追記**（`tests/test_rip.py`）

```python
from roba_cli import cli as _cli


def test_trackball_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["trackball", "set", "scale-divisor", "4"])
    assert ns.field == "scale-divisor" and ns.value == "4" and ns.id == 0
    ns2 = p.parse_args(["trackball", "get", "--id", "1"])
    assert ns2.id == 1 and ns2.func is _cli.cmd_trackball_get
    ns3 = p.parse_args(["trackball", "reset"])
    assert ns3.func is _cli.cmd_trackball_reset
```

- [ ] **Step 2: テストが落ちるのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_rip.py::test_trackball_subcommands_parse -q`
Expected: FAIL。

- [ ] **Step 3: `cli.py` にコマンドと parser を追記**

import に `from .rip_client import RipClient` と `from . import rip_client` を追加。コマンド関数:

```python
def cmd_trackball_get(args: argparse.Namespace) -> int:
    with RipClient(args.port) as client:
        res = client.get(args.id)
    _emit({"op": "trackball_get", "id": args.id, **res})
    return 0 if res["ok"] else 1


def cmd_trackball_set(args: argparse.Namespace) -> int:
    with RipClient(args.port) as client:
        before = client.get(args.id)
        _append_backup({"op": "trackball_set", "id": args.id,
                        "field": args.field, "value": args.value,
                        "before": before.get("processor")})
        res = client.set(args.field, args.id, args.value)
        after = client.get(args.id) if res["ok"] else {"processor": None}
    _emit({"op": "trackball_set", "id": args.id, "field": args.field,
           "value": args.value, "ok": res["ok"], "error": res["error"],
           "after": after.get("processor")})
    return 0 if res["ok"] else 1


def cmd_trackball_reset(args: argparse.Namespace) -> int:
    with RipClient(args.port) as client:
        before = client.get(args.id)
        _append_backup({"op": "trackball_reset", "id": args.id,
                        "before": before.get("processor")})
        res = client.reset(args.id)
        after = client.get(args.id) if res["ok"] else {"processor": None}
    _emit({"op": "trackball_reset", "id": args.id, "ok": res["ok"],
           "error": res["error"], "after": after.get("processor")})
    return 0 if res["ok"] else 1
```

`build_parser()` に追記:

```python
    tb = sub.add_parser("trackball", help="Runtime trackball/pointer config (cormoran_rip)").add_subparsers(
        dest="trackball_cmd", required=True)
    tbg = tb.add_parser("get", help="Get processor state as JSON")
    tbg.add_argument("--id", type=int, default=0)
    tbg.set_defaults(func=cmd_trackball_get)
    tbs = tb.add_parser("set", help=f"Set a field. fields: {sorted(rip_client.FIELD_SPECS)}")
    tbs.add_argument("field")
    tbs.add_argument("value")
    tbs.add_argument("--id", type=int, default=0)
    tbs.set_defaults(func=cmd_trackball_set)
    tbr = tb.add_parser("reset", help="Reset processor to devicetree defaults")
    tbr.add_argument("--id", type=int, default=0)
    tbr.set_defaults(func=cmd_trackball_reset)
```

- [ ] **Step 4: テストが通るのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_rip.py -q`
Expected: PASS。

- [ ] **Step 5: 全スイート＋ヘルプ確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest -q && .venv/bin/roba trackball --help`
Expected: テスト全 PASS、trackball サブコマンドが列挙。

- [ ] **Step 6: Commit**

```bash
git add tools/roba-cli/roba_cli/cli.py tools/roba-cli/tests/test_rip.py
git commit -m "feat(roba-cli): add 'roba trackball' get/set/reset (W1b)"
```

---

## Task 5: 実機 E2E＋revert 確定＋ドキュメント

**Files:**
- Modify: `tools/roba-cli/README.md`
- Test: 実機（HIL）— Task1 の uf2 を flash 済みの roBa で確認

**Interfaces:** なし（検証とドキュメント）。

- [ ] **Step 1: 接続と subsystem 検出の確認**

```bash
cd tools/roba-cli
.venv/bin/roba trackball get          # InputProcessorInfo が JSON で出る（scale_divisor 等）
```
Expected: `cormoran_rip` が解決され、id 0 の現状が出力。出なければ `_resolve_index` の Available 一覧で identifier を確認。

- [ ] **Step 2: 感度変更の体感＋revert を実機確認**

```bash
.venv/bin/roba trackball get                       # 既定値を控える（例 scale_divisor）
.venv/bin/roba trackball set scale-divisor 4       # カーソルが遅くなる体感
.venv/bin/roba trackball get                        # after に反映
.venv/bin/roba trackball reset                      # 既定へ戻す
.venv/bin/roba trackball get                        # 既定値に復帰
```
Expected: 設定変更がカーソル挙動に反映、`reset` で既定復帰。`.roba-backup.jsonl` に before が残る。

- [ ] **Step 2b: 永続性と revert 経路の確定（実機知見の記録）**

`set scale-divisor 4` の後、**電源オフ→再接続**して `roba trackball get` を確認:
- 値が保持 → cormoran_rip は NVS 永続。revert は `roba trackball reset`（＋必要なら `roba reset`/`settings_reset.uf2`）。
- 値が既定に戻る → 非永続（RAM のみ）。
いずれかを README と memory に記録。`roba reset`（Studio reset_settings）が rip 設定を消すかも確認。

- [ ] **Step 3: README に `trackball` コマンドと revert 注記を追記**

`tools/roba-cli/README.md` のコマンド一覧に追加:

```markdown
### トラックボール/ポインタ設定（cormoran_rip・焼き直し不要）
- `roba trackball get [--id N]` — プロセッサ状態を JSON 表示
- `roba trackball set <field> <value> [--id N]` — フィールドを変更（変更前は `.roba-backup.jsonl` に記録）
  - fields: scale-multiplier, scale-divisor, rotation, x-invert, y-invert, xy-swap,
    xy-to-scroll, axis-snap-mode(none|x|y), axis-snap-threshold, axis-snap-timeout,
    temp-layer-enabled, temp-layer-layer, temp-layer-activation-delay,
    temp-layer-deactivation-delay, active-layers
- `roba trackball reset [--id N]` — そのプロセッサを devicetree 既定へ戻す（第一の revert 手段）

注: この機能はファームに runtime-input-processor を含める必要があり、**初回のみ roBa_R の flash が必要**。
以後の設定変更は焼き直し不要。永続性/`roba reset` の効きは Step 2b の実機結果に従う。
```

- [ ] **Step 4: Commit**

```bash
git add tools/roba-cli/README.md
git commit -m "docs(roba-cli): document 'roba trackball' commands + revert (W1b)"
```

- [ ] **Step 5: 全スイート最終確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest -q`
Expected: 全 PASS。

---

## Self-Review（記入後チェック）

- **Spec coverage**: spec W1b の受け入れ条件（モジュール有効でビルド成功＝Task1 / `set` 反映＋`reset` 復帰＋永続＝Task5 / known-good 復元の明文化＝Global Constraints・Task1 Step5・Task5 Step2b）をカバー。✓
- **Placeholder scan**: 全 step に実コード/コマンド/期待値。CI run-id とビルドエラー詳細は実行時に判明する性質（go/no-go タスク）として明示。✓
- **Type consistency**: `decode_response` の `{ok,error[,processor]}` を client と cli が一貫使用。`FIELD_SPECS` のキー（kebab）は cli の `set <field>` とテストで一致。`build_set_request` は全 Set* を網羅。rip 応答は custom 封筒（`request_response.custom.call.payload`）で取り出し、W1a で堅牢化した `send_recv`（notification 破棄）に依存。✓
- **既知の注意**: ①Task1 は CI ビルド＋ユーザー flash を伴う唯一のファーム変更タスク（go/no-go）。`<zmk/studio/custom.h>` 系 link error が出たら停止しユーザー報告（known-good=main 04fabef へ即復帰）。②`cormoran_rip` の `list_input_processors` は結果を notification で返すため、host は read 主体に `get_input_processor(id)` を使う（本プランは get/set/reset のみで list 非依存）。③set 後の `after` 再読込は client が同一接続で2回 `get` するが、`send_recv` は notification を破棄するので InputProcessorChangedNotification と混線しない。
