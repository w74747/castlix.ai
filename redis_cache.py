"""
redis_cache.py — وحدة إدارة الذاكرة السريعة والجلسات عبر Redis لمنصة Castlix.

المزايا:
  - حفظ واسترجاع سياق المحادثات المؤقتة بسرعة فائقة.
  - قفل المهام الثقيلة لمنع تكرار التنفيذ المتزامن لنفس المستخدم.
  - دعم التراجع التلقائي إلى الذاكرة المحلية في حال غياب REDIS_URL.
"""
import os
import json
import logging
from typing import Optional, Any, Dict

logger = logging.getLogger("CastlixRedis")

# استيراد مكتبة redis
try:
    import redis
except ImportError:
    redis = None

REDIS_URL = os.getenv("REDIS_URL")

class RedisManager:
    def __init__(self, url: Optional[str] = REDIS_URL):
        self.client = None
        self._local_cache: Dict[str, Any] = {}
        
        if redis and url:
            try:
                self.client = redis.from_url(
                    url,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5
                )
                self.client.ping()
                logger.info("تم الاتصال بـ Redis بنجاح.")
            except Exception as exc:
                logger.warning(f"تعذر الاتصال بـ Redis ({exc})؛ سيتم استخدام الذاكرة المحلية كبديل.")
                self.client = None
        else:
            logger.info("لم يتم ضبط REDIS_URL؛ الاعتماد على الذاكرة المحلية.")

    def set_session(self, user_id: int, data: Dict[str, Any], expire_seconds: int = 3600) -> bool:
        """حفظ بيانات جلسة المستخدم مع مهلة صلاحية."""
        key = f"castlix:session:{user_id}"
        payload = json.dumps(data, ensure_ascii=False)
        if self.client:
            try:
                return bool(self.client.setex(key, expire_seconds, payload))
            except Exception as exc:
                logger.error(f"خطأ أثناء الكتابة في Redis: {exc}")
        
        # حفظ محلي بديل
        self._local_cache[key] = data
        return True

    def get_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """استرجاع بيانات جلسة المستخدم."""
        key = f"castlix:session:{user_id}"
        if self.client:
            try:
                val = self.client.get(key)
                if val:
                    return json.loads(val)
                return None
            except Exception as exc:
                logger.error(f"خطأ أثناء القراءة من Redis: {exc}")
        
        return self._local_cache.get(key)

    def clear_session(self, user_id: int) -> bool:
        """حذف جلسة المستخدم."""
        key = f"castlix:session:{user_id}"
        if self.client:
            try:
                self.client.delete(key)
            except Exception as exc:
                logger.error(f"خطأ أثناء حذف الجلسة من Redis: {exc}")
        
        self._local_cache.pop(key, None)
        return True

    def acquire_lock(self, user_id: int, timeout_seconds: int = 300) -> bool:
        """قفل تشغيلي لمنع إطلاق مهمتين ثقيلتين في نفس الوقت لنفس المستخدم."""
        lock_key = f"castlix:lock:{user_id}"
        if self.client:
            try:
                # nx=True تضمن أن القفل يُكتسب فقط إذا لم يكن موجوداً مسبقاً
                return bool(self.client.set(lock_key, "locked", nx=True, ex=timeout_seconds))
            except Exception as exc:
                logger.error(f"خطأ أثناء ضبط القفل في Redis: {exc}")
        
        if lock_key in self._local_cache:
            return False
        self._local_cache[lock_key] = True
        return True

    def release_lock(self, user_id: int) -> bool:
        """تحرير القفل التشغيلي للمستخدم."""
        lock_key = f"castlix:lock:{user_id}"
        if self.client:
            try:
                self.client.delete(lock_key)
            except Exception as exc:
                logger.error(f"خطأ أثناء تحرير القفل من Redis: {exc}")
        
        self._local_cache.pop(lock_key, None)
        return True

# إنشاء نسخة عامة واحدة جاهزة للاستخدام في كافة وحدات البوت
cache = RedisManager()
