from aiogram.dispatcher.filters.state import StatesGroup, State

class CheckoutState(StatesGroup):
    check_cart = State()
    name = State()
    address = State()
    confirm = State()
    send_location = State()
    choose_address = State()  # Убедитесь, что это состояние присутствует
    send_location_or_text = State()
    send_contact_or_text = State()  # Для сохранения мобильного номера из сообщения или контакта
    confirm_mobile = State()  # Для подтверждения или изменения мобильного номера
