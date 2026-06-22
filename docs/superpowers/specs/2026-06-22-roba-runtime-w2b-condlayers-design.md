# W2b: runtime conditional layers 編集 — 設計

**日付**: 2026-06-22
**プロジェクト**: 焼かずに Claude Code から roBa の ZMK 設定を runtime 編集（[[project_roba_studio_cli]]）。
**位置づけ**: W2（自作の本丸）の第2スライス。W2a(hold-tap) に続き、[[reference_holdtap_fork_pattern]] の「コア逐語フォーク」型を**サブシステム**に適用する。

---

## 背景

W2 feasibility（2026-06-22）で conditional layers は「中難度・fork パターン適用可」。upstream Studio は Planned 止まりで runtime 非対応。`app/src/conditional_layer.c` は `static const struct conditional_layer_cfg CONDITIONAL_LAYER_CFGS[]`（`{if_layers_state_mask, then_layer}`）を init で構築し、単一 `layer_state_changed_listener` が層変化時に全エントリを走査して AND マスク判定するだけ。**behavior driver ではなくサブシステム**（per-key binding/slot 無し）。runtime 化＝この cfg 配列を nvs 可変にし、listener がそれを読むようにする。

## スコープ

**含む**:
- 新モジュール `qtrnmr/zmk-module-runtime-conditional-layers`：`conditional_layer.c` 逐語フォーク（判定ロジック不変）＋エントリ配列を RAM 可変＋nvs 永続化＋custom RPC `zmk__condlayers`。
- runtime 編集対象：各エントリの `if_layers`（層番号集合＝ビットマスク）と `then_layer`。
- host `roba condlayer list|get|set|reset`。
- roBa の 5 conditional layers（apple_mouse/ipad_mouse/ipad_arrow/iphone_mouse/iphone_arrow）を runtime 編集可能に。

**含まない**: エントリの**追加/削除**（DT で定義した個数 N 固定。値の編集のみ）。combos / sensor binding（後続）。

## 横断制約（[[feedback_roba_always_revertible]]）

- 常時 revert：各エントリに reset op（DT 既定へ）＋`roba reset`（settings-reset hook）＋settings_reset.uf2。set 前に現値を `.roba-backup.jsonl` に記録。
- known-good = 現 main `5686ffa`＋現 flash 済みファーム。**W2b は新ファーム flash を1回伴う**（モジュール導入。以後は焼き直し不要）。
- transport USB serial、roBa_L 不変、host 出力1行 JSON、既存 47 テスト緑維持。
- **判定ロジック不変**（fork の絶対条件）。変更は cfg 配列の格納場所と読取り元のみ。
- upstream conditional_layer と共存（リネーム＋非 static グローバル static 化）。get は **RPC response 返却**（notification 非依存）。

---

## アーキテクチャ（[[reference_holdtap_fork_pattern]] をサブシステムに適用）

### モジュール `qtrnmr/zmk-module-runtime-conditional-layers`
- module.yml / Kconfig（`CONFIG_ZMK_RUNTIME_CONDLAYERS`, `_STUDIO_RPC`）/ CMakeLists（macro モジュールの nanopb ブロック流用）/ LICENSE / README。
- **サブシステム fork**：base `conditional_layer.c` を逐語取得（curl, `v0.3-branch%2Bdya`）。`DT_DRV_COMPAT`/`ZMK_LISTENER`/`ZMK_SUBSCRIPTION`/listener 関数/非 static グローバルをリネーム＋static 化で共存。`compatible` は `zmk,conditional-layers` のまま使えない（upstream が同じ compatible で DT を取る）ので、**roBa keymap 側の `conditional_layers` ノードの compatible を `zmk,runtime-conditional-layers` に変更**し、フォーク側はそれを `DT_DRV_COMPAT` にする（upstream の素の conditional layers は使わない＝二重発火回避）。
- **データ模型**：`struct rt_condlayer_entry { uint32_t if_layers_mask; uint8_t then_layer; }`。エントリ数 N は DT 子ノード数（roBa=5）。起動時 DT 既定で RAM 配列を seed→nvs override。listener は RAM 配列を走査（元ロジックの mask AND 判定不変）。
- **nvs ストア**：key `rt_condlayer/<index>`、値 `rt_condlayer_entry`。mutex、NVS-first、register/load 両順序対応（W2a 同型）。settings-reset hook で全消去→DT 既定復元。

### custom RPC `zmk__condlayers`（proto `proto/zmk/condlayers/condlayers.proto`、response 返却）
- `Count` → エントリ数。`Get{index}` → `{index, if_layers_mask, then_layer, found}`。`Set{index, if_layers_mask, then_layer}` → `{ok}`。`Reset{index}` → DT 既定へ。repeated 無し（W1b/W2a 教訓）。

### host `tools/roba-cli`
- `holdtap_client` と同型の `condlayer_client.py`（custom 封筒、count/get/set/reset）。`if_layers` は層番号リスト ⇄ ビットマスク変換（例 `set 0 --if 1,7 --then 13`）。
- `cli.py`：`roba condlayer list|get <i>|set <i> <if_csv> <then>|reset <i>`。set 前バックアップ。

## データフロー
層変化イベント → フォーク listener が RAM 配列（nvs 由来 or DT 既定）を走査し then_layer を活性/非活性（元の再入ガード/活性化ロジック不変）→ host が `Set` で nvs-first 書込＋RAM 更新→次の層変化から反映。

## 主リスクと対策
- **fork 版ずれ**：curl 逐語取得＋逆リネーム diff で許容変更のみ確認（opus）。
- **二重発火**：keymap の compatible を runtime 版へ変えることで upstream conditional layers を無効化（roBa の該当ノードのみ）。
- **層ループ/振動**：元 listener の再入ガードをそのまま使う（新規ロジック無し）。
- **ビットマスク表現**：host は層番号 CSV ⇄ mask、firmware は mask をそのまま保存。

## テスト戦略
- host 単体（serial 不要）：proto builder/decoder、層CSV⇄mask 変換、FakeSerial で get/count の response 経路。
- firmware：CI green（roBa_R にモジュール有効）。
- 実機 E2E：例として `ipad_arrow`（if IPAD+ARROW → IPAD_ARROW）の then_layer を別層に `set`→層挙動が変化→`get` 反映→電源再投入で永続→`reset`/`roba reset` で既定復帰。
- 既存 47 テスト不変で緑。

## known-good / ロールバック
現 main `5686ffa`＋現ファーム。ブランチ実装、CI/実機確認後マージ。問題時は現ファーム再 flash／settings_reset.uf2／main 状態へ。
