"""
出現判定モジュール
- 企業名・ブランド名キーワード検出
- ドメイン別 URL 検出（コーポレートサイト + サービスサイト の2URL）
- リスト中の掲載順位推定
- 言及前後の文脈抽出
- 否定・留保ガード（false-positive 対策）：
    キーワードがヒットした「同一文」に留保・拒否フレーズが共起する場合、
    その出現は設問の復唱にすぎないとみなし検出から除外する。
    （例：「Raffiria について確認しましたが…情報を持ち合わせておりません」→ 検出しない）
"""

import re


# 文境界（この文字までを1文とみなす）。指示書 §A の「。！？改行」に準拠。
_SENTENCE_BOUNDARIES = "。．！？!?\n\r"

# config に disclaimer_phrases が無い場合のフォールバック辞書。
_DEFAULT_DISCLAIMER_PHRASES = [
    "持ち合わせておりません", "持ち合わせていません", "持ち合わせておらず",
    "見当たりません", "存じ上げません", "確認できません", "確認できませんでした",
    "見つけることができませんでした", "見つかりませんでした",
    "わかりません", "分かりません", "特定できません",
    "私の知識の範囲では", "私の知識の中には", "私の知識では",
    "情報がありません", "情報はありません", "情報を持ち合わせて",
    "お答えすることは控え", "お答えできません",
    "申し訳ございません", "申し訳ありません",
]

# config に echo_question_markers が無い場合のフォールバック辞書。
# 回答がユーザーに聞き返している（＝ブランドを知らず設問名を復唱している）文の目印。
_DEFAULT_ECHO_MARKERS = [
    "でしょうか", "ますか", "ですか", "なのか", "のか、",
    "教えてください", "教えていただ", "お聞かせください", "お知らせください",
    "いただけますか", "いただけますでしょうか", "いただけますと",
]


class MentionDetector:

    def __init__(self, keywords: dict):
        self.primary   = keywords.get("primary",   [])
        self.secondary = keywords.get("secondary", [])
        self.all_keywords = self.primary + self.secondary

        # 留保・拒否フレーズ（否定・留保ガード用）
        self.disclaimer_phrases = keywords.get(
            "disclaimer_phrases", _DEFAULT_DISCLAIMER_PHRASES
        )

        # 聞き返し（設問エコー）マーカー
        self.echo_question_markers = keywords.get(
            "echo_question_markers", _DEFAULT_ECHO_MARKERS
        )

        # ドメイン別 URL 辞書（小文字化して保持）
        self.domain_urls: dict[str, list[str]] = {
            domain: [u.lower() for u in urls]
            for domain, urls in keywords.get("domain_urls", {}).items()
        }

    # ------------------------------------------------------------------ #
    # メイン検出メソッド
    # ------------------------------------------------------------------ #
    def detect(self, text: str, domain: str = None, question: str = None) -> dict:
        """
        Parameters
        ----------
        text     : LLM の回答テキスト
        domain   : 質問の axis_domain（例: "C2", "C3-EC"）
                   指定されると domain_urls から対象URLも検出する
        question : 設問文（任意）。将来の「設問エコー除去」拡張用に受け取る。
                   現状の判定ロジックでは未使用だが、呼び出し側との互換のため受理する。

        Returns
        -------
        dict:
            detected            (bool)       : キーワードまたはURLが1つでも検出されたか
            position            (int|None)   : 推定掲載順位（番号付きリスト形式の場合）
            entities            (list[str])  : 検出（留保ガード後に残った）キーワード一覧
            urls_found          (list[str])  : 検出されたURL一覧
            context             (str)        : 最初にヒットした箇所の前後文脈（最大300文字）
            disclaimer_detected (bool)       : 留保・拒否により少なくとも1つのキーワード
                                               ヒットを無効化したか（誤検知抑止の根拠）
        """
        if not text:
            return {
                "detected":  False,
                "position":  None,
                "entities":  [],
                "urls_found": [],
                "context":   "",
                "disclaimer_detected": False,
            }

        lower = text.lower()

        # --- キーワード検出（部分一致した候補を列挙）---
        entities_raw = [kw for kw in self.all_keywords if kw.lower() in lower]

        # --- 否定・留保ガード（＋設問エコー除去）---
        # 各キーワードについて全出現箇所を調べ、「すべての出現が非実体文の中」であれば
        # そのキーワードは設問の復唱にすぎないとみなして除外する。
        # 非実体文＝ 留保・拒否文（例：情報を持ち合わせておりません）
        #           または 聞き返し文（例：〜はどのようなサービスなのか）。
        # 1箇所でも実体文（＝実際に言及・説明している文）に現れていれば残す。
        entities: list[str] = []
        disclaimer_detected = False
        for kw in entities_raw:
            has_evidential_occurrence = False
            for idx in self._find_all(lower, kw.lower()):
                sentence = self._sentence_around(text, idx, len(kw))
                if not self._is_non_evidential(sentence):
                    has_evidential_occurrence = True
                    break
            if has_evidential_occurrence:
                entities.append(kw)
            else:
                # 全出現が留保文／聞き返し文の中 → 誤検知として除外
                disclaimer_detected = True

        # --- ドメイン別 URL 検出 ---
        # URL の一致は「実際に自社サイトを提示した」強い根拠のため留保ガードの対象外。
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
            "disclaimer_detected": disclaimer_detected,
        }

    # ------------------------------------------------------------------ #
    # 補助メソッド
    # ------------------------------------------------------------------ #
    @staticmethod
    def _find_all(haystack: str, needle: str):
        """needle の全出現開始インデックスを返すジェネレータ。"""
        if not needle:
            return
        start = 0
        while True:
            idx = haystack.find(needle, start)
            if idx < 0:
                return
            yield idx
            start = idx + len(needle)

    @staticmethod
    def _sentence_around(text: str, idx: int, term_len: int) -> str:
        """
        text 中の位置 idx（長さ term_len のヒット語）を含む「1文」を返す。
        文境界は _SENTENCE_BOUNDARIES（。．！？!?改行）。
        """
        # 文頭：idx より前で最後に現れた文境界の直後
        start = 0
        for i in range(idx - 1, -1, -1):
            if text[i] in _SENTENCE_BOUNDARIES:
                start = i + 1
                break
        # 文末：ヒット語の末尾以降で最初に現れた文境界（境界文字を含める）
        end = len(text)
        for i in range(idx + term_len, len(text)):
            if text[i] in _SENTENCE_BOUNDARIES:
                end = i + 1
                break
        return text[start:end]

    def _is_disclaimer(self, sentence: str) -> bool:
        """文に留保・拒否フレーズが1つでも含まれるか。"""
        return any(phrase in sentence for phrase in self.disclaimer_phrases)

    def _is_echo_question(self, sentence: str) -> bool:
        """
        文が『ユーザーへの聞き返し（設問エコー）』か。
        末尾が ？/? の疑問文、または echo_question_markers を含む文。
        """
        s = sentence.rstrip("」』）)】 \t\r\n")
        if s.endswith("？") or s.endswith("?"):
            return True
        return any(marker in sentence for marker in self.echo_question_markers)

    def _is_non_evidential(self, sentence: str) -> bool:
        """
        文が『実体としての言及ではない』か。
        留保・拒否文（_is_disclaimer）または聞き返し文（_is_echo_question）なら True。
        """
        return self._is_disclaimer(sentence) or self._is_echo_question(sentence)
