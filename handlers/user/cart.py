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

async def check_address(data, message, state):
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
        await CheckoutState.confirm.set()

async def check_mobile(data, message, state):
    if not data["mobile"]:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        phone_button = KeyboardButton(text="Отправить контакт", request_contact=True)
        markup.add(phone_button)
        await message.answer("Пожалуйста, укажите свой номер телефона или поделитесь контактом.", reply_markup=markup)
        await CheckoutState.send_contact_or_text.set()
    else:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        markup.add("Номер верный")
        markup.add("Изменить номер")
        await message.answer(f'Подтвердите номер для связи с курьером: {data["mobile"]}\nЧтобы изменить номер, выберите "Изменить номер".', reply_markup=markup)
        await confirm(message, state)

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
            if not await check_address(data, message, state):
                return
            if not await check_mobile(data, message, state):
                return
        else:
            await CheckoutState.name.set()
            await message.answer('Укажите свое имя.', reply_markup=back_markup())

@dp.message_handler(IsUser(), state=CheckoutState.name)
async def process_name_for_new_user(message: Message, state: FSMContext):
    async with state.proxy() as data:
        data["name"] = message.text
        # Сохраняем имя пользователя в таблице users
        db.query("UPDATE users SET name = ? WHERE cid = ?", (message.text, message.chat.id))
        await check_mobile(data, message, state)  # Добавлен запрос на номер телефона после указания имени

# Обработчик для сохранения мобильного номера из текстового сообщения
@dp.message_handler(IsUser(), content_types=["text"], state=FSMContext)
async def process_user_mobile_from_text(message: Message, state: FSMContext):
    async with state.proxy() as data:
        mobile = message.text
        db.query("UPDATE users SET mobile = ? WHERE cid = ?", (mobile, message.chat.id))
        await check_address(data, message, state)
        await CheckoutState.confirm.set()

# Обработчик для сохранения мобильного номера из контакта
@dp.message_handler(IsUser(), content_types=["contact"], state=FSMContext)
async def process_user_mobile_from_contact(message: Message, state: FSMContext):
    async with state.proxy() as data:
        contact = message.contact
        mobile = contact.phone_number
        db.query("UPDATE users SET mobile = ? WHERE cid = ?", (mobile, message.chat.id))
        await check_address(data, message, state)
        await CheckoutState.confirm.set()

# Обработчик для подтверждения или изменения мобильного номера
@dp.message_handler(IsUser(), text=["Номер верный", "Отправить контакт"], state=CheckoutState.confirm_mobile)
async def process_confirm_or_change_mobile(message: Message, state: FSMContext):
    if message.text == "Телефон верный":
        await confirm(message, state)
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
    async with state.proxy() as data:
        data["address"] = address
        await check_mobile(data, message, state)  # Проверяем номер телефона

@dp.message_handler(IsUser(), text="Отправить на этот", state=CheckoutState.choose_address)
async def process_use_same_address(message: Message, state: FSMContext):
    await confirm(message, state)
    await CheckoutState.confirm.set()

@dp.message_handler(IsUser(), text="Отправить новый адрес", state=CheckoutState.choose_address)
async def process_new_address(message: Message, state: FSMContext):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    location_button = KeyboardButton(text="Отправить локацию", request_location=True)
    markup.add(location_button)
    await message.answer("Пожалуйста, отправьте вашу геолокацию или напишите и отправьте адрес.", reply_markup=markup)
    await CheckoutState.send_location_or_text.set()  # Изменено состояние

@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.name)
async def process_name_back(message: Message, state: FSMContext):
    await CheckoutState.check_cart.set()
    await checkout(message, state)

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


@dp.message_handler(IsUser(), state=CheckoutState.address)
async def process_address(message: Message, state: FSMContext):

    async with state.proxy() as data:
        data['address'] = message.text


    await message.answer("Напишите комментарий (этаж, квартира, домофон) или напишите, если нет комментария для доставки.")
    await CheckoutState.comment.set()

@dp.message_handler(IsUser(), state=CheckoutState.comment)
async def process_comment(message: Message, state: FSMContext):

    async with state.proxy() as data:
        data['comment'] = message.text

    await confirm(message, state)
    await CheckoutState.next()


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
@dp.message_handler(IsUser(), state=CheckoutState.send_location_or_text, content_types=["text"])
async def process_user_new_address_text(message: Message, state: FSMContext):
    async with state.proxy() as data:
        data["address"] = message.text
        # Обновляем адрес в базе данных
        db.query("UPDATE users SET address = ? WHERE cid = ?", (message.text, message.chat.id))
    await confirm(message, state)
    await CheckoutState.confirm.set()

@dp.message_handler(IsUser(), state=CheckoutState.send_location_or_text, content_types=["location"])
async def process_user_new_address_location(message: Message, state: FSMContext):
    user_location = message.location
    latitude, longitude = user_location.latitude, user_location.longitude
    address = await get_address_from_coordinates(latitude, longitude)
    if address:
        async with state.proxy() as data:
            data["address"] = address
            data["coordinates"] = f"{latitude}, {longitude}"
            # Обновляем адрес и координаты в базе данных
            db.query("UPDATE users SET address = ?, coordinates = ? WHERE cid = ?", (address, coordinates, message.chat.id))
        await confirm(message, state)
        await CheckoutState.confirm.set()
    else:
        await message.answer("Не удалось получить адрес на основе геолокации. Пожалуйста, попробуйте еще раз или укажите адрес текстовым сообщением.")

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
