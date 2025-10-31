import os
import time
from datetime import datetime

import telebot
from telebot import types
from flask import Flask
import openai

# ------------------ Конфигурация ------------------
from tgbot.config import load_config
config = load_config()

app = Flask(__name__)
bot = telebot.TeleBot(config.tg_bot.token)

# Удаляем webhook перед polling (чтобы не было 409)
bot.remove_webhook()
time.sleep(1)

# OpenAI
openai.api_key = config.openai_api_key

# ------------- Память диалогов и состояний ----------
# history для GPT-диалога
user_conversations: dict[int, list[dict]] = {}

# состояние пользователя: None | "self_help" | "listener" | "therapist"
user_state: dict[int, str] = {}

# Админский чат (обнови в .env после /getchatid в нужном чате)
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# ------------------ Логи заявок ------------------
LOG_FILE = "requests.log"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=== Журнал заявок ===\n\n")

def log_request(request_type: str, user):
    try:
        username = user.username or "нет"
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = (
            f"[{timestamp}] "
            f"Тип: {request_type} | "
            f"Имя: {full_name} | "
            f"Username: @{username} | "
            f"Chat ID: {user.id}\n"
        )
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        print(f"✅ Заявка записана в лог: {log_entry.strip()}")
    except Exception as e:
        print(f"⚠️ Ошибка при записи лога: {e}")

# ------------------ Клавиатуры ------------------

def main_menu_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # слушатель + терапевт — в одну строку
    kb.row('Мне нужен слушатель', 'Мне нужен психотерапевт')
    # самопомощь — со следующей строки
    kb.row('Самопомощь')
    return kb

def exit_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    kb.row('❌ Завершить диалог')
    return kb

def remove_kb() -> types.ReplyKeyboardRemove:
    return types.ReplyKeyboardRemove()

# ------------------ Текстовые блоки ------------------
welcome_text = (
    "Приветствую!\n\n"
    "Psyinc — это бот эмоциональной онлайн-поддержки, который поможет вам самостоятельно справиться с "
    "повседневными переживаниями, позволит анонимно пообщаться с чутким слушателем, а также предложит "
    "помощь квалифицированного специалиста.\n\n"
    "Автор бота — Александр Гуртопов, ведущий канала "
    "<a href='https://t.me/+qyO1cAXLfgRhMTNi'>Под коробкой</a>."
)

# ------------------ Команды ------------------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    user_conversations[chat_id] = []
    user_state.pop(chat_id, None)
    bot.send_message(chat_id, welcome_text, parse_mode='html', reply_markup=main_menu_kb())

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = (
        "Вот список доступных команд:\n"
        "/start — начать работу с ботом\n"
        "/info или /get_info — узнать о возможностях бота\n"
        "/help — справка\n"
        "/cancel — выйти из текущего режима\n"
        "/feedback — оставить отзыв\n"
        "/settings — настройки\n"
        "/about — информация о боте\n"
        "/reset — сброс истории"
    )
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['about'])
def cmd_about(message):
    about_text = (
        "Psyinc — бот эмоциональной поддержки.\n\n"
        "Версия: 1.0-beta\n"
        "Автор: Александр Гуртопов (@bugseekerok)\n"
        "Канал: <a href='https://t.me/+qyO1cAXLfgRhMTNi'>Под коробкой</a>"
    )
    bot.send_message(message.chat.id, about_text, parse_mode='html')

@bot.message_handler(commands=['reset'])
def cmd_reset(message):
    user_conversations[message.chat.id] = []
    bot.send_message(message.chat.id, "История разговора сброшена.")

@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    # универсальный выход
    chat_id = message.chat.id
    user_state.pop(chat_id, None)
    bot.send_message(chat_id, "Диалог завершён. Чем ещё помочь?", reply_markup=main_menu_kb())

@bot.message_handler(commands=['feedback'])
def cmd_feedback(message):
    bot.send_message(message.chat.id, "Пожалуйста, введите свой отзыв:")
    bot.register_next_step_handler(message, process_feedback)

def process_feedback(message):
    # при необходимости — сохранить отзыв
    bot.send_message(message.chat.id, "Спасибо за обратную связь!", reply_markup=main_menu_kb())

@bot.message_handler(commands=['settings'])
def cmd_settings(message):
    bot.send_message(message.chat.id, "Настройки пока не реализованы.")

# Команда, чтобы узнать chat_id чата (запусти в админском чате)
@bot.message_handler(commands=['getchatid'])
def cmd_getchatid(message):
    bot.reply_to(message, f"Chat ID: {message.chat.id}")

# ------------------ /info с инлайн-кнопками ------------------
@bot.message_handler(commands=['get_info', 'info'])
def cmd_get_info(message):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Да", callback_data="info_yes"),
        types.InlineKeyboardButton("Нет", callback_data="info_no"),
    )
    bot.send_message(message.chat.id, "Хотите узнать о возможностях?", reply_markup=markup)

# ------------------ Служебные функции режимов ------------------

def start_listener_or_therapist(kind: str, message):
    """Запуск режима 'listener' или 'therapist' и первичная заявка админу."""
    chat_id = message.chat.id
    username = message.from_user.username or None
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()

    kind_label = "слушателя" if kind == "listener" else "психотерапевта"

    # лог заявки
    log_request(kind_label, message.from_user)

    request_text = (
        f"📩 <b>Новая заявка на {kind_label}</b>\n\n"
        f"👤 Пользователь: {full_name}\n"
        f"💬 Username: @{username if username else 'нет'}\n"
        f"🆔 Chat ID: <code>{chat_id}</code>\n"
        f"🕓 Время: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text="🔁 Ответить пользователю", callback_data=f"reply_{chat_id}"
    ))

    # сообщение админу
    bot.send_message(ADMIN_CHAT_ID, request_text, parse_mode='HTML', reply_markup=markup)

    # включаем режим и даём инструкцию пользователю
    user_state[chat_id] = kind
    bot.send_message(
        chat_id,
        "✅ Заявка отправлена.\nОпишите ваши детали/вопрос — я буду пересылать их специалисту.\n"
        "Чтобы завершить диалог — нажмите кнопку ниже.",
        reply_markup=exit_kb()
    )

def forward_user_note_to_admin(kind: str, message):
    """Любое новое сообщение пользователя в режиме listener/therapist — пересылаем админу как продолжение."""
    username = message.from_user.username or "нет"
    full_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
    kind_label = "слушателя" if kind == "listener" else "психотерапевта"

    note = (
        f"🧩 <b>Продолжение диалога ({kind_label})</b>\n\n"
        f"👤 {full_name} (@{username})\n"
        f"🆔 <code>{message.chat.id}</code>\n"
        f"💬 Текст:\n{message.text}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="🔁 Ответить пользователю", callback_data=f"reply_{message.chat.id}"))
    bot.send_message(ADMIN_CHAT_ID, note, parse_mode='HTML', reply_markup=markup)

# ------------------ Обработка текста ------------------
@bot.message_handler(content_types=['text'])
def on_text(message):
    text = message.text.strip()
    chat_id = message.chat.id

    # если это команда — пусть обрабатывают командные хэндлеры
    if text.startswith('/'):
        return

    # универсальная кнопка выхода
    if text == '❌ Завершить диалог':
        return cmd_cancel(message)

    # если пользователь в активном режиме — обрабатываем и выходим
    state = user_state.get(chat_id)
    if state == "self_help":
        return handle_self_help_message(message)
    if state == "listener":
        forward_user_note_to_admin("listener", message)
        bot.send_message(chat_id, "📨 Передал сообщение специалисту. Пишите дальше или нажмите «❌ Завершить диалог».",
                         reply_markup=exit_kb())
        return
    if state == "therapist":
        forward_user_note_to_admin("therapist", message)
        bot.send_message(chat_id, "📨 Передал сообщение специалисту. Пишите дальше или нажмите «❌ Завершить диалог».",
                         reply_markup=exit_kb())
        return

    # запуск режимов по кнопкам
    if text == 'Мне нужен слушатель':
        return start_listener_or_therapist("listener", message)

    if text == 'Мне нужен психотерапевт':
        return start_listener_or_therapist("therapist", message)

    if text == 'Самопомощь':
        user_state[chat_id] = "self_help"
        bot.send_message(chat_id, "Что вас беспокоит? Пишите — я отвечу. Нажмите «❌ Завершить диалог», чтобы выйти.",
                         reply_markup=exit_kb())
        return

    # всё остальное
    bot.send_message(chat_id, 'Я не знаю, что сказать..', reply_markup=main_menu_kb())

# ------------------ Ответ админа пользователю ------------------

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def cb_reply_user(call):
    try:
        user_id = call.data.split('_')[1]
        bot.send_message(call.message.chat.id, f"✍️ Введите сообщение для пользователя (chat_id: {user_id})")
        bot.register_next_step_handler(call.message, lambda msg: forward_admin_reply(msg, user_id))
    except Exception as e:
        bot.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")

def forward_admin_reply(message, user_id):
    """Отправляет ответ администратора пользователю + подтверждение админу"""
    try:
        bot.send_message(
            int(user_id),
            f"💬 <b>Сообщение от администратора:</b>\n\n{message.text}",
            parse_mode='HTML',
            reply_markup=exit_kb()
        )
        bot.send_message(message.chat.id, f"✅ Сообщение успешно отправлено пользователю ({user_id})")
        if message.chat.id != ADMIN_CHAT_ID:
            bot.send_message(ADMIN_CHAT_ID, f"📨 Доставлено пользователю <code>{user_id}</code> ✅", parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Не удалось отправить сообщение: {e}")

# ------------------ Инлайн-ответ на /info ------------------

@bot.callback_query_handler(func=lambda call: call.data in ('info_yes', 'info_no'))
def cb_info(call):
    if call.data == 'info_yes':
        bot.send_message(call.message.chat.id, "Чем вам помочь?", reply_markup=main_menu_kb())
    else:
        bot.send_message(call.message.chat.id, "Тогда, хорошего вам дня! 😉", reply_markup=main_menu_kb())

# ------------------ OpenAI (непрерывный диалог) ------------------

def handle_self_help_message(message):
    """Все сообщения в режиме Самопомощи идут в GPT; кнопка выхода видна всегда."""
    chat_id = message.chat.id
    history = user_conversations.setdefault(chat_id, [])
    history.append({"role": "user", "content": message.text})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=history,
            temperature=0.8,
            max_tokens=500
        )
        answer = response['choices'][0]['message']['content'].strip()
        history.append({"role": "assistant", "content": answer})
        bot.send_message(chat_id, answer, reply_markup=exit_kb())
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Ошибка при обращении к OpenAI: {e}", reply_markup=exit_kb())

# ------------------ Запуск ------------------
if __name__ == '__main__':
    bot.polling(none_stop=True)
