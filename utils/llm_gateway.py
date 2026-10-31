"""
llm_gateway.py — بوابة النماذج اللغوية الموحدة مع خاصية التبديل التلقائي (Auto-Failover).
"""
import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("CastlixLLMGateway")

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


class LLMGateway:
    def __init__(self):
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        self.xai_key = os.getenv("XAI_API_KEY")
        self.together_key = os.getenv("TOGETHER_API_KEY")

        self.claude_client = Anthropic(api_key=self.anthropic_key) if (Anthropic and self.anthropic_key) else None
        self.deepseek_client = (
            OpenAI(api_key=self.deepseek_key, base_url="https://api.deepseek.com")
            if (OpenAI and self.deepseek_key) else None
        )
        self.xai_client = (
            OpenAI(api_key=self.xai_key, base_url="https://api.x.ai/v1")
            if (OpenAI and self.xai_key) else None
        )
        self.together_client = (
            OpenAI(api_key=self.together_key, base_url="https://api.together.xyz/v1")
            if (OpenAI and self.together_key) else None
        )

    def _call_single(
        self,
        provider: str,
        prompt: str,
        system_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        tracker=None
    ) -> str:
        provider = provider.lower()
        content = ""
        tokens = 0

        if provider == "deepseek":
            if not self.deepseek_client:
                raise ValueError("DEEPSEEK_API_KEY غير مهيأ")
            m = model or "deepseek-chat"
            res = self.deepseek_client.chat.completions.create(
                model=m,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = res.choices[0].message.content or ""
            if res.usage:
                tokens = res.usage.total_tokens or 0

        elif provider == "xai":
            if not self.xai_client:
                raise ValueError("XAI_API_KEY غير مهيأ")
            m = model or "grok-2-latest"
            res = self.xai_client.chat.completions.create(
                model=m,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = res.choices[0].message.content or ""
            if res.usage:
                tokens = res.usage.total_tokens or 0

        elif provider == "claude":
            if not self.claude_client:
                raise ValueError("ANTHROPIC_API_KEY غير مهيأ")
            m = model or "claude-3-5-sonnet-20241022"
            res = self.claude_client.messages.create(
                model=m,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            content = "".join([b.text for b in res.content if hasattr(b, "text")])
            tokens = (res.usage.input_tokens or 0) + (res.usage.output_tokens or 0)

        elif provider == "together":
            if not self.together_client:
                raise ValueError("TOGETHER_API_KEY غير مهيأ")
            m = model or "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
            res = self.together_client.chat.completions.create(
                model=m,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = res.choices[0].message.content or ""
            if res.usage:
                tokens = res.usage.total_tokens or 0
        else:
            raise ValueError(f"مزود غير معروف: {provider}")

        if tracker and tokens > 0:
            tracker.add_tokens(tokens)

        return content.strip()

    def generate_with_failover(
        self,
        prompt: str,
        system_prompt: str,
        preferred_order: Optional[List[str]] = None,
        tracker=None
    ) -> str:
        """
        تجربة المزودين تباعاً؛ إذا تعثر الأول ينتقل فوراً للثاني لضمان عدم توقف النظام أبداً.
        """
        order = preferred_order or ["deepseek", "claude", "xai", "together"]
        last_error = None

        for p in order:
            try:
                # التحقق المسبق من وجود المفتاح قبل محاولة الاستدعاء
                if p == "deepseek" and not self.deepseek_key:
                    continue
                if p == "xai" and not self.xai_key:
                    continue
                if p == "claude" and not self.anthropic_key:
                    continue
                if p == "together" and not self.together_key:
                    continue

                logger.info(f"محاولة استدعاء النموذج عبر المزود: {p}")
                return self._call_single(p, prompt, system_prompt, tracker=tracker)
            except Exception as e:
                logger.warning(f"تعذر الاستدعاء عبر {p} ({e})؛ الانتقال للمزود التالي...")
                last_error = e

        raise RuntimeError(f"فشلت جميع محاولات الاتصال بالنماذج اللغوية: {last_error}")
