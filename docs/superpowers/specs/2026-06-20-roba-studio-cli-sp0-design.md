# roBa 設定を「焼かずに Claude Code から変更」する — SP0 設計

- 日付: 2026-06-20
- 対象リポジトリ: `qtrnmr/zmk-config-roBa`
- 対象ハード: roBa（split, 右=セントラル, `seeeduino_xiao_ble` / nRF52840）

## 1. 背景と最終ゴール

ファームを毎回焼き直さずに、Claude Code から接続した状態で roBa の設定（最終的には
keymap・マクロ・combos・hold-tap・エンコーダ）を変更したい。

現状の `config/roBa.keymap` の「マクロ」は文字列入力ではなく、レイヤー/BT 切替の
オーケストレーション（`to_layer_0`、`bt_to_win0` など）。ユーザーが変えたいのは
マクロ単体ではなく設定全般であり、それぞれ「焼かずに変更できるか」が異なる。

| 設定 | 焼かずに変更 | 手段 |
|---|:--:|---|
| キー割り当て / レイヤー有効化 / behavior のキー配置 | ✅ | ZMK Studio RPC（本ファームは `CONFIG_ZMK_STUDIO=y`、keymap に `&studio_unlock` 配線済み） |
| トラックボール CPI / オートマウス / スクロール / 電源 | ✅ | dya settings-rpc / runtime-input-processor |
| combos / マクロの中身 / hold-tap / エンコーダ / conditional layers | ❌ | devicetree。runtime 化にはファーム拡張が必要 |

### アーキテクチャ方針（決定済み）

**ZMK Studio コアを拡張する**路線を採用（ゼロからの新規プロトコル自作は不採用）。
理由: 転送(USB serial / BLE GATT)・protobuf・ロック・GUI/クライアントが既存で、
本家が combos/マクロの runtime 化を「Studio コア拡張」として設計している領域と一致する。
cormoran/dya 自体が「Studio を拡張する」エコシステムであり流儀とも合致する。

## 2. プロジェクト分解

②（全部 runtime 化）は 1 spec に収まらないため、サブプロジェクトに分解し各々で
spec→plan→実装を回す。

| # | サブプロジェクト | 内容 | 依存 |
|---|---|---|---|
| **SP0** | **CLI 土台（本書）** | 既存 Studio プロトコルを BLE で叩く CLI を作り「接続→keymap 読取→キー1個変更→永続化→復元」を通す。①サブセットが実用化し、以降の足場になる | なし |
| SP1 | runtime マクロストア | nvs ベースの編集可能マクロ定義＋実行 behavior＋RPC＋CLI 動詞 | SP0 |
| SP2 | runtime combos | combos を nvs 化 | SP0/SP1 |
| SP3 | runtime hold-tap / behavior props | tapping-term・flavor 等。USB シリアル転送の復活もここで検討 | SP0 |
| SP4 | エンコーダ / センサー bindings | 回転挙動の runtime 化 | SP0 |

本書は **SP0 のみ**を確定スコープとする。SP1 以降は別 spec。

## 2.5. 横断要件: 常に「すぐ戻せる」(ユーザー必須要求)

全 SP に適用する最優先の制約。**いつでもワンステップで known-good 状態へ戻せる**こと。

- 変更前に必ず現状を退避する（SP0: `keymap dump` の JSON スナップショット / ファーム変更を伴う SP: known-good `.uf2` を保管）。
- 破壊的操作は必ず可逆操作とセットで実装・提示する（「変更」を出すなら「戻す」も同時に）。
- 復元の段階的フォールバック:
  1. CLI `restore`（直前変更を戻す）
  2. CLI `reset`（runtime 変更を全消去＝devicetree 既定へ）
  3. 最終手段 `settings_reset` uf2 で nvs 初期化（`build.yaml` に定義済み。リセット ダブルタップ→書込は物理操作が必要）

## 3. SP0 スコープ

### やること
- BLE で roBa に接続し、Studio RPC で keymap を読み、キー1個を変更・永続化・復元する
  Claude Code から駆動可能な CLI を作る。
- **変更前スナップショットと復元を必須機能として含める**（§2.5）。

### やらないこと（YAGNI / 明示的に範囲外）
- マクロ / combos / hold-tap / エンコーダの runtime 化（SP1 以降）
- ファーム（C / devicetree）の改造
- GUI
- USB シリアル転送（現ファームでは `studio-rpc-usb-uart` が build 都合で除外済み。SP3 で再検討）

## 4. 技術前提（調査で確定）

- ZMK Studio 転送は BLE(GATT) と USB serial(CDC-ACM) の2系統。**本ファームは BLE のみ有効**
  （`roBa_R.conf`: `CONFIG_ZMK_STUDIO_TRANSPORT_BLE=y` / コミット `drop studio-rpc-usb-uart` で USB 側は除外）。
- **ロック解除不要**: `roBa_R.conf` が `CONFIG_ZMK_STUDIO_LOCKING=n`。`&studio_unlock` の儀式は省略可。
- 流用クライアント: **`srwi/zmk-studio-api`**（Rust + Python, Serial + BLE 両対応, keymap 読取・変更）。
  protobuf スキーマは `zmkfirmware/zmk-studio-messages`（`studio.proto` → `core/behaviors/keymap.proto`）。
- BLE デバイス: 名前 `roBa` / アドレス `F8:9A:A2:21:64:D4` / VID `0x1D50` / PID `0x615E`。

## 5. コンポーネント

- **`tools/roba-cli/`**（本リポジトリ内 Python プロジェクト）: `zmk-studio-api` を薄くラップ。
- CLI 動詞（最小）:
  - `roba info` — デバイス情報・レイヤー一覧を JSON 出力
  - `roba keymap dump` — 現キーマップを JSON 取得
  - `roba key set <layer> <pos> <behavior>` — キー1個を変更
  - `roba snapshot [path]` — 現キーマップを known-good として保存（変更前に自動でも取る）
  - `roba restore [path]` — スナップショット（既定: 直近）へ全体復元
  - `roba reset` — runtime 変更を全消去し devicetree 既定へ戻す
- 出力は**機械可読(JSON)**。Claude Code がパースして次手を判断できる形にする。

## 6. データフロー

```
Claude Code → roba-cli(コマンド) → zmk-studio-api → BLE GATT → roBa
            ← stdout(JSON)       ←                 ← 応答    ←
```

- 接続: BLE で `roBa`（`F8:9A:A2:21:64:D4`）を探索して接続。
- ロック解除は不要（§4）。

## 7. エラー処理

- デバイス未検出 / BLE 切断 / 保存失敗 は JSON の `error` フィールドで返す（Claude が判定可能に）。
- 破壊的操作は `key set` のみ。実行前に `dump` で事前状態を退避し、失敗時は `restore` で戻す。

## 8. テスト方針（ハードウェア・イン・ザ・ループ）

1. **非破壊**: `info` / `keymap dump` が通る（読取のみ）＝接続実証。
2. **可逆**: 未使用キー1個を `set` → `dump` で反映確認 → `restore` で復元。
3. 自動 unit test は薄く（CLI 引数解析・JSON 整形のみ）。本質は実機確認。

## 9. 最初の技術スパイク（実装初手でリスクを潰す）

- `zmk-studio-api` が protobuf v3 / macOS の BLE で実際に roBa に繋がるか、最小コードで疎通確認。
- ここを通してから動詞を肉付けする。スパイクが失敗した場合の代替: 公式 TS クライアント
  `@zmkfirmware/zmk-studio-ts-client`、または USB シリアル転送の復活（build 修正込み）。

## 10. 完了条件（SP0 Definition of Done）

- `roba info` と `roba keymap dump` が実機 roBa に対し JSON を返す。
- `roba key set` → `dump` で反映確認 → `restore` で復元、が一連で通る。
- 変更が再起動後も保持される（nvs 永続化の確認）。
- `roba snapshot`/`restore`/`reset` で known-good へ確実に戻せる（§2.5 の要件充足）。

## 11. リスクと留意点

- **方針転換**: 従来 memory の「ZMK Studio runtime keymap edit は使わない」を本プロジェクトで
  意図的に反転する。memory を更新済み。
- `zmk-studio-api` の成熟度・macOS BLE 対応が未検証（§9 のスパイクで先に確認）。
- BLE は USB シリアルより遅延・切断リスクがある。SP1 以降で頻繁に書くなら USB 復活を再検討。
