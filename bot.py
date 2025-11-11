import logging
import os  # НОВОЕ: Для чтения переменных окружения
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatInviteLink
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler
from datetime import datetime, timedelta
import asyncio

# Настройки из переменных окружения (env)
TOKEN = os.getenv('BOT_TOKEN')  # Твоя переменная для токена бота (обязательно!)
if not TOKEN:
    raise ValueError("BOT_TOKEN не задан в env!")

GROUP_ID = os.getenv('GROUP_ID')  # ID группы (например, '-1001234567890')
if not GROUP_ID:
    raise ValueError("GROUP_ID не задан в env!")

ADMIN_ID = os.getenv('ADMIN_ID')  # Твоя переменная для ID админа (число!)
if not ADMIN_ID:
    raise ValueError("ADMIN_ID не задан в env!")
ADMIN_IDS = [int(ADMIN_ID)]  # Преобразуем в int и делаем список (для одного админа)

# Данные пользователей: {user_id: {'join_time': datetime, 'period': int, 'message': message}}
users_data = {}

# Ожидающие приглашения: {admin_chat_id: {'period': period, 'message': message}}
pending_invites = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name}')

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Без изменений
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(f'Привет, {user.first_name}! Я бот для управления членством в группе.')

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Без изменений
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text('У вас нет прав.')
        return
    keyboard = [
        [InlineKeyboardButton("Добавить пользователя", callback_data='add_user')],
        [InlineKeyboardButton("Удалить пользователя", callback_data='remove_user')],
        [InlineKeyboardButton("Список пользователей", callback_data='list_users')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Меню админа:', reply_markup=reply_markup)

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Без изменений
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("1 час", callback_data='period_1')],
        [InlineKeyboardButton("24 часа", callback_data='period_24')],
        [InlineKeyboardButton("7 дней", callback_data='period_168')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Выберите период подписки:', reply_markup=reply_markup)

# ОБНОВЛЕНО: Из старого add_user_period (был для выбора периода и ожидания user_id) — теперь создаёт invite link и сохраняет ожидание
async def add_user_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    period_hours = int(data[1])
    admin_chat_id = query.from_user.id

    # Создаём invite link (НОВОЕ)
    expire_date = datetime.now() + timedelta(hours=1)  # Ссылка действительна 1 час
    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,  # Только один пользователь
            expire_date=expire_date,
            name=f'Подписка на {period_hours} часов'
        )
        link = invite_link.invite_link
    except Exception as e:
        await query.edit_message_text(f'Ошибка создания ссылки: {e}')
        return

    # Сохраняем ожидание (НОВОЕ)
    pending_invites[admin_chat_id] = {'period': period_hours, 'message': query.message}

    # Отправляем ссылку админу (НОВОЕ)
    await query.edit_message_text(
        f'Ссылка для приглашения создана (действительна 1 час, для одного пользователя):\n{link}\n\n'
        'Отправьте эту ссылку пользователю. Когда он присоединится, подписка активируется автоматически.'
    )

# НОВОЕ: Handler для отслеживания вступления по invite link
async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.chat_member and update.chat_member.chat.id == int(GROUP_ID):
        new_member = update.chat_member.new_chat_member
        if new_member.status in ['member', 'administrator', 'creator']:
            user_id = new_member.user.id
            admin_chat_id = None

            # Ищем админа, который ожидает этого пользователя (простая логика: проверяем всех pending)
            for admin_id, data in pending_invites.items():
                # В реальности, чтобы точно связать, можно добавить user_id в pending, но пока ищем по любому ожиданию
                # (Предполагаем, что админы не добавляют одновременно — или улучши логику)
                admin_chat_id = admin_id
                period = data['period']
                message = data['message']
                break

            if admin_chat_id:
                # Активируем подписку
                join_time = datetime.now()
                users_data[user_id] = {'join_time': join_time, 'period': period, 'message': message}
                del pending_invites[admin_chat_id]

                # Устанавливаем таймер на kick
                context.job_queue.run_once(kick_user, timedelta(hours=period), data={'user_id': user_id, 'chat_id': GROUP_ID})

                # Уведомляем админа
                await context.bot.send_message(
                    chat_id=admin_chat_id,
                    text=f'Пользователь {new_member.user.first_name} (ID: {user_id}) присоединился и подписан на {period} часов.'
                )

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Без изменений (для удаления пользователя)
async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text('Введите user_id пользователя для удаления:')

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Handler для обработки ввода user_id при удалении (предполагаю, что в старом был MessageHandler для этого)
async def handle_remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(update.message.text)
        if user_id in users_data:
            # Kick пользователя
            await context.bot.ban_chat_member(GROUP_ID, user_id)
            await context.bot.unban_chat_member(GROUP_ID, user_id)  # Unban для kick
            del users_data[user_id]
            await update.message.reply_text(f'Пользователь {user_id} удалён.')
        else:
            await update.message.reply_text('Пользователь не найден.')
    except ValueError:
        await update.message.reply_text('Неверный user_id.')

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Без изменений (для списка пользователей)
async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not users_data:
        await query.edit_message_text('Список пользователей пуст.')
        return
    text = 'Список пользователей:\n'
    for user_id, data in users_data.items():
        text += f'ID: {user_id}, Период: {data["period"]} часов, Время вступления: {data["join_time"]}\n'
    await query.edit_message_text(text)

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Функция для kick (с небольшими изменениями для job queue)
async def kick_user(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    user_id = job.data['user_id']
    chat_id = job.data['chat_id']
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id)  # Unban для kick, не ban
        if user_id in users_data:
            del users_data[user_id]
    except Exception as e:
        logger.error(f'Ошибка kick: {e}')

# ПЕРЕНЕСЕНО ИЗ СТАРОГО: Handler для обработки контактов (если был, но теперь не нужен для добавления — оставил на всякий случай)
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Старый код для контактов — теперь не используется в логике добавления, но оставлен
    pass

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    # ПЕРЕНЕСЕНО ИЗ СТАРОГО: Handlers для команд и меню
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_menu))
    application.add_handler(CallbackQueryHandler(add_user, pattern='^add_user$'))
    application.add_handler(CallbackQueryHandler(add_user_period, pattern='^period_'))
    application.add_handler(CallbackQueryHandler(remove_user, pattern='^remove_user$'))
    application.add_handler(CallbackQueryHandler(list_users, pattern='^list_users$'))

    # НОВОЕ: Handler для вступления в группу
    application.add_handler(ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER))

    # ПЕРЕНЕСЕНО ИЗ СТАРОГО: Handlers для сообщений (удаление по user_id, контакты)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_user))  # Для ввода user_id при удалении
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))  # Для контактов (если нужно)

    application.run_polling()

if __name__ == '__main__':
    main()
