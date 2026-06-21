# roBa Studio CLI (SP0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BLE 経由で roBa に接続し、キーを焼かずに変更・永続化し、いつでも devicetree 既定へ全戻しできる Claude Code 駆動の CLI を作る（SP0）。

**Architecture:** 既存 `zmk-studio-api`(Python, BLE) を薄くラップした CLI。純ロジック（behavior 文字列パーサ）は単体テスト、転送を伴う部分は実機(HIL)検証。出力は JSON で Claude Code がパース可能。

**Tech Stack:** Python 3.11+, `zmk-studio-api`(source-built 0.4.0, serial+ble features — PyPI 0.3.1 は macOS で BLE 無効), pytest, venv。対象は macOS / roBa。

> **転送ピボット（2026-06-21, 実機確定）**: BLE は GATT 接続できても Studio RPC が無応答だった。
> dya Studio 拡張（ble-management/settings-rpc/battery-history）を roBa_R.conf で無効化し
> `studio-rpc-usb-uart` スニペットを復活 → **USB serial 経由で上流 zmk-studio-api が標準 Studio に疎通**。
> 以降 SP0 の転送は **USB serial**（`/dev/cu.usbmodem*` 自動検出、`--port` で明示可）。
> `connection.open(port)` は `StudioClient.open_serial(port)` を使う。Task1 で `roba info` 疎通確認済み。

## Global Constraints

- 常に known-good へ即戻せること: 確実な全戻しは `client.reset_settings()`（nvs→devicetree 既定）で担保。物理 uf2 `settings_reset` は最終手段。
- 破壊的操作（`key set`）は実行前に対象キーの現 behavior を backup ログへ記録してから行う。
- 転送は BLE のみ（このファームは USB studio-rpc-uart 除外済み）。
- ロック解除不要（`CONFIG_ZMK_STUDIO_LOCKING=n`）。
- CLI 出力は機械可読 JSON（成功は結果オブジェクト、失敗は `{"error": "..."}` を stderr/stdout に）。
- 依存はピン留め: `zmk-studio-api==0.3.1`。
- 配置: 本リポジトリ `tools/roba-cli/`。

---

## File Structure

- `tools/roba-cli/pyproject.toml` — プロジェクト定義・依存・`roba` エントリポイント
- `tools/roba-cli/roba_cli/__init__.py` — パッケージ
- `tools/roba-cli/roba_cli/behaviors.py` — behavior 文字列パーサ（純）＋ zmk オブジェクト builder（薄）
- `tools/roba-cli/roba_cli/connection.py` — roBa を BLE で探索して `StudioClient` を開く
- `tools/roba-cli/roba_cli/cli.py` — argparse・コマンド分岐・JSON 出力・backup ログ
- `tools/roba-cli/tests/test_behaviors.py` — パーサ単体テスト（ハード不要）
- `tools/roba-cli/README.md` — 使い方と「戻し方」ランブック

---

## Task 1: プロジェクト雛形 + BLE 疎通 + `roba info`

**Files:**
- Create: `tools/roba-cli/pyproject.toml`
- Create: `tools/roba-cli/roba_cli/__init__.py`
- Create: `tools/roba-cli/roba_cli/connection.py`
- Create: `tools/roba-cli/roba_cli/cli.py`

**Interfaces:**
- Produces: `connection.find_roba_device_id() -> str | None`、`connection.open(device_id: str | None) -> StudioClient`、`cli.main(argv: list[str]) -> int`、コマンド `roba info`。

- [ ] **Step 1: venv 作成と依存インストール、BLE スタブでないことを確認（スパイク）**

```bash
cd tools/roba-cli
python3 -m venv .venv && . .venv/bin/activate
pip install "zmk-studio-api==0.3.1" pytest
python -c "import zmk_studio_api as zmk; print(zmk.StudioClient.list_ble_devices())"
```
Expected: roBa を含むデバイス一覧（例 `[('F8:9A:A2:21:64:D4', 'roBa')]`）。
もし `RuntimeError: BLE not enabled`（feature 無し wheel）なら contingency:
```bash
pip install maturin
pip install "git+https://github.com/srwi/zmk-studio-api.git#subdirectory=." --config-settings=build-args="--features ble"
```
（それでも不可なら spec §11 の代替＝公式 TS クライアント検討。ここで停止して報告）

- [ ] **Step 2: `pyproject.toml` を作成**

```toml
[project]
name = "roba-cli"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = ["zmk-studio-api==0.3.1"]

[project.scripts]
roba = "roba_cli.cli:run"

[project.optional-dependencies]
dev = ["pytest"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 3: `roba_cli/__init__.py` を作成（空）**

```python
```

- [ ] **Step 4: `roba_cli/connection.py` を作成**

```python
from __future__ import annotations

import zmk_studio_api as zmk

ROBA_NAME = "roBa"


def find_roba_device_id() -> str | None:
    """ペア済み BLE から roBa の device_id を返す。無ければ None。"""
    for device_id, local_name in zmk.StudioClient.list_ble_devices():
        if (local_name or "") == ROBA_NAME:
            return device_id
    return None


def open(device_id: str | None = None) -> "zmk.StudioClient":
    """roBa に BLE 接続した StudioClient を返す。"""
    target = device_id or find_roba_device_id()
    if target is None:
        raise RuntimeError("roBa not found over BLE. Pair/connect the keyboard first.")
    return zmk.StudioClient.open_ble(target)
```

- [ ] **Step 5: `roba_cli/cli.py` を作成（`info` のみ）**

```python
from __future__ import annotations

import argparse
import json
import sys

from . import connection


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def cmd_info(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    _emit({
        "lock_state": client.get_lock_state(),
        "behavior_count": len(client.list_all_behaviors()),
        "keymap_bytes": len(client.get_keymap_bytes()),
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roba")
    parser.add_argument("--device", default=None, help="BLE device id (default: auto-detect roBa)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="Show device/lock/keymap summary").set_defaults(func=cmd_info)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - CLI 境界で JSON エラーに変換
        _emit({"error": str(exc)})
        return 1


def run() -> None:
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 6: editable install して `roba info` を実機実行**

Run:
```bash
pip install -e .
roba info
```
Expected: `{"lock_state": "...", "behavior_count": <n>, "keymap_bytes": <n>}` が出る（実機 roBa 接続）。
失敗時は `{"error": "..."}` と exit 1。

- [ ] **Step 7: Commit**

```bash
git add tools/roba-cli/pyproject.toml tools/roba-cli/roba_cli/
git commit -m "feat(roba-cli): scaffold CLI with BLE connection and info command"
```

---

## Task 2: behavior 文字列パーサ（純ロジック・TDD）

> 注: behavior の文法はユーザー設計判断の好適点。学習スタイル運用時は実装前に `TODO(human)` 化して入力を仰いでよい。

**Files:**
- Create: `tools/roba-cli/roba_cli/behaviors.py`
- Test: `tools/roba-cli/tests/test_behaviors.py`

**Interfaces:**
- Produces: `behaviors.BehaviorSpec(kind: str, args: tuple)`、`behaviors.parse_behavior(spec: str) -> BehaviorSpec`、`behaviors.build_behavior(spec: BehaviorSpec, zmk) -> Behavior`。
- Consumes: Task1 は無し。Task3 が `parse_behavior` / `build_behavior` を使う。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tools/roba-cli/tests/test_behaviors.py
import pytest

from roba_cli.behaviors import BehaviorSpec, parse_behavior


def test_keypress():
    assert parse_behavior("KP A") == BehaviorSpec("KeyPress", ("A",))


def test_keypress_lowercase_head():
    assert parse_behavior("kp ENTER") == BehaviorSpec("KeyPress", ("ENTER",))


def test_transparent():
    assert parse_behavior("trans") == BehaviorSpec("Transparent", ())


def test_momentary_layer():
    assert parse_behavior("MO 5") == BehaviorSpec("MomentaryLayer", (5,))


def test_raw():
    assert parse_behavior("RAW 12 1 0") == BehaviorSpec("Raw", (12, 1, 0))


def test_unknown_raises():
    with pytest.raises(ValueError):
        parse_behavior("WAT 1")


def test_keypress_arity_error():
    with pytest.raises(ValueError):
        parse_behavior("KP")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tools/roba-cli && . .venv/bin/activate && pytest tests/test_behaviors.py -v`
Expected: FAIL（`ModuleNotFoundError: roba_cli.behaviors` または ImportError）

- [ ] **Step 3: 最小実装を書く**

```python
# tools/roba-cli/roba_cli/behaviors.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BehaviorSpec:
    kind: str
    args: tuple


def parse_behavior(spec: str) -> BehaviorSpec:
    parts = spec.split()
    if not parts:
        raise ValueError("empty behavior spec")
    head = parts[0].upper()
    rest = parts[1:]
    if head in ("KP", "KEYPRESS"):
        if len(rest) != 1:
            raise ValueError("KP requires exactly one keycode, e.g. 'KP A'")
        return BehaviorSpec("KeyPress", (rest[0].upper(),))
    if head in ("TRANS", "TRANSPARENT"):
        return BehaviorSpec("Transparent", ())
    if head in ("MO", "MOMENTARYLAYER"):
        if len(rest) != 1:
            raise ValueError("MO requires one layer id, e.g. 'MO 5'")
        return BehaviorSpec("MomentaryLayer", (int(rest[0]),))
    if head == "RAW":
        if len(rest) != 3:
            raise ValueError("RAW requires behavior_id param1 param2")
        return BehaviorSpec("Raw", (int(rest[0]), int(rest[1]), int(rest[2])))
    raise ValueError(f"unknown behavior: {spec!r}")


def build_behavior(spec: BehaviorSpec, zmk):
    if spec.kind == "KeyPress":
        return zmk.KeyPress(getattr(zmk.Keycode, spec.args[0]))
    if spec.kind == "Transparent":
        return zmk.Transparent()
    if spec.kind == "MomentaryLayer":
        return zmk.MomentaryLayer(spec.args[0])
    if spec.kind == "Raw":
        return zmk.Raw(*spec.args)
    raise ValueError(f"cannot build behavior of kind {spec.kind!r}")
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/test_behaviors.py -v`
Expected: PASS（7 件）

- [ ] **Step 5: Commit**

```bash
git add tools/roba-cli/roba_cli/behaviors.py tools/roba-cli/tests/test_behaviors.py
git commit -m "feat(roba-cli): add behavior spec parser and builder with tests"
```

---

## Task 3: `key get` / `key set`（backup ログ + 永続化・HIL）

**Files:**
- Modify: `tools/roba-cli/roba_cli/cli.py`

**Interfaces:**
- Consumes: `connection.open`、`behaviors.parse_behavior`、`behaviors.build_behavior`。
- Produces: コマンド `roba key get <layer> <pos>`、`roba key set <layer> <pos> "<behavior>"`、backup ログ `tools/roba-cli/.roba-backup.jsonl`。

- [ ] **Step 1: `cli.py` に key サブコマンドを追加**

`cli.py` の import 群に追記:
```python
import datetime as _dt
from pathlib import Path

from . import behaviors
```

`_emit` の下に追記:
```python
BACKUP_LOG = Path(__file__).resolve().parent.parent / ".roba-backup.jsonl"


def _append_backup(entry: dict) -> None:
    entry["ts"] = _dt.datetime.now().isoformat(timespec="seconds")
    with BACKUP_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_key_get(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    behavior = client.get_key_at(args.layer, args.position)
    _emit({"layer": args.layer, "position": args.position,
           "kind": behavior.kind, "repr": repr(behavior)})
    return 0


def cmd_key_set(args: argparse.Namespace) -> int:
    import zmk_studio_api as zmk
    client = connection.open(args.port)
    before = client.get_key_at(args.layer, args.position)
    _append_backup({"op": "set", "layer": args.layer, "position": args.position,
                    "before_kind": before.kind, "before_repr": repr(before),
                    "new": args.behavior})
    spec = behaviors.parse_behavior(args.behavior)
    client.set_key_at(args.layer, args.position, behaviors.build_behavior(spec, zmk))
    client.save_changes()
    _emit({"layer": args.layer, "position": args.position,
           "before": repr(before), "after_spec": args.behavior, "saved": True})
    return 0
```

`build_parser()` の `info` 定義の下に追記:
```python
    key = sub.add_parser("key", help="Per-key get/set").add_subparsers(dest="key_cmd", required=True)
    kg = key.add_parser("get")
    kg.add_argument("layer", type=int)
    kg.add_argument("position", type=int)
    kg.set_defaults(func=cmd_key_get)
    ks = key.add_parser("set")
    ks.add_argument("layer", type=int)
    ks.add_argument("position", type=int)
    ks.add_argument("behavior", help="e.g. 'KP B', 'trans', 'MO 5'")
    ks.set_defaults(func=cmd_key_set)
```

- [ ] **Step 2: 可逆な実機テスト（手順実行）**

Run（未使用キーで実施。例: FUNCTION レイヤー=4 の空き位置を選ぶ。まず get で現状確認）:
```bash
roba key get 0 0
roba key set 0 0 "KP B"
roba key get 0 0
```
Expected: set 後の `key get` の `kind` が `KeyPress`、`repr` に `B` が含まれる。`.roba-backup.jsonl` に before が1行記録される。

- [ ] **Step 3: 戻せることを確認（Task4 の reset を先取り確認、無ければ手動で元キーコードを set）**

Run:
```bash
roba key set 0 0 "KP A"   # 元が A だった場合。before_repr を見て正しい元へ戻す
roba key get 0 0
```
Expected: 元の behavior に戻る。

- [ ] **Step 4: Commit**

```bash
git add tools/roba-cli/roba_cli/cli.py
git commit -m "feat(roba-cli): add key get/set with backup log and persistence"
```

---

## Task 4: `reset` / `snapshot` + 戻し方ランブック（安全網・HIL）

**Files:**
- Modify: `tools/roba-cli/roba_cli/cli.py`
- Create: `tools/roba-cli/README.md`

**Interfaces:**
- Consumes: `connection.open`。
- Produces: コマンド `roba reset`、`roba snapshot [path]`。

- [ ] **Step 1: `cli.py` に reset / snapshot を追加**

`cmd_key_set` の下に追記:
```python
def cmd_reset(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    ok = client.reset_settings()
    _emit({"reset_settings": ok, "note": "nvs reverted to devicetree defaults"})
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    client = connection.open(args.port)
    data = client.get_keymap_bytes()
    out = Path(args.path) if args.path else (
        BACKUP_LOG.parent / f"keymap-snapshot-{_dt.datetime.now():%Y%m%d-%H%M%S}.bin")
    out.write_bytes(data)
    _emit({"snapshot": str(out), "bytes": len(data),
           "note": "record only; full restore is via 'reset' (no set_keymap_bytes API)"})
    return 0
```

`build_parser()` に追記:
```python
    sub.add_parser("reset", help="Revert nvs to devicetree defaults").set_defaults(func=cmd_reset)
    snap = sub.add_parser("snapshot", help="Save raw keymap bytes for record")
    snap.add_argument("path", nargs="?", default=None)
    snap.set_defaults(func=cmd_snapshot)
```

- [ ] **Step 2: 実機で安全網を検証**

Run:
```bash
roba snapshot
roba key set 0 0 "KP Z"
roba reset
roba key get 0 0
```
Expected: `reset` 後の `key get` が devicetree 既定（=flash 済みファームの元 behavior）に戻る。`snapshot` で .bin が出力される。

- [ ] **Step 3: 再起動跨ぎの永続化を確認**

Run（手順）: `roba key set 0 0 "KP B"` → roBa を一度電源オフ/オン → `roba key get 0 0`
Expected: `B` が保持されている（nvs 永続化）。確認後 `roba reset` で戻す。

- [ ] **Step 4: README に戻し方ランブックを記載**

```markdown
# roba-cli (SP0)

roBa を BLE 経由で焼かずに設定変更する CLI。

## セットアップ
    python3 -m venv .venv && . .venv/bin/activate
    pip install -e .

## コマンド
- `roba info` — デバイス/ロック/keymap サマリ
- `roba key get <layer> <pos>` — キーの現 behavior
- `roba key set <layer> <pos> "<behavior>"` — 変更して保存（例 `"KP B"`, `"trans"`, `"MO 5"`）
- `roba snapshot [path]` — 現 keymap 生バイトを記録
- `roba reset` — devicetree 既定へ全戻し（第一の安全網）

## 戻し方（重要）
1. まず `roba reset`（nvs を devicetree 既定へ。flash 済みファームの元 keymap に戻る）
2. 直前変更の内容は `.roba-backup.jsonl` に before_repr が残る
3. 最終手段: `settings_reset` uf2 を書込（リセット ダブルタップ→マウント→コピー。物理操作）
```

- [ ] **Step 5: Commit**

```bash
git add tools/roba-cli/roba_cli/cli.py tools/roba-cli/README.md
git commit -m "feat(roba-cli): add reset/snapshot safety net and revert runbook"
```

---

## Self-Review（spec 照合）

- **§3 やること（接続→keymap 読取→キー変更→永続化→復元）**: Task1(接続/読取) / Task3(変更/永続化) / Task4(復元) で網羅。✓
- **§2.5 横断要件（常に戻せる）**: Task4 `reset`(=`reset_settings`) と README ランブック、Task3 の backup ログで充足。✓
- **§5 動詞（info/key get/key set/snapshot/reset）**: Task1/3/4 で全て実装。✓
- **§8 テスト方針（非破壊→可逆→薄い単体）**: Task1(非破壊 info)、Task2(単体 TDD)、Task3/4(可逆 HIL) に対応。✓
- **§9 スパイク（BLE 疎通／wheel feature）**: Task1 Step1 に contingency 込みで配置。✓
- **§10 DoD**: Task1(info/dump 相当=keymap_bytes)、Task3(set→get→永続化)、Task4(reset で known-good 復帰) で達成。✓
- Placeholder 走査: 「適切に処理」等の曖昧記述なし。各コードステップは実コード。✓
- 型整合: `BehaviorSpec(kind,args)` / `parse_behavior` / `build_behavior` / `connection.open` / `find_roba_device_id` の名称は Task 間で一致。✓
- 既知の割り切り: 任意 behavior のピンポイント復元は API 非対応（spec §2.5 記載）。SP0 は全戻し(`reset`)で担保し、`snapshot` は記録用。
