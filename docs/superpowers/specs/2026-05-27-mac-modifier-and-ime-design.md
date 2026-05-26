# Mac/iPad/iPhone レイヤーの修飾キーと IME 切替の整理

- 日付: 2026-05-27
- 対象ファイル: `config/roBa.keymap`
- 対象レイヤー: `APPLE_DEFAULT` / `IPAD` / `IPHONE`

## 背景と目的

直近のコミット `55a0b73` で、Apple 系レイヤーの親指段を Win 配列と「物理位置」で揃える方針（`Ctrl | Cmd | Alt`）にした。しかし実運用では「Win での Ctrl 操作 ≡ Mac での Cmd 操作」という**操作感**で揃えたほうが、両 OS を行き来する際の指の動きが完全一致する。

加えて、Mac (`APPLE_DEFAULT`) では Space 左右が `GLOBE` になっており、Win の「JIS 英数/かな」相当の動作（押したキーで状態が一意に確定する）が再現できていない。`GLOBE` はトグルなので「常に英数化」「常にかな化」ができない。IPAD/IPHONE レイヤーは既に `LANG2`/`LANG1` を採用済みで、ここに合わせる。

## 設計

### 1. 親指段の修飾キーを「操作感」で対応させる

対応関係を以下に統一する。

| Win 修飾キー | Mac/iPad/iPhone での対応 |
|---|---|
| `Ctrl` | `Cmd` (`LEFT_GUI`) |
| `Win` | `Ctrl` (`LCTRL`) |
| `Alt` | `Alt/Option` (`LEFT_ALT`) |

これにより、外側親指の最頻出修飾キーが **Win:Ctrl ≡ Mac:Cmd** で一致し、ホームポジション `A` の mod-tap（`mt LEFT_CONTROL A` ↔ `mt LEFT_GUI A`）の対応関係とも完全に揃う。

#### 変更箇所

`APPLE_DEFAULT` / `IPAD` / `IPHONE` の親指段、それぞれの先頭3キー:

- 変更前: `&kp LCTRL  &kp LEFT_GUI  &kp LEFT_ALT`
- 変更後: `&kp LEFT_GUI  &kp LCTRL  &kp LEFT_ALT`

### 2. APPLE_DEFAULT の Space 左右を `LANG2`/`LANG1` に統一

`APPLE_DEFAULT` レイヤーの Space 左右、`lt_to_apple_default` のタップ側を `GLOBE` から `LANG2` / `LANG1` に変更する。`lt`/`mt` 系のホールド側挙動（L_SETTING / L_ARROW への遷移）は影響を受けない。

#### 変更箇所（`APPLE_DEFAULT` のみ）

- Space 左: `&lt_to_apple_default L_SETTING GLOBE` → `&lt_to_apple_default L_SETTING LANG2`
- Space 右: `&lt_to_apple_default L_ARROW GLOBE` → `&lt_to_apple_default L_ARROW LANG1`

`IPAD` / `IPHONE` は既に `LANG2`/`LANG1` のため変更不要。

## 変更後の親指段（イメージ）

```
APPLE_DEFAULT / IPAD / IPHONE 共通:
  LGUI | LCTRL | LALT | LT(SETTING/LANG2) | LT(NUM/SPACE) | LT(ARROW/LANG1) | BSPC | LT(FUNC/ENT) | DEL
   Cmd   Ctrl   Alt    英数(tap)             Space          かな(tap)
```

## 前提条件

macOS 側でキーボードを **JIS 配列として認識** させる必要がある。

- システム設定 → キーボード → 「キーボードの種類を変更…」で JIS 配列を選ぶ
- これがされていない場合、`LANG1`/`LANG2` が IME に渡らず無視される
- iPadOS / iOS は外付けキーボードを JIS として扱うのが標準的で、既にこの設定で動作している実績がある（IPAD/IPHONE レイヤーが `LANG2`/`LANG1` のまま運用できている事実が裏付け）

Karabiner-Elements は使用しない方針（ZMK 単体で完結させる）。万一 macOS が JIS 認識できないケースに当たった場合は、別途 Karabiner を入れて未使用 F キー（例: F18/F19）を経由する案に切り替えを検討する。

## 影響範囲と非変更項目

- 変更対象は `config/roBa.keymap` の3レイヤーの親指段、計 8 キー位置
  - `APPLE_DEFAULT`: 親指 5 箇所（外側3つ + Space 左右2つ）
  - `IPAD`: 親指 3 箇所（外側3つのみ）
  - `IPHONE`: 親指 3 箇所（外側3つのみ）
- 他レイヤー（FUNCTION/NUM/ARROW/MOUSE/SCROLL/SETTING/APPLE_MOUSE/IPAD_ARROW/IPHONE_ARROW/IPAD_MOUSE/IPHONE_MOUSE）は変更しない
- ホームポジションの mod-tap（A キーの `LEFT_GUI` 等）は既に「操作感」で対応済みのため変更不要
- combos（`redo_apple` 等）は `LG()` を使用しており、Cmd の物理位置に依存しないため変更不要

## テスト計画

ファーム書き込み後、以下を実機で確認する。

- **APPLE_DEFAULT**:
  - 親指外側を押下しながら C/V/A → コピー/ペースト/全選択が動く（Cmd 系として動作）
  - 親指中央を押下しながら任意キー → Mac の Ctrl ショートカットとして動作（例: Ctrl+F2 等）
  - Space 左タップで「英数」、Space 右タップで「かな」に切り替わる
  - Space 左/右ホールドで L_SETTING / L_ARROW に遷移する（従来動作維持）
- **IPAD / IPHONE**:
  - 親指外側で Cmd ショートカットが動く
  - Space 左右の `LANG2`/`LANG1` 動作が従来通り動く（回帰なし）
- **DEFAULT (Win)**: 変更なしのため動作が変わらないこと（回帰確認）

## ロールバック

`git revert` で元に戻せる。設計の前提（macOS の JIS 認識）が崩れていた場合は、APPLE_DEFAULT の `LANG2`/`LANG1` のみ `GLOBE` に戻して様子を見る選択肢を取る。
