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

# Данные пользователей: {user_id: {'username': str, 'link': str, 'expire_date': datetime, 'job': Job}}
users_data = {}
# Ожидающие добавления: {link: {'period': int, 'admin_id': int}}
pending_adds = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ... (остальные handlers без изменений до extend_user)

# Handler для 'extend_{user_id}' (только для выбора продления)
async def extend_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[1])  # Теперь data[1] всегда число, т.к. pattern '^extend_\d+$'
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

# Handler для 'extend_period_{seconds}'
async def extend_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    period_seconds = int(data[2])
    user_id = context.user_data.get('extending_user')
    if not user_id or user_id not in users_data:
        await query.edit_message_text('Ошибка: пользователь не найден.')
        return
    # Отменяем старый job, если есть
    old_job = users_data[user_id].get('job')
    if old_job:
        old_job.schedule_removal()
    # Продлеваем дату
    users_data[user_id]['expire_date'] += timedelta(seconds=period_seconds)
    # Запускаем новый job
    new_job = context.job_queue.run_once(kick_user, users_data[user_id]['expire_date'] - datetime.now(), data={'user_id': user_id, 'chat_id': GROUP_ID})
    users_data[user_id]['job'] = new_job
    # Возврат в меню
    keyboard = [
        [InlineKeyboardButton("Добавить нового пользователя в группу", callback_data='add_new')],
        [InlineKeyboardButton("Управление членством группы", callback_data='manage_members')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f'Подписка продлена на {period_seconds} секунд. Новая дата окончания: {users_data[user_id]["expire_date"].strftime("%Y-%m-%d %H:%M:%S")}.',
        reply_markup=reply_markup
    )

# ... (остальные handlers без изменений)

# В handle_new_member добавляем сохранение job
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
            job = context.job_queue.run_once(kick_user, timedelta(seconds=period_seconds), data={'user_id': user_id, 'chat_id': GROUP_ID})
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

# В delete_user добавляем отмену job
async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[1])
    if user_id in users_data:
        # Отменяем job
        job = users_data[user_id].get('job')
        if job:
            job.schedule_removal()
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

# ... (kick_user и main без изменений, но в main обнови patterns)

async def main():
    app = Application.builder().token(TOKEN).updater(None).build()

    # Добавляем handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin, pattern='^admin$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password))
    app.add_handler(CallbackQueryHandler(add_new, pattern='^add_new$'))
    app.add_handler(CallbackQueryHandler(add_new_period, pattern='^period_'))
    app.add_handler(ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(manage_members, pattern='^manage_members$'))
    app.add_handler(CallbackQueryHandler(user_details, pattern='^user_'))
    app.add_handler(CallbackQueryHandler(delete_user, pattern='^delete_'))
    app.add_handler(CallbackQueryHandler(extend_user, pattern='^extend_\d+$'))  # Изменено
    app.add_handler(CallbackQueryHandler(extend_period, pattern='^extend_period_\d+$'))  # Изменено
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$'))

    # ... (остальное без изменений)
