# Mac/iPad/iPhone Modifier and IME Key Remap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apple系3レイヤー（`APPLE_DEFAULT` / `IPAD` / `IPHONE`）の親指段で Cmd と Ctrl の物理位置を入れ替え、さらに `APPLE_DEFAULT` の Space 左右タップ動作を `GLOBE` から `LANG2`/`LANG1` に変えて、Win レイヤーと操作感を一致させる。

**Architecture:** `config/roBa.keymap` の3レイヤーの親指段4行を編集するのみ。ZMK の `lt`/`mt` のホールド側挙動は維持し、タップ側のキーコードと `&kp` の並び順だけを変更する。ビルドと書き込みは既存の GitHub Actions ワークフロー（push 時に自動）と DYA Studio／既存の手段に任せる。

**Tech Stack:** ZMK firmware (devicetree keymap), git。テストフレームワークは無く、動作確認は (1) ファイル grep による静的検証、(2) ファーム書き込み後の実機動作確認、で行う。

**Spec:** `docs/superpowers/specs/2026-05-27-mac-modifier-and-ime-design.md`

---

## File Structure

変更対象は1ファイルのみ。

- Modify: `config/roBa.keymap`
  - `APPLE_DEFAULT` レイヤーの親指段（line 254 相当）
  - `IPAD` レイヤーの親指段（line 265 相当）
  - `IPHONE` レイヤーの親指段（line 276 相当）

新規ファイル、削除ファイルなし。

---

## Task 1: APPLE_DEFAULT レイヤーの修正

**Files:**
- Modify: `config/roBa.keymap` (APPLE_DEFAULT の親指段 1 行)

このタスクで「Cmd ↔ Ctrl の入れ替え」と「`GLOBE` → `LANG2`/`LANG1`」を**同時に**実施する。両者とも APPLE_DEFAULT の同じ行に対する編集なので分割しても意味がない。

- [ ] **Step 1: 編集前の状態を grep で確認**

Run:
```bash
grep -n 'lt_to_apple_default L_SETTING GLOBE' config/roBa.keymap
grep -n 'lt_to_apple_default L_ARROW GLOBE' config/roBa.keymap
grep -nE '&kp LCTRL +&kp LEFT_GUI +&kp LEFT_ALT +&lt_to_apple_default' config/roBa.keymap
```
Expected: それぞれ 1 件ずつヒット（=現状が想定通り）

- [ ] **Step 2: APPLE_DEFAULT 親指段を編集**

Edit tool 操作:

old_string:
```
&kp LCTRL         &kp LEFT_GUI  &kp LEFT_ALT  &lt_to_apple_default L_SETTING GLOBE  &lt L_NUM SPACE  &lt_to_apple_default L_ARROW GLOBE      &kp BACKSPACE  &lt L_FUNCTION ENTER                               &kp DEL
```

new_string:
```
&kp LEFT_GUI      &kp LCTRL     &kp LEFT_ALT  &lt_to_apple_default L_SETTING LANG2  &lt L_NUM SPACE  &lt_to_apple_default L_ARROW LANG1      &kp BACKSPACE  &lt L_FUNCTION ENTER                               &kp DEL
```

変更点:
1. `&kp LCTRL` ↔ `&kp LEFT_GUI` の順序入れ替え（先頭2つ）
2. `&kp LCTRL` 列幅を 18 → 14 char 相当に調整（13 spaces → 5 spaces で後続列の桁を維持）
3. `&kp LEFT_GUI` 列幅を 14 → 18 char に調整（2 spaces → 6 spaces）
4. Space 左の `GLOBE` → `LANG2`
5. Space 右の `GLOBE` → `LANG1`

- [ ] **Step 3: 編集後の grep 検証**

Run:
```bash
grep -n 'lt_to_apple_default L_SETTING LANG2' config/roBa.keymap
grep -n 'lt_to_apple_default L_ARROW LANG1' config/roBa.keymap
grep -nE '&kp LEFT_GUI +&kp LCTRL +&kp LEFT_ALT +&lt_to_apple_default' config/roBa.keymap
grep -n 'lt_to_apple_default L_SETTING GLOBE' config/roBa.keymap
grep -n 'lt_to_apple_default L_ARROW GLOBE' config/roBa.keymap
```
Expected:
- 上3つ: 各 1 件ヒット
- 下2つ: ヒット 0 件（`GLOBE` が `apple_default` 行から消えていること）

- [ ] **Step 4: git diff で目視確認（コミットはしない）**

Run: `git --no-pager diff config/roBa.keymap`
Expected: APPLE_DEFAULT の親指段 1 行のみが差分として出る。他の行に意図しない変更がない。

---

## Task 2: IPAD レイヤーの修正

**Files:**
- Modify: `config/roBa.keymap` (IPAD の親指段 1 行)

IPAD はすでに `LANG2`/`LANG1` を使っているため、Cmd ↔ Ctrl の入れ替えのみ行う。

- [ ] **Step 1: 編集前の状態を grep で確認**

Run:
```bash
grep -nE '&kp LCTRL +&kp LEFT_GUI +&kp LEFT_ALT +&lt_to_ipad' config/roBa.keymap
```
Expected: 1 件ヒット

- [ ] **Step 2: IPAD 親指段を編集**

Edit tool 操作:

old_string:
```
&kp LCTRL         &kp LEFT_GUI  &kp LEFT_ALT  &lt_to_ipad L_SETTING LANG2  &lt L_NUM SPACE  &lt_to_ipad L_ARROW LANG1      &kp BACKSPACE  &lt L_FUNCTION ENTER                               &kp DEL
```

new_string:
```
&kp LEFT_GUI      &kp LCTRL     &kp LEFT_ALT  &lt_to_ipad L_SETTING LANG2  &lt L_NUM SPACE  &lt_to_ipad L_ARROW LANG1      &kp BACKSPACE  &lt L_FUNCTION ENTER                               &kp DEL
```

変更点:
1. `&kp LCTRL` ↔ `&kp LEFT_GUI` の順序入れ替え
2. 列幅の調整（Task 1 と同じ規則）

- [ ] **Step 3: 編集後の grep 検証**

Run:
```bash
grep -nE '&kp LEFT_GUI +&kp LCTRL +&kp LEFT_ALT +&lt_to_ipad' config/roBa.keymap
grep -nE '&kp LCTRL +&kp LEFT_GUI +&kp LEFT_ALT +&lt_to_ipad' config/roBa.keymap
```
Expected:
- 1 件目: 1 件ヒット
- 2 件目: 0 件（旧パターンは無くなった）

- [ ] **Step 4: git diff で目視確認**

Run: `git --no-pager diff config/roBa.keymap`
Expected: APPLE_DEFAULT に加え IPAD の親指段 1 行も差分に含まれる。意図しない他行の変更が無い。

---

## Task 3: IPHONE レイヤーの修正

**Files:**
- Modify: `config/roBa.keymap` (IPHONE の親指段 1 行)

IPHONE も IPAD と同じく、Cmd ↔ Ctrl の入れ替えのみ。

- [ ] **Step 1: 編集前の状態を grep で確認**

Run:
```bash
grep -nE '&kp LCTRL +&kp LEFT_GUI +&kp LEFT_ALT +&lt_to_iphone' config/roBa.keymap
```
Expected: 1 件ヒット

- [ ] **Step 2: IPHONE 親指段を編集**

Edit tool 操作:

old_string:
```
&kp LCTRL         &kp LEFT_GUI  &kp LEFT_ALT  &lt_to_iphone L_SETTING LANG2  &lt L_NUM SPACE  &lt_to_iphone L_ARROW LANG1      &kp BACKSPACE  &lt L_FUNCTION ENTER                               &kp DEL
```

new_string:
```
&kp LEFT_GUI      &kp LCTRL     &kp LEFT_ALT  &lt_to_iphone L_SETTING LANG2  &lt L_NUM SPACE  &lt_to_iphone L_ARROW LANG1      &kp BACKSPACE  &lt L_FUNCTION ENTER                               &kp DEL
```

変更点:
1. `&kp LCTRL` ↔ `&kp LEFT_GUI` の順序入れ替え
2. 列幅の調整

- [ ] **Step 3: 編集後の grep 検証**

Run:
```bash
grep -nE '&kp LEFT_GUI +&kp LCTRL +&kp LEFT_ALT +&lt_to_iphone' config/roBa.keymap
grep -nE '&kp LCTRL +&kp LEFT_GUI +&kp LEFT_ALT +&lt_to_iphone' config/roBa.keymap
```
Expected:
- 1 件目: 1 件ヒット
- 2 件目: 0 件

- [ ] **Step 4: 全レイヤーの最終 grep 整合性チェック**

Run:
```bash
echo "--- 旧パターン（Cmd in middle, GLOBE）が残っていないこと ---"
grep -nE '&kp LCTRL +&kp LEFT_GUI +&kp LEFT_ALT' config/roBa.keymap
grep -n 'lt_to_apple_default.*GLOBE' config/roBa.keymap
echo "--- 新パターン（Cmd outside, LANG2/LANG1）が3レイヤー全てに存在すること ---"
grep -cE '&kp LEFT_GUI +&kp LCTRL +&kp LEFT_ALT' config/roBa.keymap
```
Expected:
- 旧 `LCTRL LEFT_GUI LEFT_ALT` パターン: 0 件
- 旧 `apple_default ... GLOBE`: 0 件
- 新 `LEFT_GUI LCTRL LEFT_ALT` パターン: 3 件（3レイヤー分）

---

## Task 4: 最終差分確認とコミット

**Files:**
- Modify: なし（コミットのみ）

- [ ] **Step 1: 全体差分を確認**

Run: `git --no-pager diff config/roBa.keymap`
Expected: 3 レイヤーの親指段 3 行のみが変更されており、他の行に変更が一切無い。`-` 行 3 本、`+` 行 3 本。

- [ ] **Step 2: ステージング**

Run: `git add config/roBa.keymap`

- [ ] **Step 3: ステータス確認**

Run: `git status`
Expected: `modified:   config/roBa.keymap` のみがステージ済み。他のファイルは変更されていない。

- [ ] **Step 4: コミット**

Run:
```bash
git commit -m "$(cat <<'EOF'
feat: align Apple-layer modifiers and IME keys with Win operation feel

Swap LEFT_GUI and LCTRL in the thumb cluster of APPLE_DEFAULT, IPAD,
and IPHONE layers so that "Win Ctrl op" maps to "Mac Cmd op" by
finger position. Also switch APPLE_DEFAULT's Space-adjacent tap keys
from GLOBE to LANG2/LANG1 to match the JIS 英数/かな behavior already
in use on IPAD/IPHONE layers.

See: docs/superpowers/specs/2026-05-27-mac-modifier-and-ime-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: コミット後の状態確認**

Run: `git --no-pager log --oneline -3`
Expected: 直近のコミットが上記メッセージで作成されている。

---

## 動作確認（実機テスト）

コミット後、ファーム書き込みと実機での動作確認を行う。コードレベルの自動テストは存在しないため、これは人手による検証となる。

**確認項目:**

1. **macOS 側の前提確認**
   - システム設定 → キーボード → 「キーボードの種類を変更…」を開き、JIS 配列として認識されていることを確認。されていない場合は JIS を選び直す。

2. **APPLE_DEFAULT (Mac) レイヤー**
   - 親指外側を押下しながら `C` → コピー（Cmd+C 相当）が動く
   - 親指中央を押下しながら任意キー → Mac の Ctrl ショートカットとして動作する
   - Space 左タップで「英数」に固定切替される（押すたび英数化）
   - Space 右タップで「かな」に固定切替される（押すたびかな化）
   - Space 左ホールド → L_SETTING に遷移する（従来動作維持）
   - Space 右ホールド → L_ARROW に遷移する（従来動作維持）

3. **IPAD レイヤー**
   - 親指外側を押下しながら `C` → Cmd+C 相当が動く
   - Space 左右の `LANG2`/`LANG1` が回帰なく動く

4. **IPHONE レイヤー**
   - IPAD と同様の確認

5. **DEFAULT (Win) レイヤー（回帰確認）**
   - 親指段が変更されていないこと、Ctrl+C 等が従来通り動くことを確認

**前提が崩れていた場合のロールバック:**

macOS が JIS として認識できず `LANG1`/`LANG2` が無視される場合は、APPLE_DEFAULT 行のタップキーのみ `GLOBE` に戻すコミットを追加する（Cmd/Ctrl の入れ替えは維持）。

---

## Self-Review チェック結果

- **Spec coverage:** 設計ドキュメントの「変更 1」(3レイヤーの Cmd/Ctrl 入れ替え) は Task 1/2/3 で、「変更 2」(APPLE_DEFAULT の GLOBE → LANG2/LANG1) は Task 1 でカバー済み
- **Placeholder scan:** TBD / TODO / 曖昧表現なし。全 Edit に exact old_string / new_string、全コマンドに expected 出力を記載
- **Type consistency:** `LEFT_GUI` / `LCTRL` / `LANG1` / `LANG2` / `GLOBE` の表記が全タスクで一貫。`lt_to_apple_default` / `lt_to_ipad` / `lt_to_iphone` のマクロ名も `roBa.keymap` 定義と一致
