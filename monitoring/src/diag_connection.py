"""
接続診断ツール
────────────────────────────────────────────────
「本番実行で Connection error になる」原因を切り分けるための診断。
- Python / anthropic / httpx のバージョン
- プロキシ環境変数
- urllib（標準）での api.anthropic.com 到達確認
- anthropic SDK での実呼び出し（.env のキー使用）＋ 例外の根本原因を表示

使い方（Anaconda Prompt）:
    cd /d <monitoringフォルダ>
    python src/diag_connection.py
"""

import os
import sys
import ssl
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from envload import load_env
load_env(BASE_DIR / ".env")

# OS の証明書ストアを使う（社内CA/中間証明書対策）
_TRUSTSTORE = False
try:
    import truststore
    truststore.inject_into_ssl()
    _TRUSTSTORE = True
except Exception:
    _TRUSTSTORE = False


def line(t=""):
    print(t)


def main():
    line("=" * 56)
    line("  接続診断")
    line("=" * 56)

    # 1) バージョン
    line("\n[1] バージョン")
    line(f"  Python : {sys.version.split()[0]}")
    for mod in ("anthropic", "httpx", "httpcore", "certifi", "socksio", "truststore"):
        try:
            m = __import__(mod)
            line(f"  {mod:11}: {getattr(m, '__version__', '(不明)')}")
        except Exception:
            line(f"  {mod:11}: 未インストール")
    line(f"  OS証明書ストア(truststore): {'有効' if _TRUSTSTORE else '無効（未導入）'}")

    # 2) プロキシ環境変数
    line("\n[2] プロキシ環境変数")
    found = False
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        v = os.environ.get(k)
        if v:
            found = True
            line(f"  {k} = {v}")
    if not found:
        line("  （プロキシ環境変数は設定されていません）")

    # 3) urllib で到達確認
    line("\n[3] urllib（標準）で api.anthropic.com へ到達確認")
    import urllib.request
    try:
        urllib.request.urlopen("https://api.anthropic.com/v1/models", timeout=15)
        line("  → 応答（200）")
    except urllib.error.HTTPError as e:
        line(f"  → HTTP {e.code}（401ならネットワーク/TLSは正常）")
    except Exception as e:
        line(f"  → 到達失敗: {type(e).__name__}: {e}")

    # 4) anthropic SDK で実呼び出し
    line("\n[4] anthropic SDK で実呼び出し（.env のキー使用）")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        line("  ANTHROPIC_API_KEY が読み込めていません（.env を確認）")
        return
    line(f"  キー: {key[:14]}...{key[-4:]}（長さ {len(key)}）")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=30.0)
        r = client.messages.create(
            model="claude-sonnet-5", max_tokens=40,
            messages=[{"role": "user", "content": "1文で自己紹介してください。"}])
        line("  → 成功！ 応答: " + r.content[0].text[:120])
        line("\n[結果] 接続・認証ともにOKです。本番実行できます。")
    except Exception as e:
        line(f"  → 失敗: {type(e).__name__}: {str(e)[:200]}")
        cause = getattr(e, "__cause__", None)
        depth = 0
        while cause and depth < 5:
            line(f"     └ 原因: {type(cause).__name__}: {str(cause)[:200]}")
            cause = getattr(cause, "__cause__", None)
            depth += 1
        line("\n[ヒント]")
        line("  ・原因が 'SOCKS'/'socksio' → pip install \"httpx[socks]\"")
        line("  ・原因が 'certificate verify failed' → 社内CA証明書の設定が必要")
        line("  ・原因が proxy 関連 → プロキシURLの設定/解除を確認")
        line("  ・この[原因]の行を、そのまま担当者/次のチャットに共有してください")


if __name__ == "__main__":
    main()
