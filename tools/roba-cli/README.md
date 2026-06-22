# roba-cli (SP0 / SP1 / W1a)

roBa を USB シリアル経由で焼かずに設定変更する CLI。

## セットアップ
    python3 -m venv .venv && . .venv/bin/activate
    pip install -e .
    pip install pyserial
    # zmk-studio-api は PyPI 0.3.1 では macOS で serial/BLE が無効。
    # 動作確認済みは source ビルド(0.4.0系, serial+ble feature):
    pip install maturin
    pip install "git+https://github.com/srwi/zmk-studio-api.git" --config-settings=build-args="--features python,serial,ble"

## コマンド
- `roba info` — デバイス/ロック/keymap サマリ
- `roba key get <layer> <pos>` — キーの現 behavior
- `roba key set <layer> <pos> "<behavior>"` — 変更して保存（例 `"KP B"`, `"trans"`, `"MO 5"`）
- `roba snapshot [path]` — 現 keymap 生バイトを記録
- `roba reset` — devicetree 既定へ全戻し（**マクロも消える**。第一の安全網）
- `roba macro get <slot>` — マクロスロットの現ステップを JSON 表示
- `roba macro set <slot> "<dsl>"` — マクロを DSL から書き込み（変更前は `.roba-backup.jsonl` にバックアップ）

### レイヤー管理（Studio native・焼き直し不要）
- `roba layer list` — 全レイヤーを `index/id/name/bindings(数)` で JSON 列挙
- `roba layer rename <id> <name>` — レイヤー名を変更（set+save で**NVS 永続**）
- `roba layer add` — devicetree 定義済みの空きレイヤー枠を有効化（`list` の `available_layers` が 0 のときは不可）
- `roba layer remove <index>` — レイヤーを削除（同セッション中は `restore` で復元可）
- `roba layer move <start> <dest>` — レイヤーの並べ替え
- `roba layer restore <id> <at_index>` — 削除したレイヤーを復元

mutating 操作はすべて変更前のレイヤー一覧を `.roba-backup.jsonl` に記録し、`save_changes` を伴う。

## マクロ DSL
    type <text>       — ASCII 文字をキーとして送信
    C-<key>           — Ctrl+key（S-=Shift, A-=Alt, G-=GUI/Win/Cmd）
    wait <ms>         — 直前ステップに wait_ms を付加
    区切り: ' | '

例: `"type hi | wait 50 | C-c"` — "hi" 入力後 50ms 待ち Ctrl+C

## 戻し方（重要）
1. まず `roba reset`（nvs を devicetree 既定へ。flash 済みファームの元 keymap に戻る。**マクロも既定に消去される**）
2. 直前変更の内容は `.roba-backup.jsonl` に before_repr / before_steps が残る
3. マクロだけ戻す: `roba macro set 0 "<前のDSLまたはバックアップから復元>"`
4. 最終手段: `settings_reset` uf2 を書込（リセット ダブルタップ→マウント→コピー。物理操作）

### レイヤー名変更の戻し方（実機検証済みの注意点）
`roba layer rename` は **set_layer_props を即時適用し save で NVS 永続**する。ただしこの firmware では:
- `roba reset`（reset_settings）は true を返すが **live では戻らない**。**電源再投入（reboot）で devicetree 既定へ復帰**する（`roba reset` ＋再起動が正規の revert）。
- 元の名前が空（roBa は全レイヤー名が空）の場合、proto3 仕様で**空文字を host から再設定できない**ため、空名への復元は上記の reset+再起動（または settings_reset.uf2）で行う。
- 保存前（save 未実行）の編集は **reboot だけで戻る**。
