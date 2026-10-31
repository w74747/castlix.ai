"""اختبارات الأمان والإدخال/الإخراج: الصلاحية تفشل مغلقة، تنظيف أسماء الملفات، Gamma بالمحاكاة."""
import datetime as dt
import importlib

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import filters


def _update(uid: int, text: str = "hi") -> Update:
    msg = Message(
        message_id=1, 
        date=dt.datetime.now(dt.timezone.utc), 
        chat=Chat(id=uid, type="private"),
        from_user=User(id=uid, first_name="t", is_bot=False), 
        text=text
    )
    return Update(update_id=1, message=msg)


def test_empty_allowlist_blocks_everyone():
    assert not filters.User(user_id=[]).check_update(_update(5))


def _reload(monkeypatch, **env):
    for k in ("ALLOWED_USER_IDS", "ADMIN_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config, bot
    importlib.reload(config)
    return importlib.reload(bot)


def test_bot_fail_closed_without_config(monkeypatch):
    bot = _reload(monkeypatch)
    assert not bot.config.ALLOWED_USER_IDS
    assert not bot.AUTH.check_update(_update(123))


def test_bot_allows_only_listed(monkeypatch):
    bot = _reload(monkeypatch, ALLOWED_USER_IDS="111,222", ADMIN_CHAT_ID="333")
    assert bot.AUTH.check_update(_update(111))
    assert bot.AUTH.check_update(_update(333))
    assert not bot.AUTH.check_update(_update(999))


def test_application_builds_with_persistence(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    monkeypatch.setenv("PERSISTENCE_PATH", str(tmp_path / "state.pkl"))
    bot = _reload(monkeypatch, ALLOWED_USER_IDS="1")
    app = bot.build_application()
    assert app.handlers  # بُنيت المعالجات بلا أخطاء


def test_safe_filename_blocks_traversal():
    from utils.doc_parser import safe_filename
    assert safe_filename("../../etc/passwd") == "passwd"
    assert "/" not in safe_filename("a/b\\c.pdf")
    assert safe_filename("قوائم 2024.pdf").endswith(".pdf")


def test_html_escape_and_chunk():
    from utils.telegram_text import chunk, esc
    assert esc("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
    parts = chunk("x" * 9000)
    assert all(len(p) <= 3900 for p in parts) and "".join(parts) == "x" * 9000


def test_cost_tracker_real_metering(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "COST_LOG_PATH", str(tmp_path / "c.jsonl"))
    from utils.cost_tracker import CostTracker
    t = CostTracker("T", 1)
    assert t.total_usd() == 0
    t.add_tavily(2)
    t.add_tavily(1)
    t.add_llama_pages(5)
    expect = 3 * config.PRICES["tavily_usd_per_credit"] + 5 * config.PRICES["llama_usd_per_page"]
    assert abs(t.total_usd() - round(expect, 4)) < 1e-9
    t.stage("presentation", "failed: x")
    assert "مراحل لم تكتمل" in t.report_html()
    t.persist()
    assert (tmp_path / "c.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_gamma_flow_with_mocks(monkeypatch):
    import config
    monkeypatch.setattr(config, "GAMMA_API_KEY", "k")
    from agents import presentation as pres

    calls = {"get": 0, "post_payload": None, "post_headers": None}

    class R:
        def __init__(self, code, data): 
            self.status_code, self._d, self.ok, self.text = code, data, code < 400, str(data)
        def json(self): 
            return self._d

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["post_payload"], calls["post_headers"] = json, headers
        assert url == "https://public-api.gamma.app/v1.0/generations"
        return R(201, {"generationId": "g1"})

    def fake_get(url, headers=None, timeout=None):
        calls["get"] += 1
        assert url.endswith("/generations/g1")
        return R(
            200, 
            {"status": "pending"} if calls["get"] < 2 else {
                "status": "completed", 
                "gammaUrl": "https://gamma.app/docs/x", 
                "credits": {"deducted": 12}
            }
        )

    monkeypatch.setattr(pres.requests, "post", fake_post)
    monkeypatch.setattr(pres.requests, "get", fake_get)
    monkeypatch.setattr(pres.time, "sleep", lambda s: None)
    from utils.cost_tracker import CostTracker
    t = CostTracker("T", 1)
    out = pres.PresentationAgent().generate_pitch_deck(
        "مشروع", 
        "صحار", 
        "1M", 
        "ملخص", 
        {"capex": 1e6, "payback": None, "min_dscr": None}, 
        undocumented=5, 
        tracker=t
    )
    assert out["url"] == "https://gamma.app/docs/x" and t.gamma_credits == 12
    assert "X-API-KEY" in calls["post_headers"] and "Authorization" not in calls["post_headers"]
    assert calls["post_payload"]["textMode"] == "generate" and calls["post_payload"]["inputText"]
    assert "نسخة أولية" in calls["post_payload"]["inputText"]  # تحذير التوثيق يصل للعرض
