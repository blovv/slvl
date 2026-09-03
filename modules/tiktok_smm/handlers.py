import asyncio
import json
import logging
import os
import re
from html import escape
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from playerokapi.enums import ItemDealStatuses, EventTypes
from .meta import PREFIX
from . import set_module

logger = logging.getLogger(PREFIX)
BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "module_settings", "config.json")
PENDING_PATH = os.path.join(BASE, "module_data", "pending.json")
ORDERS_PATH = os.path.join(BASE, "module_data", "orders.json")
_lock = asyncio.Lock()
_processing_chats = set()
TIKTOK_RE = re.compile(r"^https?://(?:www\.)?(?:tiktok\.com|m\.tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/\S+$", re.I)


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _save(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_config():
    return _load(CONFIG_PATH, {})


def update_config(mutator):
    c = get_config()
    mutator(c)
    _save(CONFIG_PATH, c)
    return c


def _item_id(deal):
    item = getattr(deal, "item", None)
    if item is None:
        return ""
    value = getattr(item, "id", None)
    if value is None and isinstance(item, dict):
        value = item.get("id") or item.get("item_id")
    return str(value or "").strip()


def _chat_id(event):
    return str(getattr(getattr(event, "chat", None), "id", "") or "").strip()


def _deal_id(deal):
    return str(getattr(deal, "id", "") or "").strip()


def _item_name(deal):
    item = getattr(deal, "item", None)
    if item is None:
        return ""
    value = getattr(item, "name", None)
    if value is None and isinstance(item, dict):
        value = item.get("name") or item.get("title")
    return str(value or "").strip()


def _normalize_phrase(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def get_keyphrases():
    c = get_config()
    phrases = c.get("keyphrases", [])
    if isinstance(phrases, str):
        phrases = [phrases]
    return [_normalize_phrase(x) for x in phrases if _normalize_phrase(x)]


def is_bound(deal):
    name = _normalize_phrase(_item_name(deal))
    if not name:
        return False
    return any(phrase in name or name == phrase for phrase in get_keyphrases())


def matched_keyphrase(deal):
    name = _normalize_phrase(_item_name(deal))
    return next((phrase for phrase in get_keyphrases() if phrase in name or name == phrase), None)


def valid_tiktok_link(x):
    x = (x or "").strip().rstrip(".,);]}")
    return bool(TIKTOK_RE.match(x)) and len(x) <= 512


def _api_sync(params, timeout):
    cfg = get_config().get("never_smm", {})
    req = Request(
        cfg.get("api_url", "https://neversmm.com/api/v2"),
        data=urlencode(params).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw)


async def api_call(**params):
    c = get_config()
    key = str(c.get("never_smm", {}).get("api_key", "")).strip()
    if not key:
        raise RuntimeError("NeverSMM API key is not configured")
    params["key"] = key
    return await asyncio.to_thread(_api_sync, params, int(c.get("never_smm", {}).get("timeout", 30)))


async def create_order(service_id, link, quantity):
    if not service_id:
        raise RuntimeError("Service ID is not configured")
    quantity = int(quantity)
    if quantity <= 0:
        raise RuntimeError("Quantity must be positive")
    r = await api_call(action="add", service=int(service_id), link=link, quantity=quantity)
    if not isinstance(r, dict) or "order" not in r:
        raise RuntimeError(f"NeverSMM add error: {r}")
    return str(r["order"])


async def _pending_get(chat_id):
    async with _lock:
        return _load(PENDING_PATH, {}).get(str(chat_id))


async def _pending_set(chat_id, value):
    async with _lock:
        d = _load(PENDING_PATH, {})
        d[str(chat_id)] = value
        _save(PENDING_PATH, d)


async def _pending_update(chat_id, **changes):
    async with _lock:
        d = _load(PENDING_PATH, {})
        key = str(chat_id)
        if key in d:
            d[key].update(changes)
            _save(PENDING_PATH, d)


async def _pending_pop(chat_id):
    async with _lock:
        d = _load(PENDING_PATH, {})
        x = d.pop(str(chat_id), None)
        _save(PENDING_PATH, d)
        return x


async def _save_order(deal_id, data):
    async with _lock:
        d = _load(ORDERS_PATH, {})
        d[str(deal_id)] = data
        _save(ORDERS_PATH, d)


async def _update_order(deal_id, **changes):
    async with _lock:
        d = _load(ORDERS_PATH, {})
        key = str(deal_id)
        if key in d:
            d[key].update(changes)
            _save(ORDERS_PATH, d)


async def on_module_enabled(module):
    set_module(module)
    logger.warning("[%s] READY: Playerok event handlers registered", PREFIX)


async def on_playerok_init(plbot):
    logger.warning("[%s] READY: PlayerokBot initialized; listening for NEW_DEAL", PREFIX)


async def on_new_deal(plbot, event):
    try:
        logger.warning("[%s] EVENT NEW_DEAL received", PREFIX)
        deal = getattr(event, "deal", None)
        if deal is None:
            logger.warning("[%s] NEW_DEAL has no deal", PREFIX)
            return
        deal_id = _deal_id(deal)
        item_id = _item_id(deal)
        chat_id = _chat_id(event) or str(getattr(getattr(deal, "chat", None), "id", "") or "").strip()
        logger.warning("[%s] NEW_DEAL deal=%s item=%s chat=%s", PREFIX, deal_id, item_id, chat_id)
        if not get_config().get("enabled", True):
            logger.warning("[%s] ignored: module config disabled", PREFIX)
            return
        item_name = _item_name(deal)
        matched = matched_keyphrase(deal)
        if not matched:
            logger.warning(
                "[%s] ignored: item=%s name=%r has no matching keyphrase. keyphrases=%s",
                PREFIX, item_id, item_name, get_keyphrases()
            )
            return
        logger.warning("[%s] matched item=%s name=%r by keyphrase=%r", PREFIX, item_id, item_name, matched)
        if not chat_id or not deal_id:
            logger.warning("[%s] ignored: missing deal/chat id", PREFIX)
            return

        existing = await _pending_get(chat_id)
        if existing and str(existing.get("deal_id")) == deal_id:
            logger.info("[%s] duplicate NEW_DEAL ignored: %s", PREFIX, deal_id)
            return

        cfg = get_config()
        pending = {"deal_id": deal_id, "item_id": item_id, "item_name": item_name, "matched_keyphrase": matched, "chat_id": chat_id, "status": "awaiting_link", "created_orders": {}}
        await _pending_set(chat_id, pending)
        await _save_order(deal_id, {"chat_id": chat_id, "item_id": item_id, "item_name": item_name, "matched_keyphrase": matched, "status": "awaiting_link", "link": "", "orders": {}})
        text = cfg.get("messages", {}).get("request_link", "✅ Оплата получена!\n\nПришлите ссылку на TikTok-видео одним сообщением.")
        sent = plbot.send_message(chat_id, text, exclude_watermark=True)
        if sent is None:
            logger.error("[%s] send_message returned None: chat=%s deal=%s", PREFIX, chat_id, deal_id)
        else:
            logger.warning("[%s] LINK REQUEST SENT: deal=%s chat=%s", PREFIX, deal_id, chat_id)
    except Exception:
        logger.exception("[%s] FATAL in NEW_DEAL handler", PREFIX)


async def on_new_message(plbot, event):
    try:
        if not get_config().get("enabled", True):
            return
        message = getattr(event, "message", None)
        user = getattr(message, "user", None)
        account_id = getattr(getattr(plbot, "playerok_account", None), "id", None)
        if user is None or getattr(user, "id", None) == account_id:
            return

        chat_id = _chat_id(event)
        pending = await _pending_get(chat_id)
        if not pending:
            return

        text = (getattr(message, "text", None) or "").strip().rstrip(".,);]}")
        if not valid_tiktok_link(text):
            plbot.send_message(chat_id, get_config().get("messages", {}).get("invalid_link", "❌ Пришлите корректную ссылку на TikTok-видео."), exclude_watermark=True)
            return

        if chat_id in _processing_chats:
            return
        _processing_chats.add(chat_id)
        try:
            cfg = get_config()
            q = cfg.get("quantities", {})
            s = cfg.get("services", {})
            created = dict(pending.get("created_orders") or {})
            await _pending_update(chat_id, status="processing", link=text)
            await _update_order(pending["deal_id"], status="processing", link=text, orders=created)
            plbot.send_message(chat_id, cfg.get("messages", {}).get("processing", "⏳ Ссылка получена. Создаю заказы…"), exclude_watermark=True)

            enabled = cfg.get("service_enabled", {})
            # Если настройки service_enabled ещё нет, все услуги считаются включёнными.
            enabled_names = [name for name in ("views", "likes", "saves", "shares") if enabled.get(name, True)]
            if not enabled_names:
                raise RuntimeError("Все виды накрутки отключены в настройках")

            for name in enabled_names:
                if name not in created:
                    quantity = int(q.get(name, 0) or 0)
                    if quantity <= 0:
                        raise RuntimeError(f"Количество для {name} должно быть больше 0")
                    created[name] = await create_order(s.get(name), text, quantity)
                    await _pending_update(chat_id, created_orders=created)
                    await _update_order(pending["deal_id"], status="processing", link=text, orders=created)

            await _save_order(pending["deal_id"], {
                "chat_id": chat_id,
                "item_id": pending["item_id"],
                "status": "completed",
                "link": text,
                "orders": created,
            })
            await _pending_pop(chat_id)

            if cfg.get("auto_complete_deal", True):
                try:
                    plbot.account.update_deal(pending["deal_id"], ItemDealStatuses.SENT)
                except Exception:
                    logger.exception("[%s] Deal completion failed: %s", PREFIX, pending["deal_id"])

            labels = {
                "views": "👁 Просмотры",
                "likes": "❤️ Лайки",
                "saves": "🔖 Сохранения",
                "shares": "🔁 Репосты",
            }
            success = "✅ Заказы успешно созданы!\n\n" + "\n".join(
                f"{labels[name]}: {int(q.get(name, 0)):,}".replace(",", " ")
                for name in enabled_names
            )
            plbot.send_message(chat_id, success, exclude_watermark=True)
            logger.info("[%s] Completed deal=%s orders=%s", PREFIX, pending["deal_id"], created)
        except Exception as e:
            logger.exception("[%s] TikTok SMM failed for deal=%s: %s", PREFIX, pending.get("deal_id"), e)
            await _pending_update(chat_id, status="error", link=text)
            await _update_order(pending.get("deal_id"), status="error", link=text, error=str(e)[:500])
            plbot.send_message(chat_id, get_config().get("messages", {}).get("error", "❌ Не удалось создать все заказы. Администратор уведомлён."), exclude_watermark=True)
        finally:
            _processing_chats.discard(chat_id)
    except Exception:
        logger.exception("[%s] Error in message handler", PREFIX)
