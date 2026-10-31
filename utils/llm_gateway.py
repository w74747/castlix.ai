"""
llm_gateway.py — بوابة النماذج اللغوية الموحدة لـ Castlix.

تدعم البوابة:
  * Claude (عبر Anthropic SDK)
  * DeepSeek (عبر بروتوكول OpenAI المتوافق)
  * x.ai / Grok (عبر بروتوكول OpenAI المتوافق)
  * Together AI (عبر بروتوكول OpenAI المتوافق)
"""
import os
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("CastlixLLMGateway")

# استيراد المكتبات مع معالجة غيابها المؤقت
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


class LLMGateway:
    """
    بوابة مركزية لاستدعاء مختلف النماذج اللغوية وحساب التوكنز آلياً.
    """
    def __init__(self):
        # 1. مفاتيح واجهات برمجة التطبيقات
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        self.xai_key = os.getenv("XAI_API_KEY")
        self.together_key = os.getenv("TOGETHER_API_KEY")

        # 2. عميل Anthropic (Claude)
        self.claude_client = Anthropic(api_key=self.anthropic_key) if (Anthropic and self.anthropic_key) else None

        # 3. عملاء بروتوكول OpenAI المتوافق
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

    def generate(
        self,
        prompt: str,
        system_prompt: str = "أنت مستشار استثماري وخبير أعمال محترف في منظومة Castlix Advisory.",
        provider: str = "claude",  # claude | deepseek | xai | together
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        tracker=None
    ) -> str:
        """
        استدعاء النموذج المناسب وتتبع الاستهلاك تلقائياً.
        """
        provider = provider.lower()
        content = ""
        total_tokens = 0

        try:
            # ----------------------------------------------------
            # 1. Claude (Anthropic)
            # ----------------------------------------------------
            if provider == "claude":
                if not self.claude_client:
                    raise ValueError("ANTHROPIC_API_KEY غير مهيأ أو مكتبة anthropic مفقودة!")
                
                target_model = model or "claude-3-5-sonnet-20241022"
                response = self.claude_client.messages.create(
                    model=target_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = "".join([block.text for block in response.content if hasattr(block, "text")])
                total_tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)

            # ----------------------------------------------------
            # 2. DeepSeek (Reasoning & Math)
            # ----------------------------------------------------
            elif provider == "deepseek":
                if not self.deepseek_client:
                    raise ValueError("DEEPSEEK_API_KEY غير مهيأ!")
                
                target_model = model or "deepseek-chat"
                response = self.deepseek_client.chat.completions.create(
                    model=target_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                if response.usage:
                    total_tokens = response.usage.total_tokens or 0

            # ----------------------------------------------------
            # 3. x.ai (Grok - Dialogue & Dialects)
            # ----------------------------------------------------
            elif provider == "xai":
                if not self.xai_client:
                    raise ValueError("XAI_API_KEY غير مهيأ!")
                
                target_model = model or "grok-beta"
                response = self.xai_client.chat.completions.create(
                    model=target_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                if response.usage:
                    total_tokens = response.usage.total_tokens or 0

            # ----------------------------------------------------
            # 4. Together AI (High-Speed Extraction & Routing)
            # ----------------------------------------------------
            elif provider == "together":
                if not self.together_client:
                    raise ValueError("TOGETHER_API_KEY غير مهيأ!")
                
                target_model = model or "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
                response = self.together_client.chat.completions.create(
                    model=target_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                if response.usage:
                    total_tokens = response.usage.total_tokens or 0

            else:
                raise ValueError(f"مزود غير معروف: {provider}")

            # تسجيل التوكنز الفعلي في العداد
            if tracker and total_tokens > 0:
                tracker.add_tokens(total_tokens)

            return content.strip()

        except Exception as e:
            logger.error(f"خطأ أثناء استدعاء {provider} ({model}): {e}")
            raise e
