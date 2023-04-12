import time

import openai
import telebot
from flask import Flask, request

import config
# Import the keyboard functions
from keyboards.inline import create_inline_keyboard
from keyboards.reply import create_reply_keyboard

app = Flask(__name__)

bot = telebot.TeleBot(config.TOKEN)

# Set up OpenAI API
openai.api_key = config.OPENAI_API_KEY

# Create an empty dictionary to store conversation history for each user
user_conversations = {}

welcome_text = (
    "Приветствую!\n\n"
    "Psyinc — это бот эмоциональной онлайн-поддержки, который поможет вам самостоятельно справиться с "
    "повседневными переживаниями, позволит анонимно пообщаться с чутким слушаетелем, а так же предложит "
    "помощь квалифицированного специалиста.\n\n"
    "Автор бота Александр Гуртопов, который ведёт канал <a href='https://t.me/+qyO1cAXLfgRhMTNi'>Под коробкой</a>."
)


@bot.message_handler(commands=['start'])
def welcome(message):
    chat_id = message.chat.id
    user_conversations[chat_id] = ""
    bot.send_message(chat_id, welcome_text, parse_mode='html')


@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Вот список доступных команд:\n"
        "/start - начать работу с ботом\n"
        "/info или /get_info - узнать о возможностях бота\n"
        "/help - получить справочную информацию о доступных командах\n"
        "/cancel - отменить текущее действие или диалог\n"
        "/feedback - отправить обратную связь о работе бота\n"
        "/settings - изменить настройки бота\n"
        "/about - узнать информацию о создателях бота, версии и контактных данных\n"
    )
    bot.send_message(message.chat.id, help_text)


@bot.message_handler(commands=['get_info', 'info'])
def get_info(message):
    markup_inline = create_inline_keyboard()
    bot.send_message(message.chat.id, 'Хотите узнать о возможностях?', reply_markup=markup_inline)


@app.route(f'/{config.TOKEN}', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_json(force=True))
    bot.process_new_updates([update])
    return '', 200


@bot.callback_query_handler(func=lambda call: True)
def answer(call):
    if call.data == 'yes':
        markup_reply = create_reply_keyboard()
        bot.send_message(call.message.chat.id, 'Чем вам помочь?', reply_markup=markup_reply)
    elif call.data == 'no':
        bot.send_message(call.message.chat.id, "Тогда, хорошего вам дня! 😉")


@bot.message_handler(content_types=['text'])
def get_text(message):
    available_commands = ['/    help', '/cancel', '/feedback', '/settings', '/about', '/reset']

    if message.text == 'Мне нужен слушатель':
        bot.send_message(message.chat.id,
                         f'У нас есть в наличии слушатели для ваших нужд. Для получения дополнительной '
                         f'информации или для заказа слушателя, пожалуйста, напишите @bugseekerok')
    elif message.text == 'Мне нужен психотерапевт':
        bot.send_message(message.chat.id, f'У нас есть квалифицированные психотерапевты, которые могут предоставить '
                                          f'профессиональную психотерапевтическую помощь. Для заказа услуги или для '
                                          f'получения дополнительной информации, напишите @bugseekerok')
    elif message.text == 'Самопомощь':
        bot.send_message(message.chat.id, f'Что вас беспокоит?')
        bot.register_next_step_handler(message, send_to_chatgpt)
    elif message.text.lower() in available_commands:
        if message.text.lower() == '/help':
            help_command(message)
        elif message.text.lower() == '/cancel':
            cancel_command(message)
        elif message.text.lower() == '/feedback':
            feedback_command(message)
        elif message.text.lower() == '/settings':
            settings_command(message)
        elif message.text.lower() == '/about':
            about_command(message)
        elif message.text.lower() == '/reset':
            reset_command(message)

    else:
        bot.send_message(message.chat.id, f'Я не знаю, что сказать.. ')


@bot.message_handler(commands=['reset'])
def reset_command(message):
    chat_id = message.chat.id
    if chat_id in user_conversations:
        user_conversations[chat_id] = ""
    else:
        user_conversations[chat_id] = ""
    bot.send_message(message.chat.id, "История разговора была сброшена. Теперь вы можете начать снова.")


@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    bot.send_message(message.chat.id, "Текущее действие отменено. Если вам нужна помощь, введите /help.")


@bot.message_handler(commands=['feedback'])
def feedback_command(message):
    bot.send_message(message.chat.id, "Пожалуйста, введите свою обратную связь:")
    bot.register_next_step_handler(message, process_feedback)


def process_feedback(message):
    feedback = message.text
    # Здесь вы можете сохранить обратную связь пользователя, например, в файл или базу данных
    bot.send_message(message.chat.id, "Спасибо за вашу обратную связь!")


@bot.message_handler(commands=['settings'])
def settings_command(message):
    bot.send_message(message.chat.id,
                     "Настройки пока не реализованы. Введите /help, чтобы увидеть список доступных команд.")


@bot.message_handler(commands=['about'])
def about_command(message):
    about_text = (
        "Psyinc — это бот эмоциональной онлайн-поддержки, созданный Александром Гуртоповым.\n\n"
        "Версия: 1.0-beta\n"
        "Дата создания: 13.04.2023\n\n"
        "Автор: Александр Гуртопов\n"
        "Контакты: @bugseekerok\n\n"
        "Бот разработан на основе искусственного интеллекта OpenAI GPT-4 для предоставления эмоциональной поддержки "
        "пользователям, а также предложения услуг слушателей и психотерапевтов.\n\n"
        "Автор бота ведёт канал <a href='https://t.me/+qyO1cAXLfgRhMTNi'>Под коробкой</a>."
    )
    bot.send_message(message.chat.id, about_text, parse_mode='html')


def send_to_chatgpt(message):
    chat_id = message.chat.id
    question = message.text

    # Check if the user has a conversation history
    if chat_id in user_conversations:
        conversation_history = user_conversations[chat_id]
    else:
        conversation_history = ""

    # If the message is not a command, send it to GPT-4
    if not question.startswith('/'):
        stop_sequence = '\n'
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=f"{conversation_history}\nUser: {question}\nPsyinc:",
            max_tokens=500,
            n=1,
            stop=stop_sequence,
            temperature=0.8,
        )

        # Get the response and add it to the conversation history
        answer = response.choices[0].text.strip()
        conversation_history += f"\nUser: {question}\nPsyinc: {answer}"
        user_conversations[chat_id] = conversation_history

        bot.send_message(chat_id, answer)
    else:
        bot.send_message(chat_id,
                         "Пожалуйста, используйте одну из доступных команд. Введите /help для получения списка команд.")

if __name__ == '__main__':
    bot.polling(none_stop=True)
# if __name__ == '__main__':
#     bot.remove_webhook()
#     time.sleep(0.5)
#     bot.set_webhook(url=f'{config.WEBHOOK_HOST}/{config.TOKEN}')
#     app.run(host=config.WEBHOOK_LISTEN, port=config.WEBHOOK_PORT)
