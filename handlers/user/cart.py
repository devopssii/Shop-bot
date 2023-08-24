import logging
from aiogram.dispatcher import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from keyboards.inline.products_from_cart import product_markup, product_cb
from aiogram.utils.callback_data import CallbackData
from keyboards.default.markups import *
from aiogram.types.chat import ChatActions
from states import CheckoutState
from loader import dp, db, bot
from filters import IsUser
from .menu import cart
from aiogram.types import Message, Location, KeyboardButton

@dp.message_handler(IsUser(), text=cart)
async def process_cart(message: Message, state: FSMContext):

    cart_data = db.fetchall(
        'SELECT * FROM cart WHERE cid=?', (message.chat.id,))

    if len(cart_data) == 0:

        await message.answer('Ваша корзина пуста.')

    else:

        await bot.send_chat_action(message.chat.id, ChatActions.TYPING)
        async with state.proxy() as data:
            data['products'] = {}

        order_cost = 0

        for _, idx, count_in_cart in cart_data:

            product = db.fetchone('SELECT * FROM products WHERE idx=?', (idx,))

            if product == None:

                db.query('DELETE FROM cart WHERE idx=?', (idx,))

            else:
                _, title, body, image, price, _ = product
                order_cost += price

                async with state.proxy() as data:
                    data['products'][idx] = [title, price, count_in_cart]

                markup = product_markup(idx, count_in_cart)
                text = f'<b>{title}</b>\n\n{body}\n\nЦена: {price}₽.'

                await message.answer_photo(photo=image,
                                           caption=text,
                                           reply_markup=markup)

        if order_cost != 0:
            markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            markup.add('📦 Оформить заказ')

            await message.answer('Перейти к оформлению?',
                                 reply_markup=markup)


@dp.callback_query_handler(IsUser(), product_cb.filter(action='count'))
@dp.callback_query_handler(IsUser(), product_cb.filter(action='increase'))
@dp.callback_query_handler(IsUser(), product_cb.filter(action='decrease'))
async def product_callback_handler(query: CallbackQuery, callback_data: dict, state: FSMContext):

    idx = callback_data['id']
    action = callback_data['action']

    if 'count' == action:

        async with state.proxy() as data:

            if 'products' not in data.keys():

                await process_cart(query.message, state)

            else:

                await query.answer('Количество - ' + data['products'][idx][2])

    else:

        async with state.proxy() as data:

            if 'products' not in data.keys():

                await process_cart(query.message, state)

            else:

                data['products'][idx][2] += 1 if 'increase' == action else -1
                count_in_cart = data['products'][idx][2]

                if count_in_cart == 0:

                    db.query('''DELETE FROM cart
                    WHERE cid = ? AND idx = ?''', (query.message.chat.id, idx))

                    await query.message.delete()
                else:

                    db.query('''UPDATE cart 
                    SET quantity = ? 
                    WHERE cid = ? AND idx = ?''', (count_in_cart, query.message.chat.id, idx))

                    await query.message.edit_reply_markup(product_markup(idx, count_in_cart))


@dp.message_handler(IsUser(), text='📦 Оформить заказ')
async def process_checkout(message: Message, state: FSMContext):

    await CheckoutState.check_cart.set()
    await checkout(message, state)


async def checkout(message, state):
    answer = ''
    total_price = 0

    async with state.proxy() as data:

        for title, price, count_in_cart in data['products'].values():

            tp = count_in_cart * price
            answer += f'<b>{title}</b> * {count_in_cart}шт. = {tp}₽\n'
            total_price += tp

    await message.answer(f'{answer}\nОбщая сумма заказа: {total_price}₽.',
                         reply_markup=check_markup())


@dp.message_handler(IsUser(), lambda message: message.text not in [all_right_message, back_message], state=CheckoutState.check_cart)
async def process_check_cart_invalid(message: Message):
    await message.reply('Такого варианта не было.')


@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.check_cart)
async def process_check_cart_back(message: Message, state: FSMContext):
    await state.finish()
    await process_cart(message, state)
#Функции проверки данных клиента - Проверка имени
async def check_name(data, message):
    if not data["name"]:
        await CheckoutState.name.set()
        await message.answer('Укажите свое имя.', reply_markup=back_markup())
        return False
    return True

async def check_address(data, message):
    if data["address"]:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        markup.add("Отправить на этот")
        markup.add("Отправить новый адрес")
        await message.answer(f'Последний раз Вы заказывали сюда: {data["address"]}\nОтправить на этот адрес?', reply_markup=markup)
        await CheckoutState.choose_address.set()
    else:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        location_button = KeyboardButton(text="Отправить локацию", request_location=True)
        markup.add(location_button)
        await message.answer("Отправьте свою локацию или напишите и отправьте адрес.", reply_markup=markup)
        await CheckoutState.send_location_or_text.set()

async def check_mobile(data, message):
    if not data["mobile"]:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        phone_button = KeyboardButton(text="Отправить контакт", request_contact=True)
        markup.add(phone_button)
        await message.answer("Пожалуйста, укажите свой номер телефона или поделитесь контактом.", reply_markup=markup)
        await CheckoutState.send_contact_or_text.set()
    else:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        markup.add("Номер верный")
        markup.add("Отправить контакт")
        await message.answer(f'Подтвердите номер для связи с курьером: {data["mobile"]}\nЧтобы изменить номер, отправьте сообщение с ним или поделитесь контактом.', reply_markup=markup)
        await CheckoutState.confirm_mobile.set()

@dp.message_handler(IsUser(), text=all_right_message, state=CheckoutState.check_cart)
async def process_check_cart_all_right(message: Message, state: FSMContext):
    user_data = db.fetchone("SELECT * FROM users WHERE cid=?", (message.chat.id,))
    async with state.proxy() as data:
        if user_data:
            data["name"] = user_data[6]
            data["address"] = user_data[3]
            data["mobile"] = user_data[5]

            if not await check_name(data, message): 
                return
            await check_address(data, message)
            await check_mobile(data, message)
        else:
            await CheckoutState.name.set()
            await message.answer('Укажите свое имя.', reply_markup=back_markup())

# Обработчик для сохранения мобильного номера из сообщения
@dp.message_handler(IsUser(), content_types=["text"], state=CheckoutState.send_contact_or_text)
async def process_user_mobile_from_text(message: Message, state: FSMContext):
    mobile = message.text
    db.query("UPDATE users SET mobile = ? WHERE cid = ?", (mobile, message.chat.id))
    await confirm(message)  # Метод для подтверждения заказа
    await CheckoutState.confirm.set()

# Обработчик для сохранения мобильного номера из контакта
@dp.message_handler(IsUser(), content_types=["contact"], state=CheckoutState.send_contact_or_text)
async def process_user_mobile_from_contact(message: Message, state: FSMContext):
    contact = message.contact
    mobile = contact.phone_number
    db.query("UPDATE users SET mobile = ? WHERE cid = ?", (mobile, message.chat.id))
    await confirm(message)  # Метод для подтверждения заказа
    await CheckoutState.confirm.set()

# Обработчик для подтверждения или изменения мобильного номера
@dp.message_handler(IsUser(), text=["Номер верный", "Отправить контакт"], state=CheckoutState.confirm_mobile)
async def process_confirm_or_change_mobile(message: Message, state: FSMContext):
    if message.text == "Номер верный":
        await confirm(message)
        await CheckoutState.confirm.set()
    else:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        phone_button = KeyboardButton(text="Отправить контакт", request_contact=True)
        markup.add(phone_button)
        await message.answer("Пожалуйста, укажите свой номер телефона или поделитесь контактом.", reply_markup=markup)
        await CheckoutState.send_contact_or_text.set()

@dp.message_handler(IsUser(), content_types=["text"], state=CheckoutState.send_location_or_text)
async def process_user_address(message: Message, state: FSMContext):
    address = message.text
    db.query("UPDATE users SET address = ? WHERE cid = ?", (address, message.chat.id))
    await confirm(message)
    await CheckoutState.confirm.set()

@dp.message_handler(IsUser(), text="Отправить на этот", state=CheckoutState.choose_address)
async def process_use_same_address(message: Message, state: FSMContext):
    await confirm(message)
    await CheckoutState.confirm.set()

@dp.message_handler(IsUser(), text="Отправить новый адрес", state=CheckoutState.choose_address)
async def process_new_address(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, отправьте вашу геолокацию.")
    await CheckoutState.send_location.set()

@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.name)
async def process_name_back(message: Message, state: FSMContext):
    await CheckoutState.check_cart.set()
    await checkout(message, state)
    
#Функция обработки нажатия на кнопку получения локации при остуствии в базе адреса
@dp.message_handler(IsUser(), content_types=["location"], state=CheckoutState.send_location_or_text)
async def process_user_location_from_button(message: Message, state: FSMContext):
    user_location = message.location
    latitude = user_location.latitude
    longitude = user_location.longitude

    # Сохраняем координаты в переменную
    coordinates = f"{latitude}, {longitude}"

    async with state.proxy() as data:
        data["coordinates"] = coordinates

    # Сохраняем координаты в базе данных (по вашему усмотрению, вы можете преобразовать их в адрес)
    db.query("UPDATE users SET coordinates = ? WHERE cid = ?", (coordinates, message.chat.id))

    await confirm(message)
    await CheckoutState.confirm.set()

#Функция обработки нажатия на кнопку получения локации при изменении адреса
@dp.message_handler(IsUser(), content_types=["location"], state=CheckoutState.send_location)
async def process_user_location(message: Message, state: FSMContext):
    user_location = message.location
    latitude = user_location.latitude
    longitude = user_location.longitude

    # Сохраняем координаты в переменную
    coordinates = f"{latitude}, {longitude}"

    async with state.proxy() as data:
        data["coordinates"] = coordinates

    # Сохраняем координаты в базе данных
    db.query("UPDATE users SET coordinates = ? WHERE cid = ?", (coordinates, message.chat.id))

    # Здесь вы можете добавить логику преобразования координат в адрес, когда у вас появится такая возможность

    await confirm(message)
    await CheckoutState.confirm.set()
##Разделение кода выше писали мы ниже писали не мы 

@dp.message_handler(IsUser(), state=CheckoutState.name)
async def process_name(message: Message, state: FSMContext):
    async with state.proxy() as data:
        data["name"] = message.text
        # Сохраняем имя пользователя в таблице users
        db.query("UPDATE users SET name = ? WHERE cid = ?", (message.text, message.chat.id))

        if "address" in data.keys():
            await confirm(message)
            await CheckoutState.confirm.set()
        else:
            await CheckoutState.next()
            await message.answer('Укажите свой адрес места жительства.', reply_markup=back_markup())

@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.address)
async def process_address_back(message: Message, state: FSMContext):

    async with state.proxy() as data:

        await message.answer('Изменить имя с <b>' + data['name'] + '</b>?',
                             reply_markup=back_markup())

    await CheckoutState.name.set()


@dp.message_handler(IsUser(), state=CheckoutState.address)
async def process_address(message: Message, state: FSMContext):

    async with state.proxy() as data:
        data['address'] = message.text

    await confirm(message)
    await CheckoutState.next()


async def confirm(message):

    await message.answer('Убедитесь, что все правильно оформлено и подтвердите заказ.',
                         reply_markup=confirm_markup())


@dp.message_handler(IsUser(), lambda message: message.text not in [confirm_message, back_message], state=CheckoutState.confirm)
async def process_confirm_invalid(message: Message):
    await message.reply('Такого варианта не было.')


@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.confirm)
async def process_confirm(message: Message, state: FSMContext):

    await CheckoutState.address.set()

    async with state.proxy() as data:
        await message.answer('Изменить адрес с <b>' + data['address'] + '</b>?',
                             reply_markup=back_markup())
##Разделение кода выше писали НЕ МЫ ниже писали МЫ
#Подтверждени и создание заказа в таблицу orders 
@dp.message_handler(IsUser(), text=confirm_message, state=CheckoutState.confirm)
async def process_confirm(message: Message, state: FSMContext):
    enough_money = True  # enough money on the balance sheet
    markup = ReplyKeyboardRemove()

    if enough_money:
        logging.info('Deal was made.')

        cid = message.chat.id

        # Получаем данные Имя и Адрес из таблицы users для данного пользователя
        user_data = db.fetchone('SELECT name, address FROM users WHERE cid=?', (cid,))

        if not user_data:
            await message.answer('Произошла ошибка при получении данных пользователя. Пожалуйста, попробуйте снова.', reply_markup=markup)
            await state.finish()
            return

        name, address = user_data

        products = [idx + '=' + str(quantity)
                    for idx, quantity in db.fetchall('''SELECT idx, quantity FROM cart WHERE cid=?''', (cid,))]  # idx=quantity

        db.query('INSERT INTO orders VALUES (?, ?, ?, ?)', (cid, name, address, ' '.join(products)))
        db.query('DELETE FROM cart WHERE cid=?', (cid,))

        await message.answer('Ок! Ваш заказ уже в пути 🚀\nИмя: <b>' + name + '</b>\nАдрес: <b>' + address + '</b>', reply_markup=markup)
    else:
        await message.answer('У вас недостаточно денег на счете. Пополните баланс!', reply_markup=markup)

    await state.finish()
