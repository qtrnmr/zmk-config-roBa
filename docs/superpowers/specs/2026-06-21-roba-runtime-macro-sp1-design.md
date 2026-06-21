# roBa runtime マクロ編集 — SP1（最小バーティカルスライス）設計

- 日付: 2026-06-21
- 対象リポジトリ: `qtrnmr/zmk-config-roBa`
- 対象ハード: roBa（右=セントラル, `seeeduino_xiao_ble` / nRF52840）, cormoran `v0.3-branch+dya`
- 前提: SP0 完了（USB serial 経由で標準 ZMK Studio が `zmk-studio-api` と疎通、`tools/roba-cli` 稼働）。
  関連: `2026-06-20-roba-studio-cli-sp0-design.md`

## 1. 目的

ファームを焼き直さず、Claude Code から接続した状態で**マクロの中身（送出キー列）を編集・永続化・実行**できるようにする。
SP1 はその最小バーティカルスライス：**マクロ1スロット**を serial 越しに編集→nvs永続→実行まで通し、
本機能の 5 大技術リスクを小さく全て踏んで de-risk する。

### 全体計画における位置
SP1（本書, 1スロット walking skeleton）→ SP2 複数スロット/プールUI → SP3 Rust/公式クライアント整備
→ SP4 任意 behavior ステップ(③) → … 各々別 spec。

## 2. スコープ

### やること（v1 確定）
- マクロ**1スロット**（`&rt_macro 0`）を devicetree に事前宣言し、押下で nvs 上のステップ列を実行。
- ステップは**キー入力＋ステップ毎の wait/tap 制御**（ヒアリング ①+②）。
- ホスト `roba-cli` から `macro get/set` で中身を編集、nvs 永続、再起動を跨いで保持。
- 編集チャネルは firmware に新 RPC サブシステム `zmk.macros` を追加し、ホストは SP0 の serial+framing を再利用。

### やらないこと（YAGNI / 別 spec）
- 複数スロット・プールUI・GUI。
- ③ 任意 behavior をステップに（`&mo`/`&to`/ネストマクロ等）。※ストア形式に type タグを持たせ前方互換にはする。
- `zmk-studio-api`(Rust) の fork / 公式クライアント対応。
- BLE 経由（USB serial のみ）。

## 3. 技術前提とリスク（調査で確定）

ZMK マクロは devicetree `zmk,behavior-macro` の固定 `bindings[]` をコンパイル時に flash へ焼く方式
（`app/src/behaviors/behavior_macro.c`）。runtime 編集は上流・他フォークに**前例なし**（本家 Studio は
「macros = Planned」、dynamic-macros PR #2678 は録音式 RAM・非永続）。新規に nvs ストア＋実行 behavior＋
RPC を作る中規模ファーム実装。

| # | リスク | 本スライスでの扱い |
|---|---|---|
| R1 | Zephyr はデバイス実体をコンパイル時登録＝runtime にマクロ“数”を増やせない | **固定1スロットを devicetree 事前宣言**で踏む（最小プール） |
| R2 | nvs 可変長レコード（`CONFIG_NVS_MAX_ELEM_SIZE` ≒ sector/4）・flash 摩耗 | 1スロット・上限ステップ数を設け1レコードに収める |
| R3 | `behavior_local_id` がビルドで振り直り保存データが壊れる | **ステップを HID キーコードで直接保存**し回避（③を入れない理由） |
| R4 | nRF52840 RAM（BLE+Studio で逼迫） | 1スロット・小さな RAM キャッシュのみ |
| R5 | proto 拡張＝クライアント保守の尾 | firmware に proto 追加、**ホストは Python で生成バインディング＋既存 transport**。Rust fork しない |

## 4. アーキテクチャ

SP0 の「ZMK Studio コア拡張」路線を踏襲。firmware に `zmk.macros` RPC・nvs マクロストア・実行 behavior を追加。
ホストは SP0 の serial チャネル（CDC + framing: SoF `0xAB`/EoF `0xAD`/Esc `0xAC`）を再利用し、ローカル拡張 proto から
**Python バインディングを生成**して `roba-cli` がメッセージを組む。Rust クライアントは触らない。

## 5. コンポーネント

### 5.1 firmware（cormoran fork に追加 — west の zmk か自前モジュールとして）
- **`zmk,behavior-runtime-macro` ドライバ**: devicetree で**1スロット事前宣言**（`&rt_macro` を keymap の1キーに配置）。
  押下時に RAM キャッシュのステップ列を読み、各ステップを `&kp`(tap) 相当でキュー投入（wait/tap 反映）。
  空スロットは no-op。
- **nvs マクロストア**: Zephyr settings。キー `rt_macro/0` に 1 blob 保存：
  - header: `version:u8`, `step_count:u8`
  - steps[]: `type:u8`(0=key), `keycode:u16`(HID usage, 修飾は別バイト `mods:u8`), `wait_ms:u16`, `tap_ms:u16`
  - 上限: `MAX_STEPS`（例 32）。型タグで③拡張に前方互換。
- **RPC ハンドラ `zmk.macros`**:
  - `GetMacro(slot) -> { steps[] }`
  - `SetMacro(slot, steps[]) -> { status }`（nvs 保存＋RAM キャッシュ更新、上限/不正は status エラー）
- boot 時 nvs→RAM キャッシュ復元。

### 5.2 proto
- `zmk-studio-messages` のローカルコピーに `macros.proto`（`GetMacro`/`SetMacro`/`MacroStep`）を追加し、
  `studio.proto` の Request/Response `oneof` に `zmk.macros` subsystem を追加。proto3 で後方互換。

### 5.3 host（`tools/roba-cli` 拡張）
- 動詞（JSON 出力）:
  - `roba macro get <slot>` — ステップ列を JSON で取得
  - `roba macro set <slot> "<steps-dsl>"` — 編集して保存（変更前を backup ログへ）
- **steps DSL**（v1）: `|` 区切りトークン。例 `"C-c | wait 200 | type hello"`
  - `C-c` / `G-space` 等 = 修飾＋キーの1タップ（`C`=Ctrl,`S`=Shift,`A`=Alt,`G`=GUI）
  - `wait <ms>` = 次までの待機（ステップの wait_ms）
  - `type <text>` = 文字列を1文字ずつ tap に展開
- 実装: ローカル拡張 proto から生成した Python クラスで Request 構築 → framing → **pyserial で直接送受信**
  （key/info/snapshot/reset は従来どおり `zmk-studio-api`。マクロ系のみ独自 serial クライアント。serial ポートは排他なので同時併用しない）。

## 6. データフロー

```
roba macro set 0 "C-c | wait 200 | type hello"
  → DSL parse → MacroStep[] → macros.SetMacro(proto) → framing → /dev/cu.usbmodem*
  → firmware zmk.macros handler → nvs 保存 + RAM キャッシュ更新 → status
キー押下 &rt_macro 0 → RAM キャッシュのステップ列を順次 &kp タップ（wait/tap）
再起動 → boot で nvs→RAM キャッシュ復元
```

## 7. エラー処理 / 安全網（SP0 の「すぐ戻せる」を継承）

- `macro set` 前に `macro get` で現状を backup ログ（`.roba-backup.jsonl`）へ記録。
- `roba reset`（`reset_settings()`）は nvs を devicetree 既定へ戻す＝**マクロ定義も消えて既定動作に戻る**。最終安全網は維持。
- firmware は MAX_STEPS / blob サイズ上限を enforce、超過・不正 keycode・空スロット実行は status エラー → CLI は `{"error": ...}`/exit 1。
- known-good ファーム uf2 と `settings_reset` uf2 は引き続き物理フォールバック。

## 8. テスト

- **ユニット（ハード不要）**: steps DSL パーサ（`C-c`/`wait`/`type` の展開）、proto/framing エンコードを既知バイト列と突合。
- **HIL**: `macro set 0` → `macro get 0` 往復一致 → 物理キーで実打鍵確認（`hello` 等が出る）→ **電源オフ→再接続で永続** → `roba reset` で消去（既定へ）。
- **firmware ビルド**: CI グリーン必須（roBa_R）。known-good を保持してから flash。

## 9. 完了条件（SP1 DoD）

- `roba macro set 0 "<dsl>"` → `roba macro get 0` が同じステップ列を返す。
- `&rt_macro 0` を割り当てたキー押下で、設定どおりのキー列が実際に入力される。
- 設定が**再起動を跨いで保持**される（nvs 永続）。
- `roba reset` でマクロが消え devicetree 既定へ戻る。
- ステップ数上限超過・不正入力が JSON エラーで返る。
- 5 大リスク（R1–R5）が本スライス上で具体的に踏まれ、対処が動作で確認できる。

## 10. 留意点 / 未決（plan 段階で詰める）

- firmware 変更の置き場所: cormoran fork の zmk を直接いじるか、**自前 zmk-module として west.yml に足す**か（モジュール化が上流追従に強い・推奨候補）。plan で確定。
- `zmk.macros` の proto フィールド番号は firmware とホストで厳密一致が必須（単一の proto ソースから両者生成）。
- DSL の修飾子記法（`C-` 等）と `type` の非ASCII/記号の扱いは v1 では ASCII 英数＋基本記号に限定。
- RAM キャッシュ vs 都度 nvs 読み: v1 は boot 時ロード＋RAM 実行（実行時 nvs 読みは避ける）。
