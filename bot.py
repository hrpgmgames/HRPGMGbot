import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Ваш токен бота от BotFather
TOKEN = '8466597404:AAGWBwitA0LZv_NPdTkbwgxHr-xELzv3laI'
bot = telebot.TeleBot(TOKEN)

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Подписка", callback_data="subscription"),
        InlineKeyboardButton("Тарифы", callback_data="tariffs")
    )
    bot.send_message(message.chat.id, "Выберите опцию:", reply_markup=markup)

# Обработчик callback-запросов от кнопок
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "subscription":
        bot.answer_callback_query(call.id)  # Закрыть "загрузку" на кнопке
        bot.send_message(call.message.chat.id, "Подписка не активна")
    
    elif call.data == "tariffs":
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("1 месяц - 100 руб", callback_data="tariff_1"),
            InlineKeyboardButton("2 месяца - 200 руб", callback_data="tariff_2"),
            InlineKeyboardButton("3 месяца - 300 руб", callback_data="tariff_3")
        )
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Выберите тариф:",
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)
    
    # Здесь можно добавить обработку для тарифов (tariff_1, tariff_2, tariff_3), если нужно (например, показать детали или оплатить)
    elif call.data.startswith("tariff_"):
        bot.answer_callback_query(call.id)
        # Пример: просто показать сообщение
        if call.data == "tariff_1":
            bot.send_message(call.message.chat.id, "Вы выбрали 1 месяц за 100 руб. (Здесь можно добавить логику оплаты)")
        elif call.data == "tariff_2":
            bot.send_message(call.message.chat.id, "Вы выбрали 2 месяца за 200 руб.")
        elif call.data == "tariff_3":
            bot.send_message(call.message.chat.id, "Вы выбрали 3 месяца за 300 руб.")

# Запуск бота
if __name__ == "__main__":
    bot.polling(none_stop=True)
