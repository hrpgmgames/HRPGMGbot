import os
import asyncio
import logging
import json
import datetime
import uvicorn  # Добавлен импорт uvicorn
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse
from starlette.requests import Request
from starlette.routing import Route
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatInviteLink
from telegram.ext import (
    Application, ContextTypes, MessageHandler, filters, CallbackQueryHandler,
    ConversationHandler, CommandHandler, ChatMemberHandler
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
URL = os.environ["RENDER_EXTERNAL_URL"]
PORT = int(os.getenv("PORT", 8000))
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  # Твой Telegram ID для доступа к админке
GROUP_ID = int(os.environ.get("GROUP_ID", 0))  # ID группового чата (получи через бота)
DATA_FILE = "users_data.json"  # Файл для сохранения данных пользователей

log_fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(format=log_fmt, level=logging.INFO)

# Состояния для ConversationHandler
START, PASSWORD, MENU, ADD_PERIOD, ADD_USER, MANAGE_USERS, USER_DETAILS, EXTEND_PERIOD = range(8)

# Словарь для данных пользователей: {user_id: {"username": str, "invite_link": str, "expiry": datetime}}
users_data = {}

def load_data():
    global users_data
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            users_data = {int(k): {"username": v["username"], "invite_link": v["invite_link"], "expiry": datetime.datetime.fromisoformat(v["expiry"])} for k, v in data.items()}
    except FileNotFoundError:
        users_data = {}

def save_data():
    data = {str(k): {"username": v["username"], "invite_link": v["invite_link"], "expiry": v["expiry"].isoformat()} for k, v in users_data.items()}
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    while True:
        now = datetime.datetime.now()
        to_kick = []
        for user_id, data in users_data.items():
            if data["expiry"] <= now:
                try:
                    await context.bot.ban_chat_member(GROUP_ID, user_id)  # Кик + бан
                    await context.bot.unban_chat_member(GROUP_ID, user_id)  # Разбан, чтобы не считался забаненным
                    await context.bot.send_message(user_id, "Ваша подписка истекла. Вы исключены из группы.")
                    to_kick.append(user_id)
                except Exception as e:
                    logging.error(f"Ошибка при кике {user_id}: {e}")
        for uid in to_kick:
            del users_data[uid]
        save_data()
        await asyncio.sleep(10)  # Проверка каждые 10 секунд

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Start called by user ID: {update.effective_user.id}, ADMIN_ID: {ADMIN_ID}")  # Добавь эту строку для логирования
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Доступ запрещён.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton("Админка", callback_data="admin")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Нажми 'Админка' для доступа.", reply_markup=reply_markup)
    return START

async def admin_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите пароль (бот-токен):")
    return PASSWORD

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == TOKEN:
        await show_menu(update, context)
        return MENU
    else:
        await update.message.reply_text("Неверный пароль. Попробуйте /start")
        return ConversationHandler.END

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data="add_user")],
        [InlineKeyboardButton("Управление членством группы", callback_data="manage_users")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Меню админки:", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text("Меню админки:", reply_markup=reply_markup)

async def add_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("10 секунд", callback_data="period_10s")],
        [InlineKeyboardButton("30 секунд", callback_data="period_30s")],
        [InlineKeyboardButton("1 минута", callback_data="period_1m")],
        [InlineKeyboardButton("Назад", callback_data="back_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите период подписки:", reply_markup=reply_markup)
    return ADD_PERIOD

async def add_user_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "back_menu":
        await show_menu(update, context)
        return MENU
    periods = {"period_10s": 10, "period_30s": 30, "period_1m": 60}
    context.user_data["period"] = periods[query.data]
    await query.edit_message_text("Отправьте тег пользователя или контакт (например, @username):")
    return ADD_USER

async def add_user_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text
    if not username.startswith('@'):
        username = '@' + username
    period = context.user_data["period"]
    expiry = datetime.datetime.now() + datetime.timedelta(seconds=period)
    
    # Создаём ссылку приглашения
    try:
        invite_link = await update.get_bot().create_chat_invite_link(
            GROUP_ID, expire_date=expiry, member_limit=1, name=f"Приглашение для {username}"
        )
        # Отправляем ссылку пользователю (предполагаем, что username — это @tag, но лучше использовать ID)
        # Для простоты отправляем по username, но Telegram требует ID для приватных сообщений.
        # В реальности получи ID из контакта или попроси пользователя написать боту.
        await update.get_bot().send_message(chat_id=username, text=f"Ваша ссылка для вступления: {invite_link.invite_link}")
        # Сохраним данные после вступления (в обработчике chat_member)
        context.user_data["invite_link"] = invite_link.invite_link
        context.user_data["username"] = username
        context.user_data["expiry"] = expiry
        await update.message.reply_text("Ссылка отправлена! После вступления пользователь будет добавлен.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")
    await show_menu(update, context)
    return MENU

async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not users_data:
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Нет пользователей.", reply_markup=reply_markup)
        return MENU
    keyboard = []
    for user_id, data in users_data.items():
        keyboard.append([InlineKeyboardButton(f"{data['username']} - {user_id} - {data['expiry'].strftime('%d.%m.%Y %H:%M')}", callback_data=f"user_{user_id}")])
    keyboard.append([InlineKeyboardButton("Назад", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Пользователи:", reply_markup=reply_markup)
    return MANAGE_USERS

async def user_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[1])
    data = users_data[user_id]
    text = f"Пользователь: {data['username']}\nID: {user_id}\nСсылка: {data['invite_link']}\nОкончание: {data['expiry'].strftime('%d.%m.%Y %H:%M')}"
    keyboard = [
        [InlineKeyboardButton("Удалить пользователя", callback_data=f"delete_{user_id}")],
        [InlineKeyboardButton("Продлить подписку", callback_data=f"extend_{user_id}")],
        [InlineKeyboardButton("Назад", callback_data="manage_users")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return USER_DETAILS

async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[1])
    try:
        await update.get_bot().ban_chat_member(GROUP_ID, user_id)
        await update.get_bot().unban_chat_member(GROUP_ID, user_id)
        del users_data[user_id]
        save_data()
        await query.edit_message_text("Пользователь удалён.")
    except Exception as e:
        await query.edit_message_text(f"Ошибка: {e}")
    await show_menu(update, context)
    return MENU

async def extend_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[1])
    context.user_data["extend_user_id"] = user_id
    keyboard = [
        [InlineKeyboardButton("10 секунд", callback_data="extend_10s")],
        [InlineKeyboardButton("30 секунд", callback_data="extend_30s")],
        [InlineKeyboardButton("1 минута", callback_data="extend_1m")],
        [InlineKeyboardButton("Назад", callback_data=f"user_{user_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите период продления:", reply_markup=reply_markup)
    return EXTEND_PERIOD

async def extend_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = context.user_data["extend_user_id"]
    periods = {"extend_10s": 10, "extend_30s": 30, "extend_1m": 60}
    if query.data == f"user_{user_id}":
        await user_details(update, context)
        return USER_DETAILS
    add_seconds = periods[query.data]
    users_data[user_id]["expiry"] += datetime.timedelta(seconds=add_seconds)
    save_data()
    await query.edit_message_text("Подписка продлена!")
    await show_menu(update, context)
    return MENU

async def chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = update.chat_member
    if member.chat.id == GROUP_ID and member.new_chat_member.status in ['member', 'administrator', 'creator']:
        user_id = member.new_chat_member.user.id
        username = member.new_chat_member.user.username or f"user_{user_id}"
        if "invite_link" in context.user_data:
            users_data[user_id] = {
                "username": username,
                "invite_link": context.user_data["invite_link"],
                "expiry": context.user_data["expiry"]
            }
            save_data()
            logging.info(f"Пользователь {username} добавлен с expiry {context.user_data['expiry']}")

async def telegram(request: Request) -> Response:
    data = await request.json()
    logging.info(f"Raw update data: {data}")  # Добавь для отладки
    update = Update.de_json(data, app.bot)
    logging.info(f"Processed update: {update}")  # Добавь для отладки
    await app.process_update(update)  # Измени с update_queue.put
    return Response()

async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")

async def main():
    global app
    load_data()
    app = Application.builder().token(TOKEN).updater(None).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            START: [CallbackQueryHandler(admin_password, pattern="^admin$")],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)],
            MENU: [
                CallbackQueryHandler(add_user_start, pattern="^add_user$"),
                CallbackQueryHandler(manage_users, pattern="^manage_users$"),
                CallbackQueryHandler(show_menu, pattern="^back_menu$")
            ],
            ADD_PERIOD: [CallbackQueryHandler(add_user_period)],
            ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_final)],
            MANAGE_USERS: [CallbackQueryHandler(user_details, pattern="^user_"), CallbackQueryHandler(show_menu, pattern="^back_menu$")],
            USER_DETAILS: [
                CallbackQueryHandler(delete_user, pattern="^delete_"),
                CallbackQueryHandler(extend_start, pattern="^extend_"),
                CallbackQueryHandler(manage_users, pattern="^manage_users$")
            ],
            EXTEND_PERIOD: [CallbackQueryHandler(extend_final)]
        },
        fallbacks=[],
        per_message=True
    )
    
    app.add_handler(conv_handler)
    app.add_handler(ChatMemberHandler(chat_member, ChatMemberHandler.CHAT_MEMBER))
    await app.bot.set_webhook(f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)
    
    # Фоновая задача для проверки подписок
    app.job_queue.run_repeating(check_subscriptions, interval=10, first=0)
    
    # Запуск ASGI-сервера
    await server.serve()

starlette = Starlette(routes=[
    Route("/telegram", telegram, methods=["POST"]),
    Route("/healthcheck", health, methods=["GET"]),
])

server = uvicorn.Server(
    uvicorn.Config(app=starlette, host="0.0.0.0", port=PORT, use_colors=False)
)

if __name__ == "__main__":
    asyncio.run(main())
