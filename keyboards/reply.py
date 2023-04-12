from telebot import types


def create_reply_keyboard():
    markup_reply = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True, row_width=1)
    item_1 = types.KeyboardButton('Мне нужен слушатель')
    item_2 = types.KeyboardButton('Мне нужен психотерапевт')
    item_3 = types.KeyboardButton('Самопомощь')

    markup_reply.add(item_1, item_2, item_3)

    return markup_reply
