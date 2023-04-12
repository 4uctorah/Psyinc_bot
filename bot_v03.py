import openai
import telebot
import config
from telebot import types

# Import the keyboard functions
from keyboards.inline import create_inline_keyboard
from keyboards.reply import create_reply_keyboard
from flask import Flask, request

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
    bot.send_message(message.chat.id, welcome_text, parse_mode='html')


@bot.message_handler(commands=['get_info', 'info'])
def get_info(message):
    markup_inline = create_inline_keyboard()
    bot.send_message(message.chat.id, 'Хотите узнать о возможностях?', reply_markup=markup_inline)


@app.route('/5006443958:AAEQaNc1K-WQG2OCT0e72HuZxNtp2UpJEY0', methods=['POST'])
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
    if message.text == 'Мне нужен слушатель':
        bot.send_message(message.chat.id, f'Перевожу на слушателя: ')
    elif message.text == 'Мне нужен психотерапевт':
        bot.send_message(message.chat.id, f'Перевожу на специалиста: ')
    elif message.text == 'Самопомощь':
        bot.send_message(message.chat.id, f'Что вас беспокоит?')
        bot.register_next_step_handler(message, send_to_chatgpt)
    else:
        bot.send_message(message.chat.id, f'Я не знаю, что сказать.. ')


def send_to_chatgpt(message):
    user_input = message.text
    chat_id = message.chat.id

    # Retrieve the conversation history or initialize an empty history
    conversation_history = user_conversations.get(chat_id, "")

    # Update the conversation history with the user's input
    conversation_history += f"User: {user_input}\nAssistant:"

    chatgpt_response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=conversation_history,
        temperature=0.8,
        max_tokens=500,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
    )

    response_text = chatgpt_response.choices[0].text.strip()

    # Update the conversation history with the assistant's response
    conversation_history += f" {response_text}\n"
    user_conversations[chat_id] = conversation_history

    bot.send_message(message.chat.id, response_text)
    # Register the next step handler to continue the conversation
    bot.register_next_step_handler(message, send_to_chatgpt)


# bot.polling(none_stop=True)

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://4uctorah.pythonanywhere.com/5006443958:AAEQaNc1K-WQG2OCT0e72HuZxNtp2UpJEY0')
    app.run()
