# roBa runtime マクロ編集 (SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** マクロ1スロットを serial 越しに編集→nvs永続→実行できる runtime マクロを、自前 zmk-module として実装する（SP1 最小スライス）。

**Architecture:** cormoran fork の `ZMK_RPC_CUSTOM_SUBSYSTEM`（custom 封筒）で studio.proto を改変せずに `zmk__macros` RPC をモジュールから追加。モジュールは `zmk,behavior-runtime-macro` ドライバ＋nvs ストア＋RPC ハンドラを持つ。ホスト `roba-cli` は cormoran `custom.proto`＋自前 `macros.proto` の Python 生成物で custom 封筒を組み、SP0 の serial+framing で送受信。walking-skeleton 順（module 雛形→behavior→nvs→RPC→host→E2E）で未知を先に潰す。

**Tech Stack:** Zephyr/ZMK C (cormoran `v0.3-branch+dya`), nanopb, Zephyr settings(nvs), Python(roba-cli, protobuf, pyserial), CI build (GitHub Actions), HIL on roBa_R(seeeduino_xiao_ble).

## Global Constraints

- 転送は USB serial のみ（BLE 不使用）。編集は cormoran `custom` 封筒経由（`ZMK_RPC_CUSTOM_SUBSYSTEM`、`ZMK_RPC_SUBSYSTEM` ではない）。
- スロットは固定1個（`&rt_macro 0`）を devicetree 事前宣言（R1）。
- ステップ＝キー入力＋wait/tap のみ。保存は HID キーコード直値で（R3 回避）。step に type タグを持たせ③前方互換。
- マクロ blob は1 nvs レコードに収める。`MAX_STEPS = 32`、`MACRO_SLOTS = 1`（R2）。
- 「すぐ戻せる」継承：`roba reset`(=`reset_settings()`) で nvs 既定化＝マクロも消える。flash 前に known-good uf2 を保持。
- firmware ビルドは CI グリーン必須。ローカル west 環境なし＝CI でビルド、roBa_R を物理 flash。
- gh の write 操作（repo 作成/ push）は qtrnmr アカウント。git push は ssh alias `git@github.com-qtrnmr`。
- proto のフィールド番号は firmware とホストで同一 .proto から生成し厳密一致させる。

---

## File Structure

**新規モジュールリポジトリ `qtrnmr/zmk-module-runtime-macro`**（cormoran モジュールに倣う。CI が west.yml から fetch するため別 repo が確実）:
- `zephyr/module.yml` — モジュールマニフェスト
- `CMakeLists.txt` — src と proto(nanopb) のビルド
- `Kconfig` — `CONFIG_ZMK_RUNTIME_MACRO`, `..._STUDIO_RPC`
- `dts/bindings/behaviors/zmk,behavior-runtime-macro.yaml` — DTS バインディング
- `proto/zmk/macros/macros.proto` — `GetMacro`/`SetMacro`/`MacroStep`（自前。custom payload に詰める）
- `include/zmk/runtime_macro.h` — 公開 API（store get/set/load）
- `src/runtime_macro_store.c` — nvs ストア＋RAM キャッシュ
- `src/behaviors/behavior_runtime_macro.c` — 実行 behavior
- `src/studio/macros_rpc_handler.c` — `ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__macros, ...)` ハンドラ

**zmk-config-roBa（このリポジトリ）**:
- `config/west.yml` — 上記モジュールを projects に追加（Modify）
- `boards/shields/roBa/roBa_R.conf` — `CONFIG_ZMK_RUNTIME_MACRO=y` 等（Modify）
- `config/roBa.keymap` — `&rt_macro 0` を空きキーに配置（Modify）
- `tools/roba-cli/roba_cli/framing.py` — Studio framing(0xAB/0xAC/0xAD)（Create）
- `tools/roba-cli/roba_cli/macro_dsl.py` — steps DSL パーサ（Create）
- `tools/roba-cli/roba_cli/macro_client.py` — custom 封筒で macros RPC を送受信（Create, pyserial）
- `tools/roba-cli/roba_cli/proto/` — `custom.proto`(cormoran), `macros.proto` から生成した Python（Create）
- `tools/roba-cli/roba_cli/cli.py` — `macro get/set` 追加（Modify）
- `tools/roba-cli/tests/test_framing.py`, `test_macro_dsl.py`（Create）

---

## Task 1: モジュール雛形 + west 配線 + CI グリーン

**目的:** 空の zmk-module が CI でビルドを壊さずロードされることを確認（module 配線 de-risk）。`custom` 封筒が現ファームで有効かもここで確認。

**Files:**
- 新 repo `qtrnmr/zmk-module-runtime-macro`: `zephyr/module.yml`, `CMakeLists.txt`, `Kconfig`, `README.md`
- Modify: `config/west.yml`
- Modify: `boards/shields/roBa/roBa_R.conf`

**Interfaces:**
- Produces: モジュール名 `zmk-module-runtime-macro`, Kconfig `CONFIG_ZMK_RUNTIME_MACRO` / `CONFIG_ZMK_RUNTIME_MACRO_STUDIO_RPC`。

- [ ] **Step 1: モジュール repo を作成（qtrnmr アカウント）**

```bash
gh auth switch --user qtrnmr
gh repo create qtrnmr/zmk-module-runtime-macro --public --description "Runtime-editable macro module for ZMK (roBa SP1)"
gh auth switch --user kt-nishimura
```
ローカルに clone: `git clone git@github.com-qtrnmr:qtrnmr/zmk-module-runtime-macro /tmp/zmk-module-runtime-macro`

- [ ] **Step 2: `zephyr/module.yml`**

```yaml
name: zmk-module-runtime-macro
build:
  cmake: .
  kconfig: Kconfig
  settings:
    board_root: .
    dts_root: .
    snippet_root: .
```

- [ ] **Step 3: `Kconfig`**

```kconfig
config ZMK_RUNTIME_MACRO
    bool "Enable runtime-editable macro"

if ZMK_RUNTIME_MACRO

config ZMK_RUNTIME_MACRO_STUDIO_RPC
    bool "Expose runtime macro editing over ZMK Studio custom RPC"
    depends on ZMK_STUDIO
    default y

config ZMK_RUNTIME_MACRO_MAX_STEPS
    int "Maximum steps per macro"
    default 32

config ZMK_RUNTIME_MACRO_SLOTS
    int "Number of runtime macro slots"
    default 1

endif
```

- [ ] **Step 4: `CMakeLists.txt`（src/proto は次タスク以降で追加。今は空ビルド可に）**

```cmake
if(CONFIG_ZMK_RUNTIME_MACRO)
    zephyr_include_directories(include)
    # src は Task2 以降で追加
endif()
```

- [ ] **Step 5: モジュールを push、config/west.yml に追加**

`/tmp/zmk-module-runtime-macro` で `git add -A && git commit -m "feat: module skeleton" && git push`。
`config/west.yml` の projects に追加:
```yaml
    - name: zmk-module-runtime-macro
      remote: qtrnmr-gh         # 下で remote 定義
      revision: main
```
remotes に追加:
```yaml
    - name: qtrnmr-gh
      url-base: https://github.com/qtrnmr
```
`boards/shields/roBa/roBa_R.conf` に追記:
```
CONFIG_ZMK_RUNTIME_MACRO=y
```

- [ ] **Step 6: CI ビルド（roBa_R グリーン確認）**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add config/west.yml boards/shields/roBa/roBa_R.conf
git commit -m "ci: add zmk-module-runtime-macro skeleton to build"
git push   # feature ブランチ
gh run watch "$(gh run list --branch "$(git branch --show-current)" --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
gh run view <id> --json jobs --jq '.jobs[] | {name:(.name[0:50]),conclusion}'
```
Expected: roBa_R ジョブ success。（`v0.3-branch+dya` には `zmk/studio/custom.h` + `custom_subsystem.c` が存在することを別調査で確認済み＝custom 封筒は使える見込み。）失敗時はログの `custom`/RPC 関連シンボル未定義有無を確認し報告。

---

## Task 2: 実行 behavior（ハードコード列）+ DTS + 1スロット配置

**目的:** `&rt_macro 0` 押下で固定列（"hi"）を打鍵。behavior driver + `zmk_behavior_queue_add` + 固定プール(R1) を nvs/RPC 抜きで de-risk。

**Files:**
- 新 repo: `dts/bindings/behaviors/zmk,behavior-runtime-macro.yaml`, `src/behaviors/behavior_runtime_macro.c`, `include/zmk/runtime_macro.h`, `CMakeLists.txt`(Modify)
- Modify: `config/roBa.keymap`

**Interfaces:**
- Produces: compatible `zmk,behavior-runtime-macro`(`#binding-cells = <1>`、param1=slot)。`include/zmk/runtime_macro.h`:
  ```c
  struct rt_macro_step { uint8_t type; uint32_t keycode; uint16_t wait_ms; uint16_t tap_ms; };
  // type: 0 = key tap. RT_MACRO_STEP_KEY 0
  // keycode は ZMK エンコード済み(暗黙修飾を上位ビットに含む。例 LC(C)=0x01000006)。&kp param1 にそのまま渡す。
  int rt_macro_get_steps(uint8_t slot, struct rt_macro_step *out, uint8_t max, uint8_t *count_out);
  ```

- [ ] **Step 1: DTS バインディング `zmk,behavior-runtime-macro.yaml`**

```yaml
description: Runtime-editable macro behavior
compatible: "zmk,behavior-runtime-macro"
include: one_param.yaml
```

- [ ] **Step 2: `include/zmk/runtime_macro.h`（構造体と API 宣言）**

```c
#pragma once
#include <zephyr/types.h>

#define RT_MACRO_STEP_KEY 0

struct rt_macro_step {
    uint8_t type;       // RT_MACRO_STEP_KEY
    uint32_t keycode;   // ZMK-encoded keycode incl. implicit mods (e.g. LC(C)=0x01000006). Passed to &kp param1.
    uint16_t wait_ms;
    uint16_t tap_ms;
};

// Task3 で nvs 実装に差し替え。Task2 では固定列を返すスタブ。
int rt_macro_get_steps(uint8_t slot, struct rt_macro_step *out, uint8_t max, uint8_t *count_out);
```

- [ ] **Step 3: behavior 実装 `src/behaviors/behavior_runtime_macro.c`（固定列 "hi" を打つ）**

`zmk_behavior_queue_add(event, binding, press, wait)` で各キーを press→release。修飾は別 &kp で囲む。v1 Task2 は keycode→`&kp` 相当を作るため、ビルド済み `&kp` の behavior_dev を流用（`zmk_behavior_queue_add` に渡す binding に `behavior_dev="key_press"`、param1=HID usage を設定）。

```c
#define DT_DRV_COMPAT zmk_behavior_runtime_macro
#include <zephyr/device.h>
#include <drivers/behavior.h>
#include <zmk/behavior.h>
#include <zmk/behavior_queue.h>
#include <zmk/runtime_macro.h>
#include <dt-bindings/zmk/keys.h>

static void queue_key_tap(struct zmk_behavior_binding_event event, uint32_t keycode,
                          uint16_t tap_ms, uint16_t wait_ms) {
    // keycode は ZMK エンコード済み(暗黙修飾込み)。&kp(key_press) に渡せば修飾も効く。
    struct zmk_behavior_binding kp = { .behavior_dev = "key_press",
                                       .param1 = keycode, .param2 = 0 };
    zmk_behavior_queue_add(&event, kp, true, tap_ms);
    zmk_behavior_queue_add(&event, kp, false, wait_ms);
}

static int on_rt_macro_pressed(struct zmk_behavior_binding *binding,
                               struct zmk_behavior_binding_event event) {
    struct rt_macro_step steps[CONFIG_ZMK_RUNTIME_MACRO_MAX_STEPS];
    uint8_t count = 0;
    if (rt_macro_get_steps((uint8_t)binding->param1, steps,
                           CONFIG_ZMK_RUNTIME_MACRO_MAX_STEPS, &count) < 0) {
        return ZMK_BEHAVIOR_OPAQUE;
    }
    for (uint8_t i = 0; i < count; i++) {
        queue_key_tap(event, steps[i].keycode, steps[i].tap_ms, steps[i].wait_ms);
    }
    return ZMK_BEHAVIOR_OPAQUE;
}

static int on_rt_macro_released(struct zmk_behavior_binding *binding,
                                struct zmk_behavior_binding_event event) {
    return ZMK_BEHAVIOR_OPAQUE;
}

static const struct behavior_driver_api rt_macro_api = {
    .binding_pressed = on_rt_macro_pressed,
    .binding_released = on_rt_macro_released,
};

static int rt_macro_init(const struct device *dev) { return 0; }

#define RT_MACRO_INST(n)                                                          \
    BEHAVIOR_DT_INST_DEFINE(n, rt_macro_init, NULL, NULL, NULL, POST_KERNEL,      \
                            CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &rt_macro_api);
DT_INST_FOREACH_STATUS_OKAY(RT_MACRO_INST)
```

`rt_macro_get_steps` の Task2 スタブ（同ファイル末尾か別 stub）："hi" = H(0x0B), I(0x0C):
```c
int rt_macro_get_steps(uint8_t slot, struct rt_macro_step *out, uint8_t max, uint8_t *count_out) {
    if (slot != 0 || max < 2) return -EINVAL;
    out[0] = (struct rt_macro_step){ RT_MACRO_STEP_KEY, 0x0B, 0, 5 };  // H
    out[1] = (struct rt_macro_step){ RT_MACRO_STEP_KEY, 0x0C, 0, 5 };  // I
    *count_out = 2;
    return 0;
}
```

- [ ] **Step 4: CMakeLists.txt に src 追加 + keymap 配置**

```cmake
if(CONFIG_ZMK_RUNTIME_MACRO)
    zephyr_include_directories(include)
    target_sources(app PRIVATE src/behaviors/behavior_runtime_macro.c)
endif()
```
keymap: ルートに behavior 参照を入れ、空きキー（例 SETTING レイヤーの空き位置）に `&rt_macro 0` を配置。`config/roBa.keymap` の SETTING レイヤーの `&trans` のどれか1つを `&rt_macro 0` に置換。

- [ ] **Step 5: CI ビルド → flash → HIL**

push → CI グリーン確認 → roBa_R uf2 を `gh run download` → Desktop へ → ユーザーが flash（known-good 保持）→ 配置キー押下で `hi` が打鍵されるか確認。
Expected: キーを押すと `hi` と入力される。

- [ ] **Step 6: Commit（両 repo）**

モジュール repo と config repo をそれぞれ commit。

---

## Task 3: nvs ストア + boot ロード（behavior を nvs 駆動へ）

**目的:** `rt_macro_get_steps` を nvs/RAM キャッシュ実装に差し替え。nvs(R2)+RAM(R4) を de-risk。RPC はまだなので、seed は一時的な default で確認。

**Files:**
- 新 repo: `src/runtime_macro_store.c`(Create), `CMakeLists.txt`(Modify), `include/zmk/runtime_macro.h`(Modify: set API 追加)

**Interfaces:**
- Produces:
  ```c
  int rt_macro_set_steps(uint8_t slot, const struct rt_macro_step *steps, uint8_t count); // RAM+nvs保存
  int rt_macro_get_steps(uint8_t slot, struct rt_macro_step *out, uint8_t max, uint8_t *count_out);
  ```
- Consumes: Zephyr settings (`SETTINGS_STATIC_HANDLER_DEFINE`, `settings_save_one`, `settings_load_subtree`).

> 雛形参考: `app/src/rgb_underglow.c` の settings 部（`SETTINGS_STATIC_HANDLER_DEFINE` + `settings_name_steq` + `read_cb` + デバウンス work で `settings_save_one`）が keymap.c より単純で本タスク向き。ZMK 起動時に中央で `settings_load()` 済みなので、本ハンドラの h_set は自動で呼ばれる（独自に `settings_subsys_init/settings_load` を呼ぶ必要はない）。

- [ ] **Step 1: `src/runtime_macro_store.c`（RAM キャッシュ + settings）**

```c
#include <zephyr/settings/settings.h>
#include <zephyr/sys/util.h>
#include <string.h>
#include <errno.h>
#include <zmk/runtime_macro.h>

#define SLOTS CONFIG_ZMK_RUNTIME_MACRO_SLOTS
#define MAX_STEPS CONFIG_ZMK_RUNTIME_MACRO_MAX_STEPS

static struct rt_macro_step cache[SLOTS][MAX_STEPS];
static uint8_t cache_count[SLOTS];

int rt_macro_get_steps(uint8_t slot, struct rt_macro_step *out, uint8_t max, uint8_t *count_out) {
    if (slot >= SLOTS) return -EINVAL;
    uint8_t n = MIN(cache_count[slot], max);
    memcpy(out, cache[slot], n * sizeof(struct rt_macro_step));
    *count_out = n;
    return 0;
}

int rt_macro_set_steps(uint8_t slot, const struct rt_macro_step *steps, uint8_t count) {
    if (slot >= SLOTS || count > MAX_STEPS) return -EINVAL;
    memcpy(cache[slot], steps, count * sizeof(struct rt_macro_step));
    cache_count[slot] = count;
    char key[24];
    snprintf(key, sizeof(key), "rt_macro/%u", slot);
    // blob: [count][steps...]
    uint8_t buf[1 + MAX_STEPS * sizeof(struct rt_macro_step)];
    buf[0] = count;
    memcpy(&buf[1], steps, count * sizeof(struct rt_macro_step));
    return settings_save_one(key, buf, 1 + count * sizeof(struct rt_macro_step));
}

static int rt_macro_set_cb(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg) {
    const char *next;
    if (!name) return -ENOENT;
    uint8_t slot = (uint8_t)strtoul(name, NULL, 10);
    if (slot >= SLOTS) return 0;
    uint8_t buf[1 + MAX_STEPS * sizeof(struct rt_macro_step)];
    int rc = read_cb(cb_arg, buf, MIN(len, sizeof(buf)));
    if (rc <= 0) return 0;
    uint8_t count = buf[0];
    if (count > MAX_STEPS) count = MAX_STEPS;
    cache_count[slot] = count;
    memcpy(cache[slot], &buf[1], count * sizeof(struct rt_macro_step));
    return 0;
}

SETTINGS_STATIC_HANDLER_DEFINE(rt_macro, "rt_macro", NULL, rt_macro_set_cb, NULL, NULL);
```

(behavior_runtime_macro.c の Task2 スタブ `rt_macro_get_steps` は削除し、本ファイルの実装に一本化。)

- [ ] **Step 2: CMakeLists に store 追加**

```cmake
    target_sources(app PRIVATE src/runtime_macro_store.c)
```

- [ ] **Step 3: 一時 seed で確認（CI/flash/HIL）**

settings load は ZMK が起動時に `settings_load()` 済み。空 nvs なら count=0＝no-op。確認のため一時的に `rt_macro_init`（behavior init）で `rt_macro_set_steps(0, {"hi"}, 2)` を1回呼ぶ seed を入れ、flash→キー押下で `hi` → **電源オフ/オン後も `hi`**（nvs 永続）を確認。確認後 seed は次タスク前に除去。
Expected: 再起動後も `hi` が出る。

- [ ] **Step 4: Commit（両 repo）**

---

## Task 4: macros.proto + custom RPC ハンドラ（Get/Set）

**目的:** `ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__macros)` で nvs ストアを get/set する RPC を追加（R5 de-risk）。

**Files:**
- 新 repo: `proto/zmk/macros/macros.proto`(Create), `src/studio/macros_rpc_handler.c`(Create), `CMakeLists.txt`(Modify), `Kconfig`(既存), `boards...roBa_R.conf`(STUDIO_RPC=y)

**Interfaces:**
- Produces: custom subsystem identifier `zmk__macros`。proto messages `Request{ get_macro|set_macro }`, `Response{ get_macro|set_macro }`, `MacroStep{type,keycode,mods,wait_ms,tap_ms}`。

- [ ] **Step 1: `proto/zmk/macros/macros.proto`**

```protobuf
syntax = "proto3";
package zmk.macros;

message MacroStep {
  uint32 type = 1;
  uint32 keycode = 2;   // ZMK-encoded keycode incl. implicit mods
  uint32 wait_ms = 3;
  uint32 tap_ms = 4;
}
message GetMacroRequest { uint32 slot = 1; }
message GetMacroResponse { repeated MacroStep steps = 1; }
message SetMacroRequest { uint32 slot = 1; repeated MacroStep steps = 2; }
message SetMacroResponse { bool ok = 1; uint32 error = 2; }

message Request {
  oneof request_type {
    GetMacroRequest get_macro = 1;
    SetMacroRequest set_macro = 2;
  }
}
message Response {
  oneof response_type {
    GetMacroResponse get_macro = 1;
    SetMacroResponse set_macro = 2;
  }
}
```
nanopb options（`macros.options`）で `steps` を固定長に：
```
zmk.macros.GetMacroResponse.steps max_count:32
zmk.macros.SetMacroRequest.steps  max_count:32
```

- [ ] **Step 2: `src/studio/macros_rpc_handler.c`（settings-rpc を踏襲）**

`ZMK_RPC_CUSTOM_SUBSYSTEM(zmk__macros, &meta, handler)` を定義。handler は payload を `zmk_macros_Request` に pb_decode → which_request_type で分岐。get は `rt_macro_get_steps` → `zmk_macros_GetMacroResponse` を pb_encode → response buffer へ。set は steps を `rt_macro_set_steps` → ok 応答。レスポンスは `ZMK_RPC_CUSTOM_SUBSYSTEM_RESPONSE_BUFFER(zmk__macros, zmk_macros_Response)` を使用。（実装は settings_rpc_handler.c の構造をそのまま雛形にする。pb_decode/pb_encode、`pb_istream_from_buffer`。）

- [ ] **Step 3: CMakeLists に studio + proto 生成追加（settings-rpc と同型）**

```cmake
    if(CONFIG_ZMK_RUNTIME_MACRO_STUDIO_RPC)
        file(GLOB_RECURSE C_FILES ${CMAKE_CURRENT_SOURCE_DIR}/src/studio/*.c)
        target_sources(app PRIVATE ${C_FILES})
        list(APPEND CMAKE_MODULE_PATH ${ZEPHYR_BASE}/modules/nanopb)
        include(nanopb)
        set(NANOPB_GENERATE_CPP_APPEND_PATH TRUE)
        set(NANOPB_GENERATE_CPP_STANDALONE OFF)
        zephyr_library()
        file(GLOB_RECURSE PROTO_FILES ${CMAKE_CURRENT_SOURCE_DIR}/proto/*.proto)
        nanopb_generate_cpp(proto_srcs proto_hdrs RELPATH ${CMAKE_CURRENT_SOURCE_DIR} ${PROTO_FILES})
        target_include_directories(${ZEPHYR_CURRENT_LIBRARY} PUBLIC ${CMAKE_CURRENT_BINARY_DIR})
        target_sources(${ZEPHYR_CURRENT_LIBRARY} PRIVATE ${proto_srcs} ${proto_hdrs})
        target_include_directories(app PUBLIC ${CMAKE_CURRENT_BINARY_DIR}/proto)
        add_dependencies(app ${ZEPHYR_CURRENT_LIBRARY})
    endif()
```
`roBa_R.conf` に `CONFIG_ZMK_RUNTIME_MACRO_STUDIO_RPC=y`。

- [ ] **Step 4: CI ビルド（グリーン）→ flash**

push → CI グリーン → flash。ハンドラ登録の確認はホスト側（Task5/6）で行う。Task3 の seed はここで除去（空スロットスタート）。
Expected: CI green。

- [ ] **Step 5: Commit（両 repo）**

---

## Task 5: ホスト — framing / DSL / custom 封筒クライアント（ユニット TDD）

**目的:** ハード不要の純ロジック（framing・DSL・custom 封筒組立）を TDD。

**Files:**
- Create: `tools/roba-cli/roba_cli/framing.py`, `roba_cli/macro_dsl.py`
- Create: `tools/roba-cli/tests/test_framing.py`, `tests/test_macro_dsl.py`
- proto 生成: `roba_cli/proto/`（cormoran `custom.proto` + 自前 `macros.proto` を protoc で Python 化）

**Interfaces:**
- Produces: `framing.encode_frame(bytes)->bytes`, `framing.decode_frame(bytes)->bytes`; `macro_dsl.parse(s:str)->list[Step]`、`Step=dict(type,keycode,mods,wait_ms,tap_ms)`。

- [ ] **Step 1: framing テスト（既知ベクタ）**

```python
from roba_cli.framing import encode_frame, decode_frame
def test_roundtrip_plain():
    assert decode_frame(encode_frame(b"\x01\x02")) == b"\x01\x02"
def test_escapes_special_bytes():
    enc = encode_frame(bytes([0xAB, 0xAC, 0xAD]))
    assert enc[0] == 0xAB and enc[-1] == 0xAD
    assert enc.count(0xAC) == 3  # 1 esc per special byte
    assert decode_frame(enc) == bytes([0xAB, 0xAC, 0xAD])
```

- [ ] **Step 2: テスト失敗確認**

Run: `cd tools/roba-cli && . .venv/bin/activate && pytest tests/test_framing.py -v` → FAIL(ImportError)

- [ ] **Step 3: `framing.py` 実装**

```python
SOF, ESC, EOF = 0xAB, 0xAC, 0xAD

def encode_frame(payload: bytes) -> bytes:
    out = bytearray([SOF])
    for b in payload:
        if b in (SOF, ESC, EOF):
            out.append(ESC)
        out.append(b)
    out.append(EOF)
    return bytes(out)

def decode_frame(frame: bytes) -> bytes:
    out = bytearray()
    escaped = False
    for b in frame[1:-1]:
        if escaped:
            out.append(b); escaped = False
        elif b == ESC:
            escaped = True
        else:
            out.append(b)
    return bytes(out)
```

- [ ] **Step 4: framing テスト成功確認** → PASS

- [ ] **Step 5: DSL テスト**

```python
from roba_cli.macro_dsl import parse
def test_type_text():
    steps = parse("type hi")
    assert [s["keycode"] for s in steps] == [0x0B, 0x0C]  # h, i (no implicit mods)
def test_modified_key():
    s = parse("C-c")[0]
    assert s["keycode"] == 0x01000006  # LC(c): ctrl bit (0x01<<24) | c(0x06)
def test_wait_attaches_to_prev():
    steps = parse("C-c | wait 200")
    assert steps[-1]["wait_ms"] == 200
def test_unknown_token_raises():
    import pytest
    with pytest.raises(ValueError):
        parse("frobnicate x")
```

- [ ] **Step 6: DSL テスト失敗確認** → FAIL

- [ ] **Step 7: `macro_dsl.py` 実装**

`|` で分割。トークン: `type <text>`（各文字→ZMKエンコード keycode。大文字は LS() 修飾ビット付与）, `wait <ms>`（直前 step の wait_ms に加算、step が無ければエラー）, `<mods->key>`（`C-/S-/A-/G-` 接頭を ZMK 修飾ビット `(1<<24)/(2<<24)/(4<<24)/(8<<24)` に、末尾キーを HID usage に変換して OR）。HID usage マップは a-z=0x04..0x1D＋基本記号（ASCII）。`Step=dict(type=0,keycode,wait_ms=0,tap_ms=0)`（keycode は修飾込み単一値）。完全な実装コード（HID テーブル＋修飾ビット）を記述。

- [ ] **Step 8: DSL テスト成功確認** → PASS（4 件）

- [ ] **Step 9: proto Python 生成**

```bash
cd tools/roba-cli && . .venv/bin/activate && pip install protobuf grpcio-tools
# cormoran custom.proto と自前 macros.proto を取得して生成
python -m grpc_tools.protoc -I proto --python_out=roba_cli/proto proto/zmk/custom.proto proto/zmk/macros/macros.proto
```
（custom.proto は cormoran/zmk-studio-messages の custom-studio-protocol ブランチから取得。macros.proto はモジュールと同一ファイルをコピー＝単一ソース。）

- [ ] **Step 10: Commit**

---

## Task 6: ホスト統合 + E2E HIL（macro get/set, 永続, reset）

**目的:** `roba macro get/set` を実機で通し、SP1 DoD を満たす。

**Files:**
- Create: `tools/roba-cli/roba_cli/macro_client.py`
- Modify: `tools/roba-cli/roba_cli/cli.py`

**Interfaces:**
- Consumes: `framing`, `macro_dsl`, 生成 proto, `connection`(serial port 検出)。
- Produces: `roba macro get <slot>`, `roba macro set <slot> "<dsl>"`。

- [ ] **Step 1: `macro_client.py`（custom 封筒で send/recv）**

pyserial で `/dev/cu.usbmodem*` を開く。**custom 封筒は2段呼び出し**（fork の custom_subsystem.c 仕様）:
1. `zmk_studio_Request{ custom: ListCustomSubsystemsRequest }` を送り、応答から identifier `"zmk__macros"` の **数値 `subsystem_index`** を引いてキャッシュ。
2. `zmk_studio_Request{ request_id, custom: CallRequest{ subsystem_index, payload = macros.Request を pb シリアライズした bytes } }` を組み、framing して送信。
応答 frame を decode → `Response.request_response.custom.CallResponse.payload`(bytes) → `macros.Response` を pb parse。
（`custom.proto` の正確なメッセージ名/フィールド番号は cormoran/zmk-studio-messages `custom-studio-protocol` 系ブランチの実ファイルに従う＝Task5 Step9 で取得した生成物を使用。）

- [ ] **Step 2: cli.py に `macro get/set` 追加**

`cmd_macro_get(slot)` → client.get → steps を JSON 出力。`cmd_macro_set(slot, dsl)` → 変更前 get を backup ログ → `macro_dsl.parse` → client.set → JSON(`{"slot":..,"steps":N,"ok":true}`)。parser 配線は SP0 の `key` サブコマンドに倣う。

- [ ] **Step 3: E2E HIL**

```bash
roba macro set 0 "type hi | wait 50 | C-c"
roba macro get 0     # 往復一致確認
```
配置キーを押す → `hi` 入力後に Ctrl+C 等が出る。
**電源オフ→再接続** → `roba macro get 0` が同じ → キー押下で同じ挙動（nvs 永続）。
`roba reset` → `roba macro get 0` が空（既定化）。
Expected: 設定どおり打鍵、再起動永続、reset で消去。

- [ ] **Step 4: README 更新（macro コマンド + 戻し方に「reset でマクロも消える」明記）**

- [ ] **Step 5: Commit**

---

## Self-Review（spec 照合）

- §2 やること（1スロット編集→nvs→実行, ①+②, custom 封筒）: Task1-6 で網羅。✓
- §3 リスク R1(固定プール=Task1/2 DTS宣言) / R2(nvs 1レコード=Task3) / R3(keycode直値=Task2/5 step) / R4(RAMキャッシュ=Task3) / R5(custom 封筒=Task4/6)。各タスクで具体的に踏む。✓
- §5 コンポーネント（behavior/store/RPC/proto/host）: Task2/3/4/5/6 に対応。✓
- §7 安全網（backup ログ, reset でマクロ消去, known-good uf2）: Task6 Step2/3/4。✓
- §8 テスト（ユニット=framing/DSL Task5、HIL=Task2/3/6、CI=各 firmware タスク）。✓
- §9 DoD: Task6 Step3 で set/get 往復・実打鍵・再起動永続・reset 消去を確認。✓
- §10 未決（module 置き場＝別 repo に確定 Task1、proto 単一ソース＝Task5 Step9、RAM 実行＝Task3）。✓
- 型整合: `rt_macro_step{type,keycode(u32,修飾込み),wait_ms,tap_ms}` と proto `MacroStep{type,keycode,wait_ms,tap_ms}` と DSL `Step{type,keycode,wait_ms,tap_ms}` のフィールド一致。`rt_macro_get_steps`/`rt_macro_set_steps` シグネチャ一致。✓
- 修飾キーの曖昧さ解決: 修飾は別フィールドにせず **ZMK エンコード済み keycode(u32) 単一値**に畳む（`&kp param1` がそのまま暗黙修飾を処理）。behavior に mods 実行ロジック不要。DSL が `C-c`→`0x01000006` を計算。全タスクでこの方式に統一済み。✓
- 既知の割り切り/spike: Task2 は behavior+queue を固定列で先行検証。Task4 の custom 封筒登録は settings-rpc を雛形に実装（fork 依存が大きく実装時に実ソース確認必須）。Task6 の custom 封筒の正確な構造(subsystem 識別子の渡し方)は Task1 取得の cormoran `custom.proto` に従い実装時確定。
