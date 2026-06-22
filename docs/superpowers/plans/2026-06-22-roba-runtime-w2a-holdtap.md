# W2a: runtime hold-tap 時間編集 — 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** core `behavior_hold_tap.c` を逐語フォークした `zmk,behavior-runtime-hold-tap` を新モジュールで提供し、`tapping-term-ms`/`quick-tap-ms`/`require-prior-idle-ms`/`flavor` を nvs 可変化＋custom RPC `zmk__holdtap` で host から焼き直し無しに編集できるようにする。

**Architecture:** SP1 マクロの三点セット（nvs ストア＋custom RPC＋behavior driver）。driver は base `v0.3-branch+dya` の `behavior_hold_tap.c`(911行) を逐語コピーし、**変更は「4つの timing 値を const config→可変 data に移し、6つの read-site をそこへ向ける」だけ**。判定ロジックは byte-identical。

**Tech Stack:** ZMK cormoran fork `v0.3-branch+dya`（custom-RPC 層は SP1 で実証済）、Zephyr settings/nvs、nanopb、Python venv、grpc_tools.protoc、pyserial、pytest。

## Global Constraints

- known-good = main `d9e2cf7` ＋現 flash 済みファーム。**W2a は新ファーム flash を1回伴う**（モジュール導入。以後 timing 変更は焼き直し不要）。flash 前に復帰手段（現 uf2 / settings_reset.uf2 / main 状態）明示。
- 常時 revert：各スロット reset op（DT 既定へ）＋`roba reset`（settings-reset hook で nvs 消去）＋settings_reset.uf2。set 前に現値を `tools/roba-cli/.roba-backup.jsonl` に記録。
- transport USB serial、roBa_L 不変、host 出力1行 JSON、既存 40 テスト緑維持。
- **判定ロジックは一切変更しない**（フォークの絶対条件）。変更は timing 値の格納場所と読取り元のみ。
- **upstream hold-tap と共存**：`DT_DRV_COMPAT`・compatible・`ZMK_LISTENER`/`ZMK_SUBSCRIPTION` トークン・listener 関数名・全 static シンボルを `runtime_hold_tap` 系へリネーム（重複シンボル/リスナ衝突回避）。
- get は **RPC response で直接返す**（W1b の get_input_processor 教訓：notification 依存にしない）。

## 確定済みソース事実（base `v0.3-branch+dya`, 2026-06-22 取得）

- `struct behavior_hold_tap_config` の timing 4フィールド: `int tapping_term_ms; int quick_tap_ms; int require_prior_idle_ms; enum flavor flavor;`
- `enum flavor { FLAVOR_HOLD_PREFERRED=0, FLAVOR_BALANCED=1, FLAVOR_TAP_PREFERRED=2, FLAVOR_TAP_UNLESS_INTERRUPTED=3 };`（YAML enum 順と一致）
- `struct active_hold_tap` は `const struct behavior_hold_tap_config *config;` をキャッシュ（press 時に `dev->config` を格納）。
- **redirect 対象 read-site（6箇所、判定に効くもの）**:
  1. `on_hold_tap_binding_pressed`: `cfg->tapping_term_ms`（`cfg = dev->config`）
  2. `on_hold_tap_binding_released`: `hold_tap->config->tapping_term_ms`
  3. `position_state_changed_listener`: `undecided_hold_tap->config->tapping_term_ms`
  4. `is_quick_tap`: `hold_tap->config->quick_tap_ms`
  5. `is_quick_tap`: `hold_tap->config->require_prior_idle_ms`
  6. `decide_hold_tap`: `switch (hold_tap->config->flavor)`（＋debug log の flavor は任意）
- `KP_INST(n)` は `.tapping_term_ms=DT_INST_PROP(n,tapping_term_ms)`, `.quick_tap_ms=DT_INST_PROP(n,quick_tap_ms)`, `.require_prior_idle_ms = DT_INST_PROP(n,global_quick_tap)?DT_INST_PROP(n,quick_tap_ms):DT_INST_PROP(n,require_prior_idle_ms)`, `.flavor=DT_ENUM_IDX(DT_DRV_INST(n),flavor)`。**この4式を data 初期化へ移植（global_quick_tap フォールバック保持）**。
- include に `<zephyr/settings/settings.h>` を追加（nvs 用）。`behavior_hold_tap_init(dev)` で `dev->data` 到達可。
- yaml は `include: two_param.yaml`（`#binding-cells const:2`）。

---

## File Structure

**モジュール repo `qtrnmr/zmk-module-runtime-holdtap`**（SP1 の runtime-macro と同構成）:
- `zephyr/module.yml`, `Kconfig`, `CMakeLists.txt`, `LICENSE`(MIT), `README.md`
- `dts/bindings/behaviors/zmk,behavior-runtime-hold-tap.yaml`（hold-tap yaml のコピー＋compatible 改名）
- `src/behaviors/behavior_runtime_hold_tap.c`（911行逐語コピー＋指定 edit）
- `include/zmk/runtime_holdtap.h`（store API）
- `src/runtime_holdtap_store.c`（nvs ストア＋settings-reset hook）
- `src/studio/holdtap_rpc_handler.c`（`ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__holdtap,...)`）
- `proto/zmk/holdtap/holdtap.proto`

**config repo `qtrnmr/zmk-config-roBa`**:
- `config/west.yml`（remote qtrnmr-gh に `zmk-module-runtime-holdtap`）
- `boards/shields/roBa/roBa_R.conf`（`CONFIG_ZMK_RUNTIME_HOLDTAP=y`/`_STUDIO_RPC=y`）
- `config/roBa.keymap`（lt_to_* 4個を `zmk,behavior-runtime-hold-tap` へ）
- `tools/roba-cli/`: `proto/zmk/holdtap/holdtap.proto`＋生成物, `roba_cli/holdtap_client.py`, `cli.py`, `tests/test_holdtap.py`

---

## Task 1: モジュール骨格＋逐語クローン（共存ビルド＆挙動同一・GATE）

**Files (module repo):** module.yml/Kconfig/CMakeLists/LICENSE/README, yaml, `src/behaviors/behavior_runtime_hold_tap.c`
**Files (config repo):** west.yml, roBa_R.conf, roBa.keymap（lt_to_layer_0 のみ試験変換）

**Interfaces:** Produces: `zmk,behavior-runtime-hold-tap`（この時点では timing は const のまま＝hold-tap と挙動同一）。

- [ ] **Step 1: GitHub に空 repo `qtrnmr/zmk-module-runtime-holdtap` 作成**（gh は必要なら qtrnmr に切替→戻す）

```bash
gh repo create qtrnmr/zmk-module-runtime-holdtap --public --description "Runtime-editable hold-tap timing for ZMK (cormoran fork)" 2>&1 | tail -2
```

- [ ] **Step 2: モジュール骨格を作成**（SP1 の runtime-macro を雛形に）。`zephyr/module.yml`:

```yaml
name: zmk-module-runtime-holdtap
build:
  cmake: .
  kconfig: Kconfig
  settings:
    dts_root: .
```

`Kconfig`:

```kconfig
config ZMK_RUNTIME_HOLDTAP
    bool "Enable runtime-editable hold-tap timing"

if ZMK_RUNTIME_HOLDTAP

config ZMK_RUNTIME_HOLDTAP_STUDIO_RPC
    bool "Enable hold-tap timing custom Studio RPC"
    depends on ZMK_STUDIO
    default y

config ZMK_RUNTIME_HOLDTAP_SLOTS
    int "Max runtime hold-tap slots"
    default 8

endif
```

`CMakeLists.txt`:

```cmake
if(CONFIG_ZMK_RUNTIME_HOLDTAP)
  zephyr_library()
  zephyr_library_sources(src/behaviors/behavior_runtime_hold_tap.c)
  zephyr_library_sources_ifdef(CONFIG_ZMK_RUNTIME_HOLDTAP src/runtime_holdtap_store.c)
  zephyr_library_sources_ifdef(CONFIG_ZMK_RUNTIME_HOLDTAP_STUDIO_RPC src/studio/holdtap_rpc_handler.c)
  # proto compiled in Task 4
endif()
```

LICENSE(MIT)、README（最小）。

- [ ] **Step 3: hold-tap ソースを逐語取得**

```bash
curl -fsSL "https://raw.githubusercontent.com/cormoran/zmk/v0.3-branch%2Bdya/app/src/behaviors/behavior_hold_tap.c" -o src/behaviors/behavior_runtime_hold_tap.c
curl -fsSL "https://raw.githubusercontent.com/cormoran/zmk/v0.3-branch%2Bdya/app/dts/bindings/behaviors/zmk,behavior-hold-tap.yaml" -o "dts/bindings/behaviors/zmk,behavior-runtime-hold-tap.yaml"
wc -l src/behaviors/behavior_runtime_hold_tap.c   # expect 911
```

- [ ] **Step 4: 共存リネーム（挙動不変）**。`src/behaviors/behavior_runtime_hold_tap.c` に対し:
  - `#define DT_DRV_COMPAT zmk_behavior_hold_tap` → `zmk_behavior_runtime_hold_tap`
  - `ZMK_LISTENER(behavior_hold_tap, ...)` → `ZMK_LISTENER(behavior_runtime_hold_tap, ...)`、`ZMK_SUBSCRIPTION(behavior_hold_tap, ...)` ×2 → `behavior_runtime_hold_tap`
  - listener 関数 `behavior_hold_tap_listener` → `behavior_runtime_hold_tap_listener`（定義と `ZMK_LISTENER` 参照の両方）
  - その他の static 関数/変数（`active_hold_taps`, `behavior_hold_tap_init`, `*_config_##n`, `*_data_##n`, driver_api 等）はファイル内 static なので衝突しないが、**混乱回避のため `behavior_hold_tap_` プレフィクスは `behavior_runtime_hold_tap_` に一括リネーム**（sed）。判定ロジック本体（式・分岐）は不変。

yaml: `compatible: "zmk,behavior-hold-tap"` → `"zmk,behavior-runtime-hold-tap"`（`include: two_param.yaml` は不変）。

- [ ] **Step 5: config repo に配線**。`config/west.yml` の projects に追加:

```yaml
    - name: zmk-module-runtime-holdtap
      remote: qtrnmr-gh
      revision: main
```

`boards/shields/roBa/roBa_R.conf` に:

```
# runtime hold-tap timing module (W2a)
CONFIG_ZMK_RUNTIME_HOLDTAP=y
CONFIG_ZMK_RUNTIME_HOLDTAP_STUDIO_RPC=y
```

`config/roBa.keymap` の `lt_to_layer_0` の compatible のみ試験変換:

```dts
        lt_to_layer_0: lt_to_layer_0 {
            compatible = "zmk,behavior-runtime-hold-tap";
            label = "LAYER_TAP_TO_0";
            bindings = <&mo>, <&to_layer_0>;
            #binding-cells = <2>;
            tapping-term-ms = <200>;
        };
```

- [ ] **Step 6: モジュール repo を push、config を commit/push、CI go/no-go**

```bash
# module repo: git init, add, commit, push to qtrnmr/zmk-module-runtime-holdtap main
# config repo:
git add config/west.yml boards/shields/roBa/roBa_R.conf config/roBa.keymap
git commit -m "feat(roBa): wire zmk-module-runtime-holdtap, convert lt_to_layer_0 (W2a Task1)"
git push -u origin feat/roba-w2a-holdtap
gh run list --branch feat/roba-w2a-holdtap --limit 1
```
Expected（GO）: roBa_R/roBa_L/settings_reset 全 green。`zmk,behavior-runtime-hold-tap` がビルドに含まれ、重複リスナ等のエラーが無い。
NO-GO 時: リネーム漏れ（重複シンボル/リスナ）か include 不足を特定して修正。深い base 非互換なら停止しユーザー報告（known-good=main d9e2cf7）。

- [ ] **Step 7: uf2 取得→ユーザー flash→HIL（挙動同一の確認）**

`gh run download` で roBa_R uf2 取得→ユーザーが flash。`lt_to_layer_0`（物理: LANG2 長押しで SETTING 層 / タップで LANG2）が**従来どおり動く**ことを確認（タップ=LANG2、200ms 長押し=SETTING 層）。＝逐語クローンが hold-tap と機能同一。

---

## Task 2: timing 4値を const→可変 data に移植（DT 既定で初期化・挙動同一）

**Files (module):** `src/behaviors/behavior_runtime_hold_tap.c`, `include/zmk/runtime_holdtap.h`

**Interfaces:** Produces: per-instance 可変 timing 構造体（DT 既定で seed）。read-site が data 経由に。RPC/nvs はまだ無し＝挙動は Task1 と同一。

- [ ] **Step 1: `include/zmk/runtime_holdtap.h` 定義**

```c
#pragma once
#include <stdint.h>

struct rt_holdtap_timing {
    int tapping_term_ms;
    int quick_tap_ms;
    int require_prior_idle_ms;
    uint8_t flavor;  // enum flavor (0..3)
};
```

- [ ] **Step 2: `behavior_runtime_hold_tap_data` に timing と index を追加**（mutable）

```c
struct behavior_runtime_hold_tap_data {
#if IS_ENABLED(CONFIG_ZMK_BEHAVIOR_METADATA)
    struct behavior_parameter_metadata_set set;
#endif
    uint8_t slot;                 // KP_INST 連番（nvs key）
    struct rt_holdtap_timing t;   // 可変 timing（DT 既定で初期化、後で nvs override）
};
```

- [ ] **Step 3: `KP_INST(n)` を timing 移植**。const config から `tapping_term_ms`/`quick_tap_ms`/`require_prior_idle_ms`/`flavor` を**削除**（残りは不変）し、data 初期化子へ（`global_quick_tap` フォールバック保持。`slot=n`）:

```c
    static struct behavior_runtime_hold_tap_data behavior_runtime_hold_tap_data_##n = {        \
        .slot = n,                                                                             \
        .t = {                                                                                 \
            .tapping_term_ms = DT_INST_PROP(n, tapping_term_ms),                               \
            .quick_tap_ms = DT_INST_PROP(n, quick_tap_ms),                                     \
            .require_prior_idle_ms = DT_INST_PROP(n, global_quick_tap)                         \
                                         ? DT_INST_PROP(n, quick_tap_ms)                       \
                                         : DT_INST_PROP(n, require_prior_idle_ms),             \
            .flavor = DT_ENUM_IDX(DT_DRV_INST(n), flavor),                                     \
        },                                                                                     \
    };
```

- [ ] **Step 4: `active_hold_tap` に `data` ポインタを追加し、press 時に格納**。`struct active_hold_tap` に `struct behavior_runtime_hold_tap_data *data;` を追加。`on_hold_tap_binding_pressed` で `cfg=dev->config;` の直後に `struct behavior_runtime_hold_tap_data *htdata = dev->data; hold_tap->data = htdata;`。

- [ ] **Step 5: 6 read-site を data 経由へ**（判定ロジックは不変、参照先だけ変更）:
  1. pressed: `cfg->tapping_term_ms` → `htdata->t.tapping_term_ms`
  2. released: `hold_tap->config->tapping_term_ms` → `hold_tap->data->t.tapping_term_ms`
  3. position listener: `undecided_hold_tap->config->tapping_term_ms` → `undecided_hold_tap->data->t.tapping_term_ms`
  4. is_quick_tap: `hold_tap->config->quick_tap_ms` → `hold_tap->data->t.quick_tap_ms`
  5. is_quick_tap: `hold_tap->config->require_prior_idle_ms` → `hold_tap->data->t.require_prior_idle_ms`
  6. decide_hold_tap: `switch (hold_tap->config->flavor)` → `switch (hold_tap->data->t.flavor)`（log の flavor も `hold_tap->data->t.flavor` に）

- [ ] **Step 6: CI green＋HIL 挙動同一**。push→CI→（既に flash 済みなら Task1 と挙動同一のはずだが、data 移植で壊れていないか）roBa_R を再 flash して `lt_to_layer_0` がタップ=LANG2/長押し=SETTING で不変を確認。
Run（host 側テストは不変）: `cd tools/roba-cli && .venv/bin/python -m pytest -q` → 40 passed。
Commit（module＋config）。

---

## Task 3: nvs ストア＋起動 load＋settings-reset hook

**Files (module):** `src/runtime_holdtap_store.c`, `include/zmk/runtime_holdtap.h`, `behavior_runtime_hold_tap.c`(init で load)

**Interfaces:** Produces: `rt_holdtap_get(slot,*out)` / `rt_holdtap_set(slot,*in)` / `rt_holdtap_clear_all()`。NVS-first、mutex、RAM キャッシュ（SP1 と同契約）。

- [ ] **Step 1: store 実装**（SP1 `runtime_macro_store.c` を雛形に）。`SETTINGS_STATIC_HANDLER_DEFINE(rt_holdtap, "rt_holdtap", ...)`、key `rt_holdtap/<slot>`、値 `struct rt_holdtap_timing`。`settings_save_one`/`settings_delete`。`K_MUTEX`。`rt_holdtap_clear_all` で全 slot delete。

- [ ] **Step 2: settings-reset hook**

```c
static void rt_holdtap_settings_reset(void) { rt_holdtap_clear_all(); }
ZMK_RPC_SUBSYSTEM_SETTINGS_RESET(rt_holdtap, rt_holdtap_settings_reset);
```

- [ ] **Step 3: init で nvs override**。`behavior_runtime_hold_tap_init(dev)` の末尾で、`struct behavior_runtime_hold_tap_data *d = dev->data;` に対し `struct rt_holdtap_timing saved; if (rt_holdtap_get(d->slot, &saved) == 0) d->t = saved;`（保存があれば DT 既定を上書き）。注意: behavior init は per-instance に呼ばれる（`dev` ごと）。settings_load のタイミングに留意（SP1 と同様 `settings_load` 後に値が入る設計。必要なら store 側 init で全 slot を RAM キャッシュ→behavior init で参照）。
- [ ] **Step 4: CI green＋HIL**（保存が無ければ DT 既定で従来どおり）。Commit。

---

## Task 4: custom RPC `zmk__holdtap`（proto＋handler, response 返却）

**Files (module):** `proto/zmk/holdtap/holdtap.proto`, `src/studio/holdtap_rpc_handler.c`, CMake に proto 追加

**Interfaces:** Produces: subsystem `zmk__holdtap`。ops: `ListHoldTaps`→`{repeated HoldTapInfo}`、`GetHoldTap{slot}`→`HoldTapInfo`、`SetHoldTap{slot, timing}`→`{ok}`、`ResetHoldTap{slot}`→`{ok}`。`HoldTapInfo{slot, tapping_term_ms, quick_tap_ms, require_prior_idle_ms, flavor}`。**全て response で返す**（notification 非依存）。

- [ ] **Step 1: proto 定義**（`HoldTapInfo`＋Request/Response oneof。flavor は uint32=enum index 0..3）。
- [ ] **Step 2: handler**（`ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__holdtap, &meta, handler)`、`ZMK_RPC_CUSTOM_SUBSYSTEM_RESPONSE_BUFFER`）。Set は `rt_holdtap_set`＋RAM キャッシュ更新（次押下から反映）。Reset は当該 slot を DT 既定へ（DT 既定値の保持が必要→store に「DT 既定」を別途保持するか、reset=nvs delete＋RAM を DT 既定へ。**DT 既定は behavior data 初期値なので、store では「DT 既定のコピー」を init 時に保持**しておき reset で復元）。List は behavior インスタンス走査（slot 数は `DT_NUM_INST` 相当 or 登録テーブル）。
- [ ] **Step 3: RX バッファ確認**（holdtap payload は小さい。現 RX_BUF=1024/PAYLOAD_MAX=512 で充分）。CI green。Commit。

> 注: List/Get で「現 RAM 値」を返すには、store か behavior 側に slot→timing の参照テーブルが要る。behavior init で各 data を登録する軽いテーブル（`rt_holdtap_register(slot, &data->t)`）を store に持たせ、RPC はそれを読む設計にする。

---

## Task 5: host `holdtap_client.py`＋`roba holdtap` verb

**Files:** `tools/roba-cli/proto/zmk/holdtap/holdtap.proto`(+生成), `roba_cli/holdtap_client.py`, `cli.py`, `tests/test_holdtap.py`

- [ ] **Step 1: proto コピー＋生成**（`grpc_tools.protoc -I proto --python_out=roba_cli/proto proto/zmk/holdtap/holdtap.proto`、`__init__.py`）。
- [ ] **Step 2: 純粋 builder/decoder＋テスト**（flavor 文字列↔index: hold-preferred=0/balanced=1/tap-preferred=2/tap-unless-interrupted=3。field map: tapping-term-ms/quick-tap-ms/require-prior-idle-ms/flavor）。FakeSerial で get/list の response 経路をテスト。
- [ ] **Step 3: `HoldtapClient`**（custom 封筒2段、`zmk__holdtap` 解決、`rpc.send_recv`）。get/list は response から HoldTapInfo を取得（notification 非依存）。
- [ ] **Step 4: cli `roba holdtap list|get <slot>|set <slot> <field> <value>|reset <slot>`**、set 前バックアップ。parser スモークテスト。
- [ ] **Step 5: 全スイート緑**（`pytest -q`）。Commit。

---

## Task 6: keymap 全変換＋実機 E2E＋ドキュメント

- [ ] **Step 1: lt_to_apple_default / lt_to_ipad / lt_to_iphone も `zmk,behavior-runtime-hold-tap` に変換**（slot 1..3）。CI green。再 flash。
- [ ] **Step 2: 実機 E2E**:
```bash
.venv/bin/roba holdtap list                     # 4 slot, 各 tapping_term_ms=200 等
.venv/bin/roba holdtap set 0 tapping-term-ms 120 # 短く
.venv/bin/roba holdtap get 0                      # 120 反映
# 物理確認: lt_to_layer_0 のキーが ~120ms で層に入る体感
# 電源オフ→再接続→get 0 が 120（永続） → reset 0 → 200 復帰 → roba reset でも復帰
.venv/bin/roba holdtap set 0 flavor balanced     # flavor 変更も確認
```
- [ ] **Step 3: revert 確定**（set 永続/reset 復帰/`roba reset` 効果を記録）。README（module＋roba-cli）更新。Commit。
- [ ] **Step 4: 全スイート緑最終確認**。

---

## Self-Review

- **Spec coverage**: spec の受け入れ条件（モジュール有効でビルド成功=Task1/2/4、set 反映+永続+reset 復帰=Task6、判定ロジック不変=Task1-2 の逐語フォーク+6 read-site 限定変更）をカバー。✓
- **Placeholder scan**: 911行はインライン展開せず curl 取得＋厳密 edit を指示（go/no-go 性質を明示）。RPC handler の List 実装は slot→timing 登録テーブル方式を明記。✓
- **Type consistency**: flavor index 0..3 を firmware enum・proto・host で一致。`rt_holdtap_timing` を store/behavior/RPC で共通。get は全経路 response 返却（W1b 教訓）。✓
- **既知の注意**: ①upstream hold-tap と共存のためリネーム必須（重複リスナ）。②reset の「DT 既定」は init 時にコピー保持して復元。③settings_load タイミング（SP1 同様 store init で RAM キャッシュ→behavior が参照）。④firmware 変更タスク（1-4,6）は CI＋flash を伴う最大規模。
