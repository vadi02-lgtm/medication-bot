import asyncio
import aiohttp
import sqlite3
import os
import ssl
from datetime import datetime, timedelta
from flask import Flask
import threading
import signal
import sys

print("🐱 БОТ-НАПОМИНАЛКА С КОТИКАМИ (TIMEZONE FIXED)")
print("=" * 50)

# Создаем Flask приложение для Railway
app = Flask(__name__)

@app.route('/')
def home():
    return "🐱 Medication Reminder Bot is running on Railway!"

@app.route('/health')
def health():
    return "✅ OK", 200

@app.route('/status')
def status():
    return {
        "status": "running",
        "bot": "Medication Reminder Bot",
        "timestamp": datetime.now().isoformat()
    }

class MedicationReminderBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.reminder_tasks = {}
        self.is_running = True
        
        # Инициализация базы данных с абсолютным путем для Railway
        self.db_path = os.path.join(os.getcwd(), 'reminder_bot.db')
        self.init_database()
        
    def init_database(self):
        """Создает базу данных для хранения настроек пользователей"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                is_active INTEGER DEFAULT 1,
                reminder_time TEXT DEFAULT '19:00 (22:00 ваше)',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
        print(f"✅ База данных инициализирована: {self.db_path}")
    
    def log(self, message):
        """Улучшенное логирование с timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    def create_ssl_context(self):
        """Создает SSL контекст для Railway"""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context
    
    async def make_request(self, method, data=None):
        """Оптимизированный запрос к Telegram API"""
        url = f"{self.base_url}/{method}"
        
        try:
            ssl_context = self.create_ssl_context()
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                if data:
                    # Для отправки фото используем form-data
                    if 'photo' in data and data['photo'].startswith('http'):
                        form_data = aiohttp.FormData()
                        for key, value in data.items():
                            form_data.add_field(key, value)
                        async with session.post(url, data=form_data, timeout=30) as response:
                            return await response.json()
                    else:
                        async with session.post(url, json=data, timeout=30) as response:
                            return await response.json()
                else:
                    async with session.get(url, timeout=30) as response:
                        return await response.json()
        except Exception as e:
            self.log(f"❌ Ошибка запроса: {e}")
            return None
    
    async def send_message(self, chat_id, text, reply_markup=None):
        """Отправляет сообщение пользователю"""
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        if reply_markup:
            data["reply_markup"] = reply_markup
            
        return await self.make_request("sendMessage", data)
    
    async def send_photo(self, chat_id, photo_url, caption=""):
        """Отправляет фото по URL с улучшенной обработкой ошибок"""
        try:
            data = {
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption
            }
            result = await self.make_request("sendPhoto", data)
            
            if result and result.get('ok'):
                self.log(f"✅ Фото отправлено пользователю {chat_id}")
                return True
            else:
                self.log(f"❌ Ошибка отправки фото: {result}")
                # Фолбэк - отправляем сообщение с ссылкой
                fallback_msg = f"{caption}\n\n📸 Ссылка на котика: {photo_url}"
                await self.send_message(chat_id, fallback_msg)
                return False
                
        except Exception as e:
            self.log(f"❌ Ошибка в send_photo: {e}")
            fallback_msg = f"{caption}\n\n📸 Ссылка на котика: {photo_url}"
            await self.send_message(chat_id, fallback_msg)
            return False
    
    async def get_updates(self):
        """Получает обновления от Telegram с улучшенным таймаутом"""
        url = f"{self.base_url}/getUpdates?offset={self.last_update_id + 1}&timeout=25"
        
        try:
            ssl_context = self.create_ssl_context()
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("result", [])
                    else:
                        self.log(f"❌ Статус ответа: {response.status}")
                        return []
        except asyncio.TimeoutError:
            self.log("⏰ Таймаут получения обновлений")
            return []
        except Exception as e:
            self.log(f"❌ Ошибка получения обновлений: {e}")
            return []
    
    def get_user_settings(self, user_id):
        """Получает настройки пользователя"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", 
            (user_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return {
                'user_id': result[0],
                'chat_id': result[1],
                'is_active': bool(result[2]),
                'reminder_time': result[3]
            }
        return None
    
    def save_user_settings(self, user_id, chat_id, is_active=True, reminder_time="19:00 (22:00 ваше)"):
        """Сохраняет настройки пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_settings 
            (user_id, chat_id, is_active, reminder_time) 
            VALUES (?, ?, ?, ?)
        ''', (user_id, chat_id, int(is_active), reminder_time))
        
        self.conn.commit()
        self.log(f"💾 Сохранены настройки для пользователя {user_id}")
    
    async def get_random_cat_image(self):
        """Получает случайное фото котика с улучшенной обработкой ошибок"""
        cat_apis = [
            "https://api.thecatapi.com/v1/images/search",
            "https://cataas.com/cat?json=true"
        ]
        
        for api_url in cat_apis:
            try:
                self.log(f"🔄 Пробуем получить котика из {api_url}")
                ssl_context = self.create_ssl_context()
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(api_url, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            if "thecatapi.com" in api_url:
                                image_url = data[0].get('url', '')
                                self.log(f"✅ Получен котик от TheCatAPI")
                                return image_url
                            elif "cataas.com" in api_url:
                                image_url = f"https://cataas.com{data.get('url', '')}"
                                self.log(f"✅ Получен котик от Cataas")
                                return image_url
                        else:
                            self.log(f"❌ API {api_url} вернул статус {response.status}")
                            
            except Exception as e:
                self.log(f"❌ Ошибка получения котика из {api_url}: {e}")
                continue
        
        # Фолбэк - статичная картинка
        fallback_url = "https://cataas.com/cat"
        self.log(f"🔄 Используем фолбэк котика")
        return fallback_url
    
    def create_main_keyboard(self):
        """Создает основную клавиатуру"""
        return {
            "keyboard": [
                ["✅ Включить напоминания", "❌ Выключить напоминания"],
                ["⚙️ Настроить время", "📊 Статус"],
                ["🐱 Получить котика сейчас", "ℹ️ Помощь"]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": False
        }
    
    def create_time_keyboard(self):
        """Создает клавиатуру для выбора времени с учетом разницы +3 часа"""
        times = [
            ["19:00 (22:00 ваше)", "20:00 (23:00 ваше)"],
            ["18:00 (21:00 ваше)", "17:00 (20:00 ваше)"],
            ["16:00 (19:00 ваше)", "15:00 (18:00 ваше)"],
            ["Назад"]
        ]
        
        return {
            "keyboard": times,
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
    
    async def send_reminder(self, user_id, chat_id):
        """Отправляет напоминание с котиком"""
        try:
            # Получаем случайного котика
            cat_url = await self.get_random_cat_image()
            
            # Отправляем напоминание
            message = (
                "⏰ <b>Время выпить таблетки!</b> 💊\n\n"
                "Не забудьте принять лекарство! 🏥\n"
                "А чтобы поднять настроение - вот вам котик! 🐱"
            )
            
            await self.send_message(chat_id, message)
            await self.send_photo(chat_id, cat_url, "😻 Держите вашего терапевтического котика!")
            
            self.log(f"📨 Отправлено напоминание пользователю {user_id}")
            
        except Exception as e:
            self.log(f"❌ Ошибка отправки напоминания: {e}")
    
    async def start_reminder_for_user(self, user_id, chat_id, reminder_time="19:00 (22:00 ваше)"):
        """Запускает ежедневное напоминание для пользователя"""
        if user_id in self.reminder_tasks:
            self.reminder_tasks[user_id].cancel()
        
        async def daily_reminder():
            while self.is_running:
                try:
                    # Текущее время на сервере (UTC+3)
                    now = datetime.now()
                    
                    # Извлекаем только время из текста (например "19:00" из "19:00 (22:00 ваше)")
                    server_time_str = reminder_time.split(' ')[0]
                    target_time = datetime.strptime(server_time_str, "%H:%M").time()
                    
                    # Вычисляем время до следующего напоминания
                    target_datetime = datetime.combine(now.date(), target_time)
                    if now.time() > target_time:
                        target_datetime += timedelta(days=1)
                    
                    wait_seconds = (target_datetime - now).total_seconds()
                    
                    # Вычисляем пользовательское время для логов
                    server_time = datetime.strptime(server_time_str, "%H:%M")
                    user_time = server_time + timedelta(hours=3)
                    user_time_str = user_time.strftime("%H:%M")
                    
                    self.log(f"⏰ Пользователь {user_id}: ждем {wait_seconds:.0f} сек до {server_time_str} (сервер) = {user_time_str} (ваше время)")
                    
                    # Ждем до времени напоминания с проверкой running
                    wait_intervals = max(1, int(wait_seconds / 60))
                    for _ in range(wait_intervals):
                        if not self.is_running:
                            return
                        await asyncio.sleep(60)
                    
                    # Проверяем, что напоминание все еще активно
                    settings = self.get_user_settings(user_id)
                    if settings and settings['is_active'] and self.is_running:
                        await self.send_reminder(user_id, chat_id)
                    
                    # Короткая пауза перед следующим циклом
                    await asyncio.sleep(10)
                    
                except asyncio.CancelledError:
                    self.log(f"🛑 Напоминание отменено для пользователя {user_id}")
                    break
                except Exception as e:
                    self.log(f"❌ Ошибка в напоминании: {e}")
                    await asyncio.sleep(3600)  # Ждем час при ошибке
        
        task = asyncio.create_task(daily_reminder())
        self.reminder_tasks[user_id] = task
        
        # Вычисляем пользовательское время для лога
        server_time = datetime.strptime(reminder_time.split(' ')[0], "%H:%M")
        user_time = server_time + timedelta(hours=3)
        user_time_str = user_time.strftime("%H:%M")
        
        self.log(f"✅ Запущено напоминание для {user_id} в {user_time_str} (по вашему времени)")
    
    async def stop_reminder_for_user(self, user_id):
        """Останавливает напоминание для пользователя"""
        if user_id in self.reminder_tasks:
            self.reminder_tasks[user_id].cancel()
            del self.reminder_tasks[user_id]
            self.log(f"🛑 Остановлено напоминание для пользователя {user_id}")
    
    async def process_message(self, message):
        """Обрабатывает входящие сообщения"""
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        text = message.get("text", "")
        
        self.log(f"📨 Сообщение от {user_id}: {text}")
        
        # Получаем или создаем настройки пользователя
        settings = self.get_user_settings(user_id)
        if not settings:
            self.save_user_settings(user_id, chat_id)
            settings = self.get_user_settings(user_id)
        
        if text == "/start" or text == "ℹ️ Помощь":
            response = (
                "🐱 <b>Бот-напоминалка с котиками</b> 💊\n\n"
                "Я буду напоминать вам выпить таблетки каждый день в указанное время "
                "и радовать фотографиями котиков! 😻\n\n"
                "<b>Внимание:</b> Сервер находится в UTC+3, время автоматически корректируется.\n\n"
                "<b>Команды:</b>\n"
                "✅ Включить напоминания - запустить ежедневные напоминания\n"
                "❌ Выключить напоминания - остановить напоминания\n"
                "⚙️ Настроить время - изменить время напоминания\n"
                "📊 Статус - посмотреть текущие настройки\n"
                "🐱 Получить котика сейчас - мгновенная доза котикотерапии\n\n"
                "Для начала нажмите «✅ Включить напоминания»!"
            )
            await self.send_message(chat_id, response, self.create_main_keyboard())
            
        elif text == "✅ Включить напоминания":
            self.save_user_settings(user_id, chat_id, is_active=True)
            await self.start_reminder_for_user(user_id, chat_id, settings['reminder_time'])
            
            # Вычисляем пользовательское время для отображения
            server_time = datetime.strptime(settings['reminder_time'].split(' ')[0], "%H:%M")
            user_time = server_time + timedelta(hours=3)
            user_time_str = user_time.strftime("%H:%M")
            
            response = (
                f"✅ <b>Напоминания включены!</b>\n\n"
                f"Я буду напоминать вам каждый день в <b>{user_time_str}</b> (по вашему времени)\n"
                f"Не забудьте выпить таблетки! 💊"
            )
            await self.send_message(chat_id, response, self.create_main_keyboard())
            
        elif text == "❌ Выключить напоминания":
            self.save_user_settings(user_id, chat_id, is_active=False)
            await self.stop_reminder_for_user(user_id)
            
            response = "❌ <b>Напоминания выключены</b>\nВы всегда можете включить их снова!"
            await self.send_message(chat_id, response, self.create_main_keyboard())
            
        elif text == "⚙️ Настроить время":
            response = "🕐 Выберите время для ежедневного напоминания (указано ваше местное время):"
            await self.send_message(chat_id, response, self.create_time_keyboard())
            
        elif text in ["19:00 (22:00 ваше)", "20:00 (23:00 ваше)", "18:00 (21:00 ваше)", "17:00 (20:00 ваше)", "16:00 (19:00 ваше)", "15:00 (18:00 ваше)"]:
            self.save_user_settings(user_id, chat_id, reminder_time=text)
            
            # Перезапускаем напоминание с новым временем
            if settings['is_active']:
                await self.start_reminder_for_user(user_id, chat_id, text)
            
            # Извлекаем пользовательское время для отображения
            user_time_str = text.split(' ')[1].strip('()')
            response = f"🕐 <b>Время установлено!</b>\nНапоминания будут в <b>{user_time_str}</b> (по вашему времени)"
            await self.send_message(chat_id, response, self.create_main_keyboard())
            
        elif text == "Назад":
            await self.send_message(chat_id, "Возвращаемся в главное меню:", self.create_main_keyboard())
            
        elif text == "📊 Статус":
            status = "🟢 ВКЛЮЧЕНЫ" if settings['is_active'] else "🔴 ВЫКЛЮЧЕНЫ"
            
            # Вычисляем пользовательское время для отображения
            server_time = datetime.strptime(settings['reminder_time'].split(' ')[0], "%H:%M")
            user_time = server_time + timedelta(hours=3)
            user_time_str = user_time.strftime("%H:%M")
            
            response = (
                f"📊 <b>Текущие настройки:</b>\n\n"
                f"• Напоминания: <b>{status}</b>\n"
                f"• Время: <b>{user_time_str}</b> (по вашему времени)\n"
                f"• Следующее напоминание: <b>сегодня в {user_time_str}</b>"
            )
            await self.send_message(chat_id, response, self.create_main_keyboard())
            
        elif text == "🐱 Получить котика сейчас":
            try:
                await self.send_message(chat_id, "🔄 Ищу котика для вас...")
                cat_url = await self.get_random_cat_image()
                self.log(f"🐱 Отправка котика пользователю {user_id}")
                success = await self.send_photo(chat_id, cat_url, "😻 Ваш внеочередной котик!")
                if not success:
                    await self.send_message(chat_id, "❌ Не удалось загрузить изображение котика, но вот ссылка выше!")
            except Exception as e:
                self.log(f"❌ Ошибка получения котика: {e}")
                await self.send_message(chat_id, "❌ Не удалось получить котика, попробуйте позже")
                
        else:
            response = "🤔 Не понимаю команду. Используйте кнопки ниже или /start для помощи"
            await self.send_message(chat_id, response, self.create_main_keyboard())
    
    async def restore_reminders(self):
        """Восстанавливает напоминания при запуске бота"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id, chat_id, reminder_time FROM user_settings WHERE is_active = 1")
        
        active_users = cursor.fetchall()
        
        for user_id, chat_id, reminder_time in active_users:
            await self.start_reminder_for_user(user_id, chat_id, reminder_time)
            
            # Вычисляем пользовательское время для лога
            server_time = datetime.strptime(reminder_time.split(' ')[0], "%H:%M")
            user_time = server_time + timedelta(hours=3)
            user_time_str = user_time.strftime("%H:%M")
            
            self.log(f"♻️ Восстановлено напоминание для {user_id} в {user_time_str} (по вашему времени)")
    
    async def run_bot(self):
        """Главный цикл бота"""
        self.log("🔄 Запуск бота-напоминалки...")
        
        # Тест подключения
        test = await self.make_request("getMe")
        if test and test.get("ok"):
            self.log("✅ Подключение к Telegram API успешно!")
            bot_info = test["result"]
            self.log(f"🤖 Бот: @{bot_info.get('username', 'N/A')} ({bot_info.get('first_name', 'N/A')})")
        else:
            self.log("❌ Ошибка подключения. Проверьте токен.")
            return
        
        # Восстанавливаем активные напоминания
        await self.restore_reminders()
        
        self.log("🎯 Бот готов к работе!")
        self.log("💊 Напоминания восстановлены для активных пользователей")
        
        # Главный цикл с проверкой флага running
        while self.is_running:
            try:
                updates = await self.get_updates()
                
                for update in updates:
                    if not self.is_running:
                        break
                    self.last_update_id = update["update_id"]
                    if "message" in update:
                        await self.process_message(update["message"])
                
                await asyncio.sleep(1)
                
            except Exception as e:
                self.log(f"💥 Ошибка в главном цикле: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        """Корректная остановка бота"""
        self.log("🛑 Останавливаем бота...")
        self.is_running = False
        
        # Отменяем все задачи напоминаний
        for user_id, task in list(self.reminder_tasks.items()):
            task.cancel()
        self.reminder_tasks.clear()
        
        # Закрываем соединение с БД
        if hasattr(self, 'conn'):
            self.conn.close()
        
        self.log("✅ Бот остановлен")

# Глобальные переменные
bot_instance = None
bot_task = None

def get_token():
    """Получает токен бота из переменных окружения Railway"""
    token = os.environ.get('BOT_TOKEN')
    
    if token:
        print("✅ Токен получен из переменных окружения Railway")
        return token
    
    # Резервный вариант - для локального тестирования
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('BOT_TOKEN='):
                    found_token = line.strip().split('=', 1)[1]
                    print("✅ Токен получен из файла .env")
                    return found_token
    except:
        pass
    
    print("❌ ТОКЕН БОТА НЕ НАЙДЕН!")
    print("ℹ️ Добавьте переменную BOT_TOKEN в настройках Railway")
    return None

async def start_bot():
    """Запускает бота в асинхронном режиме"""
    global bot_instance
    
    token = get_token()
    if not token:
        print("❌ Не удалось получить токен бота.")
        return
    
    bot_instance = MedicationReminderBot(token)
    await bot_instance.run_bot()

async def stop_bot():
    """Останавливает бота"""
    global bot_instance
    if bot_instance:
        await bot_instance.stop()

def signal_handler(signum, frame):
    """Обработчик сигналов для корректной остановки"""
    print(f"\n🛑 Получен сигнал {signum}, останавливаем бота...")
    asyncio.create_task(stop_bot())
    sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def run_flask_app():
    """Запускает Flask приложение"""
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Запускаем Flask сервер на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

async def main():
    """Основная функция запуска"""
    print("=" * 50)
    print("🐱 TELEGRAM БОТ-НАПОМИНАЛКА (TIMEZONE FIXED)")
    print("💊 Ежедневные напоминания + котики!")
    print("⏰ Время автоматически корректируется (UTC+3)")
    print("=" * 50)
    
    # Запускаем бота в фоновой задаче
    bot_task = asyncio.create_task(start_bot())
    
    try:
        # Ждем завершения задачи бота (никогда не завершится в нормальном режиме)
        await bot_task
    except asyncio.CancelledError:
        print("🛑 Задача бота отменена")
    except Exception as e:
        print(f"💥 Критическая ошибка: {e}")

if __name__ == "__main__":
    # Для Railway запускаем Flask + бота в отдельных потоках
    import threading
    
    # Запускаем бота в отдельном потоке
    def run_async_bot():
        asyncio.run(main())
    
    bot_thread = threading.Thread(target=run_async_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask в основном потоке
    run_flask_app()
