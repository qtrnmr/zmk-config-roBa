# roba-cli (SP0)

roBa を USB シリアル経由で焼かずに設定変更する CLI。

## セットアップ
    python3 -m venv .venv && . .venv/bin/activate
    pip install -e .
    # zmk-studio-api は PyPI 0.3.1 では macOS で serial/BLE が無効。
    # 動作確認済みは source ビルド(0.4.0系, serial+ble feature):
    pip install maturin
    pip install "git+https://github.com/srwi/zmk-studio-api.git" --config-settings=build-args="--features python,serial,ble"

## コマンド
- `roba info` — デバイス/ロック/keymap サマリ
- `roba key get <layer> <pos>` — キーの現 behavior
- `roba key set <layer> <pos> "<behavior>"` — 変更して保存（例 `"KP B"`, `"trans"`, `"MO 5"`）
- `roba snapshot [path]` — 現 keymap 生バイトを記録
- `roba reset` — devicetree 既定へ全戻し（第一の安全網）

## 戻し方（重要）
1. まず `roba reset`（nvs を devicetree 既定へ。flash 済みファームの元 keymap に戻る）
2. 直前変更の内容は `.roba-backup.jsonl` に before_repr が残る
3. 最終手段: `settings_reset` uf2 を書込（リセット ダブルタップ→マウント→コピー。物理操作）
