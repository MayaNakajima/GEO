"""
.env 読み込みヘルパー
────────────────────────────────────────────────
python-dotenv が入っていれば利用し、無ければ簡易パーサで .env を読み込む。
（Anaconda など、まだパッケージ未導入の環境でも最低限起動できるようにするため）
既存の環境変数は上書きしない。
"""

import os


def load_env(path):
    # 1) python-dotenv があれば使う
    try:
        from dotenv import load_dotenv
        load_dotenv(path)
        return
    except Exception:
        pass
    # 2) フォールバック：自前でパース
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass
