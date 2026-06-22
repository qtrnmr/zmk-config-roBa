# W2b: runtime conditional layers 編集 — 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** `conditional_layer.c` を逐語フォークした runtime 版を新モジュールで提供し、各 conditional layer の `if_layers`(mask)/`then_layer` を nvs 可変化＋custom RPC `zmk__condlayers` で host から焼き直し無しに編集する。

**Architecture:** [[reference_holdtap_fork_pattern]] をサブシステムに適用。判定 listener ロジックは byte-identical、変更は cfg 配列を const→可変(nvs)化＋読取り元差し替え＋compatible 改名（upstream 無効化で共存）。

**Tech Stack:** ZMK cormoran fork `v0.3-branch+dya`、Zephyr settings/nvs、nanopb、Python venv、pytest。

## Global Constraints
- known-good = main `5686ffa`＋現ファーム。**初回のみ roBa_R flash**。以後 focus 値編集は焼き直し不要。
- 常時 revert：reset op（DT 既定へ）＋`roba reset`（settings-reset hook）＋settings_reset.uf2。set 前 `.roba-backup.jsonl` 記録。
- transport USB serial、roBa_L 不変、host 1行 JSON、既存 47 テスト緑維持。
- **listener 判定ロジック不変**。get は RPC response 返却（notification 非依存）。

## 確定済みソース事実（base, 2026-06-22 取得, 124行）
- `#define DT_DRV_COMPAT zmk_conditional_layers`、`ZMK_LISTENER(conditional_layer, layer_state_changed_listener)`＋`ZMK_SUBSCRIPTION(conditional_layer, zmk_layer_state_changed)`。
- `struct conditional_layer_cfg { zmk_keymap_layers_state_t if_layers_state_mask; int8_t then_layer; }`。
- `static const struct conditional_layer_cfg CONDITIONAL_LAYER_CFGS[] = { DT_INST_FOREACH_CHILD(0, CONDITIONAL_LAYER_DECL) };`、`NUM_CONDITIONAL_LAYER_CFGS`。
- listener 読取り（差し替え対象）: `const struct conditional_layer_cfg *cfg = CONDITIONAL_LAYER_CFGS + i;`（L93）、`cfg->if_layers_state_mask`（L94）、`cfg->then_layer`（L95,96,102）。＝**配列参照1箇所を rt_cfgs に変えれば cfg-> は全部追従**。
- **init 関数なし**（const 配列＋ZMK_LISTENER のみ）。`static K_SEM_DEFINE(conditional_layer_sem,...)`。
- roBa keymap: `/{ conditional_layers { compatible="zmk,conditional-layers"; apple_mouse{if-layers=<L_APPLE L_MOUSE>; then-layer=<L_APPLEMOUSE>;} ... 5個 }; }`。

---

## File Structure
**module repo `qtrnmr/zmk-module-runtime-conditional-layers`**: module.yml / Kconfig(`CONFIG_ZMK_RUNTIME_CONDLAYERS`,`_STUDIO_RPC`) / CMakeLists(nanopb) / LICENSE / README / `src/runtime_conditional_layer.c`(fork) / `include/zmk/runtime_condlayers.h` / `src/runtime_condlayer_store.c` / `src/studio/condlayers_rpc_handler.c` / `proto/zmk/condlayers/condlayers.proto`.
**config repo**: west.yml(+module) / roBa_R.conf(+CONFIG) / roBa.keymap(compatible→runtime) / tools/roba-cli(proto+`condlayer_client.py`+cli+`tests/test_condlayer.py`).

---

## Task 1: モジュール骨格＋サブシステム逐語フォーク＋keymap 切替（CI go/no-go・GATE）
**Files:** module(skeleton, fork src) / config(west.yml, roBa_R.conf, roBa.keymap)
**Interfaces:** Produces: `zmk,runtime-conditional-layers`（この時点 cfg は DT 静的初期化の可変配列だが nvs 無し＝挙動同一）。

- [ ] **Step 1:** `gh repo create qtrnmr/zmk-module-runtime-conditional-layers --public`。
- [ ] **Step 2:** 骨格作成。module.yml（`dts_root: .`）、Kconfig（W2a と同型：`CONFIG_ZMK_RUNTIME_CONDLAYERS` bool、`_STUDIO_RPC` depends ZMK_STUDIO default y）、CMakeLists（Task1 は `target_sources(app PRIVATE src/runtime_conditional_layer.c)` のみ＋`zephyr_include_directories(include)`；store/studio は後タスク）、LICENSE(MIT)、README。
- [ ] **Step 3:** base 逐語取得：`curl -fsSL "https://raw.githubusercontent.com/cormoran/zmk/v0.3-branch%2Bdya/app/src/conditional_layer.c" -o src/runtime_conditional_layer.c`。
- [ ] **Step 4:** 共存リネーム（小文字全置換 `conditional_layer`→`runtime_conditional_layer`）：`DT_DRV_COMPAT zmk_conditional_layers`→`zmk_runtime_conditional_layers`、`ZMK_LISTENER`/`ZMK_SUBSCRIPTION` トークン・listener 関数・sem・activate/deactivate 関数・`struct conditional_layer_cfg`→`struct runtime_conditional_layer_cfg` が一括整合。大文字 `CONDITIONAL_LAYER_*`/`CONFIG_*` は不変（file-static 配列＝衝突せず、upstream は instance ゼロで `#if` 消滅）。
- [ ] **Step 5:** cfg を可変化（nvs はまだ無し）。`CONDITIONAL_LAYER_CFGS` を **DT 既定の const 源**として残しつつ、可変配列を追加（同じ initializer で静的初期化）:
```c
static struct runtime_conditional_layer_cfg rt_cfgs[] = {
    DT_INST_FOREACH_CHILD(0, CONDITIONAL_LAYER_DECL)};
#define RT_NUM_CFGS (sizeof(rt_cfgs) / sizeof(*rt_cfgs))
```
listener の `const struct runtime_conditional_layer_cfg *cfg = CONDITIONAL_LAYER_CFGS + i;` を `rt_cfgs + i;` に、`NUM_CONDITIONAL_LAYER_CFGS` 参照を `RT_NUM_CFGS` に差し替え（判定ロジックは不変）。
- [ ] **Step 6:** config 配線。west.yml に module（remote qtrnmr-gh, revision main）。roBa_R.conf に `CONFIG_ZMK_RUNTIME_CONDLAYERS=y`/`_STUDIO_RPC=y`。**roBa.keymap の `conditional_layers` ノードの `compatible = "zmk,conditional-layers"` → `"zmk,runtime-conditional-layers"`**（子ノードの if-layers/then-layer は不変）。
- [ ] **Step 7:** module push、config commit+push（feat/roba-w2b-condlayers）、`gh run list`→CI。GO=全 green、upstream conditional_layer が消えても roBa の層挙動が DT どおり（フォークが処理）。NO-GO=リネーム漏れ/compat 不一致を特定、深い非互換なら停止しユーザー報告（known-good=main 5686ffa）。
- [ ] **Step 8:** uf2 取得→ユーザー flash→HIL：conditional layer が従来どおり動く（例: IPAD+ARROW 同時で IPAD_ARROW 層の挙動）＝フォーク機能同一。

## Task 2: nvs ストア＋SYS_INIT register＋settings-reset hook
**Files:** module `src/runtime_condlayer_store.c`, `include/zmk/runtime_condlayers.h`, fork に SYS_INIT 追加、CMake に store 追加。
- [ ] **Step 1:** header：`struct rt_condlayer_entry { uint32_t if_layers_mask; int8_t then_layer; }`＋`rt_condlayer_register/get/set/reset/clear_all/registered/count`（W2a store と同型）。
- [ ] **Step 2:** store：`SETTINGS_STATIC_HANDLER_DEFINE(rt_condlayer,"rt_condlayer",...)`、key `rt_condlayer/<index>`、値 entry、mutex、NVS-first、register で load/init 両順序対応、reset で DT 既定復元、clear_all。
- [ ] **Step 3:** fork に SYS_INIT 追加（`SYS_INIT(rt_condlayer_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY)`；※ SP1 で `APPLICATION` がレベル不可なら `POST_KERNEL`/`CONFIG_KERNEL_INIT_PRIORITY_DEFAULT` に。CI で確認）：各 `rt_cfgs[i]` を `&rt_cfgs[i]`＋DT 既定(`CONDITIONAL_LAYER_CFGS[i]` を entry 化)で `rt_condlayer_register(i, ...)`。entry⇔cfg のフィールドは {if_layers_mask=if_layers_state_mask, then_layer}。register が nvs 既保存を適用、listener は rt_cfgs を読むので即反映。
- [ ] **Step 4:** CMake に store 追加。CI green。Commit。

## Task 3: custom RPC `zmk__condlayers`（proto＋handler, response 返却）
**Files:** module `proto/zmk/condlayers/condlayers.proto`, `src/studio/condlayers_rpc_handler.c`, CMake に nanopb ブロック（macro モジュール流用）。
- [ ] **Step 1:** proto（repeated 無し）：`CondLayerInfo{index, if_layers_mask, then_layer, found}`、`Empty`/`SlotRequest{index}`/`SetRequest{index, if_layers_mask, then_layer}`/`CountResponse{count}`/`OkResponse{ok,error}`、Request/Response oneof `count/get/set/reset`。
- [ ] **Step 2:** handler（W2a `holdtap_rpc_handler.c` と同型）：`ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__condlayers,...)`＋RESPONSE_BUFFER。count=registered 数、get=rt_condlayer_get、set=rt_condlayer_set、reset=rt_condlayer_reset。`ZMK_RPC_SUBSYSTEM_SETTINGS_RESET(rt_condlayer, ...)`→clear_all。
- [ ] **Step 3:** CMake nanopb。CI green（firmware artifact）。Commit。

## Task 4: host `condlayer_client.py`＋`roba condlayer` verb＋テスト
**Files:** tools/roba-cli proto(+生成), `roba_cli/condlayer_client.py`, `cli.py`, `tests/test_condlayer.py`.
- [ ] **Step 1:** proto コピー＋生成（`-I proto/zmk --python_out=roba_cli/proto proto/zmk/condlayers/condlayers.proto`、`__init__.py`）。
- [ ] **Step 2:** 純粋関数＋テスト：**層番号 CSV ⇄ ビットマスク**（`"1,7"`→`(1<<1)|(1<<7)`、逆も）、build_set_request、info_to_dict（mask→層番号リスト）。FakeSerial で get/count の custom 封筒 response 経路。
- [ ] **Step 3:** `CondlayerClient`（custom 封筒2段、`zmk__condlayers`、count/get/set/reset、`rpc.send_recv`、`_ser` 注入）。
- [ ] **Step 4:** cli `roba condlayer list|get <i>|set <i> <if_csv> <then>|reset <i>`、set 前バックアップ、parser スモークテスト。全スイート緑（47+新）。Commit。

## Task 5: 実機 E2E＋ドキュメント
- [ ] **Step 1:** flash（Task1 で keymap 切替済み）。`roba condlayer list`→5 エントリ（roBa の apple_mouse 等、if_layers/then_layer）。
- [ ] **Step 2:** E2E：あるエントリの then_layer を別層に `set`→層挙動変化→`get` 反映→電源再投入で永続→`reset`/`roba reset` で既定復帰。観測しやすい検証手順をユーザーに提示（条件層の効果が見える組合せを選ぶ。難しければ W2a 同様 set→get→persist の JSON round-trip で機構を確定）。
- [ ] **Step 3:** README（module＋roba-cli）更新。全スイート緑。Commit。

---
## Self-Review
- **Spec coverage**: ビルド成功(Task1/2/3)、set 反映+永続+reset(Task5)、判定ロジック不変(Task1 逐語フォーク＋listener 配列参照1箇所差し替え)。✓
- **Placeholder scan**: 124行は curl 取得＋指定 edit。RPC/store は W2a を雛形に明示。SYS_INIT レベルは CI 確認の go/no-go 注記。✓
- **Type consistency**: `rt_condlayer_entry{if_layers_mask,then_layer}` を store/fork/RPC/host で共通。host は層CSV⇄mask 変換。get は response 返却。✓
- **注意**: ①compatible 改名で upstream 無効化＝衝突回避（hold-tap より単純）。②init 無しサブシステムなので可変配列は静的初期化、register 用に SYS_INIT 追加（レベル要 CI 確認）。③firmware タスク(1-3,5)は CI＋flash 規模。
