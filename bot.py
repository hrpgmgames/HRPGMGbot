import os
from flask import Flask, request
import telebot

TOKEN = os.environ["BOT_TOKEN"]  # Или TELEGRAM_BOT_TOKEN
URL = os.environ["RENDER_EXTERNAL_URL"]  # Render сам добавит
PORT = int(os.environ.get("PORT", 5000))

bot = telebot.TeleBot(TOKEN)

# Твой существующий код handlers (пример для эха с кнопками — адаптируй)
@bot.message_handler(commands=['start'])
def start(message):
    print(f"Команда /start получена от {message.chat.id}")  # Добавь это для логов
    markup = telebot.types.InlineKeyboardMarkup()
    btn1 = telebot.types.InlineKeyboardButton("Кнопка 1", callback_data="btn1")
    markup.add(btn1)
    bot.send_message(message.chat.id, "Привет! Выбери:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    print(f"Callback получен: {call.data}")  # Добавь для логов
    if call.data == "btn1":
        bot.answer_callback_query(call.id, "Кнопка нажата!")

# НОВОЕ: Отладочный handler для всех текстовых сообщений (чтобы проверить, доходят ли они)
@bot.message_handler(content_types=['text'])
def debug_all_text(message):
    print(f"ОТЛАДКА: Получено текстовое сообщение: '{message.text}' от {message.chat.id}")
    # Не отправляй ответ, просто логируй — чтобы не мешать основному handler
        
# Webhook handler
app = Flask(__name__)

# НОВОЕ: Добавь установку webhook здесь (в глобальную область)
try:
    bot.remove_webhook()
    bot.set_webhook(url=f"{URL}/{TOKEN}")
    print("Webhook установлен успешно!")  # Для логов
    
    # ДОБАВЛЕНО: Логирование информации о webhook для диагностики
    webhook_info = bot.get_webhook_info()
    print(f"Webhook info: {webhook_info}")  # Покажет URL, pending updates и т.д.
    
except Exception as e:
    print(f"Ошибка при установке webhook: {e}")

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        print("Получен POST на webhook")  # ДОБАВЛЕНО: Для подтверждения получения обновления
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        print(f"Update: {update}")  # ДОБАВЛЕНО: Для отладки содержимого обновления
        bot.process_new_updates([update])
        return '', 200
    except Exception as e:
        print(f"Ошибка в webhook: {e}")  # ДОБАВЛЕНО: Логирование ошибок
        return 'error', 500

@app.route('/healthcheck', methods=['GET'])
def health():
    return 'ok', 200

# УБЕРИ весь блок if __name__ == '__main__' — он не нужен для Gunicorn
