import logging
from aiogram.dispatcher import FSMContext
from aiogram import types
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
import requests
from concurrent.futures import ThreadPoolExecutor
import asyncio
import aiohttp

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

@dp.message_handler(IsUser(), state=CheckoutState.check_cart)
async def process_check_cart_all_right(message: Message, state: FSMContext):
    user_data = db.fetchone("SELECT name FROM users WHERE cid=?", (message.chat.id,))
    if not user_data or not user_data[0]:  # Если имя отсутствует в базе данных
        await CheckoutState.name.set()
        await message.answer('Укажите свое имя.', reply_markup=back_markup())
    else:
        await CheckoutState.mobile.set()  # Если имя есть, переходим к следующему этапу - запросу номера телефона
        await message.answer('Укажите свой номер телефона или поделитесь контактом.', reply_markup=contact_markup())

@dp.message_handler(IsUser(), state=CheckoutState.name)
async def process_name(message: Message, state: FSMContext):
    db.query("UPDATE users SET name = ? WHERE cid = ?", (message.text, message.chat.id))
    await CheckoutState.mobile.set()
    await message.answer('Укажите свой номер телефона или поделитесь контактом.', reply_markup=contact_markup())

@dp.message_handler(IsUser(), content_types=["text", "contact"], state=CheckoutState.mobile)
async def process_mobile(message: Message, state: FSMContext):
    if message.content_type == "contact":
        mobile = message.contact.phone_number
    else:
        mobile = message.text

    db.query("UPDATE users SET mobile = ? WHERE cid = ?", (mobile, message.chat.id))
    await CheckoutState.address.set()
    await message.answer('Пожалуйста, отправьте вашу геолокацию или напишите и отправьте адрес.', reply_markup=location_markup())

@dp.message_handler(IsUser(), content_types=["text", "location"], state=CheckoutState.address)
async def process_address(message: Message, state: FSMContext):
    if message.content_type == "location":
        user_location = message.location
        latitude, longitude = user_location.latitude, user_location.longitude
        address = await get_address_from_coordinates(latitude, longitude)
    else:
        address = message.text

    db.query("UPDATE users SET address = ? WHERE cid = ?", (address, message.chat.id))
    await CheckoutState.comment.set()
    await message.answer('Напишите комментарий (этаж, квартира, домофон) или напишите, если нет комментария для доставки.')

@dp.message_handler(IsUser(), state=CheckoutState.comment)
async def process_comment(message: Message, state: FSMContext):
    db.query("UPDATE users SET comment = ? WHERE cid = ?", (message.text, message.chat.id))
    await message.answer('Спасибо! Ваш заказ оформлен.', reply_markup=ReplyKeyboardRemove())
    await state.finish()


async def get_address_from_coordinates(latitude, longitude, api_key):
    logging.info(f"Inside get_address_from_coordinates with lat: {latitude}, lon: {longitude}")

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://geocode-maps.yandex.ru/1.x/?apikey=8a595e00-3f23-4aae-84a0-a527f9219344&geocode={longitude},{latitude}&format=json"
            async with session.get(url) as response:
                response.raise_for_status()  # Проверяем статус ответа
                data = await response.json()

                logging.info(f"Received data from Yandex Maps API: {data}")

                # Ваш код для извлечения адреса из данных API
                address = None
                try:
                    # Получаем первый геообъект из коллекции
                    geo_object = data['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']
                    # Извлекаем полный адрес из геообъекта
                    address = geo_object['metaDataProperty']['GeocoderMetaData']['Address']['formatted']
                except KeyError:
                    logging.error("Failed to extract address from Yandex Maps API response")

                return address  # Здесь возвращайте адрес, который вы извлекли
                
    except aiohttp.ClientError as e:
        logging.error(f"Error while fetching data from Yandex Maps API: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return None


@dp.message_handler(IsUser(), content_types=["location"], state=CheckoutState.send_location_or_text)
async def process_user_location_from_button(message: Message, state: FSMContext):
    logging.info("Processing location from button")
    user_location = message.location
    latitude, longitude = user_location.latitude, user_location.longitude
    logging.info(f"About to fetch address for coordinates: lat={latitude}, lon={longitude}")

    logging.info("About to call get_address_from_coordinates")
    api_key = "8a595e00-3f23-4aae-84a0-a527f9219344"
    address = await get_address_from_coordinates(latitude, longitude, api_key)
    if not address:
        await message.answer("Не удалось получить адрес по вашей геолокации. Попробуйте еще раз или введите адрес вручную.")
        return
    coordinates = f"{latitude}, {longitude}"
    try:
        db.query("UPDATE users SET address = ?, coordinates = ? WHERE cid = ?", (address, coordinates, message.chat.id))
        logging.info(f"Updated address and coordinates for cid: {message.chat.id} to address: {address} and coordinates: {coordinates}")
    except Exception as e:
        logging.error(f"Error while updating user data in DB: {e}")
    await confirm(message, state)
    await CheckoutState.confirm.set()
    async with state.proxy() as data:
        data["address"], data["coordinates"] = address, coordinates


##Разделение кода выше писали мы ниже писали не мы 

@dp.message_handler(IsUser(), state=CheckoutState.name)
async def process_name(message: Message, state: FSMContext):
    async with state.proxy() as data:
        data["name"] = message.text
        # Сохраняем имя пользователя в таблице users
        db.query("UPDATE users SET name = ? WHERE cid = ?", (message.text, message.chat.id))

    # Переходим к следующему этапу - проверке адреса
    await check_address(data, message)

@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.address)
async def process_address_back(message: Message, state: FSMContext):

    async with state.proxy() as data:

        await message.answer('Изменить имя с <b>' + data['name'] + '</b>?',
                             reply_markup=back_markup())

    await CheckoutState.name.set()


async def confirm(message, state: FSMContext):
    # Получение данных о пользователе из базы данных
    user_data = db.fetchone('SELECT address, name, mobile, comment FROM users WHERE cid=?', (message.chat.id,))
    if user_data:
        address, name, mobile, comment = user_data
    else:
        address, name, mobile, comment = "Не указан", "Не указан", "Не указан", "Нет"

    # Получение данных о товарах из корзины
    cart_data = db.fetchall('SELECT * FROM cart WHERE cid=?', (message.chat.id,))

    cart_details = []
    total_price = 0
    for _, idx, quantity in cart_data:
        product = db.fetchone('SELECT * FROM products WHERE idx=?', (idx,))
        if product:
            _, title, _, _, price, _ = product
            cart_details.append(f"{title} - {quantity}шт. = {price * quantity}₽")
            total_price += price * quantity

    # Собираем все данные в одно сообщение
    response_message = (
        "Подтверждение заказа:\n\n"
        "Товары:\n" + '\n'.join(cart_details) + f"\n\nОбщая сумма: {total_price}₽\n"
        f"Адрес: {address}\n"
        f"Имя: {name}\n"
        f"Телефон: {mobile}\n"
        f"Комментарий: {comment}\n\n"
        "Убедитесь, что все правильно оформлено и подтвердите заказ."
    )

    await message.answer(response_message, reply_markup=confirm_markup())


#@dp.message_handler(IsUser(), lambda message: message.text not in [confirm_message, back_message], state=CheckoutState.confirm)
#async def process_confirm_invalid(message: Message):
#    await message.reply('Такого варианта не было.')


##Разделение кода выше писали НЕ МЫ ниже писали МЫ


#Изменение адреса
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
