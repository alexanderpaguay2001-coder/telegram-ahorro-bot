# bot.py
# Telegram savings bot with:
# - Language selection at /start (ES/RU)
# - Person selection (Michael/Madina)
# - 10 blocks of 10 buttons (100..10000)
# - Progress saved in savings_state.json
# - NO Reset button (removed for safety)
# - "Multas +100" button per person (tracked separately)
# - Undo works for both last tapped saving button and last fine

import json
import os
from typing import Dict, Any, List, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ====== CONFIG ======
ALLOWED_USER_IDS = {1391262954, 937307714}  # reemplaza por los 2 IDs reales
TOKEN = os.environ.get("TOKEN")
STATE_FILE = "savings_state.json"

VALUES = list(range(100, 10001, 100))  # 100..10000
COUNT = len(VALUES)  # 100
TOTAL_PER_PERSON = sum(VALUES)         # 505000
TOTAL_COMBINED = TOTAL_PER_PERSON * 2  # 1010000

PEOPLE = ["Michael", "Madina"]
FINE_VALUE = 100

# ====== I18N ======
T = {
    "es": {
        "choose_lang": "Elige el idioma:",
        "lang_es": "🇪🇸 Español",
        "lang_ru": "🇷🇺 Русский",
        "choose_person": "Elige quién está ahorrando:",
        "select_block": "Selecciona un bloque (10 bloques de 10 botones):",
        "block": "Bloque",
        "tap_to_mark": "Toca un botón para marcar ✅",
        "progress": "📊 Progreso",
        "undo": "↩️ Deshacer último",
        "change_person": "👤 Cambiar persona",
        "back_blocks": "⬅️ Volver a bloques",
        "fines_btn": "💸 Multas +100",
        "you_header": "👤",
        "together_header": "👫 Total juntos",
        "completed": "✅ Completado",
        "saved": "💰 Ahorrado",
        "left": "⏳ Falta",
        "of": "de",
        "fines": "💸 Multas",
        "fines_total": "💸 Multas juntos",
        "saved_toast": "✅ Guardado:",
        "fine_toast": "💸 +100",
        "nothing_to_undo": "Nada que deshacer",
    },
    "ru": {
        "choose_lang": "Выберите язык:",
        "lang_es": "🇪🇸 Español",
        "lang_ru": "🇷🇺 Русский",
        "choose_person": "Кто копит?",
        "select_block": "Выберите блок (10 блоков по 10 кнопок):",
        "block": "Блок",
        "tap_to_mark": "Нажмите кнопку, чтобы отметить ✅",
        "progress": "📊 Прогресс",
        "undo": "↩️ Отменить последнее",
        "change_person": "👤 Сменить человека",
        "back_blocks": "⬅️ Назад к блокам",
        "fines_btn": "💸 Штраф +100",
        "you_header": "👤",
        "together_header": "👫 Итого вместе",
        "completed": "✅ Выполнено",
        "saved": "💰 Накоплено",
        "left": "⏳ Осталось",
        "of": "из",
        "fines": "💸 Штрафы",
        "fines_total": "💸 Штрафы вместе",
        "saved_toast": "✅ Сохранено:",
        "fine_toast": "💸 +100",
        "nothing_to_undo": "Нечего отменять",
    },
}


def tr(lang: str, key: str) -> str:
    if lang not in T:
        lang = "es"
    return T[lang].get(key, key)

def is_allowed_user_id(user_id: int) -> bool:
    return user_id in ALLOWED_USER_IDS


# ====== STATE ======
def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {
            "Michael": {"pressed": [False] * COUNT, "history": [], "fines": 0},
            "Madina": {"pressed": [False] * COUNT, "history": [], "fines": 0},
            "prefs": {},  # chat_id -> {"lang": "es"}
        }

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    for p in PEOPLE:
        if p not in data:
            data[p] = {"pressed": [False] * COUNT, "history": [], "fines": 0}
        if "pressed" not in data[p] or len(data[p]["pressed"]) != COUNT:
            data[p]["pressed"] = [False] * COUNT
        if "history" not in data[p]:
            data[p]["history"] = []
        if "fines" not in data[p]:
            data[p]["fines"] = 0

    if "prefs" not in data:
        data["prefs"] = {}

    return data


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_lang(state: Dict[str, Any], chat_id: int) -> str:
    prefs = state.get("prefs", {})
    entry = prefs.get(str(chat_id), {})
    lang = entry.get("lang", "es")
    return lang if lang in T else "es"


def set_lang(state: Dict[str, Any], chat_id: int, lang: str) -> None:
    if "prefs" not in state:
        state["prefs"] = {}
    if lang not in T:
        lang = "es"
    state["prefs"][str(chat_id)] = {"lang": lang}


# ====== CALCS ======
def calc_person(state: Dict[str, Any], person: str) -> Tuple[int, int, int]:
    pressed = state[person]["pressed"]
    done_sum = sum(v for v, ok in zip(VALUES, pressed) if ok)
    remaining_sum = TOTAL_PER_PERSON - done_sum
    done_count = sum(1 for ok in pressed if ok)
    return done_sum, remaining_sum, done_count


def calc_combined(state: Dict[str, Any]) -> Tuple[int, int]:
    done_m, _, _ = calc_person(state, "Michael")
    done_a, _, _ = calc_person(state, "Madina")
    done_total = done_m + done_a
    remaining_total = TOTAL_COMBINED - done_total
    return done_total, remaining_total


def fines_person(state: Dict[str, Any], person: str) -> int:
    return int(state[person].get("fines", 0))


def fines_combined(state: Dict[str, Any]) -> int:
    return fines_person(state, "Michael") + fines_person(state, "Madina")


# ====== UI ======
def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇪🇸 Español", callback_data="lang:es")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru")],
    ])


def person_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Michael", callback_data="pick:Michael")],
        [InlineKeyboardButton("Madina", callback_data="pick:Madina")],
    ])


# Blocks: 10 blocks of 10 buttons (indices 0..9, 10..19, ... 90..99)
def block_range(block: int) -> Tuple[int, int]:
    start_idx = block * 10
    end_idx = start_idx + 9
    return start_idx, end_idx


def block_label(block: int) -> str:
    s, e = block_range(block)
    return f"{VALUES[s]}–{VALUES[e]}"


def render_header(state: Dict[str, Any], lang: str, person: str) -> str:
    done_sum, remaining_sum, done_count = calc_person(state, person)
    done_total, remaining_total = calc_combined(state)

    fines_p = fines_person(state, person)
    fines_total = fines_combined(state)

    return (
        f"{tr(lang,'you_header')} **{person}**\n"
        f"{tr(lang,'completed')}: **{done_count}/100**\n"
        f"{tr(lang,'saved')}: **${done_sum:,}**\n"
        f"{tr(lang,'left')}: **${remaining_sum:,}** ({tr(lang,'of')} ${TOTAL_PER_PERSON:,})\n"
        f"{tr(lang,'fines')}: **${fines_p:,}**\n\n"
        f"**{tr(lang,'together_header')}**\n"
        f"{tr(lang,'saved')}: **${done_total:,}**\n"
        f"{tr(lang,'left')}: **${remaining_total:,}** ({tr(lang,'of')} ${TOTAL_COMBINED:,})\n"
        f"{tr(lang,'fines_total')}: **${fines_total:,}**\n"
    )


def render_blocks_text(state: Dict[str, Any], lang: str, person: str) -> str:
    return render_header(state, lang, person) + "\n" + tr(lang, "select_block")


def render_block_text(state: Dict[str, Any], lang: str, person: str, block: int) -> str:
    return (
        render_header(state, lang, person)
        + f"\n{tr(lang,'block')}: **{block_label(block)}**\n"
        + tr(lang, "tap_to_mark")
    )


def blocks_keyboard(lang: str, person: str) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, 10, 2):
        rows.append([
            InlineKeyboardButton(block_label(i), callback_data=f"open:{person}:{i}"),
            InlineKeyboardButton(block_label(i + 1), callback_data=f"open:{person}:{i+1}"),
        ])

    rows.append([
        InlineKeyboardButton(tr(lang, "fines_btn"), callback_data=f"fine:{person}"),
        InlineKeyboardButton(tr(lang, "undo"), callback_data=f"undo:{person}"),
    ])
    rows.append([
        InlineKeyboardButton(tr(lang, "progress"), callback_data=f"stats:{person}"),
        InlineKeyboardButton(tr(lang, "change_person"), callback_data="change_person"),
    ])
    return InlineKeyboardMarkup(rows)


def block_keyboard(state: Dict[str, Any], lang: str, person: str, block: int) -> InlineKeyboardMarkup:
    pressed = state[person]["pressed"]
    s, e = block_range(block)

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for idx in range(s, e + 1):
        val = VALUES[idx]
        label = f"✅{val}" if pressed[idx] else f"{val}"
        row.append(InlineKeyboardButton(label, callback_data=f"tap:{person}:{idx}:{block}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(tr(lang, "back_blocks"), callback_data=f"back:{person}"),
        InlineKeyboardButton(tr(lang, "progress"), callback_data=f"stats:{person}:{block}"),
    ])
    rows.append([
        InlineKeyboardButton(tr(lang, "fines_btn"), callback_data=f"fine:{person}:{block}"),
        InlineKeyboardButton(tr(lang, "undo"), callback_data=f"undo:{person}:{block}"),
    ])
    return InlineKeyboardMarkup(rows)


# ====== HELPERS ======
async def safe_edit_or_send(q, text: str, reply_markup: InlineKeyboardMarkup, parse_mode: Optional[str] = None):
    """Try to edit the existing message; if Telegram refuses, send a new message."""
    try:
        await q.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await q.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


def push_history_tap(state: Dict[str, Any], person: str, idx: int) -> None:
    # New format: dict. Keep compatibility if old ints exist.
    state[person]["history"].append({"t": "tap", "i": idx})


def push_history_fine(state: Dict[str, Any], person: str) -> None:
    state[person]["history"].append({"t": "fine"})


def pop_last_action(state: Dict[str, Any], person: str) -> bool:
    """Undo last action (tap or fine). Returns True if something undone."""
    hist = state[person]["history"]
    if not hist:
        return False

    last = hist.pop()

    # Backward compatibility (old code might have int idx stored)
    if isinstance(last, int):
        idx = last
        if 0 <= idx < COUNT:
            state[person]["pressed"][idx] = False
            return True
        return False

    if isinstance(last, dict):
        t = last.get("t")
        if t == "tap":
            idx = int(last.get("i", -1))
            if 0 <= idx < COUNT:
                state[person]["pressed"][idx] = False
                return True
        elif t == "fine":
            state[person]["fines"] = max(0, int(state[person].get("fines", 0)) - FINE_VALUE)
            return True

    return False


# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None or not is_allowed_user_id(user_id):
        await update.message.reply_text("Acceso denegado / Доступ запрещён")
        return

    # Fuerza crear/guardar JSON
    state = load_state()
    save_state(state)

    # Idioma al inicio
    await update.message.reply_text(tr("es", "choose_lang"), reply_markup=lang_keyboard())

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
        user_id = update.effective_user.id if update.effective_user else None
    if user_id is None or not is_allowed_user_id(user_id):
        try:
            await q.answer("Acceso denegado / Доступ запрещён", show_alert=True)
        except Exception:
            pass
        return

    state = load_state()
    chat_id = q.message.chat_id
    lang = get_lang(state, chat_id)

    data = q.data

    # Language selection
    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        set_lang(state, chat_id, lang)
        save_state(state)
        await q.answer()
        await safe_edit_or_send(q, tr(lang, "choose_person"), person_menu_kb(), None)
        return

    # Change person
    if data == "change_person":
        lang = get_lang(state, chat_id)
        await q.answer()
        await safe_edit_or_send(q, tr(lang, "choose_person"), person_menu_kb(), None)
        return

    # Pick person
    if data.startswith("pick:"):
        person = data.split(":", 1)[1]
        lang = get_lang(state, chat_id)
        await q.answer()
        await safe_edit_or_send(
            q,
            render_blocks_text(state, lang, person),
            blocks_keyboard(lang, person),
            "Markdown",
        )
        return

    # Back to blocks
    if data.startswith("back:"):
        _, person = data.split(":")
        lang = get_lang(state, chat_id)
        await q.answer()
        await safe_edit_or_send(
            q,
            render_blocks_text(state, lang, person),
            blocks_keyboard(lang, person),
            "Markdown",
        )
        return

    # Open block
    if data.startswith("open:"):
        _, person, block_str = data.split(":")
        block = int(block_str)
        lang = get_lang(state, chat_id)
        await q.answer()
        await safe_edit_or_send(
            q,
            render_block_text(state, lang, person, block),
            block_keyboard(state, lang, person, block),
            "Markdown",
        )
        return

    # Tap (mark savings button)
    if data.startswith("tap:"):
        _, person, idx_str, block_str = data.split(":")
        idx = int(idx_str)
        block = int(block_str)
        lang = get_lang(state, chat_id)

        val = VALUES[idx]

        if not state[person]["pressed"][idx]:
            state[person]["pressed"][idx] = True
            push_history_tap(state, person, idx)
            save_state(state)

        # toast
        try:
            await q.answer(f"{tr(lang,'saved_toast')} {val}", show_alert=False)
        except Exception:
            await q.answer()

        await safe_edit_or_send(
            q,
            render_block_text(state, lang, person, block),
            block_keyboard(state, lang, person, block),
            "Markdown",
        )
        return

    # Fine (+100)
    if data.startswith("fine:"):
        parts = data.split(":")
        person = parts[1]
        block = int(parts[2]) if len(parts) == 3 else None
        lang = get_lang(state, chat_id)

        state[person]["fines"] = int(state[person].get("fines", 0)) + FINE_VALUE
        push_history_fine(state, person)
        save_state(state)

        try:
            await q.answer(tr(lang, "fine_toast"), show_alert=False)
        except Exception:
            await q.answer()

        if block is None:
            await safe_edit_or_send(
                q,
                render_blocks_text(state, lang, person),
                blocks_keyboard(lang, person),
                "Markdown",
            )
        else:
            await safe_edit_or_send(
                q,
                render_block_text(state, lang, person, block),
                block_keyboard(state, lang, person, block),
                "Markdown",
            )
        return

    # Stats (refresh)
    if data.startswith("stats:"):
        parts = data.split(":")
        person = parts[1]
        lang = get_lang(state, chat_id)
        await q.answer()

        if len(parts) == 3:
            block = int(parts[2])
            await safe_edit_or_send(
                q,
                render_block_text(state, lang, person, block),
                block_keyboard(state, lang, person, block),
                "Markdown",
            )
        else:
            await safe_edit_or_send(
                q,
                render_blocks_text(state, lang, person),
                blocks_keyboard(lang, person),
                "Markdown",
            )
        return

    # Undo
    if data.startswith("undo:"):
        parts = data.split(":")
        person = parts[1]
        block = int(parts[2]) if len(parts) == 3 else None
        lang = get_lang(state, chat_id)

        undone = pop_last_action(state, person)
        if undone:
            save_state(state)

        try:
            await q.answer(tr(lang, "nothing_to_undo") if not undone else "", show_alert=False)
        except Exception:
            await q.answer()

        if block is None:
            await safe_edit_or_send(
                q,
                render_blocks_text(state, lang, person),
                blocks_keyboard(lang, person),
                "Markdown",
            )
        else:
            await safe_edit_or_send(
                q,
                render_block_text(state, lang, person, block),
                block_keyboard(state, lang, person, block),
                "Markdown",
            )
        return

    # default
    await q.answer()


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    print("✅ Bot corriendo… (Ctrl+C para parar)")
    app.run_polling()


if __name__ == "__main__":
    main()



