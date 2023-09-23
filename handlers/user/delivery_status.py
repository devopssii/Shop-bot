
from aiogram.types import Message
from loader import dp, db
from .menu import delivery_status
from filters import IsUser

@dp.message_handler(IsUser(), text=delivery_status)
async def process_delivery_status(message: Message):
    
    orders = db.fetchall('SELECT * FROM orders WHERE cid=?', (message.chat.id,))
    
    if len(orders) == 0: await message.answer('У вас нет активных заказов.')
    else: await delivery_status_answer(message, orders)

async def delivery_status_answer(message, orders):
    res = ''

    for order in orders:
        order_number = order[3]
        order_status = order[4]  # извлечение статуса из пятого столбца

        res += f'Заказ <b>№{order_number}</b>{order_status}\n\n'

    await message.answer(res)
