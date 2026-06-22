# W2a: runtime hold-tap 時間編集 — 設計

**日付**: 2026-06-22
**プロジェクト**: 焼かずに Claude Code から roBa の ZMK 設定を runtime 編集（[[project_roba_studio_cli]]）。
**位置づけ**: W2（自作の本丸＝upstream にも runtime 化が無い差分）の first slice。SP0(keymap)/SP1(マクロ)/W1a(レイヤー)/W1b(トラックボール) に続く。

---

## 背景：W2 feasibility（2026-06-22 調査, source-grounded）

「全機能ホットスワップ」で本当に自作が要る4機能（combos / hold-tap時間 / sensor binding / conditional layers）はいずれも **upstream ZMK Studio で非対応**（Planned/低優先）。調査結論：
- **sensor binding** は cormoran `zmk-behavior-runtime-sensor-rotate` が既存（後日流用候補）。
- **combos** は高価値だが最難（core の静的 combo 配列＋位置索引を可変ストアへ置換が必要）。
- **conditional layers** は中（小さなデータ模型）。
- **hold-tap 時間** = 価値×実現性が最良で **first slice に選定**。理由：`behavior_hold_tap.c` は **判定のたびに config を読む**（init 時キャッシュでない）ので、config を可変化すれば即反映・エンジン再構築不要。per-instance・bounded。

## スコープ

**含む**:
- 新モジュール `qtrnmr/zmk-module-runtime-holdtap`：`zmk,behavior-runtime-hold-tap` ドライバ（core hold-tap の**逐語コピー**＋config を nvs 可変化）＋nvs ストア＋custom RPC `zmk__holdtap`。
- runtime 調整パラメータ：`tapping-term-ms` / `quick-tap-ms` / `flavor` / `require-prior-idle-ms`。
- host `roba holdtap list|get|set|reset`。
- roBa keymap の `lt_to_layer_0` / `lt_to_apple_default` / `lt_to_ipad` / `lt_to_iphone`（現 tapping-term-ms=200）を `zmk,behavior-runtime-hold-tap` に差し替え（bindings/`#binding-cells`=2 は不変）。

**含まない**: combos / conditional layers / sensor binding（後続）。hold-tap の非タイミング系プロパティ（retro-tap, hold-trigger-key-positions 等）の runtime 編集。`&mt`/`&lt`（ZMK 組込み behavior）の runtime 化（必要なら別途）。

## 横断制約（[[feedback_roba_always_revertible]]）

- **常時 known-good へ即 revert**：各スロットに「DT 既定へ戻す」reset op、`roba reset`、最終手段 settings_reset.uf2。set 前に現値を `tools/roba-cli/.roba-backup.jsonl` に記録。
- known-good = 現 main `d9e2cf7` ＋現 flash 済みファーム。**W2a は新ファームの flash を1回伴う**（モジュール導入。以後 timing 変更は焼き直し不要）。flash 前に復帰手段を明示。
- transport は USB serial。roBa_L 不変。host 出力は1行 JSON。既存 40 テスト緑を維持。

---

## アーキテクチャ

SP1 マクロと同じ三点セット（nvs ストア＋custom RPC＋behavior driver）。

### モジュール `qtrnmr/zmk-module-runtime-holdtap`
- `module.yml` / `Kconfig`（`CONFIG_ZMK_RUNTIME_HOLDTAP`, `_STUDIO_RPC`）/ `CMakeLists.txt` / LICENSE(MIT) / README。
- **behavior driver `zmk,behavior-runtime-hold-tap`**：当 base(`v0.3-branch+dya`)の `app/src/behaviors/behavior_hold_tap.c` を**逐語コピー**し、唯一の変更点として timing 設定（`tapping_term_ms`/`quick_tap_ms`/`flavor`/`require_prior_idle_ms`）を **const config から可変 data（DT 既定で初期化→nvs override）に移す**。判定ロジック（flavor 解決, quick-tap, decision state machine, retro 等）は一切変更しない。`#binding-cells = <2>`、`bindings = <hold>,<tap>` は hold-tap と同一。
- **slot/keying**：`zmk,behavior-runtime-hold-tap` の各 DT インスタンスを instantiation 順で index 化（0,1,2,…。マクロ slot と同型）。
- **nvs ストア**：key `rt_holdtap/<index>`、値 `{tapping_term_ms, quick_tap_ms, flavor, require_prior_idle_ms}`。RAM キャッシュ＋mutex、NVS-first 書込（SP1 と同契約）。起動時 load、未保存スロットは DT 既定。
- **settings-reset hook**：`ZMK_RPC_SUBSYSTEM_SETTINGS_RESET` で `roba reset` 時に全スロット nvs を消去（SP1 のマクロで確立した知見）。

### custom RPC `zmk__holdtap`（proto `proto/zmk/holdtap/holdtap.proto`）
- `ListHoldTaps`（index 一覧＋現 timing、※get_input_processor の二の舞回避のため**response で直接返す**設計にする。notification 依存にしない）
- `GetHoldTap{index}` → 現 timing（4値）
- `SetHoldTap{index, field 値}`（または個別 set op）→ ok/err
- `ResetHoldTap{index}` → DT 既定へ
- flavor は enum（`balanced`/`tap-preferred`/`hold-preferred`/`tap-unless-interrupted` 等、core の enum 値に一致）。

### host `tools/roba-cli`
- `roba_cli/holdtap_client.py`：custom 封筒2段（list_custom_subsystems→`zmk__holdtap` index→call）、`rpc.send_recv` 流用。純粋 builder/decoder（単体テスト）＋thin client（HIL）。
- `cli.py`：`roba holdtap list` / `get <index>` / `set <index> <field> <value>`（field: `tapping-term-ms`/`quick-tap-ms`/`flavor`/`require-prior-idle-ms`）/ `reset <index>`。set 前バックアップ。
- W1b の教訓：get は **response で返す RPC** を使い、notification 依存にしない（firmware ハンドラを response 返却で実装）。

## データフロー
キー押下 → `zmk,behavior-runtime-hold-tap` driver が RAM キャッシュ（=nvs 由来 or DT 既定）から timing を読み hold-tap 判定 → host が `SetHoldTap` を送ると nvs-first 書込→RAM 更新→次の押下から即反映。

## 主リスクと対策
- **core hold-tap フォークの版ずれ**：plan で**当 base の `behavior_hold_tap.c` を取得し逐語コピー**。判定ロジック差分ゼロをレビューで担保（upstream/base との diff を確認）。
- **flavor enum 値の不一致**：core の `dt-bindings`/enum 値に厳密一致させる。
- **per-instance keying**：index の安定性（DT instantiation 順）を実機で確認。

## テスト戦略
- host 単体（serial 不要）：holdtap proto builder/decoder、flavor 文字列↔enum、field map。
- firmware ビルド：CI green（roBa_R にモジュール有効）。
- 実機 E2E：`set <i> tapping-term-ms 120`→体感（短押しで層が出にくく/出やすく）→`get` 反映→電源再投入で永続→`reset`/`roba reset` で既定復帰。
- 既存 40 テスト不変で緑。

## known-good / ロールバック
現 main `d9e2cf7`＋現ファーム。W2a はブランチで実装、CI/実機確認後マージ。問題時は現ファーム再 flash／settings_reset.uf2／main 状態へ。
