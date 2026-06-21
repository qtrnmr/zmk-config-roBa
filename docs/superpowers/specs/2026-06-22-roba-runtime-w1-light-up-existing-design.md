# W1: 既存カバレッジの点灯（Light up existing runtime-editable coverage）— 設計

**日付**: 2026-06-22
**プロジェクト**: 焼かずに Claude Code から roBa の ZMK 設定を runtime 編集（[[project_roba_studio_cli]] の主目的＝全機能ホットスワップ）
**位置づけ**: SP0(keymap CLI 土台) / SP1(runtime マクロ) に続く第3単位。主目的「現状 roBa が使う ZMK 機能を全部、焼き直しなしで編集できる」に向け、**まず "既に runtime 化されている能力" を配線して点灯する**フェーズ。

---

## 背景：精密棚卸しの結論（2026-06-22, source-grounded）

roBa が実際に使う ZMK 機能を、現状 runtime 編集できるか source で精査した結果：

| 機能 | runtime 編集 | 手段 | roBa 現状 |
|---|---|---|---|
| (a) キーごとのバインディング | ✅ | Studio native `set_layer_binding` | SP0 `key get/set` 配線済 |
| (b) レイヤー 追加/削除/改名/並替 | ✅ | Studio native `add/remove/move/restore_layer`,`set_layer_props` | **未公開** ← W1a |
| (c) マクロのキー列 | ✅ | 自作 `zmk__macros` (SP1) | SP1 `macro get/set` |
| (h) トラックボール/ポインタ設定 | ✅ | cormoran `runtime-input-processor`(`cormoran_rip`) | **ビルドで外してある** ← W1b |
| 活動タイムアウト | ✅ | cormoran `zmk__settings` | 無効化中 ← W1c(任意) |
| BLE プロファイル/デバイス名 | ✅ | cormoran `cormoran_ble` | 無効化中 ← W1c(任意) |
| (d) combos / (e) hold-tap時間 / (f) sensor binding / (g) conditional layers | ❌ | **世界のどこにも無い**（upstream も Planned 止まり） | 後続 W2 で自作 |

**結論**: 「全部ホットスワップ」の到達には、自作が要るのは (d)(e)(f)(g) の4つだけ。残りは既存能力の**配線**で点く。W1 はその配線フェーズ。「作り直さない・既存OSS並行利用」というユーザー方針に最も忠実。

---

## スコープ

**含む**:
- **W1a** — レイヤー管理を roba-cli に公開（Studio native、ファーム不変）
- **W1b** — トラックボール/ポインタ設定の runtime 編集（cormoran `runtime-input-processor` 有効化＋host 配線）

**任意（余力があれば、本 spec の末尾に設計を置くが実装は別判断）**:
- **W1c** — 活動タイムアウト＋BLEプロファイル/デバイス名（cormoran `settings-rpc` / `ble-management`）

**含まない**:
- (d)(e)(f)(g) の自作モジュール（後続 W2）
- OSS 公開（主目的達成後、余力があれば）

## 横断制約（全 SP 共通・[[feedback_roba_always_revertible]]）

- **常時 known-good へ即 revert 可能**を維持。新しい書き込み経路は必ず①**read-before-write バックアップ**（`tools/roba-cli/.roba-backup.jsonl` に追記、SP0/SP1 と同形式）と②**reset 経路で戻る**ことを確認。
- 各 cormoran モジュールは独自 NVS を持つ。点灯する各機能で「`roba reset`(Studio `reset_settings`) で戻るか」を実機確認し、戻らなければ `ZMK_RPC_SUBSYSTEM_SETTINGS_RESET` hook 相当で対応（SP1 のマクロ store と同じ知見）。
- transport は USB serial（`studio-rpc-usb-uart` snippet）。roBa_L 不変。
- host 出力は JSON（既存 verb と一貫）。

---

## W1a — レイヤー管理の公開（ファーム不変・最優先・ノーリスク）

### 何を足すか
Studio native の keymap RPC（`config/.../keymap.proto` で確認済み）に既にある操作を host に出す：
- `roba layer list` → `get_keymap` で `[{id, name, binding数}]` を JSON 出力
- `roba layer rename <layer_id> <name>` → `set_layer_props`
- `roba layer add` → `add_layer`（devicetree 定義済みの空きレイヤー枠に限る＝Studio の制約）
- `roba layer remove <index>` → `remove_layer`
- `roba layer move <start_index> <dest_index>` → `move_layer`
- `roba layer restore <layer_id> <at_index>` → `restore_layer`（削除の取り消し）
- いずれも `save_changes` を伴い、変更前に `get_keymap` をバックアップ追記

### 設計上の単位
- `tools/roba-cli/roba_cli/layer_client.py`（または既存 `connection.py` のクライアントに layer 操作を追加）。`zmk_studio_api` が layer 操作をラップしていればそれを使い、無ければ `keymap.Request` を直接送る（SP0 の `set_layer_binding` 経路と同形）。
- `cli.py` に `layer` サブコマンド群を追加。
- **revert**: `remove` は `restore_layer`（同一セッション内）と、最終的に `roba reset` で devicetree 既定へ全戻し。`add/move/rename` も `reset` で戻る。バックアップに変更前 keymap スナップショットを残す。

### 受け入れ条件
- `roba layer list` が現行15層を id/name 付きで列挙。
- 改名→`list` 再読込で反映、電源オフ→再接続で永続、`roba reset` で既定名に復帰（実機 E2E）。
- リスクゼロ＝ファーム再ビルド不要。既存ファームのまま動く。

---

## W1b — トラックボール/ポインタ設定の runtime 編集（W1 本命）

### 既存能力（cormoran `runtime-input-processor`, subsystem `cormoran_rip`）
host から reflash 無しに変更可（research で source 確認）：
- scale multiplier / scale divisor（実効感度＝CPI 相当）
- rotation degrees、X invert、Y invert、XY swap
- XY→scroll 有効化、axis-snap mode/threshold/timeout
- temp-layer 有効化/target-layer/activation-delay/deactivation-delay、active-layers bitmask
- **reset-to-defaults**（＝revert の核）
- 読み取り: list/get processors, get layer info

### 関門：ビルドエラー
現状このモジュールは roBa_R で無効化されている。理由は**2つの別問題**：
1. `runtime-input-processor.dtsi:17` が現 Zephyr/ZMK base で **devicetree 前処理に失敗**（コミット a2f4bce/5ce16fc が記録）。→ W1b の主たる関門。
2. （別件）ble-management 系の `zmk_endpoint_*_preferred_transport` 未定義 link error は multi-endpoint＋ble-management の組合せで発生するもので、`runtime-input-processor` 単体には**無関係の可能性が高い**（要確認）。

### 方針
- まず `runtime-input-processor` を**単体で**有効化し、`dtsi:17` の前処理エラーの実体を特定（必要な define / 依存 dtsi / roBa overlay 側で供給すべき node）。ble-management 等は引き続き無効のまま。
- 解決したら `roBa_R.conf` に `CONFIG_ZMK_RUNTIME_INPUT_PROCESSOR=y` / `_STUDIO_RPC=y`、overlay に必要な input-processors property を復活。
- host: `roba_cli/rip_client.py`（`cormoran_rip` の custom 封筒2段＝list_custom_subsystems→index→call、SP1 `macro_client.py` と同形）＋ `cli.py` に `roba trackball get|set <key> <value>` / `roba trackball reset`。
- **revert**: `cormoran_rip` の reset-to-defaults op を `roba trackball reset` に割当。`roba reset`(Studio) でモジュール NVS が戻るかを実機確認、戻らなければ settings-reset hook 対応を検討。
- **時間箱**: `dtsi:17` が深掘り案件（base 側の非互換など）と判明したら、W1b を中断して W1a の成果＋判断をユーザーへ。known-good（現 HEAD）へはいつでも戻せる。

### 受け入れ条件
- roBa_R がモジュール有効でビルド成功（CI green）。
- `roba trackball set scale-divisor N` 等が反映（カーソル感度が体感変化）、`roba trackball reset` で既定復帰、電源オフ→再接続で永続（実機 E2E）。
- known-good 復元手順が明文化され、いつでも現行ファームへ戻せる。

---

## W1c — 活動タイムアウト＋BLE（任意・後回し）

- `zmk__settings`(settings-rpc): idle/sleep timeout の get/set。`cormoran_ble`(ble-management): BLE プロファイル view/switch/unpair、デバイス名。
- 関門：multi-endpoint＋ble-management の `zmk_endpoint_*_preferred_transport` 未定義 link error（pinned base に無い）。W1 で最難。実用度も低め。
- W1a/W1b 完了後に余力があれば着手。host 配線は `cormoran_rip` と同パターン。

---

## 全体アーキテクチャ

- host `tools/roba-cli` を**唯一の操作面**として、機能ごとにクライアント module（`layer_client` / `rip_client` / 既存 `macro_client`）を足し、`cli.py` が verb を束ねる。SP0/SP1 の framing(XORなし)・custom 封筒2段・JSON 出力・バックアップ追記を共通基盤として再利用。
- ファーム側は「既存モジュールの有効化」が中心で、W1 では新規 behavior driver は作らない（自作は W2）。
- revert はレイヤ別に：Studio 系=`reset_settings`＋`save/discard`/`restore_layer`、cormoran 系=各モジュールの reset op（必要なら settings-reset hook）。

## テスト戦略

- W1a: host 単体テスト（layer list の JSON 整形、引数パース）＋実機 E2E（改名/追加/削除→list→電源再投入→reset）。
- W1b: host 単体テスト（`cormoran_rip` 封筒のエンコード/デコード、値域）＋ビルド成功（CI）＋実機 E2E（感度変更の体感→reset→永続確認）。
- 既存 15 テスト（framing/dsl/behaviors）は不変で緑を維持。

## known-good / ロールバック

- 現 HEAD `4a98e16`（SP1 マージ、クリーン）が known-good。W1 は機能追加なので、各単位はブランチで実装し、ビルド/実機確認後にマージ。問題時は HEAD へ戻すだけで現行ファームに復帰。
