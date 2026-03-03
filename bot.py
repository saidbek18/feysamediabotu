import telebot
from telebot import types
import sqlite3
import logging
import time
from flask import Flask
import threading
# ----------------- 1. BOT SOZLAMALARI VA DB SETUP -----------------
API_TOKEN = '7966505221:AAHEUj82be8yTNnmfKhbpTz9CqiSR75SAx4' # O'zingizning haqiqiy TOKENINGIZNI KIRITING
DB_NAME = 'bot.db'

# --- ADMINLAR VA KANALLAR ---
ADMINS = [8165064673] # Bosh admin ID'si (Bu joyga o'z ID'ingizni kiriting)
CHANNELS = [
    '@tarjimakinolar_bizda',  # Haqiqiy kanal username'laringizni yozing!
    # '@kanal_username_2'
]
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot ishlayapti!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()
# Logging sozlamalari
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Bot obyektini yaratish
bot = telebot.TeleBot(API_TOKEN)

# Holatlar (FSM o'rniga) va ma'lumotlarni saqlash uchun lug'atlar
user_states = {} # {chat_id: 'state_name'}
user_data = {}   # {chat_id: {'code': '101', 'caption': 'matn', 'media_file_id': '...'}}

# ----------------- 2. MA'LUMOTLAR BAZASI FUNKSIYALARI (SQLite) -----------------

class Database:
    """SQLite bilan ishlash uchun sinf"""
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file, check_same_thread=False) 
        self.cursor = self.conn.cursor()
        self.setup()

    def setup(self):
        # Adminlar jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)
        """)

        # Kinolar jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS films (
                code TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                caption TEXT
            )
        """)

        # Drama jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS dramas (
                code TEXT PRIMARY KEY,
                caption TEXT,
                photo_id TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS drama_episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drama_code TEXT,
                episode_number INTEGER,
                file_id TEXT
            )
        """)

        # Multfilm jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS cartoons (
                code TEXT PRIMARY KEY,
                caption TEXT,
                photo_id TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS cartoon_episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cartoon_code TEXT,
                episode_number INTEGER,
                file_id TEXT
            )
        """)

        # Foydalanuvchilar jadvali (Statistika va Reklama uchun)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_blocked BOOLEAN DEFAULT 0,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()

        for admin_id in ADMINS:
            self.add_admin(admin_id)

    # --- USER AMALLARI ---
    def add_user(self, user_id):
        """Foydalanuvchini bazaga qo'shish yoki faolligini yangilash"""
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, is_blocked) VALUES (?, 0)", (user_id,))
        self.cursor.execute(
            "UPDATE users SET is_blocked = 0, last_active = DATETIME('now', 'localtime') WHERE user_id = ?",
            (user_id,)
        )
        self.conn.commit()

    def set_user_blocked(self, user_id, is_blocked):
        """Foydalanuvchining bloklanganlik holatini o'rnatish"""
        self.cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (is_blocked, user_id))
        self.conn.commit()

    def get_all_users_for_broadcast(self):
        """Reklama uchun bloklamagan barcha userlar ID'sini qaytaradi"""
        self.cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
        return [row[0] for row in self.cursor.fetchall()]

    # --- STATISTIKA AMALLARI ---
    def count_total_users(self):
        self.cursor.execute("SELECT COUNT(user_id) FROM users")
        return self.cursor.fetchone()[0]

    def count_blocked_users(self):
        self.cursor.execute("SELECT COUNT(user_id) FROM users WHERE is_blocked = 1")
        return self.cursor.fetchone()[0]

    def count_active_users(self):
        """Oxirgi 24 soatda faol bo'lganlarni hisoblash"""
        self.cursor.execute("""
            SELECT COUNT(user_id) FROM users 
            WHERE last_active >= DATETIME('now', '-1 day', 'localtime')
        """)
        return self.cursor.fetchone()[0]

    # --- FILM AMALLARI ---
    def add_film(self, code, file_id, caption):
        self.cursor.execute(
            "INSERT OR REPLACE INTO films (code, file_id, caption) VALUES (?, ?, ?)",
            (code, file_id, caption)
        )
        self.conn.commit()

    def get_film(self, code):
        self.cursor.execute("SELECT file_id, caption FROM films WHERE code = ?", (code,))
        row = self.cursor.fetchone()
        if row:
            return {'file_id': row[0], 'caption': row[1]}
        return None

    def delete_film(self, code):
        self.cursor.execute("DELETE FROM films WHERE code = ?", (code,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def search_films(self, query):
        """Kino kodiga yoki sarlavhasiga qarab kinolarni qidiradi."""
        query = f"%{query}%"
        self.cursor.execute(
            "SELECT code, caption FROM films WHERE code LIKE ? OR caption LIKE ? LIMIT 10",
            (query, query)
        )
        rows = self.cursor.fetchall()
        return [{'code': row[0], 'caption': row[1]} for row in rows]

    # --- DRAMA AMALLARI ---
    def add_drama(self, code, caption, photo_id):
        self.cursor.execute(
            "INSERT OR REPLACE INTO dramas (code, caption, photo_id) VALUES (?, ?, ?)",
            (code, caption, photo_id)
        )
        self.conn.commit()

    def get_drama(self, code):
        self.cursor.execute("SELECT caption, photo_id FROM dramas WHERE code = ?", (code,))
        row = self.cursor.fetchone()
        if row:
            return {'caption': row[0], 'photo_id': row[1]}
        return None

    def delete_drama(self, code):
        self.cursor.execute("DELETE FROM dramas WHERE code = ?", (code,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    # --- MULTFILM AMALLARI ---
    def add_cartoon(self, code, caption, photo_id):
        self.cursor.execute(
            "INSERT OR REPLACE INTO cartoons (code, caption, photo_id) VALUES (?, ?, ?)",
            (code, caption, photo_id)
        )
        self.conn.commit()

    def get_cartoon(self, code):
        self.cursor.execute("SELECT caption, photo_id FROM cartoons WHERE code = ?", (code,))
        row = self.cursor.fetchone()
        if row:
            return {'caption': row[0], 'photo_id': row[1]}
        return None

    def delete_cartoon(self, code):
        self.cursor.execute("DELETE FROM cartoons WHERE code = ?", (code,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    # --- ADMIN AMALLARI ---
    def add_admin(self, user_id):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_admin(self, user_id):
        self.cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def is_admin(self, user_id):
        self.cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None


# --- Database obyekti ---
db = Database(DB_NAME)

## ----------------- 3. YORDAMCHI FUNKSIYALAR VA KLAVIATURALAR -----------------
from telebot import types

# --- FOYDALANUVCHI KLAVIATURASI ---
def get_user_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("🎬 Kino qidirish"),
        types.KeyboardButton("🎭 Drama qidirish"),
        types.KeyboardButton("🧸 Multfilm qidirish"),
    )
    return keyboard

# --- SUPER ADMIN KLAVIATURASI ---
def get_super_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("🎬 Kino qo'shish"),
        types.KeyboardButton("🎭 Drama qo'shish"),
        types.KeyboardButton("🧸 Multfilm qo'shish"),
        types.KeyboardButton("🗑️ Kino o'chirish"),
        types.KeyboardButton("🗑️ Drama o'chirish"),
        types.KeyboardButton("🗑️ Multfilm o'chirish"),
        types.KeyboardButton("➕ Admin Qo'shish"),     # faqat bosh admin uchun ishlaydi
        types.KeyboardButton("➖ Admin O'chirish"),   # faqat bosh admin uchun ishlaydi
        types.KeyboardButton("📊 Statistika"),
        types.KeyboardButton("📢 Reklama"),
        types.KeyboardButton("❌ Bekor Qilish")
    )
    return keyboard

# ----------------- ODDIY ADMIN KLAVIATURA YANGILASH -----------------
def get_regular_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("🎬 Kino qo'shish"),
        types.KeyboardButton("🎭 Drama qo'shish"),
        types.KeyboardButton("🧸 Multfilm qo'shish"),
        types.KeyboardButton("🗑️ Kino o'chirish"),
        types.KeyboardButton("🗑️ Drama o'chirish"),        # qo'shildi
        types.KeyboardButton("🗑️ Multfilm o'chirish"),     # qo'shildi
        types.KeyboardButton("📊 Statistika"),
        types.KeyboardButton("📢 Reklama"),
        types.KeyboardButton("❌ Bekor Qilish")
    )
    return keyboard

# --- BEKOR QILISH KLAVIATURASI ---
def get_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("❌ Bekor Qilish"))
    return keyboard

# --- SUBSCRIPTION TEKSHIRISH ---
def check_subscription(user_id, channel_id):
    try:
        member = bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status not in ['left', 'kicked']
    except Exception as e:
        logging.error(f"Obunani tekshirishda xatolik ({channel_id}): {e}")
        return False

# --- ASOSIY MENYU FOYDALANUVCHI UCHUN ---
def send_main_menu(chat_id):
    bot.send_message(
        chat_id,
        "🎬 Botimizga xush kelibsiz! Kino yoki Drama/Multfilm kodini yuboring yoki quyidagi tugmalardan foydalaning:",
        reply_markup=get_user_keyboard()
    )

# --- QAYSI KLAVIATURA KELISHINI TANLASH ---
def get_current_keyboard(user_id):
    if db.is_admin(user_id):
        return get_super_admin_keyboard() if user_id == ADMINS[0] else get_regular_admin_keyboard()
    return get_user_keyboard()

# ----------------- 4. ASOSIY HANDLERLAR (/start, Obuna) -----------------

@bot.message_handler(commands=['start', 'admin'])
def send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # YANGI: Foydalanuvchini DBga qo'shish/faolligini yangilash
    db.add_user(user_id) 
    
    # Holatni tozalash
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)
    
    # Obunani tekshirish
    not_subscribed_channels = [ch for ch in CHANNELS if not check_subscription(user_id, ch)]

    if not_subscribed_channels:
        # --- Obuna shartlari bajarilmagan ---
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for channel_username in not_subscribed_channels:
            channel_link = f"https://t.me/{channel_username.strip('@')}"
            keyboard.add(types.InlineKeyboardButton(text=f"➕ {channel_username}", url=channel_link))
        keyboard.add(types.InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_subs"))
        bot.send_message(
            chat_id,
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:",
            reply_markup=keyboard
        )
    else:
        # --- Obuna shartlari bajarilgan ---
        if db.is_admin(user_id):
            keyboard = get_current_keyboard(user_id)
            bot.send_message(chat_id, "🛠️ Admin Panelga xush kelibsiz! Marhamat, kerakli amalni tanlang:", reply_markup=keyboard)
        else:
            send_main_menu(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "check_subs")
def check_subscription_callback(call):
    user_id = call.from_user.id
    not_subscribed_channels = [ch for ch in CHANNELS if not check_subscription(user_id, ch)]
            
    bot.answer_callback_query(call.id, "Obuna tekshirilmoqda...")

    if not_subscribed_channels:
        # ... (Qayta obuna tugmalari) ...
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for channel_username in not_subscribed_channels:
            channel_link = f"https://t.me/{channel_username.strip('@')}"
            keyboard.add(types.InlineKeyboardButton(text=f"➕ {channel_username}", url=channel_link))
        keyboard.add(types.InlineKeyboardButton(text="✅ Obunani qayta tekshirish", callback_data="check_subs"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Iltimos, avval barcha kanallarga obuna bo'ling:",
            reply_markup=keyboard
        )
    else:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        if db.is_admin(user_id):
            keyboard = get_current_keyboard(user_id)
            bot.send_message(call.message.chat.id, "✅ Obunangiz tekshirildi. Admin panelga xush kelibsiz!", reply_markup=keyboard)
        else:
            send_main_menu(call.message.chat.id)

# ----------------- 5.1. ADMIN PANEL - KINO QO'SHISH -----------------
@bot.message_handler(func=lambda message: message.text == "🎬 Kino qo'shish" and db.is_admin(message.from_user.id))
def admin_add_film_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'film_waiting_code'
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🎥 Kino uchun noyob **kod** kiriting:", reply_markup=get_cancel_keyboard())

# 1️⃣ Kod qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'film_waiting_code')
def admin_add_film_code(message):
    chat_id = message.chat.id
    film_code = message.text.strip()
    
    if db.get_film(film_code):
        bot.send_message(chat_id, "❌ Bu kod allaqachon mavjud, boshqa kod kiriting.")
        return

    user_data[chat_id]['code'] = film_code
    user_states[chat_id] = 'film_waiting_caption'
    bot.send_message(chat_id, f"📝 {film_code} kodiga tegishli **caption** yuboring:", reply_markup=get_cancel_keyboard())

# 2️⃣ Caption qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'film_waiting_caption')
def admin_add_film_caption(message):
    chat_id = message.chat.id
    user_data[chat_id]['caption'] = message.text
    user_states[chat_id] = 'film_waiting_parts'
    bot.send_message(chat_id, "🎬 Nechta qism mavjud? (Agar bitta bo‘lsa 1 deb yozing)", reply_markup=get_cancel_keyboard())

# 3️⃣ Qism sonini qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'film_waiting_parts')
def admin_add_film_parts(message):
    chat_id = message.chat.id
    try:
        parts_count = int(message.text.strip())
        if parts_count < 1:
            raise ValueError
    except ValueError:
        bot.send_message(chat_id, "❌ Iltimos, 1 yoki undan katta son kiriting.")
        return

    user_data[chat_id]['parts_count'] = parts_count
    user_data[chat_id]['current_part'] = 1
    user_states[chat_id] = 'film_waiting_video'
    bot.send_message(chat_id, f"🎬 1-qism videoni yuboring:", reply_markup=get_cancel_keyboard())

# 4️⃣ Har bir qism uchun video qabul qilish
@bot.message_handler(content_types=['video'], func=lambda message: user_states.get(message.chat.id) == 'film_waiting_video')
def admin_add_film_video(message):
    chat_id = message.chat.id
    data = user_data[chat_id]
    code = data['code']
    caption = data['caption']
    parts_count = data['parts_count']
    current_part = data['current_part']
    file_id = message.video.file_id

    if parts_count == 1:
        db.add_film(code, file_id, caption)
        bot.send_message(chat_id, f"✅ Kino qo‘shildi! Kod: {code}", reply_markup=get_current_keyboard(message.from_user.id))
    else:
        # Qism ma'lumotlarini saqlash
        db.cursor.execute(
            "INSERT INTO drama_episodes (drama_code, episode_number, file_id) VALUES (?, ?, ?)",
            (code, current_part, file_id)
        )
        db.conn.commit()

        if current_part < parts_count:
            user_data[chat_id]['current_part'] += 1
            bot.send_message(chat_id, f"🎬 {current_part+1}-qism videoni yuboring:", reply_markup=get_cancel_keyboard())
            return
        else:
            bot.send_message(chat_id, f"✅ Barcha qismlar qo‘shildi! Kod: {code}", reply_markup=get_current_keyboard(message.from_user.id))

    # Holatlarni tozalash
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)

# 5️⃣ Video o‘rniga noto‘g‘ri fayl yuborilsa
@bot.message_handler(content_types=['text', 'photo', 'document', 'audio', 'voice'], func=lambda message: user_states.get(message.chat.id) == 'film_waiting_video')
def admin_add_film_video_invalid(message):
    bot.send_message(message.chat.id, "❌ Iltimos, faqat video yuboring.")
    # ----------------- 5.2. ADMIN PANEL - DRAMA QO'SHISH -----------------
# ----------------- DRAMA QO'SHISH (ADMIN) -----------------
@bot.message_handler(func=lambda message: message.text == "🎭 Drama qo'shish" and db.is_admin(message.from_user.id))
def add_drama_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'drama_waiting_code'
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🎭 Drama uchun faqat RAQAMLI kod yuboring (masalan: 101)", reply_markup=get_cancel_keyboard())


# 1️⃣ Kodni qabul qilish (FAQAT SON)
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_code')
def add_drama_code(message):
    chat_id = message.chat.id
    code = message.text.strip()

    # ❌ Ortga qaytarish
    if code == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(message.from_user.id))
        return

    # ❌ Faqat son
    if not code.isdigit():
        bot.send_message(chat_id, "❌ Kod faqat raqam bo‘lishi kerak! Masalan: 101")
        return

    if db.get_drama(code):
        bot.send_message(chat_id, "❌ Bu kod allaqachon mavjud.")
        return

    user_data[chat_id]['code'] = code
    user_states[chat_id] = 'drama_waiting_caption'
    bot.send_message(chat_id, f"📝 Drama {code} uchun caption yuboring.", reply_markup=get_cancel_keyboard())


# 2️⃣ Caption qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_caption')
def add_drama_caption(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(message.from_user.id))
        return

    user_data[chat_id]['caption'] = message.text.strip()
    user_states[chat_id] = 'drama_waiting_photo'
    bot.send_message(chat_id, "🖼 Drama uchun rasm yuboring yoki skip yozing.", reply_markup=get_cancel_keyboard())


# 3️⃣ Rasm qabul qilish
@bot.message_handler(content_types=['photo','text'], func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_photo')
def add_drama_photo(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(message.from_user.id))
        return

    if message.text and message.text.lower() == 'skip':
        photo_id = None
    elif message.photo:
        photo_id = message.photo[-1].file_id
    else:
        bot.send_message(chat_id, "❌ Rasm yuboring yoki skip yozing.")
        return

    code = user_data[chat_id]['code']
    caption = user_data[chat_id]['caption']

    # 🔥 Dramani aniq saqlaymiz
    db.cursor.execute(
        "INSERT INTO dramas (code, caption, photo_id) VALUES (?, ?, ?)",
        (code, caption, photo_id)
    )
    db.conn.commit()

    user_states[chat_id] = 'drama_waiting_episodes'
    bot.send_message(chat_id, "🎬 Nechta qism qo‘shmoqchisiz?", reply_markup=get_cancel_keyboard())


# 4️⃣ Qism soni
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_episodes')
def add_drama_episodes_count(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(message.from_user.id))
        return

    try:
        count = int(message.text.strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(chat_id, "❌ Musbat son kiriting.")
        return

    user_data[chat_id]['episode_count'] = count
    user_data[chat_id]['current_episode'] = 1
    user_states[chat_id] = 'drama_waiting_episode_file'

    bot.send_message(chat_id, "🎬 1-qism video faylini yuboring:", reply_markup=get_cancel_keyboard())


# 5️⃣ Qism video saqlash (ISHLAYDIGAN)
@bot.message_handler(content_types=['video'], func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_episode_file')
def add_drama_episode_file(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(message.from_user.id))
        return

    if chat_id not in user_data:
        bot.send_message(chat_id, "❌ Xatolik. Qaytadan boshlang.")
        return

    code = user_data[chat_id]['code']
    current = user_data[chat_id]['current_episode']
    total = user_data[chat_id]['episode_count']
    file_id = message.video.file_id

    db.cursor.execute(
        "INSERT INTO drama_episodes (drama_code, episode_number, file_id) VALUES (?, ?, ?)",
        (code, current, file_id)
    )
    db.conn.commit()

    if current < total:
        user_data[chat_id]['current_episode'] += 1
        bot.send_message(chat_id, f"🎬 {current+1}-qism video faylini yuboring:", reply_markup=get_cancel_keyboard())
    else:
        bot.send_message(chat_id, f"✅ Drama {code} barcha qismlari qo‘shildi!",
                         reply_markup=get_current_keyboard(message.from_user.id))
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)


# Agar noto‘g‘ri fayl yuborilsa
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_episode_file')
def add_drama_episode_invalid(message):
    bot.send_message(message.chat.id, "❌ Iltimos, faqat video fayl yuboring.")
    # ----------------- 5.3. ADMIN PANEL - MULTFILM QO'SHISH -----------------
@bot.message_handler(func=lambda message: message.text == "🧸 Multfilm qo'shish" and db.is_admin(message.from_user.id))
def admin_add_cartoon_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'cartoon_waiting_code'
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🧸 Multfilm uchun noyob **kod** kiriting:", reply_markup=get_cancel_keyboard())

# 1️⃣ Kod qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'cartoon_waiting_code')
def admin_add_cartoon_code(message):
    chat_id = message.chat.id
    cartoon_code = message.text.strip()
    
    db.cursor.execute("SELECT code FROM cartoons WHERE code=?", (cartoon_code,))
    if db.cursor.fetchone():
        bot.send_message(chat_id, "❌ Bu kod allaqachon mavjud, boshqa kod kiriting.")
        return

    user_data[chat_id]['code'] = cartoon_code
    user_states[chat_id] = 'cartoon_waiting_caption'
    bot.send_message(chat_id, f"📝 {cartoon_code} kodiga tegishli **caption** yuboring:", reply_markup=get_cancel_keyboard())

# 2️⃣ Caption qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'cartoon_waiting_caption')
def admin_add_cartoon_caption(message):
    chat_id = message.chat.id
    user_data[chat_id]['caption'] = message.text
    user_states[chat_id] = 'cartoon_waiting_parts'
    bot.send_message(chat_id, "🎬 Nechta qism mavjud? (Agar bitta bo‘lsa 1 deb yozing)", reply_markup=get_cancel_keyboard())

# 3️⃣ Qism sonini qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'cartoon_waiting_parts')
def admin_add_cartoon_parts(message):
    chat_id = message.chat.id
    try:
        parts_count = int(message.text.strip())
        if parts_count < 1:
            raise ValueError
    except ValueError:
        bot.send_message(chat_id, "❌ Iltimos, 1 yoki undan katta son kiriting.")
        return

    user_data[chat_id]['parts_count'] = parts_count
    user_data[chat_id]['current_part'] = 1
    user_states[chat_id] = 'cartoon_waiting_video'
    bot.send_message(chat_id, f"🎬 1-qism videoni yuboring:", reply_markup=get_cancel_keyboard())

# 4️⃣ Har bir qism uchun video qabul qilish
@bot.message_handler(content_types=['video'], func=lambda message: user_states.get(message.chat.id) == 'cartoon_waiting_video')
def admin_add_cartoon_video(message):
    chat_id = message.chat.id
    data = user_data[chat_id]
    code = data['code']
    caption = data['caption']
    parts_count = data['parts_count']
    current_part = data['current_part']
    file_id = message.video.file_id

    # Qism ma'lumotlarini saqlash
    db.cursor.execute(
        "INSERT INTO cartoon_episodes (cartoon_code, episode_number, file_id) VALUES (?, ?, ?)",
        (code, current_part, file_id)
    )
    db.conn.commit()

    if current_part < parts_count:
        user_data[chat_id]['current_part'] += 1
        bot.send_message(chat_id, f"🎬 {current_part+1}-qism videoni yuboring:", reply_markup=get_cancel_keyboard())
    else:
        bot.send_message(chat_id, f"✅ Barcha qismlar qo‘shildi! Multfilm kod: {code}", reply_markup=get_current_keyboard(message.from_user.id))
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)

# 5️⃣ Video o‘rniga noto‘g‘ri fayl yuborilsa
@bot.message_handler(content_types=['text', 'photo', 'document', 'audio', 'voice'], func=lambda message: user_states.get(message.chat.id) == 'cartoon_waiting_video')
def admin_add_cartoon_video_invalid(message):
    bot.send_message(message.chat.id, "❌ Iltimos, faqat video yuboring.")

# ----------------- 6.1. KINO QIDIRISH HANDLERI -----------------
@bot.message_handler(func=lambda message: message.text == "🎬 Kino qidirish")
def movie_search_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'search_movie'
    bot.send_message(
        chat_id, 
        "🔍 Iltimos, qidiriladigan kinoning kodini yoki nomini yozing:", 
        reply_markup=get_cancel_keyboard()
    )

# Kino kodini qabul qilish va chiqarish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'search_movie')
def movie_search_execute(message):
    chat_id = message.chat.id
    query = message.text.strip()

    if query.lower() == '❌ bekor qilish':
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        return

    # Faqat kinolarni qidiradi
    film_data = db.get_film(query)

    if film_data:
        try:
            bot.send_video(
                chat_id, 
                video=film_data['file_id'], 
                caption=film_data['caption'], 
                reply_to_message_id=message.message_id
            )
        except Exception as e:
            bot.send_message(chat_id, "😔 Kino yuborishda xatolik yuz berdi.")
            logging.error(f"Kino yuborishda xatolik: {e}")
    else:
        bot.send_message(chat_id, "❌ Bu kod bo‘yicha kino topilmadi. Iltimos, tekshirib qayta yuboring.")

    # Holatni tozalash
    user_states.pop(chat_id, None)
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'search_drama')
def user_drama_search_query(message):
    chat_id = message.chat.id
    query = message.text.strip()

    # Bekor qilish
    if query == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        return

    # Faqat son qabul qilish
    if not query.isdigit():
        bot.send_message(chat_id, "❌ Iltimos, faqat raqamli kod kiriting.")
        return

    code_int = int(query)

    # Drama qidiruv
    db.cursor.execute(
        "SELECT code, caption, photo_id FROM dramas WHERE code = ?",
        (code_int,)
    )
    drama = db.cursor.fetchone()

    if not drama:
        bot.send_message(chat_id, "❌ Drama topilmadi. Kodni tekshiring.")
        return

    code, caption, photo_id = drama
    user_data[chat_id]['drama_code'] = code

    # Epizodlarni olish
    db.cursor.execute(
        "SELECT episode_number, file_id FROM drama_episodes WHERE drama_code=? ORDER BY episode_number",
        (code,)
    )
    episodes = db.cursor.fetchall()

    if not episodes:
        bot.send_message(chat_id, "❌ Bu dramada epizodlar topilmadi.")
        return

    # Inline tugmalar
    markup = types.InlineKeyboardMarkup(row_width=5)
    for ep in episodes[:10]:
        markup.add(types.InlineKeyboardButton(text=str(ep[0]), callback_data=f"drama_{code}_{ep[0]}"))

    if len(episodes) > 10:
        markup.add(types.InlineKeyboardButton(text="➡️ Keyingi", callback_data=f"drama_next_{code}_10"))

    markup.add(types.InlineKeyboardButton(text="❌ Bekor Qilish", callback_data="drama_cancel"))

    # Drama rasm + caption bilan yuboriladi
    bot.send_photo(chat_id, photo_id, caption=f"🎭 {caption}\nKod: {code}", reply_markup=markup)


# ----------------- DRAMA INLINE CALLBACK -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("drama_"))
def drama_callback(call):
    chat_id = call.message.chat.id
    data = call.data.split("_")

    # ===== BEKOR QILISH =====
    if data[1] == "cancel":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        bot.answer_callback_query(call.id)
        return

    # ===== KEYINGI QISMLAR =====
    if data[1] == "next":
        drama_code = data[2]
        offset = int(data[3])
        db.cursor.execute(
            "SELECT episode_number FROM drama_episodes WHERE drama_code=? ORDER BY episode_number LIMIT 10 OFFSET ?",
            (drama_code, offset)
        )
        episodes = db.cursor.fetchall()
        if episodes:
            keyboard = types.InlineKeyboardMarkup(row_width=5)
            for ep in episodes:
                keyboard.add(types.InlineKeyboardButton(
                    text=str(ep[0]),
                    callback_data=f"drama_{drama_code}_{ep[0]}"
                ))
            if len(episodes) == 10:
                keyboard.add(types.InlineKeyboardButton(
                    text="➡️ Keyingi",
                    callback_data=f"drama_next_{drama_code}_{offset+10}"
                ))
            keyboard.add(types.InlineKeyboardButton(
                text="❌ Bekor Qilish",
                callback_data="drama_cancel"
            ))
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)
        return

    # ===== EPIZODNI OCHISH =====
    drama_code = data[1]
    episode_number = int(data[2])
    db.cursor.execute(
        "SELECT file_id FROM drama_episodes WHERE drama_code=? AND episode_number=?",
        (drama_code, episode_number)
    )
    episode = db.cursor.fetchone()
    if episode:
        bot.send_video(
            chat_id, 
            episode[0], 
            caption=f"🎭 {drama_code} - {episode_number}-qism"
        )
        bot.answer_callback_query(call.id, f"{episode_number}-qism ochildi")
    else:
        bot.answer_callback_query(call.id, "❌ Qism topilmadi")
      # ----------------- MULTFILM QIDIRISH HANDLERI -----------------
from telebot import types

@bot.message_handler(func=lambda message: message.text == "🧸 Multfilm qidirish")
def cartoon_search_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'search_cartoon'
    bot.send_message(
        chat_id,
        "🔍 Iltimos, qidiriladigan multfilm kodini yoki nomini yozing:",
        reply_markup=get_cancel_keyboard()
    )

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'search_cartoon')
def cartoon_search_execute(message):
    chat_id = message.chat.id
    query = message.text.strip()

    if query.lower() in ['❌ bekor qilish', '/cancel']:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        return

    # ----------------- MULTFILM MA'LUMOTINI OLISH -----------------
    cur = db.conn.cursor()  # yangi cursor
    cur.execute(
        "SELECT code, caption, photo_id FROM cartoons WHERE LOWER(code) = ? OR LOWER(caption) LIKE ?",
        (query.lower(), f"%{query.lower()}%")
    )
    row = cur.fetchone()

    if not row:
        bot.send_message(chat_id, "❌ Bu kod yoki nom bo‘yicha multfilm topilmadi. Iltimos, qayta urinib ko‘ring.")
        cur.close()
        user_states.pop(chat_id, None)
        return

    cartoon_code, caption, photo_id = row
    cur.close()

    # ----------------- MULTFILM RASMI -----------------
    if photo_id:
        bot.send_photo(chat_id, photo=photo_id, caption=caption)

    # ----------------- QISMLARINI OLISH -----------------
    cur = db.conn.cursor()
    cur.execute(
        "SELECT episode_number, file_id FROM cartoon_episodes WHERE cartoon_code = ? ORDER BY episode_number ASC",
        (cartoon_code,)
    )
    episodes = cur.fetchall()
    cur.close()

    if episodes:
        keyboard = types.InlineKeyboardMarkup(row_width=5)
        for ep in episodes[:10]:  # birinchi 10 qism
            keyboard.add(types.InlineKeyboardButton(text=f"{ep[0]}-qism", callback_data=f"cartoon_{cartoon_code}_{ep[0]}"))

        if len(episodes) > 10:
            keyboard.add(types.InlineKeyboardButton(text="➡️ Keyingi", callback_data=f"cartoon_next_{cartoon_code}_10"))

        bot.send_message(chat_id, "🔹 Multfilm qismlarini tanlang:", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, "🔹 Bu multfilm hali qismlarga ega emas.")

    user_states.pop(chat_id, None)

# ----------------- MULTFILM QISM TUGMALARI CALLBACK -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("cartoon_"))
def cartoon_episode_callback(call):
    data = call.data.split("_")
    chat_id = call.message.chat.id

    if data[1] == 'next':
        cartoon_code = data[2]
        offset = int(data[3])

        cur = db.conn.cursor()
        cur.execute(
            "SELECT episode_number, file_id FROM cartoon_episodes WHERE cartoon_code = ? ORDER BY episode_number ASC LIMIT 10 OFFSET ?",
            (cartoon_code, offset)
        )
        episodes = cur.fetchall()
        cur.close()

        if episodes:
            keyboard = types.InlineKeyboardMarkup(row_width=5)
            for ep in episodes:
                keyboard.add(types.InlineKeyboardButton(text=f"{ep[0]}-qism", callback_data=f"cartoon_{cartoon_code}_{ep[0]}"))
            if len(episodes) == 10:
                keyboard.add(types.InlineKeyboardButton(text="➡️ Keyingi", callback_data=f"cartoon_next_{cartoon_code}_{offset+10}"))
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=keyboard)

        bot.answer_callback_query(call.id)

    else:
        cartoon_code = data[1]
        episode_number = int(data[2])

        cur = db.conn.cursor()
        cur.execute(
            "SELECT file_id FROM cartoon_episodes WHERE cartoon_code = ? AND episode_number = ?",
            (cartoon_code, episode_number)
        )
        ep_row = cur.fetchone()
        cur.close()

        if ep_row:
            bot.send_video(chat_id, ep_row[0], caption=f"{cartoon_code} - {episode_number}-qism")
            bot.answer_callback_query(call.id, f"{episode_number}-qism ochildi")
        else:
            bot.answer_callback_query(call.id, "❌ Qism topilmadi")
# ----------------- FOYDALANUVCHI QIDIRUV HANDLERLARI -----------------
@bot.message_handler(func=lambda message: message.text in ["🎬 Kino qidirish", "🎭 Drama qidirish", "🧸 Multfilm qidirish"])
def user_search_start(message):
    chat_id = message.chat.id
    text = message.text
    user_id = message.from_user.id

    db.add_user(user_id)  # Faollik yangilash
    user_states[chat_id] = 'searching'
    user_data[chat_id] = {'type': text}  # Qaysi turdagi qidiruv

    if text == "🎬 Kino qidirish":
        bot.send_message(chat_id, "🎬 Kino kodini yoki nomini yozing:", reply_markup=get_cancel_keyboard())
    elif text == "🎭 Drama qidirish":
        bot.send_message(chat_id, "🎭 Drama kodini yoki nomini yozing:", reply_markup=get_cancel_keyboard())
    elif text == "🧸 Multfilm qidirish":
        bot.send_message(chat_id, "🧸 Multfilm kodini yoki nomini yozing:", reply_markup=get_cancel_keyboard())


# ----------------- GLOBAL BEKOR QILISH -----------------
@bot.message_handler(func=lambda m: m.text == "❌ Bekor Qilish")
def global_cancel(message):
    chat_id = message.chat.id
    if chat_id in user_states:
        user_states.pop(chat_id, None)
    if chat_id in user_data:
        user_data.pop(chat_id, None)
    bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())


# ----------------- DRAMA QIDIRUV (FAOL KOD) -----------------
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'searching')
def user_search_query(message):
    chat_id = message.chat.id
    search_type = user_data[chat_id]['type']
    query = message.text.strip()

    if search_type == "🎬 Kino qidirish":
        results = db.search_films(query)
        if results:
            for film in results:
                bot.send_video(chat_id, video=film['file_id'], caption=f"🎬 {film['code']}\n{film['caption']}")
        else:
            bot.send_message(chat_id, "❌ Kino topilmadi.")

    elif search_type == "🎭 Drama qidirish":
        # Faqat KOD bo'yicha qidiruv
        db.cursor.execute(
            "SELECT code, caption, photo_id FROM dramas WHERE code = ?",
            (query,)
        )
        drama = db.cursor.fetchone()

        if not drama:
            bot.send_message(chat_id, "❌ Drama topilmadi.")
            return

        code, caption, photo_id = drama

        # Inline tugmalar tayyorlash
        markup = types.InlineKeyboardMarkup(row_width=5)
        db.cursor.execute(
            "SELECT episode_number FROM drama_episodes WHERE drama_code=? ORDER BY episode_number",
            (code,)
        )
        episodes = db.cursor.fetchall()

        if episodes:
            for ep in episodes[:10]:
                markup.add(types.InlineKeyboardButton(
                    text=str(ep[0]),
                    callback_data=f"drama_{code}_{ep[0]}"
                ))
            if len(episodes) > 10:
                markup.add(types.InlineKeyboardButton(
                    text="➡️ Keyingi",
                    callback_data=f"drama_next_{code}_10"
                ))

        # Bekor qilish tugmasi
        markup.add(types.InlineKeyboardButton(
            text="❌ Bekor Qilish",
            callback_data="drama_cancel"
        ))

        bot.send_photo(chat_id, photo_id, caption=caption, reply_markup=markup)

    elif search_type == "🧸 Multfilm qidirish":
        db.cursor.execute(
            "SELECT code, caption, photo_id FROM cartoons WHERE code LIKE ? OR caption LIKE ?",
            (f"%{query}%", f"%{query}%")
        )
        cartoons = db.cursor.fetchall()
        if cartoons:
            for cartoon in cartoons:
                code, caption, photo_id = cartoon
                markup = types.InlineKeyboardMarkup(row_width=5)
                db.cursor.execute(
                    "SELECT episode_number FROM cartoon_episodes WHERE cartoon_code=? ORDER BY episode_number",
                    (code,)
                )
                episodes = db.cursor.fetchall()
                if episodes:
                    for ep in episodes[:10]:
                        markup.add(types.InlineKeyboardButton(
                            text=str(ep[0]),
                            callback_data=f"cartoon_{code}_{ep[0]}"
                        ))
                    if len(episodes) > 10:
                        markup.add(types.InlineKeyboardButton(
                            text="➡️ Keyingi",
                            callback_data=f"cartoon_next_{code}_10"
                        ))
                markup.add(types.InlineKeyboardButton(
                    text="❌ Bekor Qilish",
                    callback_data="cartoon_cancel"
                ))
                bot.send_photo(chat_id, photo_id, caption=caption, reply_markup=markup)
        else:
            bot.send_message(chat_id, "❌ Multfilm topilmadi.")

    # Holatni tozalash
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)
# ----------------- EPIZOD VA QISM CALLBACKLARI -----------------
@bot.callback_query_handler(func=lambda call: True)
def episodes_callback(call):
    data = call.data
    chat_id = call.message.chat.id

    # ----------------- DRAMA QISM TUGMALARI -----------------
    if data.startswith("drama_") and not data.startswith("drama_next_"):
        _, code, ep = data.split("_")
        db.cursor.execute(
            "SELECT file_id, caption FROM drama_episodes WHERE drama_code=? AND episode_number=?",
            (code, ep)
        )
        episode = db.cursor.fetchone()
        if episode:
            file_id, caption = episode
            bot.send_video(chat_id, file_id, caption=f"{caption}\n🎭 Drama {code} | Qism {ep}")
        bot.answer_callback_query(call.id, f"{ep}-qism ochildi")
        return

    # ----------------- DRAMA KEYINGI QISM -----------------
    elif data.startswith("drama_next_"):
        _, code, offset = data.split("_")
        offset = int(offset)
        db.cursor.execute(
            "SELECT episode_number FROM drama_episodes WHERE drama_code=? ORDER BY episode_number LIMIT 10 OFFSET ?",
            (code, offset)
        )
        episodes = db.cursor.fetchall()
        if episodes:
            keyboard = types.InlineKeyboardMarkup(row_width=5)
            for ep in episodes:
                keyboard.add(types.InlineKeyboardButton(text=str(ep[0]), callback_data=f"drama_{code}_{ep[0]}"))
            if len(episodes) == 10:
                keyboard.add(types.InlineKeyboardButton(text="➡️ Keyingi", callback_data=f"drama_next_{code}_{offset+10}"))
            keyboard.add(types.InlineKeyboardButton(text="❌ Bekor Qilish", callback_data="drama_cancel"))
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)
        return

    # ----------------- DRAMA BEKOR QILISH -----------------
    elif data == "drama_cancel":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        bot.answer_callback_query(call.id)
        return

    # ----------------- MULTFILM QISM TUGMALARI -----------------
    elif data.startswith("cartoon_") and not data.startswith("cartoon_next_"):
        _, code, ep = data.split("_")
        db.cursor.execute(
            "SELECT file_id, caption FROM cartoon_episodes WHERE cartoon_code=? AND episode_number=?",
            (code, ep)
        )
        episode = db.cursor.fetchone()
        if episode:
            file_id, caption = episode
            bot.send_video(chat_id, file_id, caption=f"{caption}\n🧸 Multfilm {code} | Qism {ep}")
        bot.answer_callback_query(call.id, f"{ep}-qism ochildi")
        return

    # ----------------- MULTFILM KEYINGI QISM -----------------
    elif data.startswith("cartoon_next_"):
        _, code, offset = data.split("_")
        offset = int(offset)
        db.cursor.execute(
            "SELECT episode_number FROM cartoon_episodes WHERE cartoon_code=? ORDER BY episode_number LIMIT 10 OFFSET ?",
            (code, offset)
        )
        episodes = db.cursor.fetchall()
        if episodes:
            keyboard = types.InlineKeyboardMarkup(row_width=5)
            for ep in episodes:
                keyboard.add(types.InlineKeyboardButton(text=str(ep[0]), callback_data=f"cartoon_{code}_{ep[0]}"))
            if len(episodes) == 10:
                keyboard.add(types.InlineKeyboardButton(text="➡️ Keyingi", callback_data=f"cartoon_next_{code}_{offset+10}"))
            keyboard.add(types.InlineKeyboardButton(text="❌ Bekor Qilish", callback_data="cartoon_cancel"))
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)
        return

    # ----------------- MULTFILM BEKOR QILISH -----------------
    elif data == "cartoon_cancel":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        bot.answer_callback_query(call.id)
        return
        # ----------------- ADMIN PANEL: O'CHIRISH -----------------
@bot.message_handler(func=lambda message: message.text == "🗑️ Kino o'chirish" and db.is_admin(message.from_user.id))
def film_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_film_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan kinoning **kodini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_film_waiting_for_code')
def film_delete_code(message):
    chat_id = message.chat.id
    film_code = message.text.strip()
    
    if db.delete_film(film_code):
        msg = f"✅ **{film_code}** kodli kino ma'lumotlar bazasidan o'chirildi."
    else:
        msg = f"❌ Uzr, **{film_code}** kodli kino topilmadi."
    
    bot.send_message(chat_id, msg, reply_markup=get_current_keyboard(message.from_user.id))
    user_states.pop(chat_id, None)


@bot.message_handler(func=lambda message: message.text == "🗑️ Drama o'chirish" and db.is_admin(message.from_user.id))
def drama_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_drama_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan dramaning **kodini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_drama_waiting_for_code')
def drama_delete_code(message):
    chat_id = message.chat.id
    drama_code = message.text.strip()
    
    if db.delete_drama(drama_code):
        msg = f"✅ **{drama_code}** kodli drama ma'lumotlar bazasidan o'chirildi."
        # Drama qismlari ham o'chiriladi
        db.cursor.execute("DELETE FROM drama_episodes WHERE drama_code=?", (drama_code,))
        db.conn.commit()
    else:
        msg = f"❌ Uzr, **{drama_code}** kodli drama topilmadi."
    
    bot.send_message(chat_id, msg, reply_markup=get_current_keyboard(message.from_user.id))
    user_states.pop(chat_id, None)


@bot.message_handler(func=lambda message: message.text == "🗑️ Multfilm o'chirish" and db.is_admin(message.from_user.id))
def cartoon_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_cartoon_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan multfilmning **kodini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_cartoon_waiting_for_code')
def cartoon_delete_code(message):
    chat_id = message.chat.id
    cartoon_code = message.text.strip()
    
    if db.delete_cartoon(cartoon_code):
        msg = f"✅ **{cartoon_code}** kodli multfilm ma'lumotlar bazasidan o'chirildi."
        # Multfilm qismlari ham o'chiriladi
        db.cursor.execute("DELETE FROM cartoon_episodes WHERE cartoon_code=?", (cartoon_code,))
        db.conn.commit()
    else:
        msg = f"❌ Uzr, **{cartoon_code}** kodli multfilm topilmadi."
    
    bot.send_message(chat_id, msg, reply_markup=get_current_keyboard(message.from_user.id))
    user_states.pop(chat_id, None)
    # ----------------- ADMIN PANEL: O'CHIRISH -----------------
@bot.message_handler(func=lambda message: message.text == "🗑️ Kino o'chirish" and db.is_admin(message.from_user.id))
def film_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_film_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan kinoning **kodini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_film_waiting_for_code')
def film_delete_code(message):
    chat_id = message.chat.id
    film_code = message.text.strip()
    
    if db.delete_film(film_code):
        msg = f"✅ **{film_code}** kodli kino ma'lumotlar bazasidan o'chirildi."
    else:
        msg = f"❌ Uzr, **{film_code}** kodli kino topilmadi."
    
    bot.send_message(chat_id, msg, reply_markup=get_current_keyboard(message.from_user.id))
    user_states.pop(chat_id, None)


@bot.message_handler(func=lambda message: message.text == "🗑️ Drama o'chirish" and db.is_admin(message.from_user.id))
def drama_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_drama_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan dramaning **kodini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_drama_waiting_for_code')
def drama_delete_code(message):
    chat_id = message.chat.id
    drama_code = message.text.strip()
    
    if db.delete_drama(drama_code):
        msg = f"✅ **{drama_code}** kodli drama ma'lumotlar bazasidan o'chirildi."
        # Drama qismlari ham o'chiriladi
        db.cursor.execute("DELETE FROM drama_episodes WHERE drama_code=?", (drama_code,))
        db.conn.commit()
    else:
        msg = f"❌ Uzr, **{drama_code}** kodli drama topilmadi."
    
    bot.send_message(chat_id, msg, reply_markup=get_current_keyboard(message.from_user.id))
    user_states.pop(chat_id, None)


@bot.message_handler(func=lambda message: message.text == "🗑️ Multfilm o'chirish" and db.is_admin(message.from_user.id))
def cartoon_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_cartoon_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan multfilmning **kodini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_cartoon_waiting_for_code')
def cartoon_delete_code(message):
    chat_id = message.chat.id
    cartoon_code = message.text.strip()
    
    if db.delete_cartoon(cartoon_code):
        msg = f"✅ **{cartoon_code}** kodli multfilm ma'lumotlar bazasidan o'chirildi."
        # Multfilm qismlari ham o'chiriladi
        db.cursor.execute("DELETE FROM cartoon_episodes WHERE cartoon_code=?", (cartoon_code,))
        db.conn.commit()
    else:
        msg = f"❌ Uzr, **{cartoon_code}** kodli multfilm topilmadi."
    
    bot.send_message(chat_id, msg, reply_markup=get_current_keyboard(message.from_user.id))
    user_states.pop(chat_id, None)
# ----------------- 7. INLINE QUERY HANDLER (Qidiruv) -----------------

@bot.inline_handler(func=lambda query: True)
def inline_query_handler(inline_query):
    query = inline_query.query.strip()
    articles = []

    if not query or len(query) < 2:
        item = types.InlineQueryResultArticle(
            id='0',
            title="🔍 Kino kodini yoki nomini yozing",
            description="Qidiruv kamida 2ta harfdan iborat bo'lishi kerak.",
            input_message_content=types.InputTextMessageContent(message_text="Kino kodini yuboring. Masalan: 101")
        )
        bot.answer_inline_query(inline_query.id, [item], cache_time=1)
        return

    search_results = db.search_films(query)

    if search_results:
        for i, film in enumerate(search_results):
            input_content = types.InputTextMessageContent(message_text=film['code'])
            keyboard = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    text="▶️ Bu kinoni menga yubor",
                    url=f"https://t.me/{bot.get_me().username}?start={film['code']}"
                )
            )
            article = types.InlineQueryResultArticle(
                id=str(i + 1),
                title=f"🎬 Kod: {film['code']} - {film['caption'][:30]}...",
                description=film['caption'],
                input_message_content=input_content,
                reply_markup=keyboard
            )
            articles.append(article)
    else:
        articles.append(
            types.InlineQueryResultArticle(
                id='-1',
                title="❌ Hech narsa topilmadi",
                description=f"'{query}' bo‘yicha kino topilmadi.",
                input_message_content=types.InputTextMessageContent(message_text=f"Uzr, '{query}' bo‘yicha kino topilmadi.")
            )
        )

    bot.answer_inline_query(inline_query.id, articles, cache_time=300)

    # ===================== 🎬 KINO =====================
    films = db.search_films(query)

    if films:
        for i, film in enumerate(films):
            keyboard = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    text="▶️ Kinoni ochish",
                    url=f"https://t.me/{bot.get_me().username}?start={film['code']}"
                )
            )

            articles.append(
                types.InlineQueryResultArticle(
                    id=f"film_{i}",
                    title=f"🎬 Kino | {film['code']}",
                    description=film['caption'],
                    input_message_content=types.InputTextMessageContent(
                        message_text=film['code']
                    ),
                    reply_markup=keyboard
                )
            )


# ----------------- 🎭 DRAMA QIDIRUV -----------------
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'searching')
def user_search_query(message):
    chat_id = message.chat.id
    search_type = user_data[chat_id]['type']  # Kino, Drama yoki Multfilm
    query = message.text.strip()

    # ===================== 🎭 DRAMA =====================
    if search_type == "🎭 Drama qidirish":
        # Faqat raqamli kod
        if not query.isdigit():
            bot.send_message(chat_id, "❌ Iltimos, faqat raqamli kod kiriting.")
            return

        # Drama qidiruv (faqat kod bo'yicha)
        db.cursor.execute(
            "SELECT code, caption, photo_id FROM dramas WHERE code = ?",
            (query,)
        )
        drama = db.cursor.fetchone()

        if not drama:
            bot.send_message(chat_id, "❌ Drama topilmadi. Kodni tekshiring.")
            return

        code, caption, photo_id = drama

        # Epizodlarni olish
        db.cursor.execute(
            "SELECT episode_number FROM drama_episodes WHERE drama_code=? ORDER BY episode_number",
            (code,)
        )
        episodes = db.cursor.fetchall()

        # Inline tugmalar
        markup = types.InlineKeyboardMarkup(row_width=5)
        if episodes:
            for ep in episodes[:10]:
                markup.add(
                    types.InlineKeyboardButton(
                        text=str(ep[0]),
                        callback_data=f"drama_{code}_{ep[0]}"
                    )
                )
            if len(episodes) > 10:
                markup.add(
                    types.InlineKeyboardButton(
                        text="➡️ Keyingi",
                        callback_data=f"drama_next_{code}_10"
                    )
                )

        # Bekor qilish tugmasi
        markup.add(
            types.InlineKeyboardButton(
                text="❌ Bekor Qilish",
                callback_data="drama_cancel"
            )
        )

        # Drama rasm va tugmalar bilan
        bot.send_photo(chat_id, photo_id, caption=f"🎭 {caption}\nKod: {code}", reply_markup=markup)

        # Holatni tozalash
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)

    # ===================== 🧸 MULTFILM =====================
    elif search_type == "🧸 Multfilm qidirish":
        db.cursor.execute(
            "SELECT code, caption FROM cartoons WHERE code LIKE ? OR caption LIKE ?",
            (f"%{query}%", f"%{query}%")
        )
        cartoons = db.cursor.fetchall()

        if cartoons:
            for i, cartoon in enumerate(cartoons):
                code, caption = cartoon

                keyboard = types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton(
                        text="▶️ Multfilmni ochish",
                        url=f"https://t.me/{bot.get_me().username}?start={code}"
                    )
                )

                bot.answer_inline_query(
                    inline_query_id=message.id,
                    results=[types.InlineQueryResultArticle(
                        id=f"cartoon_{i}",
                        title=f"🧸 Multfilm | {code}",
                        description=caption,
                        input_message_content=types.InputTextMessageContent(message_text=code),
                        reply_markup=keyboard
                    )],
                    cache_time=300
                )


# ----------------- ADMIN PANEL HANDLER -----------------
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'admin_panel')
def admin_panel_handler(message):
    chat_id = message.chat.id
    text = message.text.strip()

    # ❌ Bekor qilish
    if text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_super_admin_keyboard())
        return

    # Kino qo'shish
    if text == "🎬 Kino qo'shish":
        user_states[chat_id] = 'add_film'
        bot.send_message(chat_id, "🎬 Kino qo'shish: kodni kiriting.")
        return

    # Kino o'chirish
    if text == "🗑️ Kino o'chirish":
        user_states[chat_id] = 'delete_film'
        bot.send_message(chat_id, "🗑️ Kino o'chirish: kodni kiriting.")
        return

    # Drama qo'shish
    if text == "🎭 Drama qo'shish":
        user_states[chat_id] = 'add_drama'
        bot.send_message(chat_id, "🎭 Drama qo'shish: kodni kiriting.")
        return

    # Drama o'chirish
    if text == "🗑️ Drama o'chirish":
        user_states[chat_id] = 'delete_drama'
        bot.send_message(chat_id, "🗑️ Drama o'chirish: kodni kiriting.")
        return

    # Multfilm qo'shish
    if text == "🧸 Multfilm qo'shish":
        user_states[chat_id] = 'add_cartoon'
        bot.send_message(chat_id, "🧸 Multfilm qo'shish: kodni kiriting.")
        return

    # Multfilm o'chirish
    if text == "🗑️ Multfilm o'chirish":
        user_states[chat_id] = 'delete_cartoon'
        bot.send_message(chat_id, "🗑️ Multfilm o'chirish: kodni kiriting.")
        return

    # Reklama berish
    if text == "📢 Reklama":
        user_states[chat_id] = 'send_ad'
        bot.send_message(chat_id, "📢 Reklama yuborish uchun matnni kiriting:")
        return

    # Statistika
    if text == "📊 Statistika":
        stats = db.get_stats()  # sizning bazadagi statistika funksiyangiz
        bot.send_message(chat_id, stats)
        return



## ----------------- ADMIN QO'SHISH/O'CHIRISH/REKLAMA/STATISTIKA -----------------
from telebot import types

# ---------- DB METODLARI ----------
def get_admins():
    db.cursor.execute("SELECT user_id, username FROM admins")
    rows = db.cursor.fetchall()
    return [{'user_id': r[0], 'username': r[1]} for r in rows]

def add_admin(user_id, username=None):
    db.cursor.execute(
        "INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)", 
        (user_id, username)
    )
    db.conn.commit()

def remove_admin(user_id):
    db.cursor.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    db.conn.commit()

def count_users():
    db.cursor.execute("SELECT COUNT(*) FROM users")
    return db.cursor.fetchone()[0]

def get_all_users():
    db.cursor.execute("SELECT user_id FROM users")
    return [r[0] for r in db.cursor.fetchall()]

def get_blocked_users():
    db.cursor.execute("SELECT user_id FROM users WHERE blocked=1")
    return [r[0] for r in db.cursor.fetchall()]

def is_online(user_id):
    db.cursor.execute("SELECT last_seen FROM users WHERE user_id=?", (user_id,))
    row = db.cursor.fetchone()
    if not row:
        return False
    import time
    last_seen = row[0]
    return time.time() - last_seen < 300  # 5 daqiqa ichida aktiv

# ---------- ADMIN TEKSHIRUV FUNKSIYALARI ----------
SUPER_ADMINS = [123456789]  # Super admin ID larini bu yerga qo'ying

def is_super_admin(chat_id):
    return chat_id in SUPER_ADMINS

def is_admin(chat_id):
    admins = get_admins()
    return any(a['user_id'] == chat_id for a in admins) or is_super_admin(chat_id)

# ---------- HOLATLAR ----------
user_states = {}  # foydalanuvchi holatlarini saqlash
user_data = {}    # foydalanuvchi ma'lumotlarini saqlash

# ---------- ADMIN QO'SHISH/O'CHIRISH ----------
@bot.message_handler(func=lambda message: message.text in ["➕ Admin qo'shish", "➖ Admin o'chirish"])
def admin_manage_start(message):
    chat_id = message.chat.id
    if not is_super_admin(chat_id):
        bot.send_message(chat_id, "❌ Sizda ruxsat yo'q.")
        return

    if message.text == "➕ Admin qo'shish":
        user_states[chat_id] = 'add_admin'
        bot.send_message(chat_id, "📝 Qo'shmoqchi bo'lgan foydalanuvchi ID sini kiriting:")
    else:
        admins = get_admins()
        if not admins:
            bot.send_message(chat_id, "❌ Hozircha adminlar yo‘q.")
            return
        user_states[chat_id] = 'delete_admin'
        text = "🗑️ O'chirish uchun adminlar:\n" + "\n".join(
            [f"{a['username']} ({a['user_id']})" for a in admins]
        )
        bot.send_message(chat_id, text + "\n\nID ni kiriting:")

@bot.message_handler(func=lambda message: message.chat.id in user_states)
def admin_manage_input(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    text = message.text.strip()

    if not text.isdigit():
        bot.send_message(chat_id, "❌ Iltimos, faqat raqamli ID kiriting.")
        return

    user_id = int(text)

    if state == 'add_admin':
        add_admin(user_id, username=message.from_user.username)
        bot.send_message(chat_id, f"✅ Admin qo'shildi: {user_id}")
    elif state == 'delete_admin':
        remove_admin(user_id)
        bot.send_message(chat_id, f"✅ Admin o'chirildi: {user_id}")

    user_states.pop(chat_id, None)

# ---------- REKLAMA YUBORISH ----------
@bot.message_handler(func=lambda message: message.text == "📢 Reklama yuborish")
def ad_start(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        bot.send_message(chat_id, "❌ Siz admin emassiz.")
        return
    user_states[chat_id] = 'ad_caption'
    user_data[chat_id] = {}
    bot.send_message(chat_id, "📝 Reklama caption kiriting:")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) in ['ad_caption','ad_photo','ad_confirm'])
def ad_process(message):
    chat_id = message.chat.id
    state = user_states[chat_id]

    if state == 'ad_caption':
        user_data[chat_id]['caption'] = message.text
        user_states[chat_id] = 'ad_photo'
        bot.send_message(chat_id, "📸 Rasm jo'nating yoki /skip deb o‘tkazing:")
        return

    if state == 'ad_photo':
        if message.text == "/skip":
            user_data[chat_id]['photo'] = None
        elif message.photo:
            file_id = message.photo[-1].file_id
            user_data[chat_id]['photo'] = file_id
        else:
            bot.send_message(chat_id, "❌ Rasm jo'nating yoki /skip deb o‘tkazing:")
            return
        # Tasdiqlash
        caption = user_data[chat_id]['caption']
        photo = user_data[chat_id].get('photo')
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Yuborish", callback_data="ad_send"))
        markup.add(types.InlineKeyboardButton("❌ Bekor qilish", callback_data="ad_cancel"))
        if photo:
            bot.send_photo(chat_id, photo, caption=caption, reply_markup=markup)
        else:
            bot.send_message(chat_id, caption, reply_markup=markup)
        user_states[chat_id] = 'ad_confirm'
        return

@bot.callback_query_handler(func=lambda call: call.data in ['ad_send','ad_cancel'])
def ad_callback(call):
    chat_id = call.message.chat.id
    if call.data == 'ad_send':
        all_users = get_all_users()
        caption = user_data[chat_id]['caption']
        photo = user_data[chat_id].get('photo')
        for uid in all_users:
            try:
                if photo:
                    bot.send_photo(uid, photo, caption=caption)
                else:
                    bot.send_message(uid, caption)
            except:
                continue
        bot.send_message(chat_id, "✅ Reklama yuborildi!")
    else:
        bot.send_message(chat_id, "❌ Amal bekor qilindi.")
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)

# ---------- STATISTIKA ----------
@bot.message_handler(func=lambda message: message.text == "📊 Statistikalar")
def show_stats(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        bot.send_message(chat_id, "❌ Siz admin emassiz.")
        return
    total_users = count_users()
    online_users = len([uid for uid in get_all_users() if is_online(uid)])
    blocked_users = get_blocked_users()
    text = f"📊 Bot statistikasi:\n\n" \
           f"👥 Foydalanuvchilar: {total_users}\n" \
           f"🟢 Hozir onlayn: {online_users}\n" \
           f"⛔ Botni bloklaganlar: {len(blocked_users)}"
    bot.send_message(chat_id, text)
# --- BOTNI ISHGA TUSHIRISH ---

if __name__ == "__main__":
    keep_alive()
    logging.info("Bot ishga tushirildi...")
    bot.infinity_polling(skip_pending=True)