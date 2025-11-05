# bot_v05.py
import os
import time
import json
import sqlite3
from datetime import datetime
from secrets import token_hex

import requests
import telebot
from telebot import types, apihelper
from flask import Flask
import openai
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ------------------ Конфигурация ------------------
from tgbot.config import load_config
config = load_config()

app = Flask(__name__)
bot = telebot.TeleBot(config.tg_bot.token)

# убираем вебхук (на всякий) и даём телеге время «отпустить»
try:
    bot.remove_webhook()
except Exception:
    pass
time.sleep(1)

# OpenAI
openai.api_key = config.openai_api_key

# === СЕТЕВАЯ УСТОЙЧИВОСТЬ ДЛЯ TELEBOT ===
session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1.5,
    status_forcelist=[502, 503, 504],
    allowed_methods=False,
    raise_on_status=False,
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)
apihelper.SESSION = session
apihelper.READ_TIMEOUT = 40
apihelper.CONNECT_TIMEOUT = 20

# ------------------ Персистентное состояние (state.json) ------------------
STATE_FILE = "state.json"

# chat_id -> mode ("listener"/"self_help"/"waiting_listener"/None)
user_state = {}
# chat_id -> messages history (для чат-бота)
user_conversations = {}
# тикеты для анонимности
ticket_index = {}   # ticket -> user_id
user_ticket = {}    # user_id -> ticket

def load_persisted():
    global user_state, user_conversations, ticket_index, user_ticket
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            user_state = {int(k): v for k, v in data.get("user_state", {}).items()}
            user_conversations = {int(k): v for k, v in data.get("user_conversations", {}).items()}
            ticket_index = {k: int(v) for k, v in data.get("ticket_index", {}).items()}
            user_ticket = {int(k): v for k, v in data.get("user_ticket", {}).items()}
        except Exception as e:
            print(f"⚠️ Не удалось прочитать {STATE_FILE}: {e}")

def save_persisted():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "user_state": user_state,
                    "user_conversations": user_conversations,
                    "ticket_index": ticket_index,
                    "user_ticket": user_ticket,
                },
                f, ensure_ascii=False, indent=2
            )
    except Exception as e:
        print(f"⚠️ Не удалось сохранить {STATE_FILE}: {e}")

load_persisted()

# ------------------ Админ-чат и админ-группа ------------------
# ЛС админа (может быть 0 — тогда личку не используем)
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
# Группа слушателей (supergroup). Используется для заявок/взятия в работу.
# Ты давал: -1003083102736
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "-1003083102736"))

# ------------------ База SQLite для анонимных сессий ------------------
DB_FILE = "psyinc.db"
_conn = sqlite3.connect(DB_FILE, check_same_thread=False)
_cur = _conn.cursor()

_cur.execute("""
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket TEXT UNIQUE,
    user_id INTEGER,
    listener_id INTEGER,
    status TEXT,            -- waiting | active | closed
    created_at TEXT
)
""")
_conn.commit()

def db_create_session(ticket: str, user_id: int):
    _cur.execute(
        "INSERT INTO sessions (ticket, user_id, status, created_at) VALUES (?, ?, 'waiting', ?)",
        (ticket, user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    _conn.commit()

def db_assign_listener(ticket: str, listener_id: int):
    _cur.execute("UPDATE sessions SET listener_id=?, status='active' WHERE ticket=?",
                 (listener_id, ticket))
    _conn.commit()

def db_close_session(ticket: str):
    _cur.execute("UPDATE sessions SET status='closed' WHERE ticket=?",
                 (ticket,))
    _conn.commit()

def db_get_by_ticket(ticket: str):
    _cur.execute("SELECT * FROM sessions WHERE ticket=?", (ticket,))
    return _cur.fetchone()

def db_get_active_session_for_user(user_id: int):
    _cur.execute("SELECT * FROM sessions WHERE user_id=? AND status!='closed'", (user_id,))
    return _cur.fetchone()

def db_get_active_session_for_listener(listener_id: int):
    _cur.execute("SELECT * FROM sessions WHERE listener_id=? AND status!='closed'", (listener_id,))
    return _cur.fetchone()

# ------------------ Логи (локально на сервере) ------------------
LOG_FILE = "requests.log"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=== Журнал заявок ===\n\n")

FEEDBACK_LOG_FILE = "feedback.log"
if not os.path.exists(FEEDBACK_LOG_FILE):
    with open(FEEDBACK_LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=== Отзывы пользователей ===\n\n")

def log_request(request_type: str, user):
    try:
        username = user.username or "нет"
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] Тип: {request_type} | Имя: {full_name} | Username: @{username} | Chat ID: {user.id}\n"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        print(f"✅ {log_entry.strip()}")
    except Exception as e:
        print(f"⚠️ Ошибка при записи лога: {e}")

# ------------------ Клавиатуры ------------------
def main_menu_kb() -> types.ReplyKeyboardMarkup:
    # важно: **три строки**, как ты хотел
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('Мне нужен слушатель')
    kb.row('Мне нужен специалист 🔒')
    kb.row('Мне нужен чат-бот')
    return kb

def exit_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    kb.row('❌ Завершить диалог')
    return kb

def remove_kb() -> types.ReplyKeyboardRemove:
    return types.ReplyKeyboardRemove()

# ------------------ Тексты ------------------
welcome_text = (
    "Приветствую!\n\n"
    "Psyinc — это бот эмоциональной онлайн-поддержки. "
    "Выберите, что вам нужно, или напишите /help.\n\n"
    "Автор — Александр Гуртопов, канал "
    "<a href='https://t.me/+qyO1cAXLfgRhMTNi'>Под коробкой</a>."
)

about_text = (
    "Psyinc — бот эмоциональной поддержки.\n\n"
    "Версия: 1.0-beta\n"
    "Автор: Александр Гуртопов (@bugseekerok)\n"
    "Канал: <a href='https://t.me/+qyO1cAXLfgRhMTNi'>Под коробкой</a>"
)

# ------------------ Команды ------------------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    user_state.pop(chat_id, None)
    save_persisted()
    bot.send_message(chat_id, welcome_text, parse_mode='html', reply_markup=main_menu_kb())

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = (
        "Команды:\n"
        "/start — главное меню\n"
        "/info — о возможностях\n"
        "/about — о боте\n"
        "/feedback — оставить отзыв\n"
        "/settings — настройки\n"
        "/cancel — выйти из текущего режима\n"
        "/reset — сбросить историю чат-бота\n"
        "/getchatid — узнать ID текущего чата (видно только вам)"
    )
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['about'])
def cmd_about(message):
    bot.send_message(message.chat.id, about_text, parse_mode='html')

@bot.message_handler(commands=['settings'])
def cmd_settings(message):
    bot.send_message(message.chat.id, "Настройки пока не реализованы.", reply_markup=main_menu_kb())

@bot.message_handler(commands=['feedback'])
def cmd_feedback(message):
    bot.send_message(message.chat.id, "Пожалуйста, введите свой отзыв:", reply_markup=remove_kb())
    bot.register_next_step_handler(message, process_feedback)

def process_feedback(message):
    try:
        username = message.from_user.username or "нет"
        full_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        feedback_text = (message.text or "").strip()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = (
            f"[{timestamp}] Имя: {full_name} | Username: @{username} | Chat ID: {message.chat.id}\n"
            f"Отзыв: {feedback_text}\n\n"
        )
        with open(FEEDBACK_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        print(f"💬 Отзыв сохранён: {full_name} — {feedback_text[:60]}...")

        # Дополнительно шлём в группу слушателей (без раскрытия личности пользователя)
        if ADMIN_GROUP_ID:
            bot.send_message(
                ADMIN_GROUP_ID,
                f"📬 <b>Новый отзыв</b>\n\n"
                f"💬 {feedback_text}",
                parse_mode='HTML'
            )

        bot.send_message(message.chat.id, "Спасибо за обратную связь! Ваш отзыв сохранён 💚", reply_markup=main_menu_kb())
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка при сохранении отзыва: {e}", reply_markup=main_menu_kb())

@bot.message_handler(commands=['reset'])
def cmd_reset(message):
    user_conversations[message.chat.id] = []
    save_persisted()
    bot.send_message(message.chat.id, "История чат-бота сброшена.", reply_markup=main_menu_kb())

@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    chat_id = message.chat.id
    user_state.pop(chat_id, None)
    save_persisted()
    bot.send_message(chat_id, "Диалог завершён. Чем ещё помочь?", reply_markup=main_menu_kb())

@bot.message_handler(commands=['getchatid'])
def cmd_getchatid(message):
    # Сообщение видно только отправителю (reply) — не в группу
    bot.reply_to(message, f"Chat ID (видно только вам): {message.chat.id}")

# ------------------ /info ------------------
@bot.message_handler(commands=['get_info', 'info'])
def cmd_get_info(message):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Да", callback_data="info_yes"),
        types.InlineKeyboardButton("Нет", callback_data="info_no"),
    )
    bot.send_message(message.chat.id, "Хотите узнать о возможностях?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ('info_yes', 'info_no'))
def cb_info(call):
    if call.data == 'info_yes':
        bot.send_message(call.message.chat.id, "Чем вам помочь?", reply_markup=main_menu_kb())
    else:
        bot.send_message(call.message.chat.id, "Хорошего вам дня! 😉", reply_markup=main_menu_kb())

# ------------------ Самопомощь (системный промпт) ------------------
SELF_HELP_SYSTEM_PROMPT = (
    "Ты — доброжелательный помощник по темам психологии, психотерапии, психиатрии и эмоциональной самопомощи.\n"
    "Отвечай ТОЛЬКО в рамках этих тем. Если вопрос пользователя выходит за рамки (техника, финансы, политика, бытовое), "
    "мягко верни к теме переживаний и задай уточняющий вопрос о самочувствии/эмоциях/ситуации.\n"
    "Не ставь диагнозы и не давай медицинских назначений. Напоминай, что ответы не заменяют очную консультацию. "
    "Если слышишь признаки неотложного риска, попроси немедленно обратиться к местным экстренным службам/горячей линии и к врачу. "
    "Пиши коротко, тепло и простым языком; предлагай безопасные техники самопомощи."
)

def ensure_self_help_preamble(chat_id: int):
    history = user_conversations.setdefault(chat_id, [])
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": SELF_HELP_SYSTEM_PROMPT})
        user_conversations[chat_id] = history
        save_persisted()

# ------------------ Анонимизация: тикеты ------------------
def _new_ticket_id() -> str:
    # короткий, но уникальный: L-XXXXXX (hex)
    return f"L-{token_hex(3).upper()}"

def get_or_create_ticket(user_id: int) -> str:
    t = user_ticket.get(user_id)
    if t and ticket_index.get(t) == user_id:
        return t
    t = _new_ticket_id()
    while t in ticket_index:
        t = _new_ticket_id()
    ticket_index[t] = user_id
    user_ticket[user_id] = t
    save_persisted()
    return t

def create_fresh_ticket_for_user(user_id: int) -> str:
    """Всегда создаёт новый ticket для новой заявки пользователя.
       Старую привязку удаляем, чтобы не конфликтовать с UNIQUE(ticket)."""
    old = user_ticket.get(user_id)
    if old:
        ticket_index.pop(old, None)

    t = _new_ticket_id()
    while t in ticket_index:
        t = _new_ticket_id()

    user_ticket[user_id] = t
    ticket_index[t] = user_id
    save_persisted()
    return t

# ------------------ Режим «слушатель» ------------------
def start_listener(message):
    chat_id = message.chat.id

    # если уже есть активная сессия — не создаём новую
    existing = db_get_active_session_for_user(chat_id)
    if existing:
        bot.send_message(
            chat_id,
            "У вас уже есть активная заявка/диалог. Дождитесь отклика слушателя.",
            reply_markup=exit_kb()
        )
        return

    user_state[chat_id] = "waiting_listener"
    save_persisted()
    log_request("слушатель", message.from_user)

    # ВАЖНО: новый ticket на каждую заявку
    ticket = create_fresh_ticket_for_user(chat_id)

    # подстраховка от редких гонок/коллизий
    try:
        db_create_session(ticket, chat_id)
    except sqlite3.IntegrityError:
        # если вдруг занято, генерим ещё раз
        ticket = create_fresh_ticket_for_user(chat_id)
        db_create_session(ticket, chat_id)

    # уведомляем группу слушателей
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎧 Взять в работу", callback_data=f"take_{ticket}"))
        bot.send_message(
            ADMIN_GROUP_ID,
            f"📩 <b>Новая заявка</b>\n"
            f"🆔 Тикет: <code>{ticket}</code>\n"
            f"Пользователь ожидает слушателя.\n\n"
            f"Нажмите «Взять в работу», чтобы подключиться анонимно.",
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        # даже если в группу не отправилось, пользователю всё равно подтверждаем
        print(f"⚠️ Ошибка при отправке заявки в группу: {e}")

    bot.send_message(
        chat_id,
        "✅ Заявка отправлена. Когда слушатель подключится, начнётся анонимный диалог.",
        reply_markup=exit_kb()
    )
    chat_id = message.chat.id
    # если уже есть активная сессия — не создаём новую
    existing = db_get_active_session_for_user(chat_id)
    if existing:
        bot.send_message(chat_id, "У вас уже есть активная заявка/диалог. Дождитесь отклика слушателя.", reply_markup=exit_kb())
        return

    user_state[chat_id] = "waiting_listener"
    save_persisted()
    log_request("слушатель", message.from_user)

    ticket = get_or_create_ticket(chat_id)
    db_create_session(ticket, chat_id)

    # уведомляем группу слушателей
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎧 Взять в работу", callback_data=f"take_{ticket}"))
        bot.send_message(
            ADMIN_GROUP_ID,
            f"📩 <b>Новая заявка</b>\n"
            f"🆔 Тикет: <code>{ticket}</code>\n"
            f"Пользователь ожидает слушателя.\n\n"
            f"Нажмите «Взять в работу», чтобы подключиться анонимно.",
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        print(f"⚠️ Ошибка при отправке заявки в группу: {e}")

    bot.send_message(
        chat_id,
        "✅ Заявка отправлена. Когда слушатель подключится, начнётся анонимный диалог.",
        reply_markup=exit_kb()
    )

# ------------------ Текст из пользовательского чата ------------------
@bot.message_handler(content_types=['text'])
def on_text(message):
    text = (message.text or "").strip()
    chat_id = message.chat.id

    # Команды — отдельными хэндлерами
    if text.startswith('/'):
        return

    # 1) Завершить диалог: СНАЧАЛА сбросить режим и закрыть возможную сессию
    if text == '❌ Завершить диалог':
        # сбрасываем любой режим (в т.ч. self_help)
        user_state.pop(chat_id, None)
        save_persisted()

        # закрываем активную анонимную сессию, если чат — участник
        session = db_get_active_session_for_user(chat_id) or db_get_active_session_for_listener(chat_id)
        if session:
            _, ticket, user_id, listener_id, status, _ = session
            db_close_session(ticket)
            try:
                if user_id:
                    bot.send_message(user_id, "❌ Диалог завершён.", reply_markup=main_menu_kb())
            except Exception:
                pass
            try:
                # если вторая сторона есть и это не тот же чат
                if listener_id and listener_id != user_id:
                    bot.send_message(listener_id, "❌ Диалог завершён.", reply_markup=main_menu_kb())
            except Exception:
                pass
        else:
            bot.send_message(chat_id, "Диалог завершён.", reply_markup=main_menu_kb())
        return

    # 2) Пункты меню — ПРИОРИТЕТНЕЕ текущего state
    if text == 'Мне нужен слушатель':
        return start_listener(message)

    if text.startswith('Мне нужен специалист'):
        return bot.send_message(
            chat_id,
            "🔒 Опция «специалист» пока в разработке и будет доступна позже.",
            reply_markup=main_menu_kb()
        )

    if text == 'Мне нужен чат-бот':
        user_state[chat_id] = "self_help"
        ensure_self_help_preamble(chat_id)
        return bot.send_message(
            chat_id,
            "Что вас беспокоит? Пишите — я отвечу в рамках психологической поддержки.",
            reply_markup=exit_kb()
        )

    # 3) Роутинг по активной анонимной сессии (если есть)
    session_u = db_get_active_session_for_user(chat_id)
    session_l = db_get_active_session_for_listener(chat_id)
    session = session_u or session_l
    if session:
        _, ticket, user_id, listener_id, status, _ = session
        if status == "closed":
            bot.send_message(chat_id, "Диалог уже завершён.", reply_markup=main_menu_kb())
            return
        if chat_id == user_id and listener_id:
            bot.send_message(listener_id, f"👤 Пользователь: {text}", reply_markup=exit_kb())
        elif chat_id == listener_id and user_id:
            bot.send_message(user_id, f"🎧 Слушатель: {text}", reply_markup=exit_kb())
        else:
            bot.send_message(chat_id, "Ожидаем подключение второй стороны…", reply_markup=exit_kb())
        return

    # 4) Роутинг по режимам (после меню)
    state = user_state.get(chat_id)
    if state == "self_help":
        return handle_self_help(message)

    # 5) Дефолт
    bot.send_message(chat_id, "Я не знаю, что сказать..", reply_markup=main_menu_kb())

# ------------------ Слушатель берёт заявку (в группе) ------------------
@bot.callback_query_handler(func=lambda call: call.data.startswith('take_'))
def cb_take(call):
    try:
        listener_id = call.from_user.id
        ticket = call.data.split('_', 1)[1]

        # у слушателя не должно быть другой активной
        if db_get_active_session_for_listener(listener_id):
            bot.answer_callback_query(call.id, "❌ У вас уже есть активный диалог.")
            return

        row = db_get_by_ticket(ticket)
        if not row:
            bot.answer_callback_query(call.id, "⚠️ Заявка не найдена.")
            return

        _, _ticket, user_id, assigned_listener, status, _ = row
        if status != "waiting":
            bot.answer_callback_query(call.id, "⚠️ Заявка уже занята или закрыта.")
            return

        db_assign_listener(ticket, listener_id)

        # Обновляем сообщение в группе (чтобы не нажимали повторно)
        try:
            bot.edit_message_text(
                f"✅ Заявка {_ticket} принята слушателем {call.from_user.first_name or '—'}.",
                call.message.chat.id,
                call.message.id
            )
        except Exception:
            pass

        # уведомляем стороны
        try:
            bot.send_message(user_id, "👂 Слушатель подключился. Всё анонимно.", reply_markup=exit_kb())
        except Exception as e:
            print(f"⚠️ Не удалось уведомить пользователя: {e}")
        try:
            bot.send_message(listener_id, f"💬 Вы подключены к пользователю (тикет {_ticket}). Общайтесь анонимно.", reply_markup=exit_kb())
        except Exception as e:
            print(f"⚠️ Не удалось уведомить слушателя: {e}")

        bot.answer_callback_query(call.id, "Готово. Вы подключены.")
    except Exception as e:
        try:
            bot.answer_callback_query(call.id, f"Ошибка: {e}")
        except Exception:
            pass

# ------------------ Ответ через тикет (опционально для тебя) ------------------
# Если захочешь — оставляю вспомогательный маршрут, чтобы модерация могла
# адресно ответить тикету (не используется слушателями по умолчанию).
@bot.callback_query_handler(func=lambda call: call.data.startswith('replyt_'))
def cb_reply_ticket(call):
    try:
        ticket = call.data.split('_', 1)[1]
        row = db_get_by_ticket(ticket)
        if not row:
            return bot.send_message(call.message.chat.id, "⚠️ Заявка не найдена (возможно завершена).")
        bot.send_message(call.message.chat.id, f"✍️ Введите сообщение для заявки {ticket}")
        bot.register_next_step_handler(call.message, lambda msg: forward_admin_reply_ticket(msg, ticket))
    except Exception as e:
        bot.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")

def forward_admin_reply_ticket(message, ticket: str):
    row = db_get_by_ticket(ticket)
    if not row:
        return bot.send_message(message.chat.id, "⚠️ Не удалось найти получателя (тикет неактуален).")
    _, _ticket, user_id, listener_id, status, _ = row

    # тут можно выбрать адресата: по умолчанию пользователь
    target_id = user_id
    try:
        bot.send_message(
            target_id,
            f"💬 <b>Сообщение по заявке {_ticket}:</b>\n\n{message.text}",
            parse_mode='HTML',
            reply_markup=exit_kb()
        )
        bot.send_message(message.chat.id, f"✅ Сообщение отправлено (заявка {_ticket})")
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка при отправке: {e}")

# ------------------ Самопомощь (GPT) ------------------
def handle_self_help(message):
    chat_id = message.chat.id
    ensure_self_help_preamble(chat_id)
    history = user_conversations.setdefault(chat_id, [])
    history.append({"role": "user", "content": message.text})
    save_persisted()

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=history,
            temperature=0.8,
            max_tokens=500
        )
        answer = response['choices'][0]['message']['content'].strip()
        history.append({"role": "assistant", "content": answer})
        save_persisted()
        bot.send_message(chat_id, answer, reply_markup=exit_kb())
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Ошибка при обращении к OpenAI: {e}", reply_markup=exit_kb())

# ------------------ Запуск ------------------
if __name__ == '__main__':
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass

    print("🤖 Psyinc запущен: анонимные чаты (SQLite), GPT, логи, устойчивость сети")
    while True:
        try:
            # если доступно infinity_polling:
            bot.infinity_polling(timeout=30, long_polling_timeout=25, skip_pending=True)
            # если нет — используй:
            # bot.polling(none_stop=True, interval=1, timeout=30, long_polling_timeout=25)
        except Exception as e:
            print(f"[Polling restart] {e}")
            time.sleep(5)
