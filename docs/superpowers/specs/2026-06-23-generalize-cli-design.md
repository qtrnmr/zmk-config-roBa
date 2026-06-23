# Generalize CLI (Sub-project B) — Design

Date: 2026-06-23
Status: Approved (design)
Branch: `feat/generalize-cli` (config repo, for the dogfood/migration side) + the unified module repo `zmk-module-runtime-config` (where the CLI now lives)

## Context

Sub-project A merged the four self-built firmware modules into one repo
`qtrnmr/zmk-module-runtime-config`. Sub-project B generalizes the host CLI
(currently `tools/roba-cli` inside the roBa config repo) into a reusable,
pip-installable tool and **co-locates it inside the unified module repo** so the
firmware and CLI share a single proto source and always version-match.

The CLI talks to a keyboard's cormoran custom Studio RPC subsystems over USB
serial. Its logic (framing, transport, behavior resolution, the per-subsystem
clients for macros / hold-tap / conditional-layers / combos / trackball /
encoder) is already keyboard-agnostic. The only roBa-specific surface is:
- `PORT_GLOB = "/dev/cu.usbmodem*"` (macOS-only) in `rpc.py` and `connection.py`,
- the `roba` package/command name and "roBa" wording in messages/docstrings.

## Goal

Produce `zmk-runtime-cli` (command `zmkrt`) living in the unified module repo,
cross-platform (macOS/Linux/Windows) via pyserial port discovery, with no
roBa-specific assumptions. **No backward compatibility** is kept (nobody uses the
old names yet): the package is renamed cleanly, the `roba` command and the
`tools/roba-cli` location are removed from the config repo, and roBa consumes the
CLI by `pip install`ing it from the module repo.

## Decisions (confirmed)

- **Command name**: `zmkrt` only (no `roba` alias). PyPI/dist name `zmk-runtime-cli`.
- **Location**: inside `zmk-module-runtime-config/cli/` (firmware + CLI in one repo).
- **Port discovery**: `serial.tools.list_ports.comports()` (OS-agnostic), filter
  to USB CDC-ACM serial devices; unique → auto, otherwise list candidates and
  require `--port`.
- **Internal package rename**: `roba_cli` → `zmk_runtime_cli` (clean rename, all
  ~19 internal references updated; generated proto moves to the new package).
- **roBa migration**: `tools/roba-cli/` is **deleted** from the config repo; roBa
  uses the CLI via `pip install` from the module repo. (The dogfood HIL still
  runs the same commands, now via `zmkrt`.)
- **No behavior/logic change** to RPC, framing, behavior resolution, or any
  subsystem client — only renaming, port discovery, and packaging.

## Where the CLI lives (final layout in `zmk-module-runtime-config`)

```
zmk-module-runtime-config/
  Kconfig CMakeLists.txt zephyr/ include/ src/ proto/ dts/   # firmware (sub-project A)
  cli/
    pyproject.toml          # name zmk-runtime-cli; script zmkrt = zmk_runtime_cli.cli:run
    README.md               # CLI usage (cross-platform), points at the module
    zmk_runtime_cli/        # renamed from roba_cli/ (verbatim logic)
      __init__.py cli.py rpc.py connection.py framing.py
      behavior_resolve.py behaviors.py macro_dsl.py
      macro_client.py holdtap_client.py condlayer_client.py
      combos_client.py rip_client.py encoder_client.py keymap_client.py
      proto/                # generated *_pb2 (regenerated under the new package)
    tests/                  # the existing pytest suite, imports updated
    proto/                  # .proto sources (shared conceptually with firmware proto/)
```

Proto note: the CLI's generated `*_pb2.py` are produced from `.proto` files. To
keep a single source of truth, the CLI's `.proto` inputs are the same definitions
the firmware uses (the four `zmk.{macros,holdtap,condlayers,combos}` packages plus
the cormoran `rip`/`rsr` and the studio base protos the CLI already vendors). The
generation step lives in the CLI's setup/docs; the committed `*_pb2.py` are the
build artifacts (as today). No proto definition is duplicated with divergent
content — the firmware `proto/` and the CLI `.proto` inputs are the same files
(the CLI keeps its copies of the studio/cormoran protos it needs to talk the
envelope, exactly as `tools/roba-cli/proto` does today).

## Components & changes

### 1. Package rename `roba_cli` → `zmk_runtime_cli`
Mechanical: rename the directory, update all intra-package imports
(`from roba_cli...` / `import roba_cli...` → `zmk_runtime_cli`), update
`roba_cli/proto/__init__.py`'s sys.path shim, and the test imports. The proto
sub-package is regenerated (or moved) under `zmk_runtime_cli/proto/`. Logic
files are otherwise byte-identical.

### 2. Cross-platform port discovery (`rpc.py`)
Replace the `PORT_GLOB` + `glob.glob` approach with:
```python
from serial.tools import list_ports

def find_port() -> str:
    cands = [p.device for p in list_ports.comports() if _is_usb_serial(p)]
    if len(cands) == 1:
        return cands[0]
    raise RuntimeError(
        f"keyboard serial port not uniquely found. candidates={cands}. "
        f"Pass --port explicitly.")
```
`_is_usb_serial(p)` keeps ports that look like a USB CDC-ACM device (e.g. `p.vid
is not None`, or a USB location/`hwid` containing `USB`). This works on macOS
(`/dev/cu.usbmodem*`), Linux (`/dev/ttyACM*`), and Windows (`COMx`). `connection.py`'s
`find_roba_port`/`open` are folded into this single discovery path (the
`zmk-studio-api` `StudioClient.open_serial` path stays, just using the new
finder). Optional `--port` overrides discovery everywhere (unchanged).

### 3. De-roBa the wording
"roBa"/"roba" in messages, docstrings, help text → "keyboard"/"device". No
functional effect. The command verbs (`macro`, `holdtap`, `condlayer`, `combo`,
`encoder`, `trackball`, `key`, `layer`, `info`, `reset`, `snapshot`) are
unchanged.

### 4. Packaging (`pyproject.toml`)
```toml
[project]
name = "zmk-runtime-cli"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["zmk-studio-api", "pyserial"]
[project.scripts]
zmkrt = "zmk_runtime_cli.cli:run"
```
`pipx install .` (from the `cli/` dir) yields the `zmkrt` command. (The
`zmk-studio-api` version/source caveat from the current README is preserved in
the CLI README.)

### 5. roBa config repo cleanup
- Delete `tools/roba-cli/` from the config repo.
- roBa's workflow/docs that referenced `tools/roba-cli` now reference the
  `zmkrt` CLI installed from the module repo. (The repo memory / progress ledger
  note the move.)

## Verification

- **Existing pytest suite stays green** after the rename (logic unchanged). The
  suite moves to `cli/tests/` and runs there. Target: 88 passing.
- **New unit test** for `find_port`: monkeypatch `list_ports.comports()` to
  return (a) one USB CDC-ACM port → returns it; (b) zero/multiple → raises with
  candidate list; (c) non-USB ports filtered out.
- **HIL regression** (dogfood on roBa): after `pipx install` of the new CLI,
  `zmkrt info` / `macro get 0` / `holdtap list` / `condlayer list` / `combo list`
  / `encoder sensors` / `trackball get` all work over USB (mac). Linux/Windows are
  covered in principle by `list_ports` (not hardware-tested here; documented).
- **opus review**: confirm the rename is verbatim (no logic drift), port
  discovery is correct and OS-agnostic, no roBa-specific assumption remains, and
  packaging produces the `zmkrt` entry point.

## Risks & mitigations

- **Broad rename misses a reference** → grep for `roba_cli`/`roBa`/`roba` after
  the rename must return only intentional hits; the test suite import-failing
  catches missed internal refs; opus review double-checks.
- **`_is_usb_serial` filter too strict/loose** → if it returns zero on a real
  device, `--port` is the always-available escape hatch; the heuristic errs
  toward inclusion (vid present OR hwid contains USB) and the unique-or-prompt
  rule prevents wrong auto-selection.
- **Proto duplication drift** → the CLI keeps only the protos it needs to speak
  the envelope (studio/cormoran) plus the four feature protos that match the
  firmware; these are the same definitions. Documented; no divergent copy.
- **zmk-studio-api install caveat** (PyPI build lacks serial on some platforms)
  → carried into the CLI README as today.

## Out of scope (sub-project B)

- Firmware changes (sub-project A, done).
- OSS-wide install guide / examples / top-level README (sub-project C).
- Publishing to PyPI (local/`pipx install .` from the repo is enough for now;
  PyPI release is a sub-project C / later concern).
- Windows/Linux hardware testing (only `list_ports`-level correctness + docs).

## Acceptance

- `zmk-module-runtime-config/cli/` contains the renamed `zmk_runtime_cli`
  package, `pyproject.toml` (name `zmk-runtime-cli`, script `zmkrt`), tests, and
  a CLI README.
- `find_port` uses `list_ports` and is OS-agnostic; `--port` still overrides.
- No `roba_cli` / "roBa" references remain except intentional history/docs.
- pytest green (88 + the new port test); `pipx install .` exposes `zmkrt`.
- `tools/roba-cli/` removed from the config repo; roBa uses `zmkrt`.
- opus review: verbatim rename, correct port discovery, packaging valid.
- Module-repo changes pushed; config-repo branch merged to `main` locally
  (origin not pushed unless asked).
