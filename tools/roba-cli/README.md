# roba-cli (SP0 / SP1)

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
