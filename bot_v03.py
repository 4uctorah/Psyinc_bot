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

# Память диалогов
user_conversations = {}

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
    bot.send_message(chat_id, welcome_text, parse_mode='html')

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = (
        "Вот список доступных команд:\n"
        "/start — начать работу с ботом\n"
        "/info или /get_info — узнать о возможностях бота\n"
        "/help — справка\n"
        "/cancel — отменить текущее действие\n"
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
    bot.send_message(message.chat.id, "Действие отменено. Введите /help для справки.")

@bot.message_handler(commands=['feedback'])
def cmd_feedback(message):
    bot.send_message(message.chat.id, "Пожалуйста, введите свой отзыв:")
    bot.register_next_step_handler(message, process_feedback)

def process_feedback(message):
    # Здесь можешь сохранить отзыв при необходимости
    bot.send_message(message.chat.id, "Спасибо за обратную связь!")

@bot.message_handler(commands=['settings'])
def cmd_settings(message):
    bot.send_message(message.chat.id, "Настройки пока не реализованы.")

# Команда, чтобы узнать chat_id чата (запусти в админском чате)
@bot.message_handler(commands=['getchatid'])
def cmd_getchatid(message):
    bot.reply_to(message, f"Chat ID: {message.chat.id}")

# ------------------ /info с инлайн-кнопками ------------------
# Если у тебя есть готовые фабрики клавиатур — можно подключить их.
# Ниже — простой инлайн-интерфейс yes/no.
@bot.message_handler(commands=['get_info', 'info'])
def cmd_get_info(message):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Да", callback_data="info_yes"),
        types.InlineKeyboardButton("Нет", callback_data="info_no"),
    )
    bot.send_message(message.chat.id, "Хотите узнать о возможностях?", reply_markup=markup)

# ------------------ Контент: текст (НЕ КОМАНДЫ) ------------------
@bot.message_handler(content_types=['text'])
def on_text(message):
    # 1) Если это команда (начинается с '/'), не обрабатываем здесь,
    #    чтобы не перебивать командные хэндлеры.
    if message.text.startswith('/'):
        return

    # 2) Основные ветки
    if message.text == 'Мне нужен слушатель':
        log_request("слушатель", message.from_user)

        chat_id = message.chat.id
        username = message.from_user.username or None
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()

        request_text = (
            f"📩 <b>Новая заявка на слушателя</b>\n\n"
            f"👤 Пользователь: {full_name}\n"
            f"💬 Username: @{username if username else 'нет'}\n"
            f"🆔 Chat ID: <code>{chat_id}</code>\n"
            f"🕓 Время: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Кнопка: админ отвечает из админского чата
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            text="🔁 Ответить пользователю", callback_data=f"reply_{chat_id}"
        ))

        try:
            bot.send_message(ADMIN_CHAT_ID, request_text, parse_mode='HTML', reply_markup=markup)
            bot.send_message(chat_id, "✅ Ваша заявка на слушателя отправлена. Ожидайте ответа.")
        except Exception as e:
            bot.send_message(chat_id, f"⚠️ Ошибка при отправке админу: {e}")

    elif message.text == 'Мне нужен психотерапевт':
        log_request("психотерапевт", message.from_user)

        chat_id = message.chat.id
        username = message.from_user.username or None
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()

        request_text = (
            f"📩 <b>Новая заявка на психотерапевта</b>\n\n"
            f"👤 Пользователь: {full_name}\n"
            f"💬 Username: @{username if username else 'нет'}\n"
            f"🆔 Chat ID: <code>{chat_id}</code>\n"
            f"🕓 Время: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            text="🔁 Ответить пользователю", callback_data=f"reply_{chat_id}"
        ))

        try:
            bot.send_message(ADMIN_CHAT_ID, request_text, parse_mode='HTML', reply_markup=markup)
            bot.send_message(chat_id, "✅ Ваша заявка на психотерапевта отправлена. Ожидайте ответа.")
        except Exception as e:
            bot.send_message(chat_id, f"⚠️ Ошибка при отправке админу: {e}")

    elif message.text == 'Самопомощь':
        bot.send_message(message.chat.id, 'Что вас беспокоит?')
        bot.register_next_step_handler(message, send_to_chatgpt)

    else:
        bot.send_message(message.chat.id, 'Я не знаю, что сказать..')

# ------------------ Callback'и ------------------

# 1) Ответ админа пользователю (кнопка в админском чате)
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
            parse_mode='HTML'
        )
        bot.send_message(message.chat.id, f"✅ Сообщение успешно отправлено пользователю ({user_id})")
        # дублируем подтверждение в админский чат
        if message.chat.id != ADMIN_CHAT_ID:
            bot.send_message(ADMIN_CHAT_ID, f"📨 Доставлено пользователю <code>{user_id}</code> ✅", parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Не удалось отправить сообщение: {e}")

# 2) Инлайн «Да/Нет» из /info
@bot.callback_query_handler(func=lambda call: call.data in ('info_yes', 'info_no'))
def cb_info(call):
    if call.data == 'info_yes':
        # Покажем реплай-клавиатуру (если у тебя есть готовая фабрика, подключи её)
        # Ниже простой вариант из двух кнопок:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row('Мне нужен слушатель') 
        kb.row('Мне нужен психотерапевт')
        kb.row('Самопомощь')
        bot.send_message(call.message.chat.id, "Чем вам помочь?", reply_markup=kb)
    else:
        bot.send_message(call.message.chat.id, "Тогда, хорошего вам дня! 😉")

# ------------------ OpenAI ------------------
def send_to_chatgpt(message):
    chat_id = message.chat.id
    question = message.text

    if chat_id not in user_conversations:
        user_conversations[chat_id] = []

    conversation_history = user_conversations[chat_id]
    conversation_history.append({"role": "user", "content": question})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",   # при желании поменяешь на 4o/4.1 и т.д.
            messages=conversation_history,
            temperature=0.8,
            max_tokens=500
        )
        answer = response['choices'][0]['message']['content'].strip()
        conversation_history.append({"role": "assistant", "content": answer})
        user_conversations[chat_id] = conversation_history
        bot.send_message(chat_id, answer)
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Ошибка при обращении к OpenAI: {e}")

# ------------------ Запуск ------------------
if __name__ == '__main__':
    bot.polling(none_stop=True)
