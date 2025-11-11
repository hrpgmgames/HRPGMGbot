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
GROUP_ID = int(os.getenv('GROUP_ID'))  # ID группы
if not GROUP_ID:
    raise ValueError("GROUP_ID не задан!")

# Данные пользователей: {user_id: {'username': str, 'link': str, 'expire_date': datetime}}
users_data = {}
# Ожидающие добавления: {admin_chat_id: {'period': int}}
pending_adds = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Handler для /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("Админка", callback_data='admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Добро пожаловать! Нажмите "Админка" для доступа.', reply_markup=reply_markup)

# Handler для 'admin' (запрос пароля)
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text('Введите пароль (токен бота):')
    context.user_data['waiting_password'] = True

# Handler для ввода пароля
async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('waiting_password'):
        return
    password = update.message.text
    if password == TOKEN:
        context.user_data['waiting_password'] = False
        keyboard = [
            [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
            [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Пароль верный. Меню:', reply_markup=reply_markup)
    else:
        await update.message.reply_text('Неверный пароль. Попробуйте снова.')

# Handler для 'add_new' (выбор периода)
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

# Handler для выбора периода (запрос контакта/тега)
async def add_new_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    period_seconds = int(data[1])
    admin_chat_id = query.from_user.id
    pending_adds[admin_chat_id] = {'period': period_seconds}
    keyboard = [[InlineKeyboardButton("Назад", callback_data='add_new')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f'Период выбран: {period_seconds} секунд.\n'
        'Теперь скиньте контакт пользователя или введите его @тег/@username (или user_id):',
        reply_markup=reply_markup
    )

# Handler для контакта/тега (создание link и отправка)
async def handle_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_chat_id = update.effective_user.id
    if admin_chat_id not in pending_adds:
        return
    period_seconds = pending_adds[admin_chat_id]['period']
    user_id = None
    username = None

    if update.message.contact:
        user_id = update.message.contact.user_id
        username = update.message.contact.first_name or 'Без имени'
    elif update.message.text:
        text = update.message.text.strip()
        if text.startswith('@'):
            username = text[1:]
            # Для @username нужно получить user_id — бот не может напрямую, так что просим user_id
            await update.message.reply_text('Для @тега введите user_id пользователя (число).')
            return
        else:
            try:
                user_id = int(text)
                username = f'User_{user_id}'  # Заглушка, если нет имени
            except ValueError:
                await update.message.reply_text('Неверный формат. Скиньте контакт или введите user_id.')
                return

    if not user_id:
        return

    # Создание invite link
    expire_date = datetime.now() + timedelta(hours=1)
    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,
            expire_date=expire_date,
            name=f'Подписка на {period_seconds} секунд'
        )
        link = invite_link.invite_link
    except Exception as e:
        await update.message.reply_text(f'Ошибка создания ссылки: {e}')
        return

    # Отправка пользователю
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f'Приглашение в группу: {link}\nПодписка на {period_seconds} секунд.'
        )
        await update.message.reply_text(f'Ссылка отправлена пользователю {username} (ID: {user_id}). Ожидайте вступления.')
    except Exception as e:
        await update.message.reply_text(f'Ошибка отправки: {e}')
        return

    # Сохраняем ожидание вступления
    pending_adds[admin_chat_id]['user_id'] = user_id
    pending_adds[admin_chat_id]['username'] = username
    pending_adds[admin_chat_id]['link'] = link

# Handler для вступления в группу
async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.chat_member and update.chat_member.chat.id == GROUP_ID:
        new_member = update.chat_member.new_chat_member
        if new_member.status in ['member', 'administrator', 'creator']:
            user_id = new_member.user.id
            username = new_member.user.username or new_member.user.first_name or 'Без имени'
            # Ищем в pending_adds
            for admin_id, data in list(pending_adds.items()):
                if data.get('user_id') == user_id:
                    period_seconds = data['period']
                    link = data['link']
                    expire_date = datetime.now() + timedelta(seconds=period_seconds)
                    users_data[user_id] = {
                        'username': username,
                        'link': link,
                        'expire_date': expire_date
                    }
                    context.job_queue.run_once(kick_user, timedelta(seconds=period_seconds), data={'user_id': user_id, 'chat_id': GROUP_ID})
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f'Пользователь {username} (ID: {user_id}) присоединился. Подписка до {expire_date}.'
                    )
                    del pending_adds[admin_id]
                    break

# Handler для 'manage_members' (список пользователей)
async def manage_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not users_data:
        keyboard = [[InlineKeyboardButton("Назад", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('Нет активных подписок.', reply_markup=reply_markup)
        return
    keyboard = []
    for user_id, data in users_data.items():
        expire_str = data['expire_date'].strftime('%Y-%m-%d %H:%M:%S')
        keyboard.append([InlineKeyboardButton(f"{data['username']} - {user_id} - {expire_str}", callback_data=f'user_{user_id}')])
    keyboard.append([InlineKeyboardButton("Назад", callback_data='back_to_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Управление членством группы:', reply_markup=reply_markup)

# Handler для user_* (детали и кнопки)
async def user_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[1])
    if user_id not in users_data:
        await query.edit_message_text('Пользователь не найден.')
        return
    user_info = users_data[user_id]
    text = (
        f'Тег: @{user_info["username"]}\n'
        f'ID: {user_id}\n'
        f'Ссылка: {user_info["link"]}\n'
        f'Дата окончания: {user_info["expire_date"].strftime("%Y-%m-%d %H:%M:%S")}'
    )
    keyboard = [
        [InlineKeyboardButton("Удалить пользователя", callback_data=f'delete_{user_id}')],
        [InlineKeyboardButton("Продлить подписку", callback_data=f'extend_{user_id}')],
        [InlineKeyboardButton("Назад", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)

# Handler для 'delete_*'
async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[1])
    if user_id in users_data:
        try:
            await context.bot.ban_chat_member(GROUP_ID, user_id)
            await context.bot.unban_chat_member(GROUP_ID, user_id)
            del users_data[user_id]
            await query.edit_message_text('Пользователь удалён. Возврат в меню.')
            # Возврат в меню
            keyboard = [
                [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
                [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text('Меню:', reply_markup=reply_markup)
        except Exception as e:
            await query.edit_message_text(f'Ошибка удаления: {e}')
    else:
        await query.edit_message_text('Пользователь не найден.')

# Handler для 'extend_*' (выбор периода продления)
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
        [InlineKeyboardButton("30 секунд", callback_data='extend_period_30')],
        [InlineKeyboardButton("1 минута", callback_data='extend_period_60')],
        [InlineKeyboardButton("Назад", callback_data=f'user_{user_id}')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Выберите период продления:', reply_markup=reply_markup)

# Handler для 'extend_period_*'
async def extend_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    period_seconds = int(data[2])
    user_id = context.user_data.get('extending_user')
    if not user_id or user_id not in users_data:
        await query.edit_message_text('Ошибка.')
        return
    users_data[user_id]['expire_date'] += timedelta(seconds=period_seconds)
    # Обновить job (отменить старый, запустить новый)
    # Для простоты — перезапустить job
    context.job_queue.run_once(kick_user, users_data[user_id]['expire_date'] - datetime.now(), data={'user_id': user_id, 'chat_id': GROUP_ID})
    await query.edit_message_text(f'Подписка продлена на {period_seconds} секунд. Новая дата: {users_data[user_id]["expire_date"]}. Возврат в меню.')
    # Возврат в меню
    keyboard = [
        [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
        [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text('Меню:', reply_markup=reply_markup)

# Handler для 'back_to_menu'
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
        [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Меню:', reply_markup=reply_markup)

# Функция для kick
async def kick_user(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    user_id = job.data['user_id']
    chat_id = job.data['chat_id']
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id)
        if user_id in users_data:
            del users_data[user_id]
    except Exception as e:
        logger.error(f'Ошибка kick: {e}')

async def main():
    app = Application.builder().token(TOKEN).updater(None).build()

    # Добавляем handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin, pattern='^admin$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password))
    app.add_handler(CallbackQueryHandler(add_new, pattern='^add_new$'))
    app.add_handler(CallbackQueryHandler(add_new_period, pattern='^period_'))
    app.add_handler(MessageHandler(filters.CONTACT | filters.TEXT, handle_add_user))
    app.add_handler(ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(manage_members, pattern='^manage_members$'))
    app.add_handler(CallbackQueryHandler(user_details, pattern='^user_'))
    app.add_handler(CallbackQueryHandler(delete_user, pattern='^delete_'))
    app.add_handler(CallbackQueryHandler(extend_user, pattern='^extend_'))
    app.add_handler(CallbackQueryHandler(extend_period, pattern='^extend_period_'))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$'))

    # Устанавливаем webhook
    await app.bot.set_webhook(f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)

    # Starlette
    async def telegram(request: Request) -> Response:
        await app.update_queue.put(Update.de_json(await request.json(), app.bot))
        return Response()

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    starlette = Starlette(routes=[
        Route("/telegram", telegram, methods=["POST"]),
        Route("/healthcheck", health, methods=["GET"]),
    ])

    # Запуск
    server = uvicorn.Server(uvicorn.Config(app=starlette, host="0.0.0.0", port=PORT, use_colors=False))
    async with app:
        await app.start()
        await server.serve()
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
