from telebot import types


def create_inline_keyboard():
    markup_inline = types.InlineKeyboardMarkup()
    item_yes = types.InlineKeyboardButton(text='ДА', callback_data='yes')
    item_no = types.InlineKeyboardButton(text='НЕТ', callback_data='no')
    markup_inline.add(item_yes, item_no)

    return markup_inline
