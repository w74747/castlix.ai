"""اختبار تشغيل المسار الكامل مع بوت وهمي: يتحقق من التسلسل وإرسال الملف وتقرير التكلفة وتحرير القفل."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOWED_USER_IDS", "7")
    monkeypatch.setenv("ADMIN_CHAT_ID", "7")
    import importlib, config, bot
    importlib.reload(config)
    monkeypatch.setattr(config, "COST_LOG_PATH", str(tmp_path / "costs.jsonl"))
    monkeypatch.setattr(config, "TAVILY_API_KEY", "t")
    monkeypatch.setattr(config, "GAMMA_API_KEY", None)
    return importlib.reload(bot), config, tmp_path


def _app():
    sent = {"msgs": [], "docs": []}
    bot_obj = MagicMock()
    bot_obj.send_message = AsyncMock(side_effect=lambda **kw: sent["msgs"].append(kw["text"]))
    bot_obj.send_document = AsyncMock(side_effect=lambda **kw: sent["docs"].append(kw))
    return SimpleNamespace(bot=bot_obj), sent


def test_full_pipeline_with_fake_market(env, monkeypatch):
    bot, config, tmp = env

    class FakeMarket:
        def conduct_research(self, idea, loc, tracker=None):
            tracker.add_tavily(1)
            tracker.add_tavily(1)
            return {
                "claims": [{"category": "x"}], 
                "errors": [], 
                "report_html": "<b>سوق</b> <script>"
            }

    monkeypatch.setattr(bot, "MarketResearchAgent", FakeMarket)
    app, sent = _app()
    bot.RUNNING.add(7)
    asyncio.run(
        bot.run_new_project(
            app, 
            99, 
            7, 
            {
                "project_idea": "مصنع <تدوير>", 
                "location": "صحار", 
                "capital": "2 مليون دولار"
            }
        )
    )

    assert len(sent["docs"]) == 1                                # ملف الإكسيل أُرسل بنجاح
    assert 7 not in bot.RUNNING                                  # القفل حُرر للمستخدم
    assert (tmp / "costs.jsonl").exists()                        # التكلفة سُجلت فعلياً
    all_text = "\n".join(sent["msgs"])
    assert "تقرير تكلفة" in all_text                             # وصل تقرير التكلفة للإدارة
    assert "presentation" in all_text or "skipped" in all_text   # العرض التقديمي تم تخطيه بوضوح لعدم وجود المفتاح


def test_pipeline_survives_market_failure(env, monkeypatch):
    bot, config, tmp = env

    class Boom:
        def conduct_research(self, *a, **k):
            raise RuntimeError("api down")

    monkeypatch.setattr(bot, "MarketResearchAgent", Boom)
    app, sent = _app()
    bot.RUNNING.add(7)
    asyncio.run(
        bot.run_new_project(
            app, 
            99, 
            7, 
            {
                "project_idea": "x", 
                "location": "y", 
                "capital": "ابحث أنت"
            }
        )
    )
    assert len(sent["docs"]) == 1                                # النموذج المالي يُسلَّم بالكامل رغم فشل السوق
    assert 7 not in bot.RUNNING                                  # تحرير القفل
    assert any("failed" in m for m in sent["msgs"])              # الفشل يظهر في السجلات وتقرير الإدارة بشفافية
