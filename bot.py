import os
import asyncio
import logging
from datetime import datetime, timedelta
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse
from starlette.requests import Request
from starlette.routing import Route
import uvicorn
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler

# Env-переменные
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
URL = os.environ["RENDER_EXTERNAL_URL"]
PORT = int(os.getenv("PORT", 8000))
GROUP_ID = int(os.getenv('GROUP_ID'))
if not GROUP_ID:
    raise ValueError("GROUP_ID не задан!")

# Данные пользователей: {user_id: {'username': str, 'link': str, 'expire_date': datetime, 'job': Job}}
users_data = {}
# Ожидающие добавления: {invite_link: {'period': int, 'admin_id': int}}
pending_adds = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Функция для кика пользователя (без изменений)
async def kick_user(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    user_id = data['user_id']
    chat_id = data['chat_id']
    if user_id in users_data:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.unban_chat_member(chat_id, user_id)
            logger.info(f"Пользователь {users_data[user_id]['username']} (ID: {user_id}) кикнут по истечении подписки.")
            del users_data[user_id]
        except Exception as e:
            logger.error(f"Ошибка кика {user_id}: {e}")

# Handler для /start (без изменений)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Админ-панель", callback_data='admin')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Привет! Выберите опцию:', reply_markup=reply_markup)

# Handler для 'admin' (без изменений)
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
        [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Админ-меню:', reply_markup=reply_markup)

# Handler для пароля (без изменений)
async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text == "password":
        await admin(update, context)
    else:
        await update.message.reply_text('Неверный пароль.')

# Handler для 'add_new' (без изменений)
async def add_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("10 секунд", callback_data='period_10')],
        [InlineKeyboardButton("30 секунд", callback_data='period_30')],
        [InlineKeyboardButton("1 минута", callback_data='period_60')],
        [InlineKeyboardButton("Назад", callback_data='back_to_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Выберите период подписки:', reply_markup=reply_markup)

# Handler для 'period_{seconds}' — теперь бот сам создаёт invite link
async def add_new_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    period_seconds = int(data[1])
    admin_id = query.from_user.id
    try:
        # Создаём invite link с member_limit=1 (один пользователь может присоединиться)
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,  # Ограничение: только 1 пользователь
            expire_date=datetime.now() + timedelta(seconds=period_seconds + 60)  # Expire на период + 1 мин буфер
        )
        # Сохраняем в pending_adds
        pending_adds[invite_link.invite_link] = {'period': period_seconds, 'admin_id': admin_id}
        # Отправляем ссылку админу
        keyboard = [[InlineKeyboardButton("Назад", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f'Ссылка создана: {invite_link.invite_link}\nОтправьте её пользователю. Период: {period_seconds} секунд.',
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка создания ссылки: {e}")
        await query.edit_message_text('Ошибка создания ссылки. Убедитесь, что бот — админ группы.')

# Handler для 'manage_members' (без изменений)
async def manage_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not users_data:
        await query.edit_message_text('Нет активных пользователей.')
        return
    keyboard = []
    for user_id, data in users_data.items():
        expire_str = data['expire_date'].strftime("%Y-%m-%d %H:%M:%S")
        keyboard.append([InlineKeyboardButton(f"{data['username']} (до {expire_str})", callback_data=f'user_{user_id}')])
    keyboard.append([InlineKeyboardButton("Назад", callback_data='back_to_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Активные пользователи:', reply_markup=reply_markup)

# Handler для 'user_{user_id}' (без изменений)
async def user_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[1])
    if user_id not in users_data:
        await query.edit_message_text('Пользователь не найден.')
        return
    user = users_data[user_id]
    expire_str = user['expire_date'].strftime("%Y-%m-%d %H:%M:%S")
    keyboard = [
        [InlineKeyboardButton("Удалить", callback_data=f'delete_{user_id}')],
        [InlineKeyboardButton("Продлить", callback_data=f'extend_{user_id}')],
        [InlineKeyboardButton("Назад", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Пользователь: {user['username']}\nСсылка: {user['link']}\nИстекает: {expire_str}",
        reply_markup=reply_markup
    )

# Handler для 'extend_{user_id}' (без изменений)
async def extend_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[1])
    if user_id not in users_data:
        await query.edit_message_text('Пользователь не найден.')
        return
    context.user_data['extending_user'] = user_id
    keyboard = [
        [InlineKeyboardButton("10 секунд", callback_data='extend_period_10')],
        [InlineKeyboardButton("30 секунд", callback_data='extend_period_60')],
        [InlineKeyboardButton("1 минута", callback_data='extend_period_60')],
        [InlineKeyboardButton("Назад", callback_data=f'user_{user_id}')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Выберите период продления:', reply_markup=reply_markup)

# Handler для 'extend_period_{seconds}' (без изменений)
async def extend_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    period_seconds = int(data[2])
    user_id = context.user_data.get('extending_user')
    if not user_id or user_id not in users_data:
        await query.edit_message_text('Ошибка: пользователь не найден.')
        return
    old_job = users_data[user_id].get('job')
    if old_job:
        old_job.schedule_removal()
    users_data[user_id]['expire_date'] += timedelta(seconds=period_seconds)
    time_to_expire = users_data[user_id]['expire_date'] - datetime.now()
    new_job = context.job_queue.run_once(kick_user, time_to_expire, data={'user_id': user_id, 'chat_id': GROUP_ID})
    users_data[user_id]['job'] = new_job
    keyboard = [
        [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
        [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f'Подписка продлена на {period_seconds} секунд. Новая дата: {users_data[user_id]["expire_date"].strftime("%Y-%m-%d %H:%M:%S")}.',
        reply_markup=reply_markup
    )
    context.user_data.pop('extending_user', None)

# Handler для 'delete_{user_id}' (без изменений)
async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[1])
    if user_id in users_data:
        job = users_data[user_id].get('job')
        if job:
            job.schedule_removal()
        try:
            await context.bot.ban_chat_member(GROUP_ID, user_id)
            await context.bot.unban_chat_member(GROUP_ID, user_id)
            del users_data[user_id]
            keyboard = [
                [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
                [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text('Пользователь удалён. Возврат в меню.', reply_markup=reply_markup)
        except Exception as e:
            await query.edit_message_text(f'Ошибка удаления: {e}')
    else:
        await query.edit_message_text('Пользователь не найден.')

# Handler для handle_new_member (обновлён: использует invite_link.invite_link)
async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.chat_member and update.chat_member.chat.id == GROUP_ID:
        new_member = update.chat_member.new_chat_member
        invite_link = update.chat_member.invite_link
        if new_member.status == 'member' and invite_link and invite_link.invite_link in pending_adds:
            link = invite_link.invite_link
            data = pending_adds[link]
            user_id = new_member.user.id
            username = new_member.user.username or new_member.user.first_name or 'Без имени'
            period_seconds = data['period']
            admin_id = data['admin_id']
            expire_date = datetime.now() + timedelta(seconds=period_seconds)
            time_to_expire = timedelta(seconds=period_seconds)
            job = context.job_queue.run_once(kick_user, time_to_expire, data={'user_id': user_id, 'chat_id': GROUP_ID})
            users_data[user_id] = {
                'username': username,
                'link': link,
                'expire_date': expire_date,
                'job': job
            }
            await context.bot.send_message(
                chat_id=admin_id,
                text=f'Пользователь {username} (ID: {user_id}) присоединился по ссылке. Подписка до {expire_date}.'
            )
            del pending_adds[link]

# Handler для 'back_to_menu' (без изменений)
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
        [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Админ-меню:', reply_markup=reply_markup)

# Webhook handler для Starlette (без изменений)
async def handle_webhook(request: Request) -> Response:
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return Response()

# Healthcheck handler для Starlette (без изменений)
async def handle_healthcheck(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")

# Создаём routes для Starlette (без изменений)
routes = [
    Route("/webhook", handle_webhook, methods=["POST"]),
    Route("/healthcheck", handle_healthcheck, methods=["GET", "HEAD"]),
]

# Starlette app (без изменений)
starlette_app = Starlette(routes=routes)

# Application TG (без изменений)
app = Application.builder().token(TOKEN).build()

# Main (теперь не async, для uvicorn.run) (без изменений)
def main():
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin, pattern=r'^admin$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password))
    app.add_handler(CallbackQueryHandler(add_new, pattern=r'^add_new$'))
    app.add_handler(CallbackQueryHandler(add_new_period, pattern=r'^period_\d+$'))
    app.add_handler(ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(manage_members, pattern=r'^manage_members$'))
    app.add_handler(CallbackQueryHandler(user_details, pattern=r'^user_\d+$'))
    app.add_handler(CallbackQueryHandler(delete_user, pattern=r'^delete_\d+$'))
    app.add_handler(CallbackQueryHandler(extend_user, pattern=r'^extend_\d+$'))
    app.add_handler(CallbackQueryHandler(extend_period, pattern=r'^extend_period_\d+$'))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern=r'^back_to_menu$'))

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.bot.set_webhook(url=f"{URL}/webhook"))

    uvicorn.run(starlette_app, host="0.0.0.0", port=PORT)

if __name__ == '__main__':
    main()
