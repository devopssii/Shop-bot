import os
import handlers
from aiogram import executor, types
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove
from data import config
from loader import dp, db, bot
import filters
import logging

filters.setup(dp)

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.environ.get("PORT", 5000))
user_message = 'Пользователь'
admin_message = 'Админ'

@dp.message_handler(commands='start')
async def cmd_start(message: types.Message):

    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    
    if message.from_user.id in config.ADMINS:
        markup.row('Пользователь', 'Админ')
    else:
        markup.row('Пользователь')

    # определение языка пользователя
    user_language = message.from_user.language_code
    user_id = message.from_user.id
    user_name = f"{message.from_user.first_name} {message.from_user.last_name}"

    # запись информации о пользователе в базу данных
    db.query(
        'INSERT OR IGNORE INTO users (id, cid, name, lang) VALUES (?, ?, ?, ?)',
        (user_id, user_id, user_name, user_language)
    )

    await message.answer('''Привет! 👋

🤖 Я бот-магазин по подаже товаров любой категории.
    
🛍️ Чтобы перейти в каталог и выбрать приглянувшиеся товары возпользуйтесь командой /menu.

    ''', reply_markup=markup)

@dp.message_handler(text=user_message)
async def user_mode(message: types.Message):
    cid = message.chat.id
    if cid in config.ADMINS:
        config.ADMINS.remove(cid)

    await message.answer('Включен пользовательский режим.', reply_markup=ReplyKeyboardRemove())

@dp.message_handler(text=admin_message)
async def admin_mode(message: types.Message):
    cid = message.chat.id
    if cid not in config.ADMINS:
        config.ADMINS.append(cid)

    await message.answer('Включен админский режим.', reply_markup=ReplyKeyboardRemove())

async def on_startup(dp):
    logging.basicConfig(level=logging.INFO)
    db.create_tables()

    try:
        await bot.delete_webhook()
    except Exception as e:
        logging.warning(f"Failed to delete webhook: {e}")

    await bot.set_webhook(config.WEBHOOK_URL)

async def on_shutdown():
    logging.warning("Shutting down..")
    await bot.delete_webhook()
    await dp.storage.close()
    await dp.storage.wait_closed()
    logging.warning("Bot down")

if __name__ == '__main__':
    executor.start_webhook(
        dispatcher=dp,
        webhook_path=config.WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )
