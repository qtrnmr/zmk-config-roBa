# Unify Runtime Modules (Sub-project A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the four self-built runtime-edit modules into one repo `zmk-module-runtime-config` (verbatim file relocation + unified Kconfig/CMake), and migrate roBa's `west.yml` from four entries to one, CI green.

**Architecture:** New module repo holds all four features' files unchanged. One Kconfig menu declares the four independent feature options (verbatim from each source). One CMakeLists adds each feature's sources under its Kconfig and runs the nanopb proto generation ONCE over all protos (the four per-repo CMakes each had their own nanopb block — naive concatenation would call `zephyr_library()`/`include(nanopb)` multiple times and double-glob studio handlers, so the unified CMake restructures this). roBa is the dogfood: same CONFIG flags + same keymap, so a green CI build proves the merge.

**Tech Stack:** ZMK (cormoran custom-RPC base), Zephyr, nanopb, west; `gh` for repo creation/push.

## Global Constraints

- **Verbatim relocation only.** No source-logic changes. Every copied `src/`, `include/`, `proto/`, `dts/` file must be byte-identical to its origin (opus review diffs each).
- **Preserve all identifiers**: Kconfig option names, RPC subsystem ids (`zmk__macros/holdtap/condlayers/combos`), proto packages (`zmk.{macros,holdtap,condlayers,combos}`), DT compatibles, and source file names — NO renames.
- Module repo: `qtrnmr/zmk-module-runtime-config`, branch `main`, **public** (CI fetches via https; siblings are public). Module commits use qtrnmr identity: `git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit`. Module push uses the `github.com-qtrnmr` SSH host.
- Config repo branch `feat/unify-runtime-modules`. roBa `roBa_R.conf` and `roBa.keymap` are **unchanged**. Only `config/west.yml` changes (4 entries → 1).
- The cormoran companion modules (`zmk-module-runtime-input-processor`, `zmk-behavior-runtime-sensor-rotate`) stay as separate west.yml entries (out of scope).
- Commit trailers on every commit (config repo + module repo):
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F`
- Merge config branch to `main` locally `--no-ff`; **do not push origin main** unless the user asks.

## Source repos & exact file inventory (all on `qtrnmr`, branch `main`)

Fetch each by cloning over the SSH host, e.g.
`git clone git@github.com-qtrnmr:qtrnmr/zmk-module-runtime-macro /tmp/src-macro`.

**zmk-module-runtime-macro**
- `include/zmk/runtime_macro.h`
- `src/behaviors/behavior_runtime_macro.c`, `src/runtime_macro_store.c`, `src/studio/macros_rpc_handler.c`
- `proto/zmk/macros/macros.proto`, `proto/zmk/macros/macros.options`
- `dts/bindings/behaviors/zmk,behavior-runtime-macro.yaml`

**zmk-module-runtime-holdtap**
- `include/zmk/runtime_holdtap.h`
- `src/behaviors/behavior_runtime_hold_tap.c`, `src/runtime_holdtap_store.c`, `src/studio/holdtap_rpc_handler.c`
- `proto/zmk/holdtap/holdtap.proto`
- `dts/bindings/behaviors/zmk,behavior-runtime-hold-tap.yaml`

**zmk-module-runtime-conditional-layers**
- `include/zmk/runtime_condlayers.h`
- `src/runtime_conditional_layer.c`, `src/runtime_condlayer_store.c`, `src/studio/condlayers_rpc_handler.c`
- `proto/zmk/condlayers/condlayers.proto`
- `dts/bindings/zmk,runtime-conditional-layers.yaml`

**zmk-module-runtime-combos**
- `include/zmk/runtime_combos.h`
- `src/runtime_combo.c`, `src/runtime_combo_store.c`, `src/studio/combos_rpc_handler.c`
- `proto/zmk/combos/combos.proto`, `proto/zmk/combos/combos.options`
- `dts/bindings/zmk,runtime-combos.yaml`

(condlayers/combos protos: combos has a `.options`, condlayers — copy whatever files exist under its `proto/` verbatim. When copying, copy the entire `src/`, `include/`, `proto/`, `dts/` trees per repo to avoid missing any file.)

## File Structure (unified repo `zmk-module-runtime-config`)

```
Kconfig                # one menu, 4 verbatim feature blocks (Task 1 Step 3)
CMakeLists.txt         # restructured: per-feature sources + nanopb-once (Task 1 Step 4)
zephyr/module.yml      # name: zmk-module-runtime-config
LICENSE                # MIT (copy from any source repo)
README.md              # cormoran-RPC requirement + per-feature setup (Task 1 Step 5)
include/zmk/{runtime_macro,runtime_holdtap,runtime_condlayers,runtime_combos}.h
src/behaviors/{behavior_runtime_macro,behavior_runtime_hold_tap}.c
src/{runtime_macro_store,runtime_holdtap_store,runtime_conditional_layer,runtime_condlayer_store,runtime_combo,runtime_combo_store}.c
src/studio/{macros,holdtap,condlayers,combos}_rpc_handler.c
proto/zmk/{macros,holdtap,condlayers,combos}/*  (proto + options where present)
dts/bindings/{zmk,runtime-conditional-layers.yaml, zmk,runtime-combos.yaml,
              behaviors/zmk,behavior-runtime-macro.yaml, behaviors/zmk,behavior-runtime-hold-tap.yaml}
```

---

### Task 1: Build the unified module repo (verbatim merge + unified Kconfig/CMake)

**Files:** create the new repo `/tmp/zmk-module-runtime-config` with the tree above.

**Interfaces:**
- Produces: a self-contained module repo providing the four features behind
  `CONFIG_ZMK_RUNTIME_{MACRO,HOLDTAP,CONDLAYERS,COMBOS}` (+`_STUDIO_RPC`).
- Consumes: the four source repos (clone from GitHub `main`).

- [ ] **Step 1: Clone the four source repos and scaffold the unified repo**

```bash
for m in macro holdtap conditional-layers combos; do
  rm -rf /tmp/src-$m
  git clone -q git@github.com-qtrnmr:qtrnmr/zmk-module-runtime-$m /tmp/src-$m
done
rm -rf /tmp/zmk-module-runtime-config && mkdir -p /tmp/zmk-module-runtime-config
cd /tmp/zmk-module-runtime-config && git init -q
mkdir -p include/zmk src/behaviors src/studio proto dts/bindings
```

- [ ] **Step 2: Copy every source/include/proto/dts file verbatim**

```bash
cd /tmp/zmk-module-runtime-config
for m in macro holdtap conditional-layers combos; do
  cp -R /tmp/src-$m/include/zmk/.       include/zmk/    2>/dev/null
  cp -R /tmp/src-$m/src/.               src/            2>/dev/null
  cp -R /tmp/src-$m/proto/.             proto/          2>/dev/null
  cp -R /tmp/src-$m/dts/.               dts/            2>/dev/null
done
cp /tmp/src-macro/LICENSE LICENSE 2>/dev/null || true
```
After copying, verify the expected files are present:
```bash
find include src proto dts -type f | sort
```
Expected (12 code/proto/dts files + headers): the 4 headers, the 8 src files
(`behavior_runtime_macro.c`, `runtime_macro_store.c`, `macros_rpc_handler.c`,
`behavior_runtime_hold_tap.c`, `runtime_holdtap_store.c`, `holdtap_rpc_handler.c`,
`runtime_conditional_layer.c`, `runtime_condlayer_store.c`, `condlayers_rpc_handler.c`,
`runtime_combo.c`, `runtime_combo_store.c`, `combos_rpc_handler.c`), the proto dirs
`proto/zmk/{macros,holdtap,condlayers,combos}/`, and the 4 dts binding yamls.

- [ ] **Step 3: Write the unified `Kconfig`**

Verbatim concatenation of the four source Kconfigs inside one menu (option names,
help, defaults exactly as in the sources — note macro uses `_MAX_STEPS`+`_SLOTS`,
holdtap uses `_SLOTS`, condlayers/combos use `_MAX`):

```
menu "ZMK Runtime Config (runtime-editable features over custom Studio RPC)"

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

config ZMK_RUNTIME_HOLDTAP
    bool "Enable runtime-editable hold-tap timing"
    help
      Provides a zmk,behavior-runtime-hold-tap behavior — a verbatim fork of
      ZMK's hold-tap whose tapping-term-ms / quick-tap-ms / require-prior-idle-ms
      / flavor are stored in NVS and editable at runtime over a custom Studio RPC,
      without reflashing firmware.

if ZMK_RUNTIME_HOLDTAP

config ZMK_RUNTIME_HOLDTAP_STUDIO_RPC
    bool "Enable hold-tap timing custom Studio RPC (zmk__holdtap)"
    depends on ZMK_STUDIO
    default y

config ZMK_RUNTIME_HOLDTAP_SLOTS
    int "Max runtime hold-tap slots"
    default 8

endif

config ZMK_RUNTIME_CONDLAYERS
    bool "Enable runtime-editable conditional layers"
    help
      Provides zmk,runtime-conditional-layers — a verbatim fork of ZMK's
      conditional_layer subsystem whose {if-layers, then-layer} entries are
      stored in NVS and editable at runtime over a custom Studio RPC, without
      reflashing firmware.

if ZMK_RUNTIME_CONDLAYERS

config ZMK_RUNTIME_CONDLAYERS_STUDIO_RPC
    bool "Enable conditional-layers custom Studio RPC (zmk__condlayers)"
    depends on ZMK_STUDIO
    default y

config ZMK_RUNTIME_CONDLAYERS_MAX
    int "Max runtime conditional-layer entries"
    default 16

endif

config ZMK_RUNTIME_COMBOS
    bool "Enable runtime-editable combos"
    help
      Provides zmk,runtime-combos — a verbatim fork of ZMK's combo subsystem;
      binding/timeout/layers/require-prior-idle/slow-release editable over
      zmk__combos, key-positions fixed.

if ZMK_RUNTIME_COMBOS

config ZMK_RUNTIME_COMBOS_STUDIO_RPC
    bool "Enable combos custom Studio RPC (zmk__combos)"
    depends on ZMK_STUDIO
    default y

config ZMK_RUNTIME_COMBOS_MAX
    int "Max runtime combo entries"
    default 16

endif

endmenu
```

- [ ] **Step 4: Write the unified `CMakeLists.txt`**

Restructured so the nanopb block runs ONCE (the four per-repo CMakes each had
their own nanopb block; running it 4× would redefine `zephyr_library()` and
double-add globbed studio sources). Studio handlers are added per-feature
explicitly (not globbed), so a disabled feature's handler isn't compiled.

```cmake
if(CONFIG_ZMK_RUNTIME_MACRO OR CONFIG_ZMK_RUNTIME_HOLDTAP OR CONFIG_ZMK_RUNTIME_CONDLAYERS OR CONFIG_ZMK_RUNTIME_COMBOS)
    zephyr_include_directories(include)
endif()

if(CONFIG_ZMK_RUNTIME_MACRO)
    target_sources(app PRIVATE src/behaviors/behavior_runtime_macro.c)
    target_sources(app PRIVATE src/runtime_macro_store.c)
    if(CONFIG_ZMK_RUNTIME_MACRO_STUDIO_RPC)
        target_sources(app PRIVATE src/studio/macros_rpc_handler.c)
    endif()
endif()

if(CONFIG_ZMK_RUNTIME_HOLDTAP)
    target_sources(app PRIVATE src/behaviors/behavior_runtime_hold_tap.c)
    target_sources(app PRIVATE src/runtime_holdtap_store.c)
    if(CONFIG_ZMK_RUNTIME_HOLDTAP_STUDIO_RPC)
        target_sources(app PRIVATE src/studio/holdtap_rpc_handler.c)
    endif()
endif()

if(CONFIG_ZMK_RUNTIME_CONDLAYERS)
    target_sources(app PRIVATE src/runtime_conditional_layer.c)
    target_sources(app PRIVATE src/runtime_condlayer_store.c)
    if(CONFIG_ZMK_RUNTIME_CONDLAYERS_STUDIO_RPC)
        target_sources(app PRIVATE src/studio/condlayers_rpc_handler.c)
    endif()
endif()

if(CONFIG_ZMK_RUNTIME_COMBOS)
    target_sources(app PRIVATE src/runtime_combo.c)
    target_sources(app PRIVATE src/runtime_combo_store.c)
    if(CONFIG_ZMK_RUNTIME_COMBOS_STUDIO_RPC)
        target_sources(app PRIVATE src/studio/combos_rpc_handler.c)
    endif()
endif()

if(CONFIG_ZMK_RUNTIME_MACRO_STUDIO_RPC OR CONFIG_ZMK_RUNTIME_HOLDTAP_STUDIO_RPC OR CONFIG_ZMK_RUNTIME_CONDLAYERS_STUDIO_RPC OR CONFIG_ZMK_RUNTIME_COMBOS_STUDIO_RPC)
    list(APPEND CMAKE_MODULE_PATH ${ZEPHYR_BASE}/modules/nanopb)
    include(nanopb)
    set(NANOPB_GENERATE_CPP_APPEND_PATH TRUE)
    set(NANOPB_GENERATE_CPP_STANDALONE OFF)

    # NOTE: adding to app target directly causes build issues, so we create a library instead
    zephyr_library()
    file(GLOB_RECURSE PROTO_FILES ${CMAKE_CURRENT_SOURCE_DIR}/proto/*.proto)

    nanopb_generate_cpp(proto_srcs proto_hdrs RELPATH ${CMAKE_CURRENT_SOURCE_DIR} ${PROTO_FILES})
    target_include_directories(${ZEPHYR_CURRENT_LIBRARY} PUBLIC ${CMAKE_CURRENT_BINARY_DIR})
    target_sources(${ZEPHYR_CURRENT_LIBRARY} PRIVATE ${proto_srcs} ${proto_hdrs})

    target_include_directories(app PUBLIC ${CMAKE_CURRENT_BINARY_DIR}/proto)
    add_dependencies(app ${ZEPHYR_CURRENT_LIBRARY})
endif()
```

- [ ] **Step 5: Write `zephyr/module.yml` and `README.md`**

`zephyr/module.yml`:
```yaml
name: zmk-module-runtime-config
build:
  cmake: .
  kconfig: Kconfig
  settings:
    dts_root: .
```

`README.md` (concise): one module that makes ZMK macros / hold-tap / conditional-layers / combos runtime-editable over the custom Studio RPC, **without reflashing**. State the **requirement: a ZMK base that provides the custom Studio RPC layer (`zmk/studio/custom.h`, `ZMK_RPC_CUSTOM_SUBSYSTEM`) — e.g. cormoran's ZMK fork; this is NOT in mainline ZMK**. Setup: add to `west.yml`; enable the per-feature `CONFIG_ZMK_RUNTIME_*`(+`_STUDIO_RPC`) flags; in the keymap switch the relevant nodes to the runtime compatibles (`zmk,behavior-runtime-macro`, `zmk,behavior-runtime-hold-tap`, `zmk,runtime-conditional-layers`, `zmk,runtime-combos`); recommended Studio RPC buffer sizes (`CONFIG_ZMK_STUDIO_RPC_RX_BUF_SIZE=1024`, `CONFIG_ZMK_STUDIO_RPC_CUSTOM_SUBSYSTEM_REQUEST_PAYLOAD_MAX_BYTES=512`). Mention the CLI (sub-project B) and the cormoran companion modules for trackball/encoder.

- [ ] **Step 6: Commit (module repo, qtrnmr identity)**

```bash
cd /tmp/zmk-module-runtime-config
git add -A
git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit -m "$(printf 'feat: unified zmk-module-runtime-config (macro/holdtap/condlayers/combos)\n\nVerbatim merge of the four self-built runtime-edit modules into one module\nwith per-feature Kconfig and a single nanopb proto-generation block.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

- [ ] **Step 7: Verify verbatim (diff each copied file against its source)**

```bash
cd /tmp/zmk-module-runtime-config
for m in macro holdtap conditional-layers combos; do
  for f in $(cd /tmp/src-$m && find include src proto dts -type f); do
    diff "/tmp/src-$m/$f" "$f" >/dev/null && echo "OK $f" || echo "DIFF $f"
  done
done
```
Expected: every line `OK …`, no `DIFF`. (This is the verbatim gate; the opus
review repeats it.)

---

### Task 2: Migrate roBa `west.yml` + push + CI gate

**Files:**
- Modify: `config/west.yml` (config repo, branch `feat/unify-runtime-modules`)

**Interfaces:**
- Consumes: the unified module repo from Task 1 (must be pushed to GitHub).
- Produces: a roBa firmware that builds from the single unified module with the
  same features as before.

- [ ] **Step 1: Create + push the unified module repo to GitHub**

```bash
cd /tmp/zmk-module-runtime-config
gh repo create qtrnmr/zmk-module-runtime-config --public -d "Runtime-editable ZMK macros/hold-tap/conditional-layers/combos over custom Studio RPC (no reflash)."
git branch -M main
git remote add origin git@github.com-qtrnmr:qtrnmr/zmk-module-runtime-config
git push -u origin main
```
(`gh` active account must be `qtrnmr`; siblings are public.)

- [ ] **Step 2: Replace the four west.yml entries with one**

In `config/west.yml`, remove the four projects `zmk-module-runtime-macro`,
`zmk-module-runtime-holdtap`, `zmk-module-runtime-conditional-layers`,
`zmk-module-runtime-combos`, and add a single:
```yaml
    - name: zmk-module-runtime-config
      remote: qtrnmr-gh
      revision: main
```
Leave the cormoran entries (`zmk-module-runtime-input-processor`,
`zmk-behavior-runtime-sensor-rotate`) and everything else unchanged. Do NOT
touch `roBa_R.conf` or `roBa.keymap`.

- [ ] **Step 3: Commit (config repo)**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git add config/west.yml
git commit -m "$(printf 'feat(unify): point roBa at unified zmk-module-runtime-config (4 modules -> 1)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

- [ ] **Step 4: Push the feat branch and confirm the CI build**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git push -u origin feat/unify-runtime-modules
```
Watch `build.yml` for the branch to completion (`gh run watch <id> --exit-status`).
Expected: **success** — roBa_R builds with all four features from the unified
module (same CONFIG flags, same keymap as before). If the build fails, the
unified Kconfig/CMake is mis-wired or a file was dropped — fix in the module
repo, push, and re-run CI (`gh run rerun <id>` re-fetches module `main`).

---

### Task 3: HIL smoke, opus review, deprecate old repos, local merge

**Files:** none in config repo beyond the merge; READMEs in the four old module repos.

- [ ] **Step 1: opus verbatim + wiring review**

Dispatch an opus review: (a) re-run the Task-1 diff-vs-source check (every file
byte-identical to its origin repo), (b) confirm the unified Kconfig declares all
four options with the exact original names/sub-options/defaults
(`MACRO`+`_MAX_STEPS`+`_SLOTS`, `HOLDTAP`+`_SLOTS`, `CONDLAYERS`+`_MAX`,
`COMBOS`+`_MAX`), (c) confirm the unified CMake adds each feature's sources under
its CONFIG and the nanopb block runs exactly once and globs all protos, (d)
confirm no file from any source repo is missing. Resolve Critical/Important.

- [ ] **Step 2: User flashes roBa_R + HIL smoke (all four subsystems respond)**

Provide the uf2 (download from the green CI run, place on Desktop). After flash,
over USB:
```bash
cd tools/roba-cli
.venv/bin/roba macro get 0        # responds (not "subsystem not found")
.venv/bin/roba holdtap list       # 4 slots
.venv/bin/roba condlayer list     # 5 entries
.venv/bin/roba combo list         # 6 combos
```
Expected: all four return data — confirms the unified module wired every RPC
subsystem. (No deep per-feature retest; each was validated in its own cycle.)

- [ ] **Step 3: Deprecate the four old module repos**

For each of `zmk-module-runtime-{macro,holdtap,conditional-layers,combos}`, prepend
a deprecation note to its `README.md` pointing to `zmk-module-runtime-config`,
and commit+push (qtrnmr identity). Do not delete the repos (preserve history /
existing references).

- [ ] **Step 4: Local merge to main**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
# take any [Draw] auto-commit first
git fetch origin && git pull --rebase origin feat/unify-runtime-modules
git checkout main
git merge --no-ff feat/unify-runtime-modules -m "$(printf 'Merge: unify runtime modules into zmk-module-runtime-config (sub-project A)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
.venv/bin/python -m pytest tools/roba-cli/ -q   # host untouched: still green
git branch -d feat/unify-runtime-modules
```
Do NOT push origin main unless the user asks. Update the Claude auto-memory +
`.git/sdd/progress.md` with completion.

---

## Self-Review

**Spec coverage:** unified repo layout + verbatim copy → Task 1 (Steps 1-2,7);
unified Kconfig (4 verbatim options) → Task 1 Step 3; unified CMake (nanopb-once)
→ Task 1 Step 4; module.yml + README (cormoran-RPC requirement) → Task 1 Step 5;
roBa west.yml 4→1, conf/keymap unchanged → Task 2; CI gate → Task 2 Step 4; HIL
smoke (4 subsystems) → Task 3 Step 2; opus verbatim/wiring review → Task 3 Step
1; deprecate old repos → Task 3 Step 3; local merge → Task 3 Step 4. All spec
acceptance items covered.

**Placeholder scan:** No TBD/TODO. The Kconfig and CMakeLists are given in full.
File copy uses whole-tree `cp -R` to avoid per-file omissions; Step 7 + the opus
review enforce verbatim. README content is described concretely (requirement +
flags + compatibles + buffer sizes).

**Type/identifier consistency:** Kconfig names (`ZMK_RUNTIME_MACRO`/`_MAX_STEPS`/
`_SLOTS`, `HOLDTAP`/`_SLOTS`, `CONDLAYERS`/`_MAX`, `COMBOS`/`_MAX`) match the CMake
guards and the source modules verbatim. Source file names in the CMake match the
copied files (`macros_rpc_handler.c`, `holdtap_rpc_handler.c`,
`condlayers_rpc_handler.c`, `combos_rpc_handler.c`, etc.). The unified module
name `zmk-module-runtime-config` is used consistently in module.yml, the repo
creation, and roBa's west.yml entry.
