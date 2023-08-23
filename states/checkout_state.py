from aiogram.dispatcher.filters.state import StatesGroup, State

class CheckoutState(StatesGroup):
    check_cart = State()
    name = State()
    address = State()
    confirm = State()
    send_location = State()
    choose_address = State()  # Убедитесь, что это состояние присутствует
