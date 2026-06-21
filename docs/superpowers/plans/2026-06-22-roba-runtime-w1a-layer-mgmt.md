# W1a: レイヤー管理を roba-cli に公開 — 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Studio native の keymap RPC（既にファームにある add/remove/move/restore_layer・set_layer_props）を `roba layer` サブコマンドとして host に公開し、レイヤーの一覧/改名/追加/削除/並替/復元を焼き直し無しで行えるようにする。

**Architecture:** ファーム不変。SP1 で実証した「`studio.Request` を framing して USB serial に送り `studio.Response` を読む」transport を `rpc.py` に抽出して共有し、その上に純粋な request ビルダ/response デコーダ（単体テスト対象）と薄い `KeymapClient`（実機 E2E 対象）を載せる。`cli.py` に `layer` verb 群を足し、変更前バックアップ＋`save_changes` を伴う。

**Tech Stack:** Python 3.12（venv `tools/roba-cli/.venv`）、pyserial、生成済み protobuf（`roba_cli/proto/` の `studio_pb2`/`keymap_pb2`）、pytest。

## Global Constraints

- 横断制約「常時 known-good へ即 revert」：mutating な操作は必ず①実行前に現 keymap を `tools/roba-cli/.roba-backup.jsonl` へ追記（既存 `cli._append_backup` 形式）、②`roba reset`（Studio `reset_settings`）で devicetree 既定へ全戻しできること。known-good = 現 HEAD `4a98e16`。
- transport は USB serial。ZMK Studio framing は **SOF=0xAB / ESC=0xAC / EOF=0xAD、XOR しない**（`framing.py` 既存実装、改変禁止）。
- host の標準出力は **1行 JSON**（既存 verb と一貫、`cli._emit`）。
- 既存 15 テスト（test_framing / test_macro_dsl / test_behaviors）は不変で**緑を維持**。
- proto は `import roba_cli.proto` で sys.path を通してから `import studio_pb2` / `import keymap_pb2`（`macro_client.py` と同じ作法）。
- `pytest` は `tools/roba-cli` で `.venv/bin/python -m pytest -q` で実行。

---

## File Structure

- Create `tools/roba-cli/roba_cli/rpc.py` — 共有 transport（`find_port` / `read_frame` / `send_recv` と定数）。`macro_client.py` から移設。
- Modify `tools/roba-cli/roba_cli/macro_client.py` — 移設した transport を `rpc.py` から import して使用（重複削除）。
- Create `tools/roba-cli/roba_cli/keymap_client.py` — 純粋関数（req ビルダ・resp デコーダ・`parse_keymap`）＋ `KeymapClient`。
- Modify `tools/roba-cli/roba_cli/cli.py` — `layer` サブコマンド群＋バックアップ。
- Create `tools/roba-cli/tests/test_keymap_ops.py` — 純粋関数の単体テスト。
- Modify `tools/roba-cli/README.md` — `layer` コマンドの記載。

---

## Task 1: 共有 transport を `rpc.py` に抽出

**Files:**
- Create: `tools/roba-cli/roba_cli/rpc.py`
- Modify: `tools/roba-cli/roba_cli/macro_client.py`
- Test: 既存スイート（移設で壊れないこと）

**Interfaces:**
- Produces: `rpc.find_port() -> str`、`rpc.read_frame(ser, timeout=2.0) -> bytes`、`rpc.send_recv(ser, studio_req, timeout=2.0) -> studio_pb2.Response`、定数 `rpc.SOF/rpc.EOF/rpc.PORT_GLOB/rpc.DEFAULT_BAUD/rpc.READ_TIMEOUT/rpc.CHUNK`。
- Consumes（W1b 以降）: `rip_client` も同じ transport を使う。

- [ ] **Step 1: `rpc.py` を新規作成**（`macro_client.py` の `_find_port`/`_read_frame`/`_send_recv` と定数をそのまま移設し、公開名へ）

```python
"""Shared ZMK Studio serial transport (framing + request/response loop).

Wire format: SOF=0xAB, ESC=0xAC, EOF=0xAD, no XOR (see framing.py). Used by all
roba-cli clients that talk the Studio RPC directly over USB serial.
"""
from __future__ import annotations

import glob
import time

import serial

import roba_cli.proto  # noqa: F401  sets sys.path for proto imports
import studio_pb2

from .framing import encode_frame, decode_frame

SOF = 0xAB
ESC = 0xAC
EOF = 0xAD
PORT_GLOB = "/dev/cu.usbmodem*"
DEFAULT_BAUD = 115200
READ_TIMEOUT = 2.0
CHUNK = 256


def find_port() -> str:
    ports = sorted(glob.glob(PORT_GLOB))
    if len(ports) == 1:
        return ports[0]
    raise RuntimeError(
        f"roBa serial port not uniquely found. candidates={ports}. "
        "Pass --port explicitly."
    )


def read_frame(ser: "serial.Serial", timeout: float = READ_TIMEOUT) -> bytes:
    buf = bytearray()
    in_frame = False
    deadline = time.monotonic() + timeout
    escaped = False
    while time.monotonic() < deadline:
        chunk = ser.read(CHUNK)
        if not chunk:
            continue
        for b in chunk:
            if not in_frame:
                if b == SOF:
                    buf = bytearray([b])
                    in_frame = True
                    escaped = False
            else:
                buf.append(b)
                if escaped:
                    escaped = False
                elif b == ESC:
                    escaped = True
                elif b == EOF:
                    return bytes(buf)
    raise TimeoutError(
        f"Timed out waiting for frame (got {len(buf)} bytes so far: {buf.hex()})"
    )


def send_recv(ser: "serial.Serial", studio_req: "studio_pb2.Request",
              timeout: float = READ_TIMEOUT) -> "studio_pb2.Response":
    payload = studio_req.SerializeToString()
    ser.write(encode_frame(payload))
    ser.flush()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for request_response frame")
        raw_frame = read_frame(ser, timeout=remaining)
        resp = studio_pb2.Response()
        resp.ParseFromString(decode_frame(raw_frame))
        if resp.HasField("request_response"):
            return resp
        # notification frame; discard and keep waiting
```

- [ ] **Step 2: `macro_client.py` を `rpc.py` 利用に書き換え**（重複した transport を削除し import に置換）

`macro_client.py` 冒頭の import 群を次のように整理し、ローカルの `_find_port`/`_read_frame`/`_send_recv` と重複定数を削除する。本文中の `_send_recv(self._ser, req)` 呼び出しは `rpc.send_recv(self._ser, req)` に、`_find_port()` は `rpc.find_port()` に、`serial.Serial(target, baud, ...)` の `baud` 既定は `rpc.DEFAULT_BAUD` に置き換える。

```python
import serial

import roba_cli.proto  # sets sys.path for proto imports
import studio_pb2
import custom_pb2
from roba_cli.proto.macros import macros_pb2
from . import rpc
```

`__init__` は:

```python
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD):
        target = port or rpc.find_port()
        self._ser = serial.Serial(target, baud, timeout=0.1)
        self._subsystem_index: int | None = None
```

`_resolve_index` / `_call` 内の `_send_recv(self._ser, ...)` を `rpc.send_recv(self._ser, ...)` に置換。

- [ ] **Step 3: 既存スイートが緑のままか確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest -q`
Expected: 15 passed（移設で挙動不変）。

- [ ] **Step 4: import 健全性の確認**

Run: `cd tools/roba-cli && .venv/bin/python -c "from roba_cli import rpc, macro_client; print(rpc.find_port.__name__, hasattr(macro_client,'MacroClient'))"`
Expected: `find_port True`（例外なし。ポート未接続でも import は通る）。

- [ ] **Step 5: Commit**

```bash
git add tools/roba-cli/roba_cli/rpc.py tools/roba-cli/roba_cli/macro_client.py
git commit -m "refactor(roba-cli): extract shared Studio serial transport to rpc.py"
```

---

## Task 2: `keymap_client.py` — get/parse（レイヤー一覧）

**Files:**
- Create: `tools/roba-cli/roba_cli/keymap_client.py`
- Test: `tools/roba-cli/tests/test_keymap_ops.py`

**Interfaces:**
- Produces:
  - `req_get_keymap(request_id: int) -> studio_pb2.Request`
  - `parse_keymap(km: keymap_pb2.Keymap) -> list[dict]` → `[{"index": int, "id": int, "name": str, "bindings": int}]`
  - `KeymapClient(port=None)` with `.get_layers() -> list[dict]`
- Consumes: `rpc.send_recv`, `rpc.find_port`, `rpc.DEFAULT_BAUD`。

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_keymap_ops.py`）

```python
import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import keymap_pb2

from roba_cli import keymap_client as kc


def test_req_get_keymap_wraps_in_studio_request():
    req = kc.req_get_keymap(7)
    assert req.request_id == 7
    assert req.WhichOneof("subsystem") == "keymap"
    assert req.keymap.WhichOneof("request_type") == "get_keymap"
    assert req.keymap.get_keymap is True


def test_parse_keymap_lists_layers_with_index_id_name_and_binding_count():
    km = keymap_pb2.Keymap()
    l0 = km.layers.add(); l0.id = 0; l0.name = "DEFAULT"
    l0.bindings.add(); l0.bindings.add()  # 2 bindings
    l1 = km.layers.add(); l1.id = 9; l1.name = "SETTING"
    l1.bindings.add()  # 1 binding
    out = kc.parse_keymap(km)
    assert out == [
        {"index": 0, "id": 0, "name": "DEFAULT", "bindings": 2},
        {"index": 1, "id": 9, "name": "SETTING", "bindings": 1},
    ]
```

- [ ] **Step 2: テストが落ちるのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_keymap_ops.py -q`
Expected: FAIL（`roba_cli.keymap_client` が無い / 関数未定義）。

- [ ] **Step 3: 最小実装**（`keymap_client.py`）

```python
"""KeymapClient: layer management over Studio native keymap RPC (no reflash).

Pure request builders / response decoders (unit-tested) + a thin transport
client (HIL-tested) on top of rpc.send_recv. Wraps zmk.keymap.Request in
studio.Request{keymap=...}; reads studio.Response.request_response.keymap.
"""
from __future__ import annotations

import serial

import roba_cli.proto  # noqa: F401  sets sys.path
import studio_pb2
import keymap_pb2

from . import rpc


def req_get_keymap(request_id: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.get_keymap = True
    return req


def parse_keymap(km: "keymap_pb2.Keymap") -> list[dict]:
    return [
        {"index": i, "id": layer.id, "name": layer.name,
         "bindings": len(layer.bindings)}
        for i, layer in enumerate(km.layers)
    ]


class KeymapClient:
    def __init__(self, port: str | None = None, baud: int = rpc.DEFAULT_BAUD):
        target = port or rpc.find_port()
        self._ser = serial.Serial(target, baud, timeout=0.1)
        self._rid = 0

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "KeymapClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _next_rid(self) -> int:
        self._rid += 1
        return self._rid

    def _keymap_call(self, req: "studio_pb2.Request") -> "keymap_pb2.Response":
        resp = rpc.send_recv(self._ser, req)
        return resp.request_response.keymap

    def get_layers(self) -> list[dict]:
        km_resp = self._keymap_call(req_get_keymap(self._next_rid()))
        return parse_keymap(km_resp.get_keymap)
```

- [ ] **Step 4: テストが通るのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_keymap_ops.py -q`
Expected: PASS（2 件）。

- [ ] **Step 5: Commit**

```bash
git add tools/roba-cli/roba_cli/keymap_client.py tools/roba-cli/tests/test_keymap_ops.py
git commit -m "feat(roba-cli): keymap_client get_layers + parse_keymap (W1a)"
```

---

## Task 3: mutating ops（rename/add/remove/move/restore/save）の builder＋decoder

**Files:**
- Modify: `tools/roba-cli/roba_cli/keymap_client.py`
- Test: `tools/roba-cli/tests/test_keymap_ops.py`

**Interfaces:**
- Produces（純粋関数）:
  - `req_set_layer_props(rid, layer_id, name)` / `req_add_layer(rid)` / `req_remove_layer(rid, index)` / `req_move_layer(rid, start, dest)` / `req_restore_layer(rid, layer_id, at_index)` / `req_save_changes(rid)` → `studio_pb2.Request`
  - `decode_status(km_resp) -> dict` … 各 response oneof を共通形 `{"ok": bool, "error": str}` に正規化（`error` は空文字なら成功）
- Produces（`KeymapClient`）: `.rename(layer_id, name)` / `.add()` / `.remove(index)` / `.move(start, dest)` / `.restore(layer_id, at_index)` / `.save() -> dict`

- [ ] **Step 1: 失敗するテストを追記**（`tests/test_keymap_ops.py`）

```python
def test_req_set_layer_props_fields():
    req = kc.req_set_layer_props(3, layer_id=9, name="GAME")
    assert req.request_id == 3
    assert req.keymap.WhichOneof("request_type") == "set_layer_props"
    assert req.keymap.set_layer_props.layer_id == 9
    assert req.keymap.set_layer_props.name == "GAME"


def test_req_move_and_remove_and_restore_fields():
    m = kc.req_move_layer(1, 2, 5).keymap.move_layer
    assert (m.start_index, m.dest_index) == (2, 5)
    r = kc.req_remove_layer(1, 4).keymap.remove_layer
    assert r.layer_index == 4
    rs = kc.req_restore_layer(1, 9, 3).keymap.restore_layer
    assert (rs.layer_id, rs.at_index) == (9, 3)


def test_req_add_layer_and_save_changes():
    assert kc.req_add_layer(1).keymap.WhichOneof("request_type") == "add_layer"
    sc = kc.req_save_changes(1)
    assert sc.keymap.WhichOneof("request_type") == "save_changes"
    assert sc.keymap.save_changes is True


def test_decode_status_set_layer_props_ok_and_err():
    ok = keymap_pb2.Response()
    ok.set_layer_props = keymap_pb2.SET_LAYER_PROPS_RESP_OK
    assert kc.decode_status(ok) == {"ok": True, "error": ""}
    err = keymap_pb2.Response()
    err.set_layer_props = keymap_pb2.SET_LAYER_PROPS_RESP_ERR_INVALID_ID
    d = kc.decode_status(err)
    assert d["ok"] is False and "INVALID_ID" in d["error"]


def test_decode_status_add_layer_ok_returns_index():
    resp = keymap_pb2.Response()
    resp.add_layer.ok.index = 12
    d = kc.decode_status(resp)
    assert d["ok"] is True and d.get("index") == 12


def test_decode_status_save_changes_err():
    resp = keymap_pb2.Response()
    resp.save_changes.err = keymap_pb2.SAVE_CHANGES_ERR_NO_SPACE
    d = kc.decode_status(resp)
    assert d["ok"] is False and "NO_SPACE" in d["error"]
```

- [ ] **Step 2: テストが落ちるのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_keymap_ops.py -q`
Expected: FAIL（新規関数未定義）。

- [ ] **Step 3: builder＋decoder＋client メソッドを実装**（`keymap_client.py` に追記）

```python
def req_set_layer_props(request_id: int, layer_id: int, name: str) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.set_layer_props.layer_id = layer_id
    req.keymap.set_layer_props.name = name
    return req


def req_add_layer(request_id: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.add_layer.SetInParent()  # empty AddLayerRequest selects the oneof
    return req


def req_remove_layer(request_id: int, layer_index: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.remove_layer.layer_index = layer_index
    return req


def req_move_layer(request_id: int, start_index: int, dest_index: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.move_layer.start_index = start_index
    req.keymap.move_layer.dest_index = dest_index
    return req


def req_restore_layer(request_id: int, layer_id: int, at_index: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.restore_layer.layer_id = layer_id
    req.keymap.restore_layer.at_index = at_index
    return req


def req_save_changes(request_id: int) -> "studio_pb2.Request":
    req = studio_pb2.Request()
    req.request_id = request_id
    req.keymap.save_changes = True
    return req


# Map the scalar-enum response fields to readable names for error reporting.
_ENUM_NAME = {
    "set_layer_binding": keymap_pb2.SetLayerBindingResponse,
    "set_layer_props": keymap_pb2.SetLayerPropsResponse,
}


def decode_status(km_resp: "keymap_pb2.Response") -> dict:
    """Normalize any keymap.Response variant to {ok, error[, index]}."""
    which = km_resp.WhichOneof("response_type")
    # Scalar enum responses (ok == 0)
    if which in _ENUM_NAME:
        val = getattr(km_resp, which)
        if val == 0:
            return {"ok": True, "error": ""}
        return {"ok": False, "error": _ENUM_NAME[which].Name(val)}
    # bool responses
    if which in ("check_unsaved_changes", "discard_changes"):
        return {"ok": bool(getattr(km_resp, which)), "error": ""}
    # oneof result{ok|err} responses
    sub = getattr(km_resp, which)
    result = sub.WhichOneof("result")
    if result == "err":
        enum_val = sub.err
        enum_desc = sub.DESCRIPTOR.fields_by_name["err"].enum_type
        return {"ok": False, "error": enum_desc.values_by_number[enum_val].name}
    out = {"ok": True, "error": ""}
    if which == "add_layer":
        out["index"] = sub.ok.index
    return out
```

`KeymapClient` に下記メソッドを追記（mutating は呼び出し側 `cli.py` がバックアップを取り、必要に応じ `save()` する）:

```python
    def rename(self, layer_id: int, name: str) -> dict:
        return decode_status(self._keymap_call(
            req_set_layer_props(self._next_rid(), layer_id, name)))

    def add(self) -> dict:
        return decode_status(self._keymap_call(req_add_layer(self._next_rid())))

    def remove(self, layer_index: int) -> dict:
        return decode_status(self._keymap_call(
            req_remove_layer(self._next_rid(), layer_index)))

    def move(self, start_index: int, dest_index: int) -> dict:
        return decode_status(self._keymap_call(
            req_move_layer(self._next_rid(), start_index, dest_index)))

    def restore(self, layer_id: int, at_index: int) -> dict:
        return decode_status(self._keymap_call(
            req_restore_layer(self._next_rid(), layer_id, at_index)))

    def save(self) -> dict:
        return decode_status(self._keymap_call(req_save_changes(self._next_rid())))
```

- [ ] **Step 4: テストが通るのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_keymap_ops.py -q`
Expected: PASS（全件）。

- [ ] **Step 5: 全スイートが緑か確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest -q`
Expected: 既存 15 + 新規が全 PASS。

- [ ] **Step 6: Commit**

```bash
git add tools/roba-cli/roba_cli/keymap_client.py tools/roba-cli/tests/test_keymap_ops.py
git commit -m "feat(roba-cli): keymap layer mutation builders/decoders + client methods (W1a)"
```

---

## Task 4: `cli.py` に `layer` サブコマンド＋バックアップ

**Files:**
- Modify: `tools/roba-cli/roba_cli/cli.py`
- Test: `tools/roba-cli/tests/test_keymap_ops.py`（parser のスモークのみ）

**Interfaces:**
- Consumes: `KeymapClient`、既存 `cli._emit` / `cli._append_backup`。
- Produces（CLI verb）: `roba layer list` / `roba layer rename <id> <name>` / `roba layer add` / `roba layer remove <index>` / `roba layer move <start> <dest>` / `roba layer restore <id> <at_index>`。

- [ ] **Step 1: parser のスモークテストを追記**（`tests/test_keymap_ops.py`）

```python
from roba_cli import cli as _cli


def test_layer_subcommands_parse():
    p = _cli.build_parser()
    ns = p.parse_args(["layer", "rename", "9", "GAME"])
    assert ns.layer_id == 9 and ns.name == "GAME"
    ns2 = p.parse_args(["layer", "move", "2", "5"])
    assert ns2.start == 2 and ns2.dest == 5
    ns3 = p.parse_args(["layer", "list"])
    assert ns3.func is _cli.cmd_layer_list
```

- [ ] **Step 2: テストが落ちるのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_keymap_ops.py::test_layer_subcommands_parse -q`
Expected: FAIL（`layer` サブコマンド未定義）。

- [ ] **Step 3: `cli.py` にコマンド実装と parser を追記**

ファイル先頭の import に `from .keymap_client import KeymapClient` を追加。次のコマンド関数を追記:

```python
def cmd_layer_list(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        layers = client.get_layers()
    _emit({"layers": layers})
    return 0


def _backup_layers(client) -> None:
    """Snapshot current layers before a mutating op (for revert audit trail)."""
    try:
        layers = client.get_layers()
    except Exception:  # noqa: BLE001
        layers = None
    _append_backup({"op": "layer_mutate", "before_layers": layers})


def cmd_layer_rename(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.rename(args.layer_id, args.name)
        if res["ok"]:
            res.update(client.save())
    _emit({"op": "rename", "layer_id": args.layer_id, "name": args.name, **res})
    return 0 if res["ok"] else 1


def cmd_layer_add(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.add()
        if res["ok"]:
            save = client.save()
            res["ok"] = save["ok"]
            res.setdefault("error", save["error"])
    _emit({"op": "add", **res})
    return 0 if res["ok"] else 1


def cmd_layer_remove(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.remove(args.index)
        if res["ok"]:
            res = client.save()
    _emit({"op": "remove", "index": args.index, **res})
    return 0 if res["ok"] else 1


def cmd_layer_move(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.move(args.start, args.dest)
        if res["ok"]:
            res = client.save()
    _emit({"op": "move", "start": args.start, "dest": args.dest, **res})
    return 0 if res["ok"] else 1


def cmd_layer_restore(args: argparse.Namespace) -> int:
    with KeymapClient(args.port) as client:
        _backup_layers(client)
        res = client.restore(args.layer_id, args.at_index)
        if res["ok"]:
            res = client.save()
    _emit({"op": "restore", "layer_id": args.layer_id, "at_index": args.at_index, **res})
    return 0 if res["ok"] else 1
```

`build_parser()` の `sub` 定義群に次を追記（`reset`/`snapshot` 登録の前後どこでもよい）:

```python
    layer = sub.add_parser("layer", help="Layer management (Studio native)").add_subparsers(
        dest="layer_cmd", required=True)
    layer.add_parser("list", help="List layers as JSON").set_defaults(func=cmd_layer_list)
    lr = layer.add_parser("rename", help="Rename a layer by id")
    lr.add_argument("layer_id", type=int)
    lr.add_argument("name")
    lr.set_defaults(func=cmd_layer_rename)
    layer.add_parser("add", help="Add a layer (devicetree-defined free slot)").set_defaults(
        func=cmd_layer_add)
    lrm = layer.add_parser("remove", help="Remove a layer by index")
    lrm.add_argument("index", type=int)
    lrm.set_defaults(func=cmd_layer_remove)
    lm = layer.add_parser("move", help="Move a layer from start index to dest index")
    lm.add_argument("start", type=int)
    lm.add_argument("dest", type=int)
    lm.set_defaults(func=cmd_layer_move)
    lrs = layer.add_parser("restore", help="Restore a removed layer by id at index")
    lrs.add_argument("layer_id", type=int)
    lrs.add_argument("at_index", type=int)
    lrs.set_defaults(func=cmd_layer_restore)
```

- [ ] **Step 4: テストが通るのを確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest tests/test_keymap_ops.py -q`
Expected: PASS（parser スモーク含む全件）。

- [ ] **Step 5: 全スイート＋ヘルプ表示確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest -q && .venv/bin/python -m roba_cli.cli layer --help`

> 注: `roba_cli.cli` は `run()` を `__main__` 経由で呼ぶ。`python -m roba_cli.cli` が動かない場合は `.venv/bin/roba layer --help`（entry point）を使う。
Expected: テスト全 PASS、`layer` のサブコマンドが列挙される。

- [ ] **Step 6: Commit**

```bash
git add tools/roba-cli/roba_cli/cli.py tools/roba-cli/tests/test_keymap_ops.py
git commit -m "feat(roba-cli): add 'roba layer' list/rename/add/remove/move/restore (W1a)"
```

---

## Task 5: 実機 E2E＋ドキュメント＋仕上げ

**Files:**
- Modify: `tools/roba-cli/README.md`
- Test: 実機（HIL）— roBa を USB 接続して手動確認

**Interfaces:** なし（検証とドキュメントのみ）。

- [ ] **Step 1: 実機 E2E チェックリスト**（roBa を USB 接続。各コマンドの JSON 出力を確認）

```bash
cd tools/roba-cli
.venv/bin/roba layer list                 # 15層が index/id/name/bindings で並ぶ
.venv/bin/roba layer rename 9 SETTING2     # ok:true
.venv/bin/roba layer list                  # id=9 の name が SETTING2 に
# 電源オフ→再接続
.venv/bin/roba layer list                  # SETTING2 が永続している
.venv/bin/roba reset                       # devicetree 既定へ全戻し
.venv/bin/roba layer list                  # name が元（SETTING 等）に復帰
```
Expected: 改名が反映・永続し、`reset` で known-good に戻る。`.roba-backup.jsonl` に `layer_mutate` の before スナップショットが残る。

> 注意: `add`/`remove`/`move` は keymap 構造を変える。検証は**まず `rename` と `reset` の往復で revert を確認**してから、`remove`→`restore`→`reset` を試す。各操作前に `roba layer list` で現状を控える。

- [ ] **Step 2: README に `layer` コマンドを追記**

`tools/roba-cli/README.md` のコマンド一覧に次を追加:

```markdown
### Layer management (Studio native, no reflash)

| Command | Effect |
|---|---|
| `roba layer list` | List layers (index, id, name, binding count) as JSON |
| `roba layer rename <id> <name>` | Rename a layer (persists; revert via `roba reset`) |
| `roba layer add` | Add a devicetree-defined free layer |
| `roba layer remove <index>` | Remove a layer (restore via `roba layer restore`) |
| `roba layer move <start> <dest>` | Reorder layers |
| `roba layer restore <id> <at_index>` | Restore a removed layer |

All mutating layer ops back up the prior layer list to `.roba-backup.jsonl`
and call `save_changes`. `roba reset` reverts everything to devicetree defaults.
```

- [ ] **Step 3: Commit**

```bash
git add tools/roba-cli/README.md
git commit -m "docs(roba-cli): document 'roba layer' commands (W1a)"
```

- [ ] **Step 4: 全スイート最終確認**

Run: `cd tools/roba-cli && .venv/bin/python -m pytest -q`
Expected: 全 PASS。

---

## Self-Review（記入後チェック）

- **Spec coverage**: spec の W1a 受け入れ条件（list が id/name 付き列挙 / 改名→反映→永続→reset 復帰 / ファーム再ビルド不要）を Task 2・5 がカバー。レイヤー add/remove/move/restore は Task 3・4。✓
- **Placeholder scan**: 全 step に実コード/実コマンド/期待値あり。✓
- **Type consistency**: `decode_status` の返り値 `{ok,error[,index]}` を client メソッドと cli が一貫使用。`req_*` は全て `studio_pb2.Request` を返す。`parse_keymap` の dict キー（index/id/name/bindings）はテストと list 出力で一致。✓
- **既知の注意**: `add_layer` の AddLayerRequest は空 message のため `SetInParent()` で oneof を選択（フィールド代入では選択されない）。`decode_status` は oneof result を持つ応答（add/remove/move/restore/save_changes）とスカラ enum 応答（set_layer_props）の両方を正規化。
