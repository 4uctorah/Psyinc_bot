import telebot
import config
from telebot import types

bot = telebot.TeleBot(config.TOKEN)


@bot.message_handler(commands=['start'])
def welcome(message):
    mess = f'Здравствуйте, <b>{message.from_user.first_name}</b>!' \
           f' Я, бот который поможет получить поддержку в трудной ситуации.'
    bot.send_message(message.chat.id, mess, parse_mode='html')


@bot.message_handler(commands=['get_info', 'info'])
def get_user_info(message):
    markup_inline = types.InlineKeyboardMarkup()
    item_yes = types.InlineKeyboardButton(text='ДА', callback_data='yes')
    item_no = types.InlineKeyboardButton(text='НЕТ', callback_data='no')
    markup_inline.add(item_yes, item_no)
    bot.send_message(message.chat.id, 'Хотите узнать о возможностях?',
                     reply_markup=markup_inline)



@bot.callback_query_handler(func=lambda call: True)
def answer(call):
    if call.data == 'yes':
        # keyboard
        markup_reply = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        item_1 = types.InlineKeyboardButton('Мне нужен слушатель')
        item_2 = types.InlineKeyboardButton('Мне нужен психотерапевт')

        markup_reply.add(item_1, item_2)
        bot.send_message(call.message.chat.id, 'Чем вам помочь?',
                         reply_markup=markup_reply)
    elif call.data == 'no':
        bot.send_message(call.message.chat.id, "Тогда, хорошего вам дня! 😉")


@bot.message_handler(content_types=['text'])
def get_text(message):
    if message.text == 'Мне нужен слушатель':
        bot.send_message(message.chat.id, f'Перевожу на слушателя: ')
    elif message.text == 'Мне нужен психотерапевт':
        bot.send_message(message.chat.id, f'Перевожу на специалиста: ')
    else:
        bot.send_message(message.chat.id, f'Я не знаю, что сказать: ')

# RUN
# bot.enable_save_next_step_handlers(delay=2)
# bot.load_next_step_handlers()
bot.polling(none_stop=True)
# python bot0.2.py