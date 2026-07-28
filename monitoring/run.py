"""
AI出現モニタリング｜メニュー・ランチャー
────────────────────────────────────────────────
batファイルがダブルクリックで動かない環境向けの、コマンド1つで使えるメニュー。

使い方（Anaconda Prompt）:
    cd /d C:\\Users\\...\\monitoring
    python run.py

数字を入力してEnterで各機能を実行します。
────────────────────────────────────────────────
"""

import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
os.chdir(BASE)
PY = sys.executable  # 実行中と同じPython（Anaconda）を使う

MENU = """
============================================================
  AI出現モニタリング  メニュー
============================================================
  1) GUIを起動（ブラウザで実行画面を開く）
  2) 接続診断（APIに接続できるか確認）
  3) データを全削除（検証データの一掃）
  4) データを選択削除（番号で選んで削除）
  0) 終了
============================================================
"""


def run(*args):
    subprocess.run([PY, *args])


def main():
    while True:
        print(MENU)
        try:
            c = input("番号を入力 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            return

        if c == "1":
            print("\nGUIを起動します。ブラウザで http://127.0.0.1:8765/ を開いてください。")
            print("（終了するにはこのウィンドウで Ctrl+C）\n")
            run("src/webapp.py")
        elif c == "2":
            run("src/diag_connection.py")
            input("\nEnterでメニューに戻ります…")
        elif c == "3":
            run("src/reset_data.py")
            input("\nEnterでメニューに戻ります…")
        elif c == "4":
            run("src/reset_data.py", "--select")
            input("\nEnterでメニューに戻ります…")
        elif c == "0":
            print("終了します。")
            return
        else:
            print("1〜4 または 0 を入力してください。")


if __name__ == "__main__":
    main()
