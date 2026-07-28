"""
出現判定モジュール
- 企業名・ブランド名キーワード検出
- ドメイン別 URL 検出（コーポレートサイト + サービスサイト の2URL）
- リスト中の掲載順位推定
- 言及前後の文脈抽出
"""

import re


class MentionDetector:

    def __init__(self, keywords: dict):
        self.primary   = keywords.get("primary",   [])
        self.secondary = keywords.get("secondary", [])
        self.all_keywords = self.primary + self.secondary

        # ドメイン別 URL 辞書（小文字化して保持）
        self.domain_urls: dict[str, list[str]] = {
            domain: [u.lower() for u in urls]
            for domain, urls in keywords.get("domain_urls", {}).items()
        }

    # ------------------------------------------------------------------ #
    # メイン検出メソッド
    # ------------------------------------------------------------------ #
    def detect(self, text: str, domain: str = None) -> dict:
        """
        Parameters
        ----------
        text   : LLM の回答テキスト
        domain : 質問の axis_domain（例: "C2", "C3-EC"）
                 指定されると domain_urls から対象URLも検出する

        Returns
        -------
        dict:
            detected      (bool)       : キーワードまたはURLが1つでも検出されたか
            position      (int|None)   : 推定掲載順位（番号付きリスト形式の場合）
            entities      (list[str])  : 検出されたキーワード一覧
            urls_found    (list[str])  : 検出されたURL一覧
            context       (str)        : 最初にヒットした箇所の前後文脈（最大300文字）
        """
        if not text:
            return {
                "detected":  False,
                "position":  None,
                "entities":  [],
                "urls_found": [],
                "context":   "",
            }

        lower = text.lower()

        # --- キーワード検出 ---
        entities = [kw for kw in self.all_keywords if kw.lower() in lower]

        # --- ドメイン別 URL 検出 ---
        urls_found: list[str] = []
        if domain and domain in self.domain_urls:
            urls_found = [url for url in self.domain_urls[domain] if url in lower]

        detected = bool(entities) or bool(urls_found)

        # --- 掲載順位推定 ---
        position = None
        if detected:
            # 最初にヒットした位置（キーワード or URL）を特定
            hit_pos = len(text)
            for term in entities + urls_found:
                idx = lower.find(term.lower())
                if 0 <= idx < hit_pos:
                    hit_pos = idx

            # ヒット位置より前の番号付きリスト項目を数える
            before = text[:hit_pos]
            patterns = [
                r'\d+[\.．\)）、]',   # 1. 2. 1) 1）
                r'[①②③④⑤⑥⑦⑧⑨⑩]', # 丸数字
                r'第\s*\d+',           # 第1、第 2
            ]
            count = 0
            for pat in patterns:
                count = max(count, len(re.findall(pat, before)))
            position = count + 1  # 手前に n 個あれば n+1 番目

        # --- 文脈抽出（前後150文字）---
        context = ""
        if detected:
            all_terms = entities + urls_found
            if all_terms:
                term = all_terms[0]
                idx  = lower.find(term.lower())
                start = max(0, idx - 80)
                end   = min(len(text), idx + len(term) + 200)
                context = text[start:end].strip()

        return {
            "detected":   detected,
            "position":   position,
            "entities":   entities,
            "urls_found": urls_found,
            "context":    context[:300],
        }
