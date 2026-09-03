import json, os
from aiogram import F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from tgbot.telegrambot import get_telegram_bot
from plbot.playerokbot import get_playerok_bot
from settings import Settings as sett
from ...handlers import get_config, update_config, api_call
from .states import TikTokAdminStates
from .. import router

PAGE_SIZE=12

def _admins():
    try: return {int(x) for x in sett.get("config")["telegram"]["bot"].get("signed_users",[])}
    except Exception: return set()

def _auth(obj): return getattr(obj.from_user,"id",0) in _admins()

def _menu():
    c=get_config(); return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🟢 Модуль включён" if c.get("enabled",True) else "🔴 Модуль выключен"),callback_data="tt:toggle")],
        [InlineKeyboardButton(text="🔑 Ключевые слова",callback_data="tt:keyphrases")],
        [InlineKeyboardButton(text="⚙️ Услуги NeverSMM",callback_data="tt:services")],
        [InlineKeyboardButton(text="📊 Количества",callback_data="tt:quantities")],
        [InlineKeyboardButton(text="🔑 API-ключ",callback_data="tt:key")],
        [InlineKeyboardButton(text="📋 Заказы",callback_data="tt:orders")],
        [InlineKeyboardButton(text="📝 Сообщения",callback_data="tt:messages")]
    ])

def _status():
    c=get_config(); s=c.get("services",{}); q=c.get("quantities",{}); en=c.get("service_enabled",{}); phrases=[str(x).strip() for x in c.get("keyphrases",[]) if str(x).strip()]
    def line(kind, label, default):
        return f"{'🟢' if en.get(kind, True) else '🔴'} {label}: <code>{s.get(kind) or '—'}</code> × {q.get(kind,default):,}".replace(","," ")
    return ("🎵 <b>TikTok SMM — админ-панель</b>\n\n"
            f"Модуль: {'🟢 включён' if c.get('enabled',True) else '🔴 выключен'}\n"
            f"API: {'🟢 установлен' if c.get('never_smm',{}).get('api_key') else '🔴 не установлен'}\n"
            f"Ключевых слов: <b>{len(phrases)}</b>\n"
            f"🔎 {', '.join(phrases[:5]) if phrases else 'не заданы'}\n\n"
            + line('views','Просмотры',20000) + "\n"
            + line('likes','Лайки',2200) + "\n"
            + line('saves','Сохранения',1200) + "\n"
            + line('shares','Репосты',450))

def _back(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад",callback_data="tt:menu")]])

def _all_items():
    bot = get_playerok_bot()
    if not bot:
        raise RuntimeError("Playerok бот ещё не запущен")
    # PlayerokBot.get_my_items() already returns a plain list of ItemProfile.
    return bot.get_my_items(count=-1)


async def _items_screen(callback,page):
    import asyncio
    items=await asyncio.to_thread(_all_items)
    bound={str(x) for x in get_config().get("bound_items",[])}
    total_pages=max(1,(len(items)+PAGE_SIZE-1)//PAGE_SIZE)
    page=max(0,min(page,total_pages-1)); chunk=items[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
    rows=[]
    for it in chunk:
        iid=str(it.id); mark="✅" if iid in bound else "▫️"; name=(it.name or "Без названия")[:34]
        rows.append([InlineKeyboardButton(text=f"{mark} {name}",callback_data=f"tt:item:{iid}")])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton(text="◀️",callback_data=f"tt:items:{page-1}"))
    if page<total_pages-1: nav.append(InlineKeyboardButton(text="▶️",callback_data=f"tt:items:{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Обновить",callback_data=f"tt:items:{page}"),InlineKeyboardButton(text="⬅️ Назад",callback_data="tt:menu")])
    await callback.message.edit_text(f"🛍 <b>Мои товары Playerok</b>\n\nСтраница {page+1}/{total_pages}. Нажмите на товар, чтобы открыть настройки.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),parse_mode="HTML")

async def _item_screen(callback,item_id):
    import asyncio
    bot=get_playerok_bot(); item=await asyncio.to_thread(bot.account.get_item,id=item_id)
    bound={str(x) for x in get_config().get("bound_items",[])}; isb=item_id in bound
    name=getattr(item,"name","Без названия"); price=getattr(item,"price","")
    text=f"🛍 <b>{name}</b>\n\nID: <code>{item_id}</code>\nЦена: <b>{price}</b>\n\nСтатус TikTok SMM: {'🟢 привязан' if isb else '🔴 не привязан'}"
    action="tt:unbind:" if isb else "tt:bind:"
    label="❌ Отвязать TikTok SMM" if isb else "🎵 Привязать TikTok SMM"
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label,callback_data=action+item_id)],[InlineKeyboardButton(text="⬅️ К товарам",callback_data="tt:items:0")]])
    await callback.message.edit_text(text,reply_markup=kb,parse_mode="HTML")

def _keyphrases_screen():
    phrases=[str(x).strip() for x in get_config().get("keyphrases",[]) if str(x).strip()]
    shown="\n".join(f"• <code>{x}</code>" for x in phrases) if phrases else "Пока не заданы."
    return (
        "🔑 <b>Ключевые слова TikTok SMM</b>\n\n"
        "Лот считается подходящим, если его название содержит хотя бы одно из этих слов/фраз. "
        "Проверка работает так же, как в автоподтверждениях Playerok.\n\n"
        f"{shown}\n\n"
        "Нажмите «Изменить» и отправьте фразы через запятую или с новой строки.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить",callback_data="tt:keyphrases_edit")],
            [InlineKeyboardButton(text="🗑 Очистить",callback_data="tt:keyphrases_clear")],
            [InlineKeyboardButton(text="⬅️ Назад",callback_data="tt:menu")]
        ])
    )


def _service_kinds(): return [("views","👁 Просмотры"),("likes","❤️ Лайки"),("saves","🔖 Сохранения"),("shares","🔁 Репосты")]

def _services_screen():
    s=get_config().get("services",{}); rows=[[InlineKeyboardButton(text=f"{label}: {s.get(kind) or '—'}",callback_data=f"tt:service_find:{kind}")] for kind,label in _service_kinds()]
    rows.append([InlineKeyboardButton(text="⬅️ Назад",callback_data="tt:menu")]); return InlineKeyboardMarkup(inline_keyboard=rows)

def _qty_screen():
    c=get_config(); q=c.get("quantities",{}); en=c.get("service_enabled",{})
    rows=[]
    for kind,label in _service_kinds():
        status="🟢 ВКЛ" if en.get(kind, True) else "🔴 ВЫКЛ"
        rows.append([InlineKeyboardButton(text=f"{status} {label}: {q.get(kind,0):,}".replace(","," "),callback_data=f"tt:q:{kind}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад",callback_data="tt:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(Command("tiktok"))
async def cmd_tiktok(message:types.Message,state:FSMContext):
    if not _auth(message): return
    await state.clear(); await message.answer(_status(),reply_markup=_menu(),parse_mode="HTML")

@router.callback_query(F.data.startswith("tt:"))
async def callbacks(callback:CallbackQuery,state:FSMContext):
    if not _auth(callback): await callback.answer("Нет доступа",show_alert=True); return
    d=callback.data
    try:
        if d=="tt:menu": await state.clear(); await callback.message.edit_text(_status(),reply_markup=_menu(),parse_mode="HTML")
        elif d=="tt:toggle": update_config(lambda c:c.update(enabled=not c.get("enabled",True))); await callback.message.edit_text(_status(),reply_markup=_menu(),parse_mode="HTML")
        elif d=="tt:keyphrases":
            text,kb=_keyphrases_screen(); await callback.message.edit_text(text,reply_markup=kb,parse_mode="HTML")
        elif d=="tt:keyphrases_edit":
            await state.set_state(TikTokAdminStates.waiting_keyphrases)
            await callback.message.edit_text(
                "✏️ <b>Введите ключевые слова</b>\n\n"
                "Например:\n<code>TikTok SMM, тикток, буст тикток</code>\n\n"
                "Можно также по одному слову/фразе на строку.",
                reply_markup=_back(), parse_mode="HTML"
            )
        elif d=="tt:keyphrases_clear":
            update_config(lambda c:c.update(keyphrases=[]))
            text,kb=_keyphrases_screen(); await callback.message.edit_text("✅ Ключевые слова очищены.\n\n"+text,reply_markup=kb,parse_mode="HTML")
        elif d=="tt:services": await callback.message.edit_text("⚙️ <b>Услуги NeverSMM</b>\n\nНажмите нужный показатель — плагин получит список TikTok-услуг и даст выбрать одну кнопкой.",reply_markup=_services_screen(),parse_mode="HTML")
        elif d.startswith("tt:service_find:"):
            kind=d.split(":",2)[2]; await callback.message.edit_text("⏳ Получаю услуги NeverSMM…",reply_markup=_back()); result=await api_call(action="services")
            rows=[]
            for x in result if isinstance(result,list) else []:
                hay=" ".join(str(x.get(k,"")) for k in ("name","category","network")).lower()
                if "tiktok" in hay:
                    sid=x.get("service"); nm=str(x.get("name") or x.get("category") or sid); rows.append([InlineKeyboardButton(text=f"#{sid} {nm[:38]}",callback_data=f"tt:setservice:{kind}:{sid}")])
            rows.append([InlineKeyboardButton(text="⬅️ Назад",callback_data="tt:services")])
            await callback.message.edit_text(f"🎵 <b>Выберите услугу для {dict(_service_kinds())[kind]}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),parse_mode="HTML")
        elif d.startswith("tt:setservice:"):
            _,_,kind,sid=d.split(":"); update_config(lambda c:c.setdefault("services",{}).update({kind:int(sid)})); await callback.message.edit_text("✅ Услуга сохранена.",reply_markup=_services_screen(),parse_mode="HTML")
        elif d=="tt:quantities": await callback.message.edit_text("📊 <b>Количество</b>\n\nНажмите показатель и отправьте новое целое число.",reply_markup=_qty_screen(),parse_mode="HTML")
        elif d.startswith("tt:q:"):
            kind=d.split(":",2)[2]
            c=get_config(); enabled=c.get("service_enabled",{}).get(kind, True)
            label=dict(_service_kinds())[kind]
            kb=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=("🔴 Отключить" if enabled else "🟢 Включить"),callback_data=f"tt:toggle_service:{kind}")],
                [InlineKeyboardButton(text="✏️ Изменить количество",callback_data=f"tt:setqty:{kind}")],
                [InlineKeyboardButton(text="⬅️ Назад",callback_data="tt:quantities")]
            ])
            await callback.message.edit_text(f"📊 <b>{label}</b>\n\nСтатус: {'🟢 включено' if enabled else '🔴 отключено'}\nКоличество: <b>{int(c.get('quantities',{}).get(kind,0)):,}</b>\n\nМожно отдельно включать/отключать эту накрутку и менять её количество.".replace(","," "),reply_markup=kb,parse_mode="HTML")
        elif d.startswith("tt:toggle_service:"):
            kind=d.split(":",2)[2]
            def toggle(c):
                en=c.setdefault("service_enabled", {})
                en[kind]=not en.get(kind, True)
            update_config(toggle)
            await callback.message.edit_text("✅ Настройка изменена.",reply_markup=_qty_screen(),parse_mode="HTML")
        elif d.startswith("tt:setqty:"):
            kind=d.split(":",2)[2]; await state.update_data(quantity_kind=kind); await state.set_state(TikTokAdminStates.waiting_quantity); await callback.message.edit_text(f"Введите количество для {dict(_service_kinds())[kind]}:",reply_markup=_back())
        elif d=="tt:key": await state.set_state(TikTokAdminStates.waiting_api_key); await callback.message.edit_text("🔑 Отправьте API-ключ NeverSMM одним сообщением.",reply_markup=_back())
        elif d=="tt:orders":
            p=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),"module_data","orders.json"); data={}
            try: data=json.load(open(p,encoding="utf-8"))
            except Exception: pass
            lines=[]
            for k,v in list(data.items())[-10:]:
                status=str(v.get("status","unknown"))
                orders=v.get("orders",{}) or {}
                lines.append(f"• <code>{k}</code> — <b>{status}</b> — заказов: {len(orders)}")
                if v.get("link"): lines.append("  🔗 " + str(v.get("link")))
                if v.get("error"): lines.append("  ❌ " + str(v.get("error")))
            await callback.message.edit_text("📋 <b>Последние заказы</b>\n\n"+("\n".join(lines) if lines else "Пока нет заказов."),reply_markup=_back(),parse_mode="HTML")
        elif d=="tt:messages":
            m=get_config().get("messages",{}); await callback.message.edit_text(f"📝 <b>Сообщения</b>\n\nЗапрос ссылки:\n<blockquote>{m.get('request_link','')}</blockquote>\n\nОшибка:\n<blockquote>{m.get('invalid_link','')}</blockquote>",reply_markup=_back(),parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: <code>{str(e)[:800]}</code>",reply_markup=_back(),parse_mode="HTML"); await callback.answer()

@router.message(TikTokAdminStates.waiting_api_key)
async def save_key(message:types.Message,state:FSMContext):
    if not _auth(message): return
    key=(message.text or "").strip()
    if not key: await message.answer("❌ Ключ пустой."); return
    update_config(lambda c:c.setdefault("never_smm",{}).update(api_key=key)); await state.clear(); await message.answer("✅ API-ключ сохранён.",reply_markup=_menu(),parse_mode="HTML")

@router.message(TikTokAdminStates.waiting_quantity)
async def save_qty(message:types.Message,state:FSMContext):
    if not _auth(message): return
    try: n=int((message.text or "").strip()); assert n>0
    except Exception: await message.answer("❌ Введите положительное целое число."); return
    data=await state.get_data(); kind=data.get("quantity_kind"); update_config(lambda c:c.setdefault("quantities",{}).update({kind:n})); await state.clear(); await message.answer("✅ Количество сохранено.",reply_markup=_menu(),parse_mode="HTML")


@router.message(TikTokAdminStates.waiting_keyphrases)
async def save_keyphrases(message:types.Message,state:FSMContext):
    if not _auth(message): return
    raw=(message.text or "").strip()
    phrases=[]
    for part in raw.replace("\n", ",").split(","):
        part=" ".join(part.strip().split())
        if part and part.lower() not in {x.lower() for x in phrases}:
            phrases.append(part)
    if not phrases:
        await message.answer("❌ Укажите хотя бы одно ключевое слово или фразу.")
        return
    update_config(lambda c:c.update(keyphrases=phrases, bound_items=[]))
    await state.clear()
    text,kb=_keyphrases_screen()
    await message.answer("✅ Ключевые слова сохранены.\n\n"+text,reply_markup=kb,parse_mode="HTML")
