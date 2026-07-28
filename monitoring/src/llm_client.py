"""
LLM API クライアント
対応プロバイダ: OpenAI / Anthropic / Google Gemini / Perplexity / xAI(Grok)
"""

import os
import time

# ------------------------------------------------------------------ #
# SSL：OS（Windows等）の証明書ストアを利用する
#   社内ネットワークのSSL検査/社内CA/中間証明書により、
#   httpx 同梱の certifi では「certificate verify failed」になる環境向け。
#   truststore が入っていれば OS の証明書ストアを使うよう注入する。
#   （未インストールでもエラーにはせず、その場合は従来どおり certifi を使用）
# ------------------------------------------------------------------ #
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass


SYSTEM_PROMPT = (
    "あなたは企業の調達担当者・経営者・医療機関の管理職などの業務上の質問に答えるアシスタントです。"
    "質問に対して、具体的な企業名・サービス名・ブランド名を積極的に含めて回答してください。"
    "日本語で回答してください。"
)


class LLMClient:

    def ask(self, model: dict, question: str) -> str:
        provider = model["provider"]
        dispatch = {
            "openai":      self._ask_openai,
            "anthropic":   self._ask_anthropic,
            "google":      self._ask_gemini,
            "perplexity":  self._ask_perplexity,
            "xai":         self._ask_grok,
        }
        if provider not in dispatch:
            raise ValueError(f"Unknown provider: {provider}")
        return dispatch[provider](model, question)

    # ------------------------------------------------------------------ #
    # OpenAI (GPT-4o)
    # ------------------------------------------------------------------ #
    def _ask_openai(self, model: dict, question: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model=model["id"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": question},
            ],
            max_tokens=model.get("max_tokens", 800),
            temperature=model.get("temperature", 0.3),
        )
        time.sleep(0.5)
        return response.choices[0].message.content

    # ------------------------------------------------------------------ #
    # Anthropic (Claude)
    # ------------------------------------------------------------------ #
    def _ask_anthropic(self, model: dict, question: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model=model["id"],
            max_tokens=model.get("max_tokens", 800),
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        time.sleep(0.5)
        return response.content[0].text

    # ------------------------------------------------------------------ #
    # Google Gemini
    # ------------------------------------------------------------------ #
    def _ask_gemini(self, model: dict, question: str) -> str:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        gemini_model = genai.GenerativeModel(
            model_name=model["id"],
            system_instruction=SYSTEM_PROMPT,
        )
        response = gemini_model.generate_content(
            question,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=model.get("max_tokens", 800),
                temperature=model.get("temperature", 0.3),
            ),
        )
        time.sleep(0.5)
        return response.text

    # ------------------------------------------------------------------ #
    # Perplexity Sonar Pro (検索連動型)
    # ------------------------------------------------------------------ #
    def _ask_perplexity(self, model: dict, question: str) -> str:
        import requests
        headers = {
            "Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "sonar-pro",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": question},
            ],
            "max_tokens": model.get("max_tokens", 800),
            "temperature": model.get("temperature", 0.3),
        }
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        time.sleep(0.5)
        return resp.json()["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------ #
    # xAI Grok
    # ------------------------------------------------------------------ #
    def _ask_grok(self, model: dict, question: str) -> str:
        from openai import OpenAI  # Grok は OpenAI 互換 API
        client = OpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
        )
        response = client.chat.completions.create(
            model=model["id"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": question},
            ],
            max_tokens=model.get("max_tokens", 800),
            temperature=model.get("temperature", 0.3),
        )
        time.sleep(0.5)
        return response.choices[0].message.content
