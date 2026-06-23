# Generalize CLI (Sub-project B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `tools/roba-cli` into a reusable cross-platform `zmk-runtime-cli` (command `zmkrt`) living inside the unified module repo `zmk-module-runtime-config/cli/`, with no roBa-specific assumptions and no backward compatibility; delete `tools/roba-cli` from the config repo.

**Architecture:** Copy `tools/roba-cli` into the module repo's `cli/`, rename the package `roba_cli`→`zmk_runtime_cli` (verbatim logic), replace the macOS-only `glob` port discovery with pyserial `list_ports` (OS-agnostic, in `rpc.py`; `connection.py` reuses it), de-roBa the wording, and repackage (`pyproject.toml` name `zmk-runtime-cli`, script `zmkrt`). roBa dogfoods by `pip install`ing it.

**Tech Stack:** Python 3.11+, pyserial (`serial.tools.list_ports`), protobuf, `zmk-studio-api`, pytest; `gh`/git for the module repo.

## Global Constraints

- **No backward compatibility.** Command is `zmkrt` only (no `roba` alias). Package dir `zmk_runtime_cli` (renamed from `roba_cli`). Dist name `zmk-runtime-cli`.
- **No logic change** to RPC/framing/behavior-resolution/subsystem clients — only rename, port discovery, wording, packaging.
- CLI lives in `zmk-module-runtime-config/cli/`. Module repo: `qtrnmr/zmk-module-runtime-config` (already exists, public). Module commits use qtrnmr identity (`git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit`), push via `github.com-qtrnmr` SSH host.
- `tools/roba-cli/` is **deleted** from the config repo (`/Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa`) on branch `feat/generalize-cli`.
- Port discovery: `serial.tools.list_ports.comports()`, keep USB-serial candidates, unique→auto else raise listing candidates; `--port` always overrides.
- Existing pytest suite (88 tests) must stay green after rename (logic unchanged); add the port-discovery test.
- Commit trailers on every commit (both repos):
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F`
- Config-repo branch merged to `main` locally `--no-ff`; do NOT push origin main unless asked.

## Source facts (current `tools/roba-cli`)

- Package `roba_cli/` (16 modules incl. `cli.py rpc.py connection.py framing.py behavior_resolve.py behaviors.py macro_dsl.py macro_client.py holdtap_client.py condlayer_client.py combos_client.py rip_client.py encoder_client.py keymap_client.py __init__.py` + `proto/`). ~19 files reference `roba_cli`.
- Generated proto under `roba_cli/proto/` (`__init__.py` sets sys.path; subdirs `zmk/{macros,holdtap,condlayers,combos}`, `cormoran/{rip,rsr}`, plus top-level `studio_pb2`, `keymap_pb2`, `behaviors_pb2`, etc.). The `.proto` sources are under `tools/roba-cli/proto/`.
- Port discovery is duplicated in TWO places:
  - `roba_cli/rpc.py`: `PORT_GLOB="/dev/cu.usbmodem*"`, `find_port() -> str` (raises on non-unique). Constants `DEFAULT_BAUD=115200`, `READ_TIMEOUT=2.0`, `CHUNK=256`. Used by all direct-serial clients (`macro/holdtap/condlayer/combos/rip/encoder/keymap`).
  - `roba_cli/connection.py`: `PORT_GLOB` (same), `find_roba_port() -> str|None`, `open(port=None) -> zmk.StudioClient` (uses `zmk_studio_api`). Used by `cli.py` for `info`/`key`/`reset`/`snapshot`.
- Entry point: `pyproject.toml` `roba = "roba_cli.cli:run"`; `cli.py` has `def run()` and `def main(argv)`.
- Tests in `tests/` (10 files): `test_{behaviors,combos,condlayer,encoder,framing,holdtap,keymap_ops,macro_dsl,rip,rpc}.py`, all importing `roba_cli...`.

## File Structure (after sub-project B)

In `zmk-module-runtime-config/`:
```
cli/
  pyproject.toml            # name zmk-runtime-cli; [project.scripts] zmkrt = "zmk_runtime_cli.cli:run"
  README.md                 # cross-platform CLI usage
  .gitignore                # copied from tools/roba-cli/.gitignore
  zmk_runtime_cli/          # renamed package (verbatim logic)
    __init__.py cli.py rpc.py connection.py framing.py behavior_resolve.py
    behaviors.py macro_dsl.py macro_client.py holdtap_client.py
    condlayer_client.py combos_client.py rip_client.py encoder_client.py keymap_client.py
    proto/                  # generated *_pb2 + __init__.py (sys.path shim), package-renamed
  proto/                    # .proto sources (copied from tools/roba-cli/proto)
  tests/                    # 10 existing tests (imports updated) + new test_port.py
```
Config repo: `tools/roba-cli/` removed.

---

### Task 1: Copy CLI into the module repo and rename the package

**Files:**
- Create: `zmk-module-runtime-config/cli/**` (copied from `tools/roba-cli`, package renamed)
- (config repo untouched in this task)

**Interfaces:**
- Produces: a `cli/` tree where the package is `zmk_runtime_cli` and the test
  suite passes via that package name. Port discovery + packaging + wording are
  still as-copied (changed in Tasks 2-4).

- [ ] **Step 1: Copy the CLI tree into the module repo**

```bash
SRC=/Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa/tools/roba-cli
DST=/tmp/zmk-module-runtime-config/cli
rm -rf "$DST" && mkdir -p "$DST"
cp -R "$SRC"/. "$DST"/
# drop caches and any local venv/build artifacts
find "$DST" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
rm -rf "$DST"/.venv "$DST"/*.egg-info "$DST"/roba_cli.egg-info 2>/dev/null
```
Confirm `$DST/roba_cli/` and `$DST/tests/` and `$DST/pyproject.toml` exist.

- [ ] **Step 2: Rename the package directory**

```bash
cd /tmp/zmk-module-runtime-config/cli
git -C /tmp/zmk-module-runtime-config add -A >/dev/null 2>&1 || true
mv roba_cli zmk_runtime_cli
```

- [ ] **Step 3: Update all intra-package + test imports `roba_cli` → `zmk_runtime_cli`**

Rewrite every `roba_cli` reference (imports, the `import roba_cli.proto` sys.path
shim line, test imports). Mechanical global replace across the `cli/` tree EXCEPT
do not touch generated `*_pb2.py` internals beyond the package path (the proto
modules are imported as bare top-level names like `studio_pb2` via the sys.path
shim, so they need no change; only `import roba_cli.proto` / `from roba_cli...`
lines change):
```bash
cd /tmp/zmk-module-runtime-config/cli
grep -rl 'roba_cli' . --include='*.py' | while read f; do
  sed -i '' 's/roba_cli/zmk_runtime_cli/g' "$f"   # macOS sed; on Linux use: sed -i 's/.../.../g'
done
grep -rn 'roba_cli' . --include='*.py' || echo "no roba_cli references remain"
```
Expected final: `no roba_cli references remain`.

- [ ] **Step 4: Run the test suite under the new package name**

```bash
cd /tmp/zmk-module-runtime-config/cli
python -m venv .venv && .venv/bin/pip -q install -e . pytest pyserial 2>&1 | tail -2
# zmk-studio-api: install per the README caveat; if PyPI build lacks serial,
# tests that don't need hardware still run. The 88-test suite is pure unit
# (FakeSerial), so it must pass without a device.
.venv/bin/python -m pytest -q
```
Expected: 88 passed (same as before; only the package name changed). If any test
errors on import, a `roba_cli` reference was missed — fix and re-run.

- [ ] **Step 5: Commit (module repo, qtrnmr identity)**

```bash
cd /tmp/zmk-module-runtime-config
git add -A
git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit -m "$(printf 'feat(cli): vendor roba-cli into cli/ and rename package roba_cli -> zmk_runtime_cli\n\nVerbatim logic; package + imports renamed. Port discovery, wording, packaging\nupdated in follow-up tasks.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 2: Cross-platform port discovery via pyserial `list_ports`

**Files:**
- Modify: `cli/zmk_runtime_cli/rpc.py` (replace `find_port`, drop `glob`/`PORT_GLOB`)
- Modify: `cli/zmk_runtime_cli/connection.py` (reuse `rpc.find_port`, drop its own glob)
- Test: `cli/tests/test_port.py` (new)

**Interfaces:**
- Consumes: the renamed package (Task 1).
- Produces: `rpc.find_port() -> str` (OS-agnostic, via `list_ports`), `rpc._is_usb_serial(p) -> bool`; `connection.open(port=None)` delegates discovery to `rpc.find_port`. `DEFAULT_BAUD`/`READ_TIMEOUT`/`CHUNK` unchanged.

- [ ] **Step 1: Write the failing port-discovery test**

Create `cli/tests/test_port.py`:
```python
from zmk_runtime_cli import rpc


class _FakePort:
    def __init__(self, device, vid=None, hwid=""):
        self.device = device
        self.vid = vid
        self.hwid = hwid


def test_is_usb_serial_keeps_vid_and_usb_hwid():
    assert rpc._is_usb_serial(_FakePort("/dev/cu.usbmodem1", vid=0x1234))
    assert rpc._is_usb_serial(_FakePort("COM3", vid=None, hwid="USB VID:PID=1234:5678"))
    assert not rpc._is_usb_serial(_FakePort("/dev/ttyS0", vid=None, hwid=""))


def test_find_port_unique(monkeypatch):
    monkeypatch.setattr(rpc.list_ports, "comports",
                        lambda: [_FakePort("/dev/cu.usbmodem1", vid=0x1234),
                                 _FakePort("/dev/ttyS0", vid=None, hwid="")])
    assert rpc.find_port() == "/dev/cu.usbmodem1"


def test_find_port_zero_raises(monkeypatch):
    monkeypatch.setattr(rpc.list_ports, "comports",
                        lambda: [_FakePort("/dev/ttyS0", vid=None, hwid="")])
    import pytest
    with pytest.raises(RuntimeError):
        rpc.find_port()


def test_find_port_multiple_raises(monkeypatch):
    monkeypatch.setattr(rpc.list_ports, "comports",
                        lambda: [_FakePort("/dev/cu.usbmodem1", vid=0x1),
                                 _FakePort("/dev/cu.usbmodem2", vid=0x2)])
    import pytest
    with pytest.raises(RuntimeError) as e:
        rpc.find_port()
    assert "usbmodem1" in str(e.value) and "usbmodem2" in str(e.value)
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /tmp/zmk-module-runtime-config/cli && .venv/bin/python -m pytest tests/test_port.py -v
```
Expected: FAIL — `rpc` has no `list_ports`/`_is_usb_serial` (old `find_port` uses glob).

- [ ] **Step 3: Implement `list_ports`-based discovery in `rpc.py`**

In `cli/zmk_runtime_cli/rpc.py`: remove `import glob` and `PORT_GLOB`; add
`from serial.tools import list_ports`; replace `find_port`:
```python
from serial.tools import list_ports


def _is_usb_serial(p) -> bool:
    """True if the port looks like a USB CDC-ACM serial device (any OS)."""
    if getattr(p, "vid", None) is not None:
        return True
    hwid = (getattr(p, "hwid", "") or "").upper()
    return "USB" in hwid


def find_port() -> str:
    cands = [p.device for p in list_ports.comports() if _is_usb_serial(p)]
    if len(cands) == 1:
        return cands[0]
    raise RuntimeError(
        f"keyboard serial port not uniquely found. candidates={sorted(cands)}. "
        "Pass --port explicitly."
    )
```
Update the module docstring line that says "roba-cli clients" → "zmk-runtime-cli
clients" (wording; the rest of Task 4 covers remaining wording).

- [ ] **Step 4: Make `connection.py` reuse `rpc.find_port`**

In `cli/zmk_runtime_cli/connection.py`: remove `import glob` and `PORT_GLOB` and
`find_roba_port`; import the shared finder and rewrite `open`:
```python
from __future__ import annotations

import zmk_studio_api as zmk

from . import rpc


def open(port: str | None = None) -> "zmk.StudioClient":
    """Return a StudioClient connected to the keyboard over USB serial."""
    target = port or rpc.find_port()
    return zmk.StudioClient.open_serial(target)
```
(If any code imported `connection.find_roba_port`, repoint it to `rpc.find_port`;
grep to confirm none remains: `grep -rn find_roba_port cli/` → no hits.)

- [ ] **Step 5: Run port tests + full suite**

```bash
cd /tmp/zmk-module-runtime-config/cli
.venv/bin/python -m pytest tests/test_port.py -v
.venv/bin/python -m pytest -q
```
Expected: port tests pass; full suite 88 + 4 new = 92 passed. (If `test_rpc.py`
referenced `PORT_GLOB`/glob, update it to the new discovery — check and fix.)

- [ ] **Step 6: Commit (module repo, qtrnmr identity)**

```bash
cd /tmp/zmk-module-runtime-config
git add -A
git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit -m "$(printf 'feat(cli): OS-agnostic port discovery via pyserial list_ports\n\nReplace macOS-only glob with list_ports + USB-serial filter; connection.py reuses\nrpc.find_port. --port still overrides.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 3: De-roBa wording + repackage (`pyproject.toml`, README)

**Files:**
- Modify: `cli/pyproject.toml`
- Modify: `cli/README.md`
- Modify: any `cli/zmk_runtime_cli/*.py` with "roBa"/"roba" in strings/docstrings/help

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: `zmkrt` entry point; no roBa-specific wording in code/help.

- [ ] **Step 1: Rewrite `pyproject.toml`**

Replace `cli/pyproject.toml` with:
```toml
[project]
name = "zmk-runtime-cli"
version = "0.1.0"
description = "Edit ZMK runtime-config features (macros/hold-tap/conditional-layers/combos/trackball/encoder) over the custom Studio RPC, without reflashing."
requires-python = ">=3.11"
# zmk-studio-api: the PyPI build may lack serial/BLE on some platforms; see README
# for the source-build instructions used during development.
dependencies = ["zmk-studio-api", "pyserial"]

[project.scripts]
zmkrt = "zmk_runtime_cli.cli:run"

[project.optional-dependencies]
dev = ["pytest"]

[tool.setuptools.packages.find]
include = ["zmk_runtime_cli*"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: De-roBa wording in code**

```bash
cd /tmp/zmk-module-runtime-config/cli
grep -rln 'roBa\|roba' zmk_runtime_cli --include='*.py'
```
For each hit that is a user-facing string, docstring, comment, or help text,
replace "roBa"/"roba" with "keyboard"/"device" as fits (e.g. error messages
already say "keyboard serial port" from Task 2; catch any remaining "roBa ..."
in `cli.py` help/epilog and client docstrings). Do NOT rename the package, the
`zmk_runtime_cli` identifier, or any RPC/proto symbol. After editing:
```bash
grep -rn 'roBa\|roba\b' zmk_runtime_cli --include='*.py' || echo "no roBa wording remains"
```
(`roba_cli` no longer exists, so any `roba` hit is wording.)

- [ ] **Step 3: Write `cli/README.md`**

Concise CLI README: what `zmkrt` is (edit ZMK runtime-config features over USB
without reflashing), install (`pipx install .` from `cli/`, or `pip install -e .`),
the `zmk-studio-api` source-build caveat (carried from the old README), the
command groups (`info`, `key`, `layer`, `macro`, `holdtap`, `condlayer`, `combo`,
`encoder`, `trackball`, `reset`, `snapshot`), cross-platform port auto-detection
(and `--port`), and that it requires a keyboard flashed with
`zmk-module-runtime-config` (and the cormoran companion modules for trackball/encoder).

- [ ] **Step 4: Verify the entry point + full suite**

```bash
cd /tmp/zmk-module-runtime-config/cli
.venv/bin/pip -q install -e . 2>&1 | tail -1
.venv/bin/zmkrt --help >/dev/null && echo "zmkrt entry OK"
.venv/bin/python -m pytest -q
```
Expected: `zmkrt entry OK`; 92 passed.

- [ ] **Step 5: Commit (module repo, qtrnmr identity)**

```bash
cd /tmp/zmk-module-runtime-config
git add -A
git -c user.name=qtrnmr -c user.email=65361555+qtrnmr@users.noreply.github.com commit -m "$(printf 'feat(cli): repackage as zmk-runtime-cli (zmkrt) + de-roBa wording + README\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 4: Push module repo; remove `tools/roba-cli` from the config repo

**Files:**
- Delete: `tools/roba-cli/**` (config repo, branch `feat/generalize-cli`)

**Interfaces:**
- Consumes: the pushed module repo with `cli/`.
- Produces: a config repo that no longer carries the CLI.

- [ ] **Step 1: Push the module repo**

```bash
cd /tmp/zmk-module-runtime-config
git push origin main
```
(`origin` is `github.com-qtrnmr:qtrnmr/zmk-module-runtime-config`, set in sub-project A.)

- [ ] **Step 2: Remove `tools/roba-cli` from the config repo**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git rm -r -q tools/roba-cli
```

- [ ] **Step 3: Commit (config repo)**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git commit -m "$(printf 'chore(roba): remove tools/roba-cli; CLI now lives in zmk-module-runtime-config/cli (zmkrt)\n\nroBa consumes the CLI via pip install from the module repo (sub-project B).\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
```

---

### Task 5: opus review, HIL regression, install for roBa, local merge

**Files:** none (verification + merge).

- [ ] **Step 1: opus review**

Dispatch an opus review of the module repo's `cli/` (the three CLI commits) +
the config-repo deletion commit. Confirm: (a) the rename is verbatim — diff
`cli/zmk_runtime_cli/<file>.py` against the original `tools/roba-cli/roba_cli/<file>.py`
(via the config repo's pre-deletion commit) shows only `roba_cli`→`zmk_runtime_cli`
and the deliberate port/wording edits, no logic drift; (b) `find_port` is
OS-agnostic and `--port` overrides; (c) no `roba_cli`/"roBa" reference remains in
code; (d) `pyproject.toml` exposes `zmkrt` and only `zmk_runtime_cli`. Resolve
Critical/Important.

- [ ] **Step 2: Install the CLI for roBa + HIL regression**

```bash
pipx install /tmp/zmk-module-runtime-config/cli   # or: pip install -e
# (use the same zmk-studio-api source build the old README mandated)
zmkrt info
zmkrt macro get 0
zmkrt holdtap list
zmkrt condlayer list
zmkrt combo list
zmkrt encoder sensors
zmkrt trackball get
```
Expected: each responds over USB (mac), proving the renamed/cross-platform CLI is
functionally identical. Device left untouched (read-only smoke).

- [ ] **Step 3: Local merge to main (config repo)**

```bash
cd /Users/kt_nishimura/ghq/github.com/qtrnmr/zmk-config-roBa
git fetch origin && git pull --rebase origin feat/generalize-cli  # take any [Draw] commit
git checkout main
git merge --no-ff feat/generalize-cli -m "$(printf 'Merge: generalize CLI as zmk-runtime-cli in the unified module repo (sub-project B)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01McFkuBWKj5yrQjqwmQmg5F')"
git branch -d feat/generalize-cli
```
Do NOT push origin main unless asked. Update the Claude auto-memory +
`.git/sdd/progress.md` with sub-project B completion.

---

## Self-Review

**Spec coverage:** package rename → Task 1; cross-platform port discovery (list_ports, both rpc.py and connection.py) → Task 2; de-roBa wording → Task 3; repackaging (zmk-runtime-cli/zmkrt) → Task 3; CLI co-located in module repo → Tasks 1-4; delete tools/roba-cli → Task 4; opus verbatim review + HIL regression + local merge → Task 5; tests stay green + new port test → Tasks 1-2. All spec acceptance items covered.

**Placeholder scan:** No TBD/TODO. Port-discovery code, the four port tests, the full pyproject.toml, and the README contents are given concretely. The wording de-roBa step uses grep-then-edit (the exact hits depend on current strings) but bounds it precisely (user-facing strings/docstrings/help only; never identifiers/symbols) with a verify grep.

**Type/identifier consistency:** `rpc.find_port() -> str`, `rpc._is_usb_serial(p) -> bool`, `rpc.list_ports` (the imported module, monkeypatched in tests) are used identically across Task 2's code and tests. `connection.open(port=None)` delegates to `rpc.find_port` (no more `find_roba_port`). Package name `zmk_runtime_cli`, dist `zmk-runtime-cli`, command `zmkrt`, and entry `zmk_runtime_cli.cli:run` are consistent across pyproject, the rename, and the entry-point check.
