import os
from typing import Dict, Any, List, Optional, Tuple

from supabase import create_client

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# =========================
# CONFIG
# =========================

TOKEN = os.environ.get("TOKEN", "")

# Supabase envs (strip to avoid hidden spaces/newlines)
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
SUPABASE_KEY = (os.environ.get("SUPABASE_KEY") or "").strip()

# Allowed users (recommended): comma-separated in Render env ALLOWED_USER_IDS="123,456"
# If you don't set it, it will allow everyone.
ALLOWED_USER_IDS_ENV = (os.environ.get("ALLOWED_USER_IDS") or "").strip()

def parse_allowed_users(env: str) -> Optional[set]:
    if not env:
        return None
    out = set()
    for part in env.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out or None

ALLOWED_USER_IDS = parse_allowed_users(ALLOWED_USER_IDS_ENV)

PEOPLE = ["Michael", "Madina"]

# Saving buttons: 100 values of 100..10000 (sum = 505000)
# If you REALLY want max 9800, tell me and I adjust list to keep 100 buttons.
VALUES: List[int] = list(range(100, 10001, 100))  # 100..10000
COUNT = len(VALUES)  # 100
TOTAL_PER_PERSON = sum(VALUES)  # 505000
TOTAL_COMBINED = TOTAL_PER_PERSON * 2  # 1010000

FINE_VALUE = 100

# Supabase init
# (If env is wrong, it should crash early so you SEE the error in Render logs)
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY env var")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "bot_state"  # must exist
# One row per chat_id: id = "chat:<chat_id>"
def row_id(chat_id: int) -> str:
    return f"chat:{chat_id}"


# =========================
# i18n
# =========================

T: Dict[str, Dict[str, str]] = {
    "es": {
        "choose_lang": "Elige idioma / Выберите язык:",
        "choose_person": "Elige persona:",
        "choose_block": "Elige bloque:",
        "back": "⬅️ Atrás",
        "multas": "🚨 Multas +100",
        "undo": "↩️ Deshacer",
        "progress_title": "📌 Progreso",
        "saved": "Ahorrado",
        "remaining": "Falta",
        "fines": "Multas",
        "total_goal": "Meta",
        "tap_value": "Toca un valor para marcarlo:",
        "already_done": "✅ Hecho",
        "empty": "⬜️ Libre",
        "denied": "Acceso denegado / Доступ запрещён",
        "myid": "Tu user_id es:",
    },
    "ru": {
        "choose_lang": "Выберите язык / Elige idioma:",
        "choose_person": "Выберите человека:",
        "choose_block": "Выберите блок:",
        "back": "⬅️ Назад",
        "multas": "🚨 Штраф +100",
        "undo": "↩️ Отменить",
        "progress_title": "📌 Прогресс",
        "saved": "Накоплено",
        "remaining": "Осталось",
        "fines": "Штрафы",
        "total_goal": "Цель",
        "tap_value": "Нажмите сумму, чтобы отметить:",
        "already_done": "✅ Сделано",
        "empty": "⬜️ Свободно",
        "denied": "Доступ запрещён / Acceso denegado",
        "myid": "Ваш user_id:",
    },
}

def tr(lang: str, key: str) -> str:
    return T.get(lang, T["es"]).get(key, key)


# =========================
# STATE in Supabase
# =========================

def default_state() -> Dict[str, Any]:
    return {
        "prefs": {},  # per chat
        "people": {
            "Michael": {"pressed": [False] * COUNT, "history": [], "fines": 0},
            "Madina": {"pressed": [False] * COUNT, "history": [], "fines": 0},
        },
    }

def get_lang(state: Dict[str, Any], chat_id: int) -> str:
    return state.get("prefs", {}).get(str(chat_id), {}).get("lang", "es")

def set_lang(state: Dict[str, Any], chat_id: int, lang: str) -> None:
    state.setdefault("prefs", {}).setdefault(str(chat_id), {})["lang"] = lang

def get_last_person(state: Dict[str, Any], chat_id: int) -> Optional[str]:
    return state.get("prefs", {}).get(str(chat_id), {}).get("person")

def set_last_person(state: Dict[str, Any], chat_id: int, person: str) -> None:
    state.setdefault("prefs", {}).setdefault(str(chat_id), {})["person"] = person

def load_state(chat_id: int) -> Dict[str, Any]:
    try:
        res = sb.table(TABLE_NAME).select("data").eq("id", row_id(chat_id)).execute()
        if res.data and len(res.data) > 0:
            data = res.data[0]["data"]
        else:
            data = default_state()
            sb.table(TABLE_NAME).upsert({"id": row_id(chat_id), "data": data}).execute()
    except Exception as e:
        # If Supabase fails, show error in logs (otherwise you think it "saved" but it didn't)
        print("SUPABASE load_state ERROR:", repr(e))
        data = default_state()

    # ensure structure
    data.setdefault("prefs", {})
    data.setdefault("people", {})
    for p in PEOPLE:
        data["people"].setdefault(p, {"pressed": [False] * COUNT, "history": [], "fines": 0})
        if "pressed" not in data["people"][p] or len(data["people"][p]["pressed"]) != COUNT:
            data["people"][p]["pressed"] = [False] * COUNT
        data["people"][p].setdefault("history", [])
        data["people"][p].setdefault("fines", 0)
    return data

def save_state(chat_id: int, state: Dict[str, Any]) -> None:
    try:
        sb.table(TABLE_NAME).upsert({"id": row_id(chat_id), "data": state}).execute()
    except Exception as e:
        print("SUPABASE save_state ERROR:", repr(e))


# =========================
# Helpers
# =========================

def is_allowed(update: Update) -> bool:
    if ALLOWED_USER_IDS is None:
        return True
    uid = update.effective_user.id if update.effective_user else None
    return uid in ALLOWED_USER_IDS if uid is not None else False

async def safe_edit_or_send(q, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await q.message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            pass

def lang_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🇪🇸 Español", callback_data="lang:es")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru")],
    ]
    return InlineKeyboardMarkup(kb)

def person_menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("Michael", callback_data="person:Michael")],
        [InlineKeyboardButton("Madina", callback_data="person:Madina")],
    ]
    return InlineKeyboardMarkup(kb)

def blocks_menu_kb(lang: str, person: str) -> InlineKeyboardMarkup:
    # 10 blocks of 10 values
    kb = []
    for b in range(10):
        start = b * 10 + 1
        end = start + 9
        kb.append([InlineKeyboardButton(f"{start:02d}-{end:02d}", callback_data=f"block:{person}:{b}")])
    kb.append([InlineKeyboardButton(tr(lang, "back"), callback_data="back:person")])
    return InlineKeyboardMarkup(kb)

def value_buttons_kb(lang: str, person: str, block: int, pressed: List[bool]) -> InlineKeyboardMarkup:
    # block 0..9 -> indices 0..9, 10..19 ...
    start_idx = block * 10
    end_idx = start_idx + 10

    kb = []
    for i in range(start_idx, end_idx):
        v = VALUES[i]
        done = pressed[i]
        label = f"{'✅' if done else '⬜️'} {v}"
        kb.append([InlineKeyboardButton(label, callback_data=f"tap:{person}:{i}")])

    kb.append([InlineKeyboardButton(tr(lang, "multas"), callback_data=f"fine:{person}")])
    kb.append([InlineKeyboardButton(tr(lang, "undo"), callback_data=f"undo:{person}")])
    kb.append([InlineKeyboardButton(tr(lang, "back"), callback_data=f"back:blocks:{person}")])
    return InlineKeyboardMarkup(kb)

def calc_progress(state: Dict[str, Any], person: str) -> Tuple[int, int, int]:
    pdata = state["people"][person]
    saved = sum(v for v, ok in zip(VALUES, pdata["pressed"]) if ok)
    fines = int(pdata.get("fines", 0))
    remaining = TOTAL_PER_PERSON - saved
    return saved, remaining, fines

def progress_text(lang: str, state: Dict[str, Any], person: str) -> str:
    saved, remaining, fines = calc_progress(state, person)
    return (
        f"{tr(lang, 'progress_title')} — {person}\n\n"
        f"✅ {tr(lang, 'saved')}: {saved}\n"
        f"⏳ {tr(lang, 'remaining')}: {remaining}\n"
        f"🚨 {tr(lang, 'fines')}: {fines}\n"
        f"🎯 {tr(lang, 'total_goal')}: {TOTAL_PER_PERSON}\n"
    )


# =========================
# Handlers
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await update.message.reply_text("Acceso denegado / Доступ запрещён")
        return

    chat_id = update.effective_chat.id
    state = load_state(chat_id)
    save_state(chat_id, state)

    await update.message.reply_text(tr("es", "choose_lang"), reply_markup=lang_keyboard())

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(f"{tr('es','myid')} {uid}")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    if not is_allowed(update):
        try:
            await q.answer("Acceso denegado / Доступ запрещён", show_alert=True)
        except Exception:
            pass
        return

    chat_id = q.message.chat_id
    state = load_state(chat_id)
    lang = get_lang(state, chat_id)

    data = q.data

    # Language selection
    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        set_lang(state, chat_id, lang)
        save_state(chat_id, state)
        await safe_edit_or_send(q, tr(lang, "choose_person"), person_menu_kb(lang))
        return

    # Back to person
    if data == "back:person":
        await safe_edit_or_send(q, tr(lang, "choose_person"), person_menu_kb(lang))
        return

    # Person selection
    if data.startswith("person:"):
        person = data.split(":", 1)[1]
        set_last_person(state, chat_id, person)
        save_state(chat_id, state)
        await safe_edit_or_send(q, tr(lang, "choose_block"), blocks_menu_kb(lang, person))
        return

    # Back to blocks
    if data.startswith("back:blocks:"):
        person = data.split(":", 2)[2]
        await safe_edit_or_send(q, tr(lang, "choose_block"), blocks_menu_kb(lang, person))
        return

    # Open block
    if data.startswith("block:"):
        _, person, block_s = data.split(":")
        block = int(block_s)
        pressed = state["people"][person]["pressed"]
        text = progress_text(lang, state, person) + "\n" + tr(lang, "tap_value")
        await safe_edit_or_send(q, text, value_buttons_kb(lang, person, block, pressed))
        return

    # Tap value
    if data.startswith("tap:"):
        _, person, idx_s = data.split(":")
        idx = int(idx_s)

        pdata = state["people"][person]
        if not pdata["pressed"][idx]:
            pdata["pressed"][idx] = True
            pdata["history"].append({"type": "tap", "idx": idx})
            save_state(chat_id, state)

        # return to same block view
        block = idx // 10
        pressed = pdata["pressed"]
        text = progress_text(lang, state, person) + "\n" + tr(lang, "tap_value")
        await safe_edit_or_send(q, text, value_buttons_kb(lang, person, block, pressed))
        return

    # Fine +100
    if data.startswith("fine:"):
        _, person = data.split(":")
        pdata = state["people"][person]
        pdata["fines"] = int(pdata.get("fines", 0)) + FINE_VALUE
        pdata["history"].append({"type": "fine"})
        save_state(chat_id, state)

        # stay on last block if possible
        last_block = 0
        # try infer from message buttons? simplest keep 0
        pressed = pdata["pressed"]
        text = progress_text(lang, state, person) + "\n" + tr(lang, "tap_value")
        await safe_edit_or_send(q, text, value_buttons_kb(lang, person, last_block, pressed))
        return

    # Undo
    if data.startswith("undo:"):
        _, person = data.split(":")
        pdata = state["people"][person]
        if pdata["history"]:
            last = pdata["history"].pop()
            if last["type"] == "tap":
                idx = int(last["idx"])
                if 0 <= idx < COUNT:
                    pdata["pressed"][idx] = False
                    block = idx // 10
                else:
                    block = 0
            elif last["type"] == "fine":
                pdata["fines"] = max(0, int(pdata.get("fines", 0)) - FINE_VALUE)
                block = 0
            else:
                block = 0

            save_state(chat_id, state)
        else:
            block = 0

        pressed = pdata["pressed"]
        text = progress_text(lang, state, person) + "\n" + tr(lang, "tap_value")
        await safe_edit_or_send(q, text, value_buttons_kb(lang, person, block, pressed))
        return


def main() -> None:
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CallbackQueryHandler(on_callback))

    print("Bot started.")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()






