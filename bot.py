import telebot
from telebot import types
import sqlite3
import logging
import time
from flask import Flask
import threading
import time
from datetime import datetime, timedelta

# ----------------- 1. BOT SOZLAMALARI VA DB SETUP -----------------
API_TOKEN = '7966505221:AAHEUj82be8yTNnmfKhbpTz9CqiSR75SAx4' # O'zingizning haqiqiy TOKENINGIZNI KIRITING
DB_NAME = 'bot.db'

# --- ADMINLAR VA KANALLAR ---
ADMINS = [8165064673, 8134296521, 6881871621, 7035569750, 8132410053, 7126069858] # Bosh admin ID'si (Bu joyga o'z ID'ingizni kiriting)
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
import sqlite3
import time

class Database:
    """SQLite bilan ishlash uchun barcha funksiyalar jamlangan to'liq sinf"""
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file, check_same_thread=False) 
        self.cursor = self.conn.cursor()
        self.setup()

    def setup(self):
        # Adminlar jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
        """)
        # Foydalanuvchilar jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_blocked BOOLEAN DEFAULT 0,
                last_active REAL DEFAULT (strftime('%s','now'))
            )
        """)
        # Kinolar jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS films (
                code TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                caption TEXT
            )
        """)
        # Drama jadvallari
        self.cursor.execute("CREATE TABLE IF NOT EXISTS dramas (code TEXT PRIMARY KEY, caption TEXT, photo_id TEXT)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS drama_episodes (id INTEGER PRIMARY KEY AUTOINCREMENT, drama_code TEXT, episode_number INTEGER, file_id TEXT)")
        
        # Multfilm jadvallari
        self.cursor.execute("CREATE TABLE IF NOT EXISTS cartoons (code TEXT PRIMARY KEY, caption TEXT, photo_id TEXT)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS cartoon_episodes (id INTEGER PRIMARY KEY AUTOINCREMENT, cartoon_code TEXT, episode_number INTEGER, file_id TEXT)")
        
        # Anime jadvallari
        self.cursor.execute("CREATE TABLE IF NOT EXISTS animes (code TEXT PRIMARY KEY, caption TEXT, photo_id TEXT)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS anime_episodes (id INTEGER PRIMARY KEY AUTOINCREMENT, anime_code TEXT, episode_number INTEGER, file_id TEXT)")
        
        self.conn.commit()

    # --- KINO / DRAMA / MULTFILM QIDIRISH (Kino yuborish uchun) ---
    def get_film(self, code):
        self.cursor.execute("SELECT file_id, caption FROM films WHERE code = ?", (code,))
        return self.cursor.fetchone()

    def get_drama(self, code):
        self.cursor.execute("SELECT code, caption, photo_id FROM dramas WHERE code = ?", (code,))
        return self.cursor.fetchone()

    def get_cartoon(self, code):
        self.cursor.execute("SELECT code, caption, photo_id FROM cartoons WHERE code = ?", (code,))
        return self.cursor.fetchone()

    def get_anime(self, code):
        self.cursor.execute("SELECT code, caption, photo_id FROM animes WHERE code = ?", (code,))
        return self.cursor.fetchone()

    # --- QO'SHISH FUNKSIYALARI ---
    def add_film(self, code, file_id, caption):
        self.cursor.execute("INSERT OR REPLACE INTO films (code, file_id, caption) VALUES (?, ?, ?)", (code, file_id, caption))
        self.conn.commit()

    # --- O'CHIRISH FUNKSIYALARI (Admin panel uchun) ---
    def delete_film(self, code):
        self.cursor.execute("DELETE FROM films WHERE code = ?", (code,))
        self.conn.commit()

    def delete_drama(self, code):
        self.cursor.execute("DELETE FROM dramas WHERE code = ?", (code,))
        self.cursor.execute("DELETE FROM drama_episodes WHERE drama_code = ?", (code,))
        self.conn.commit()

    def delete_cartoon(self, code):
        self.cursor.execute("DELETE FROM cartoons WHERE code = ?", (code,))
        self.cursor.execute("DELETE FROM cartoon_episodes WHERE cartoon_code = ?", (code,))
        self.conn.commit()

    def delete_anime(self, code):
        self.cursor.execute("DELETE FROM animes WHERE code = ?", (code,))
        self.cursor.execute("DELETE FROM anime_episodes WHERE anime_code = ?", (code,))
        self.conn.commit()

    # --- ADMIN AMALLARI ---
    def add_admin(self, user_id, username=None):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)", (user_id, username))
            self.conn.commit()
        except sqlite3.OperationalError:
            # Agar baribir ustun topilmasa, faqat ID ning o'zini saqlaymiz
            self.cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
            self.conn.commit()

    def remove_admin(self, user_id):
        self.cursor.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        self.conn.commit()

    def get_admins(self):
        self.cursor.execute("SELECT user_id, username FROM admins")
        rows = self.cursor.fetchall()
        return [{'user_id': r[0], 'username': r[1] if r[1] else 'NoUsername'} for r in rows]

    def is_admin(self, user_id):
        self.cursor.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
        return self.cursor.fetchone() is not None

    # --- USERS AMALLARI VA STATISTIKA ---
    def add_user(self, user_id):
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, is_blocked) VALUES (?,0)", (user_id,))
        self.cursor.execute("UPDATE users SET last_active = strftime('%s','now') WHERE user_id=?", (user_id,))
        self.conn.commit()

    def set_user_blocked(self, user_id, is_blocked):
        self.cursor.execute("UPDATE users SET is_blocked=? WHERE user_id=?", (is_blocked, user_id))
        self.conn.commit()

    def get_all_users():
        cursor.execute("SELECT user_id FROM users")
        rows = cursor.fetchall()
        return [row[0] for row in rows]

    def count_users(self):
        self.cursor.execute("SELECT COUNT(user_id) FROM users")
        return self.cursor.fetchone()[0]

    def count_blocked_users(self):
        self.cursor.execute("SELECT COUNT(user_id) FROM users WHERE is_blocked=1")
        return self.cursor.fetchone()[0]

    def count_active_users(self):
        """Oxirgi 24 soatda faol bo'lganlar"""
        self.cursor.execute("SELECT COUNT(user_id) FROM users WHERE last_active >= strftime('%s','now','-1 day')")
        return self.cursor.fetchone()[0]


# --- DATABASE OBYEKTI ---
db = Database(DB_NAME)
# ----------------- 3. YORDAMCHI FUNKSIYALAR VA KLAVIATURALAR -----------------

# --- FOYDALANUVCHI KLAVIATURASI ---
def get_user_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("🎬 Kino qidirish"),
        types.KeyboardButton("🎭 Drama qidirish"),
        types.KeyboardButton("🧸 Multfilm qidirish"),
        types.KeyboardButton("🎌 Anime qidirish"),
    )
    return keyboard

# --- SUPER ADMIN KLAVIATURASI ---
def get_super_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("🎬 Kino qo'shish"), types.KeyboardButton("🎭 Drama qo'shish"),
        types.KeyboardButton("🧸 Multfilm qo'shish"), types.KeyboardButton("🎌 Anime qo'shish"),
        types.KeyboardButton("🗑️ Kino o'chirish"), types.KeyboardButton("🗑️ Drama o'chirish"),
        types.KeyboardButton("🗑️ Multfilm o'chirish"), types.KeyboardButton("🗑️ Anime o'chirish"),
        types.KeyboardButton("📊 Statistika"), types.KeyboardButton("📢 Reklama"),
        types.KeyboardButton("❌ Bekor Qilish")
    )
    return keyboard

# --- ODDIY ADMIN KLAVIATURASI ---
def get_regular_admin_keyboard():
    # Super admin bilan bir xil bo'lishi uchun (yoki o'zgartirishingiz mumkin)
    return get_super_admin_keyboard()

# --- BEKOR QILISH KLAVIATURASI ---
def get_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("❌ Bekor Qilish"))
    return keyboard

# --- QAYSI KLAVIATURA KELISHINI TANLASH (YAGONA FUNKSIYA) ---
def get_current_keyboard(user_id):
    """Foydalanuvchi darajasiga qarab klaviaturani qaytaradi"""
    if 'ADMINS' in globals() and len(ADMINS) > 0:
        admin_ids = [int(str(a)) for a in ADMINS]
        if int(user_id) in admin_ids:
            # Agar birinchi ID bo'lsa Super Admin, bo'lmasa Regular
            if int(user_id) == admin_ids[0]:
                return get_super_admin_keyboard()
            else:
                return get_regular_admin_keyboard()
    
    # Admin bo'lmasa yoki bazada admin deb belgilangan bo'lsa
    if db.is_admin(user_id):
        return get_regular_admin_keyboard()
        
    return get_user_keyboard()

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
    
    # 1. Bazaga foydalanuvchini qo'shish
    db.add_user(user_id)
    
    # 2. Holatlarni tozalash
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)

    # 3. UNIVERSAL ADMIN TEKSHIRUVI
    admin_ids = [int(str(a)) for a in ADMINS]

    if user_id in admin_ids:
        # Bazaga admin ekanini saqlaymiz
        db.add_admin(user_id, message.from_user.username)
        
        markup = get_current_keyboard(user_id)
        
        if user_id == admin_ids[0]:
            bot.send_message(chat_id, "👑 Xush kelibsiz, Bosh Admin!", reply_markup=markup)
        else:
            bot.send_message(chat_id, "🛠️ Xush kelibsiz, Admin!", reply_markup=markup)
        
        return # Admin uchun obuna shart emas

    # 4. ODDIY FOYDALANUVCHILAR
    not_subscribed = [ch for ch in CHANNELS if not check_subscription(user_id, ch)]
    
    if not_subscribed:
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for ch in not_subscribed:
            keyboard.add(types.InlineKeyboardButton(text=f"➕ {ch}", url=f"https://t.me/{ch.strip('@')}"))
        keyboard.add(types.InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs"))
        
        bot.send_message(chat_id, "Botdan foydalanish uchun kanallarga obuna bo'ling:", reply_markup=keyboard)
    else:
        send_main_menu(chat_id)


@bot.callback_query_handler(func=lambda call: call.data == "check_subs")
def check_subscription_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    admin_ids = [int(str(a)) for a in ADMINS]
    not_subscribed = [ch for ch in CHANNELS if not check_subscription(user_id, ch)]
    
    bot.answer_callback_query(call.id, "Tekshirilmoqda...")

    if not_subscribed and user_id not in admin_ids:
        # Obuna bo'lmaganlarga qayta ko'rsatish
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for ch in not_subscribed:
            keyboard.add(types.InlineKeyboardButton(text=f"➕ {ch}", url=f"https://t.me/{ch.strip('@')}"))
        keyboard.add(types.InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs"))
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="Iltimos, avval barcha kanallarga obuna bo'ling:",
            reply_markup=keyboard
        )
    else:
        # Muvaffaqiyatli o'tganda yoki Admin bo'lganda
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
            
        if user_id in admin_ids:
            markup = get_current_keyboard(user_id)
            bot.send_message(chat_id, "✅ Admin paneli faollashdi!", reply_markup=markup)
        else:
            send_main_menu(chat_id)



# 1. Kanal sozlamasi (IDni kiritish shart, bot admin bo'lsa yuboradi)
# Agar ID xato bo'lsa, konsolda xato chiqadi. 
# Taxminiy ID: -1002244493395 (O'zingiznikiga almashtiring)
CH_ID = -1003666920776

# ===============================
# 🎬 KINO QO'SHISH VA KANALGA YUBORISH
# ===============================

@bot.message_handler(func=lambda message: message.text == "🎬 Kino qo'shish" and db.is_admin(message.from_user.id))
def admin_add_film_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'film_waiting_code'
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🆔 Kino uchun **kod** kiriting:", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'film_waiting_code')
def admin_add_film_code(message):
    chat_id = message.chat.id
    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    user_data[chat_id]['code'] = message.text.strip()
    user_states[chat_id] = 'film_waiting_name'
    bot.send_message(chat_id, "🎬 Kino **NOMINI** kiriting:", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'film_waiting_name')
def admin_add_film_name(message):
    chat_id = message.chat.id
    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    user_data[chat_id]['name'] = message.text.strip()
    user_states[chat_id] = 'film_waiting_parts'
    bot.send_message(chat_id, "🔢 Nechta qism bor?", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'film_waiting_parts')
def admin_add_film_parts(message):
    chat_id = message.chat.id
    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    try:
        user_data[chat_id]['parts'] = int(message.text)
        user_data[chat_id]['current'] = 1
        user_states[chat_id] = 'film_waiting_video'
        bot.send_message(chat_id, "🎬 1-qism videoni yuboring:", reply_markup=get_cancel_keyboard())
    except:
        bot.send_message(chat_id, "❌ Son kiriting!")

@bot.message_handler(content_types=['video'], func=lambda message: user_states.get(message.chat.id) == 'film_waiting_video')
def admin_add_film_video(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id)
    if not data: return

    # 🔥 AVTO-CAPTION (Video tagiga tushadi)
    qism_str = f"🎞 **Qism:** {data['current']}-qism" if data['parts'] > 1 else "🎞 **Qism:** To'liq film"
    caption = (
        f"🆔 **Kino kodi:** {data['code']}\n"
        f"🎬 **Nomi:** {data['name']}\n"
        f"{qism_str}\n"
        f"🇺🇿 **Tili:** O'zbek tilida\n\n"
        f"🤖 **Botimiz:** @tarjimakinolarbizdabot"
    )

    # Bazaga saqlash
    if data['parts'] == 1:
        db.add_film(data['code'], message.video.file_id, caption)
    else:
        # Barcha qismlarni film_episodes ga saqlaymiz
        db.cursor.execute(
            "INSERT INTO film_episodes (film_code, episode_number, file_id) VALUES (?, ?, ?)",
            (data['code'], data['current'], message.video.file_id)
        )
        db.conn.commit()
    
    # Keyingi qismni yuborish yoki tugatish
    if data['current'] < data['parts']:
        user_data[chat_id]['current'] += 1
        bot.send_message(chat_id, f"🎬 {user_data[chat_id]['current']}-qismni yuboring:", reply_markup=get_cancel_keyboard())
    else:
        # ✅ HAMMASI TUGADI - KANALGA YUBORAMIZ
        bot.send_message(chat_id, f"✅ Saqlandi! Kanalga mundarija yuborilmoqda...", reply_markup=get_current_keyboard(chat_id))
    
        # Kanalga yuboriladigan matn
        channel_text = (
            f"🆕 Yangi kino qo'shildi!\n\n"
            f"🆔 Kino kodi: {data['code']}\n"
            f"🎬 Nomi: {data['name']}\n"
            f"🇺🇿 Tili: O'zbek tilida\n\n"
            f"📥 Tomosha qilish uchun botga kiring:\n"
            f"👉 @tarjimakinolarbizdabot"
        )
    
        try:
            bot.send_message(CH_ID, channel_text)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Kanalga yuborishda xato (Bot adminmi?): {e}")
    
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
            
        # Kanalga yuboriladigan matn (Video emas, faqat ma'lumot)
        channel_text = (
            f"🆕 **Yangi kino qo'shildi!**\n\n"
            f"🆔 **Kino kodi:** {data['code']}\n"
            f"🎬 **Nomi:** {data['name']}\n"
            f"🇺🇿 **Tili:** O'zbek tilida\n\n"
            f"📥 **Tomosha qilish uchun botga kiring:**\n"
            f"👉 @tarjimakinolarbizdabot"
        )
        
        try:
            bot.send_message(CH_ID, channel_text)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Kanalga yuborishda xato (Bot adminmi?): {e}")

        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
    # ----------------- 5.2. ADMIN PANEL - DRAMA QO'SHISH -----------------
user_states = {}
user_data = {}

CHANNEL_ID = -1003829109140  # Kanal IDsi

# 1️⃣ Kod so'rash
@bot.message_handler(func=lambda message: message.text == "🎭 Drama qo'shish" and db.is_admin(message.from_user.id))
def add_drama_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'drama_waiting_code'
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🎭 Drama uchun faqat RAQAMLI kod yuboring (masalan: 101)", reply_markup=get_cancel_keyboard())


# 2️⃣ Kod qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_code')
def add_drama_code(message):
    chat_id = message.chat.id
    code = message.text.strip()

    if code == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(message.from_user.id))
        return

    if not code.isdigit():
        bot.send_message(chat_id, "❌ Kod faqat raqam bo‘lishi kerak!")
        return

    if db.get_drama(code):
        bot.send_message(chat_id, "❌ Bu kod allaqachon mavjud.")
        return

    user_data[chat_id]['code'] = code
    user_states[chat_id] = 'drama_waiting_episode_count'
    bot.send_message(chat_id, "🎬 Nechta qism qo‘shmoqchisiz?", reply_markup=get_cancel_keyboard())


# 3️⃣ Qism soni qabul qilish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_episode_count')
def add_drama_episode_count(message):
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
    user_states[chat_id] = 'drama_waiting_caption'
    bot.send_message(chat_id, "📝 Drama uchun nom yuboring", reply_markup=get_cancel_keyboard())


# 4️⃣ Caption qabul qilish
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
    bot.send_message(chat_id, "🖼 Drama uchun rasm yuboring bu majburiy", reply_markup=get_cancel_keyboard())


# 5️⃣ Rasm qabul qilish
@bot.message_handler(content_types=['photo', 'text'], func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_photo')
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

    user_data[chat_id]['photo_id'] = photo_id
    user_states[chat_id] = 'drama_waiting_episode_file'
    bot.send_message(chat_id, f"🎬 1-qism video faylini yuboring:", reply_markup=get_cancel_keyboard())


# 6️⃣ Qism video qabul qilish
@bot.message_handler(content_types=['video'], func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_episode_file')
def add_drama_episode_file(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        bot.send_message(chat_id, "❌ Xatolik. Qaytadan boshlang.")
        return

    code = user_data[chat_id]['code']
    current = user_data[chat_id]['current_episode']
    total = user_data[chat_id]['episode_count']
    file_id = message.video.file_id

    # Qismni saqlash
    db.cursor.execute(
        "INSERT INTO drama_episodes (drama_code, episode_number, file_id) VALUES (?, ?, ?)",
        (code, current, file_id)
    )
    db.conn.commit()

    # Agar keyingi qism bo'lsa, so'raymiz
    if current < total:
        user_data[chat_id]['current_episode'] += 1
        bot.send_message(chat_id, f"🎬 {current+1}-qism video faylini yuboring:", reply_markup=get_cancel_keyboard())
    else:
        # Drama saqlash
        db.cursor.execute(
            "INSERT INTO dramas (code, caption, photo_id) VALUES (?, ?, ?)",
            (code, user_data[chat_id]['caption'], user_data[chat_id]['photo_id'])
        )
        db.conn.commit()

        # Kanalga caption bilan post qilish
        caption_text = f"""🆕 **Yangi kino qo'shildi!**

🆔 **Kino kodi:** {code}
🎬 **Nomi:** {user_data[chat_id]['caption']}
🇺🇿 **Tili:** O'zbek tilida

📥 **Tomosha qilish uchun botga kiring:**
👉 @tarjimakinolarbizdabot
"""
        bot.send_message(CHANNEL_ID, caption_text)

        bot.send_message(chat_id, f"✅ Drama {code} barcha qismlari qo‘shildi!", reply_markup=get_current_keyboard(message.from_user.id))
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)


# 7️⃣ Noto'g'ri fayl yuborilsa
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'drama_waiting_episode_file')
def add_drama_episode_invalid(message):
    bot.send_message(message.chat.id, "❌ Iltimos, faqat video fayl yuboring.")

# ===============================
# 🧸 MULTFILM QO'SHISH (KANALGA YUBORISH)
# ===============================

CH_ID = -1003605866510  # Kanal ID sini o'zingizga moslang

# --- Multfilm qo'shish boshlanishi ---
@bot.message_handler(func=lambda message: message.text == "🧸 Multfilm qo'shish" and db.is_admin(message.from_user.id))
def admin_start_add(message):
    chat_id = message.chat.id
    user_states[chat_id] = "waiting_code"
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🧸 Multfilm uchun noyob kod kiriting:", reply_markup=get_cancel_keyboard())

# --- Kod qabul qilish ---
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "waiting_code")
def admin_get_code(message):
    chat_id = message.chat.id
    code = message.text.strip()
    
    if code == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    cur = db.conn.cursor()
    cur.execute("SELECT code FROM cartoons WHERE code = ?", (code,))
    if cur.fetchone():
        return bot.send_message(chat_id, "❌ Bu kod allaqachon mavjud!")
    
    user_data[chat_id]["code"] = code
    user_states[chat_id] = "waiting_caption"
    bot.send_message(chat_id, "📝 Caption (matn) yuboring:", reply_markup=get_cancel_keyboard())

# --- Caption qabul qilish ---
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "waiting_caption")
def admin_get_caption(message):
    chat_id = message.chat.id
    text = message.text

    if text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    user_data[chat_id]["caption"] = text
    user_states[chat_id] = "waiting_photo"
    bot.send_message(chat_id, "🖼 Rasm yuboring yoki /skip yozing:", reply_markup=get_cancel_keyboard())

# --- Rasm yoki skip qabul qilish ---
@bot.message_handler(content_types=["photo", "text"], func=lambda message: user_states.get(message.chat.id) == "waiting_photo")
def admin_get_photo(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    if message.content_type == "photo":
        user_data[chat_id]["photo_id"] = message.photo[-1].file_id
    elif message.text == "/skip":
        user_data[chat_id]["photo_id"] = None
    else:
        return bot.send_message(chat_id, "❌ Rasm yuboring yoki /skip yozing.")
    
    user_states[chat_id] = "waiting_parts"
    bot.send_message(chat_id, "🎬 Nechta qism bor?", reply_markup=get_cancel_keyboard())

# --- Qism sonini qabul qilish ---
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "waiting_parts")
def admin_get_parts(message):
    chat_id = message.chat.id
    text = message.text

    if text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    try:
        parts = int(text.strip())
        if parts < 1: raise ValueError
    except:
        return bot.send_message(chat_id, "❌ 1 yoki undan katta son kiriting.")

    user_data[chat_id]["parts"] = parts
    user_data[chat_id]["current"] = 1
    user_states[chat_id] = "waiting_video"
    bot.send_message(chat_id, f"🎬 1-qism videoni yuboring:", reply_markup=get_cancel_keyboard())

# --- Video qabul qilish ---
@bot.message_handler(content_types=["video", "text"], func=lambda message: user_states.get(message.chat.id) == "waiting_video")
def admin_get_video(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    if message.content_type != "video":
        return bot.send_message(chat_id, "❌ Iltimos, faqat video yuboring yoki /skip.")

    data = user_data.get(chat_id)
    code, current, parts = data["code"], data["current"], data["parts"]
    file_id = message.video.file_id

    cur = db.conn.cursor()
    try:
        if current == 1:
            cur.execute("INSERT INTO cartoons (code, caption, photo_id) VALUES (?, ?, ?)", 
                        (code, data["caption"], data["photo_id"]))
        
        cur.execute("INSERT INTO cartoon_episodes (cartoon_code, episode_number, file_id) VALUES (?, ?, ?)", 
                    (code, current, file_id))
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        return bot.send_message(chat_id, f"❌ Xato: {e}")

    if current < parts:
        user_data[chat_id]["current"] += 1
        bot.send_message(chat_id, f"🎬 {current + 1}-qism videoni yuboring:", reply_markup=get_cancel_keyboard())
    else:
        # ✅ Hammasi tugadi - kanalga yuborish
        channel_text = (
            f"🆕 **Yangi kino qo'shildi!**\n\n"
            f"🆔 **Kino kodi:** {code}\n"
            f"🎬 **Nomi:** {data['caption']}\n"
            f"🇺🇿 **Tili:** O'zbek tilida\n\n"
            f"📥 **Tomosha qilish uchun botga kiring:**\n"
            f"👉 @tarjimakinolarbizdabot"
        )

        try:
            if data["photo_id"]:
                bot.send_photo(CH_ID, data["photo_id"], caption=channel_text, parse_mode="Markdown")
            else:
                bot.send_message(CH_ID, channel_text, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Kanalga yuborishda xato (Bot adminmi?): {e}")

        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
# ===============================
# 🎌 ANIME QO'SHISH (KANALGA YUBORISH)
# ===============================

CH_ID = -1003859167418  # O'zingizning kanal ID sini qo'ying

# --- Anime qo'shish boshlanishi ---
@bot.message_handler(func=lambda message: message.text == "🎌 Anime qo'shish" and db.is_admin(message.from_user.id))
def admin_start_add_anime(message):
    chat_id = message.chat.id
    user_states[chat_id] = "waiting_anime_code"
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🎌 Anime uchun noyob kod kiriting:", reply_markup=get_cancel_keyboard())

# --- Kod qabul qilish ---
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "waiting_anime_code")
def admin_get_anime_code(message):
    chat_id = message.chat.id
    code = message.text.strip()

    if code == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    cur = db.conn.cursor()
    cur.execute("SELECT code FROM animes WHERE code = ?", (code,))
    if cur.fetchone():
        return bot.send_message(chat_id, "❌ Bu kod allaqachon mavjud!")

    user_data[chat_id]["code"] = code
    user_states[chat_id] = "waiting_anime_caption"
    bot.send_message(chat_id, "📝 Anime caption yuboring:", reply_markup=get_cancel_keyboard())

# --- Caption qabul qilish ---
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "waiting_anime_caption")
def admin_get_anime_caption(message):
    chat_id = message.chat.id
    text = message.text

    if text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    user_data[chat_id]["caption"] = text
    user_states[chat_id] = "waiting_anime_photo"
    bot.send_message(chat_id, "🖼 Rasm yuboring yoki /skip yozing:", reply_markup=get_cancel_keyboard())

# --- Rasm yoki skip qabul qilish ---
@bot.message_handler(content_types=["photo", "text"], func=lambda message: user_states.get(message.chat.id) == "waiting_anime_photo")
def admin_get_anime_photo(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    if message.content_type == "photo":
        user_data[chat_id]["photo_id"] = message.photo[-1].file_id
    elif message.text == "/skip":
        user_data[chat_id]["photo_id"] = None
    else:
        return bot.send_message(chat_id, "❌ Rasm yuboring yoki /skip yozing.")

    user_states[chat_id] = "waiting_anime_parts"
    bot.send_message(chat_id, "🎬 Nechta qism bor?", reply_markup=get_cancel_keyboard())

# --- Qism sonini qabul qilish ---
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "waiting_anime_parts")
def admin_get_anime_parts(message):
    chat_id = message.chat.id
    text = message.text

    if text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    try:
        parts = int(text.strip())
        if parts < 1: raise ValueError
    except:
        return bot.send_message(chat_id, "❌ Musbat son kiriting.")

    user_data[chat_id]["parts"] = parts
    user_data[chat_id]["current"] = 1
    user_states[chat_id] = "waiting_anime_video"
    bot.send_message(chat_id, f"🎬 1-qism videoni yuboring:", reply_markup=get_cancel_keyboard())

# --- Video qabul qilish ---
@bot.message_handler(content_types=["video", "text"], func=lambda message: user_states.get(message.chat.id) == "waiting_anime_video")
def admin_get_anime_video(message):
    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_current_keyboard(chat_id))

    if message.content_type != "video":
        return bot.send_message(chat_id, "❌ Iltimos, faqat video yuboring.")

    data = user_data.get(chat_id)
    code, current, parts = data["code"], data["current"], data["parts"]
    file_id = message.video.file_id

    cur = db.conn.cursor()
    try:
        if current == 1:
            cur.execute("INSERT INTO animes (code, caption, photo_id) VALUES (?, ?, ?)", 
                        (code, data["caption"], data["photo_id"]))
        
        cur.execute("INSERT INTO anime_episodes (anime_code, episode_number, file_id) VALUES (?, ?, ?)", 
                    (code, current, file_id))
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        return bot.send_message(chat_id, f"❌ Xato: {e}")

    if current < parts:
        user_data[chat_id]["current"] += 1
        bot.send_message(chat_id, f"🎬 {current + 1}-qism videoni yuboring:", reply_markup=get_cancel_keyboard())
    else:
        # ✅ Hammasi tugadi - kanalga yuborish
        channel_text = (
            f"🆕 **Yangi anime qo'shildi!**\n\n"
            f"🆔 **Anime kodi:** {code}\n"
            f"🎬 **Nomi:** {data['caption']}\n"
            f"🇺🇿 **Tili:** O'zbek tilida\n\n"
            f"📥 **Tomosha qilish uchun botga kiring:**\n"
            f"👉 @tarjimakinolarbizdabot"
        )

        try:
            if data["photo_id"]:
                bot.send_photo(CH_ID, data["photo_id"], caption=channel_text, parse_mode="Markdown")
            else:
                bot.send_message(CH_ID, channel_text, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Kanalga yuborishda xato (Bot adminmi?): {e}")

        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)

# ----------------- 6.1. KINO QIDIRISH HANDLERI -----------------
@bot.message_handler(func=lambda message: message.text == "🎬 Kino qidirish")
def movie_search_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'search_movie'
    bot.send_message(
        chat_id, 
        "🔍 Iltimos, qidiriladigan kinoning kodini yozing:", 
        reply_markup=get_cancel_keyboard()
    )

# Kino kodini qabul qilish va chiqarish
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'search_movie')
def movie_search_execute(message):
    chat_id = message.chat.id
    query = message.text.strip()

    if query == '❌ bekor qilish' or query == '❌ Bekor Qilish':
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        return

    # Faqat kinolarni qidiradi
    film_data = db.get_film(query)

    if film_data:
        try:
            # film_data[0] -> file_id, film_data[1] -> caption
            bot.send_video(
                chat_id, 
                video=film_data[0], 
                caption=film_data[1], 
                reply_to_message_id=message.message_id
            )
        except Exception as e:
            bot.send_message(chat_id, "😔 Kino yuborishda xatolik yuz berdi.")
            logging.error(f"Kino yuborishda xatolik: {e}")
    else:
        bot.send_message(chat_id, "❌ Bu kod bo‘yicha kino topilmadi. Iltimos, tekshirib qayta yuboring.")

    # Holatni tozalash
    user_states.pop(chat_id, None)

# ----------------- DRAMA INLINE CALLBACK (TO'G'RILANGAN) -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("drama_"))
def drama_callback(call):
    chat_id = call.message.chat.id
    data = call.data.split("_")

    # data[0] har doim "drama"
    # data[1] yo buyruq (cancel, next), yo drama_code bo'ladi

    # ===== 1. BEKOR QILISH =====
    if data[1] == "cancel":
        user_states.pop(chat_id, None)
        if chat_id in user_data:
            user_data.pop(chat_id, None)
        
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        bot.answer_callback_query(call.id)
        return

    # ===== 2. KEYINGI QISMLAR (PAGINATION) =====
    if data[1] == "next":
        drama_code = data[2]
        offset = int(data[3])
        
        # Keyingi 10 ta qismni olish
        db.cursor.execute(
            "SELECT episode_number FROM drama_episodes WHERE drama_code=? ORDER BY episode_number LIMIT 10 OFFSET ?",
            (drama_code, offset)
        )
        episodes = db.cursor.fetchall()
        
        if episodes:
            keyboard = types.InlineKeyboardMarkup(row_width=5)
            # Epizod tugmalarini yig'ish
            btns = []
            for ep in episodes:
                btns.append(types.InlineKeyboardButton(
                    text=str(ep[0]),
                    callback_data=f"drama_{drama_code}_{ep[0]}" # Bu yerda drama_code va ep_soni ketadi
                ))
            keyboard.add(*btns)
            
            # Navigatsiya tugmalari
            nav_btns = []
            # Har doim "Oldingi" tugmasini ham qo'shish (agar offset 0 dan katta bo'lsa)
            if offset >= 10:
                nav_btns.append(types.InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"drama_next_{drama_code}_{offset-10}"))
            
            # Agar yana qismlar bo'lsa "Keyingi" tugmasi
            if len(episodes) == 10:
                nav_btns.append(types.InlineKeyboardButton(text="➡️ Keyingi", callback_data=f"drama_next_{drama_code}_{offset+10}"))
            
            if nav_btns:
                keyboard.add(*nav_btns)
                
            keyboard.add(types.InlineKeyboardButton(text="❌ Bekor Qilish", callback_data="drama_cancel"))
            
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=keyboard)
        
        bot.answer_callback_query(call.id)
        return

    # ===== 3. EPIZODNI OCHISH (VIDEO YUBORISH) =====
    # Agar data[1] buyruq bo'lmasa, demak u drama_code
    try:
        drama_code = data[1]
        episode_number = data[2] # Indeks 2 - qism raqami

        db.cursor.execute(
            "SELECT file_id FROM drama_episodes WHERE drama_code=? AND episode_number=?",
            (drama_code, episode_number)
        )
        episode = db.cursor.fetchone()
        
        if episode:
            # episode[0] - bu file_id
            bot.send_video(
                chat_id, 
                video=episode[0], 
                caption=f"🎭 Kod: {drama_code}\n🎬 {episode_number}-qism"
            )
            bot.answer_callback_query(call.id, f"{episode_number}-qism yuborildi")
        else:
            bot.answer_callback_query(call.id, "❌ Video fayli topilmadi", show_alert=True)
            
    except Exception as e:
        print(f"Callback xatosi: {e}")
        bot.answer_callback_query(call.id, "⚠️ Xatolik yuz berdi")
        
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

            # ===============================
# 🧸 MULTFILM QIDIRISH
# ===============================
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

    cur = db.conn.cursor()
    cur.execute(
        "SELECT code, caption, photo_id FROM cartoons WHERE LOWER(code) = ? OR LOWER(caption) LIKE ?",
        (query.lower(), f"%{query.lower()}%")
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        bot.send_message(chat_id, "❌ Bu kod yoki nom bo‘yicha multfilm topilmadi. Iltimos, qayta urinib ko‘ring.")
        user_states.pop(chat_id, None)
        return

    cartoon_code, caption, photo_id = row

    # RASM
    if photo_id:
        bot.send_photo(chat_id, photo=photo_id, caption=caption)

    # QISMLAR
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
            keyboard.add(types.InlineKeyboardButton(
                text=f"{ep[0]}-qism",
                callback_data=f"cartoon_{cartoon_code}_{ep[0]}"
            ))

        if len(episodes) > 10:
            keyboard.add(types.InlineKeyboardButton(
                text="➡️ Keyingi",
                callback_data=f"cartoon_next_{cartoon_code}_10"
            ))

        bot.send_message(chat_id, "🔹 Multfilm qismlarini tanlang:", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, "🔹 Bu multfilm hali qismlarga ega emas.")

    user_states.pop(chat_id, None)


# ===============================
# 🧸 MULTFILM QISM CALLBACK
# ===============================
@bot.callback_query_handler(func=lambda call: call.data.startswith("cartoon_"))
def cartoon_episode_callback(call):
    data = call.data.split("_")
    chat_id = call.message.chat.id

    if data[1] == 'next':  # Keyingi qismlar
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
                keyboard.add(types.InlineKeyboardButton(
                    text=f"{ep[0]}-qism",
                    callback_data=f"cartoon_{cartoon_code}_{ep[0]}"
                ))

            # Keyingi tugma
            if len(episodes) == 10:
                keyboard.add(types.InlineKeyboardButton(
                    text="➡️ Keyingi",
                    callback_data=f"cartoon_next_{cartoon_code}_{offset+10}"
                ))

            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    else:  # Videoni yuborish
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


            # ----------------- ANIME QIDIRISH HANDLERI -----------------
from telebot import types

@bot.message_handler(func=lambda message: message.text == "🎌 Anime qidirish")
def anime_search_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'search_anime'
    bot.send_message(
        chat_id,
        "🔍 Iltimos, qidiriladigan anime kodini yozing:",
        reply_markup=get_cancel_keyboard()
    )

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'search_anime')
def anime_search_execute(message):
    chat_id = message.chat.id
    query = message.text.strip()

    if query.lower() in ['❌ bekor qilish', '/cancel']:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())
        return

    # ----------------- ANIME MA'LUMOTINI OLISH -----------------
    cur = db.conn.cursor()
    cur.execute(
        "SELECT code, caption, photo_id FROM animes WHERE LOWER(code) = ?",
        (query.lower(),)
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        bot.send_message(chat_id, "❌ Bu kod bo‘yicha anime topilmadi. Iltimos, qayta urinib ko‘ring.")
        user_states.pop(chat_id, None)
        return

    anime_code, caption, photo_id = row

    # ----------------- ANIME RASMI / VIDEO -----------------
    # Agar rasm mavjud bo'lsa rasmni yuboramiz
    if photo_id:
        bot.send_photo(chat_id, photo=photo_id, caption=caption)
    else:
        # Rasm bo'lmasa xabar yuboramiz
        bot.send_message(chat_id, caption)

    # ----------------- QISMLARINI OLISH -----------------
    cur = db.conn.cursor()
    cur.execute(
        "SELECT episode_number, file_id FROM anime_episodes WHERE anime_code = ? ORDER BY episode_number ASC",
        (anime_code,)
    )
    episodes = cur.fetchall()
    cur.close()

    if episodes:
        keyboard = types.InlineKeyboardMarkup(row_width=5)
        for ep in episodes[:10]:  # birinchi 10 qism
            keyboard.add(types.InlineKeyboardButton(
                text=f"{ep[0]}-qism",
                callback_data=f"anime_{anime_code}_{ep[0]}"
            ))

        if len(episodes) > 10:
            keyboard.add(types.InlineKeyboardButton(
                text="➡️ Keyingi",
                callback_data=f"anime_next_{anime_code}_10"
            ))

        bot.send_message(chat_id, "🔹 Anime qismlarini tanlang:", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, "🔹 Bu anime hali qismlarga ega emas.")

    user_states.pop(chat_id, None)


# ----------------- ANIME QISM CALLBACK -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("anime_"))
def anime_episode_callback(call):
    data = call.data.split("_")
    chat_id = call.message.chat.id

    if data[1] == 'next':  # Keyingi qismlar
        anime_code = data[2]
        offset = int(data[3])

        cur = db.conn.cursor()
        cur.execute(
            "SELECT episode_number, file_id FROM anime_episodes WHERE anime_code = ? ORDER BY episode_number ASC LIMIT 10 OFFSET ?",
            (anime_code, offset)
        )
        episodes = cur.fetchall()
        cur.close()

        if episodes:
            keyboard = types.InlineKeyboardMarkup(row_width=5)
            for ep in episodes:
                keyboard.add(types.InlineKeyboardButton(
                    text=f"{ep[0]}-qism",
                    callback_data=f"anime_{anime_code}_{ep[0]}"
                ))

            # Keyingi tugma
            if len(episodes) == 10:
                keyboard.add(types.InlineKeyboardButton(
                    text="➡️ Keyingi",
                    callback_data=f"anime_next_{anime_code}_{offset+10}"
                ))

            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    else:  # Videoni yuborish
        anime_code = data[1]
        episode_number = int(data[2])

        cur = db.conn.cursor()
        cur.execute(
            "SELECT file_id FROM anime_episodes WHERE anime_code = ? AND episode_number = ?",
            (anime_code, episode_number)
        )
        ep_row = cur.fetchone()
        cur.close()

        if ep_row:
            bot.send_video(chat_id, ep_row[0], caption=f"{anime_code} - {episode_number}-qism")
            bot.answer_callback_query(call.id, f"{episode_number}-qism ochildi")
        else:
            bot.answer_callback_query(call.id, "❌ Qism topilmadi")



# ----------------- FOYDALANUVCHI QIDIRUV HANDLERLARI -----------------
@bot.message_handler(func=lambda message: message.text in ["🎬 Kino qidirish", "🎭 Drama qidirish", "🧸 Multfilm qidirish", "🎌 Anime qidirish"])
def user_search_start(message):
    chat_id = message.chat.id
    text = message.text
    user_id = message.from_user.id

    # Foydalanuvchini bazaga qo'shish / faollik yangilash
    db.add_user(user_id)

    # Qidiruv turini saqlaymiz
    user_states[chat_id] = 'searching'
    user_data[chat_id] = {'type': text}  # Kino, Drama, Multfilm yoki Anime

    # Turga mos xabar yuborish
    if text == "🎬 Kino qidirish":
        bot.send_message(chat_id, "🎬 Kino kodini yoki nomini yozing:", reply_markup=get_cancel_keyboard())
    elif text == "🎭 Drama qidirish":
        bot.send_message(chat_id, "🎭 Drama kodini yoki nomini yozing:", reply_markup=get_cancel_keyboard())
    elif text == "🧸 Multfilm qidirish":
        bot.send_message(chat_id, "🧸 Multfilm kodini yoki nomini yozing:", reply_markup=get_cancel_keyboard())
    elif text == "🎌 Anime qidirish":
        bot.send_message(chat_id, "🎌 Anime kodini yoki nomini yozing:", reply_markup=get_cancel_keyboard())
# ----------------- GLOBAL BEKOR QILISH -----------------
@bot.message_handler(func=lambda m: m.text == "❌ Bekor Qilish")
def global_cancel(message):
    chat_id = message.chat.id
    if chat_id in user_states:
        user_states.pop(chat_id, None)
    if chat_id in user_data:
        user_data.pop(chat_id, None)
    bot.send_message(chat_id, "✅ Amal bekor qilindi.", reply_markup=get_user_keyboard())


# ----------------- FOYDALANUVCHI QIDIRUV (KINO, DRAMA, MULTFILM, ANIME) -----------------
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'searching')
def user_search_query(message):
    chat_id = message.chat.id
    search_type = user_data[chat_id]['type']
    query = message.text.strip()

    # ----------------- KINO -----------------
    if search_type == "🎬 Kino qidirish":
        results = db.search_films(query)
        if results:
            for film in results:
                bot.send_video(chat_id, video=film['file_id'], caption=f"🎬 {film['code']}\n{film['caption']}")
        else:
            bot.send_message(chat_id, "❌ Kino topilmadi.")

    # ----------------- DRAMA -----------------
    elif search_type == "🎭 Drama qidirish":
        db.cursor.execute(
            "SELECT code, caption, photo_id FROM dramas WHERE code = ?",
            (query,)
        )
        drama = db.cursor.fetchone()
        if not drama:
            bot.send_message(chat_id, "❌ Drama topilmadi.")
            return

        code, caption, photo_id = drama
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
        markup.add(types.InlineKeyboardButton(
            text="❌ Bekor Qilish",
            callback_data="drama_cancel"
        ))
        bot.send_photo(chat_id, photo_id, caption=caption, reply_markup=markup)

    # ----------------- MULTFILM -----------------
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

    # ----------------- ANIME -----------------
    elif search_type == "🎌 Anime qidirish":
        db.cursor.execute(
            "SELECT code, caption, photo_id FROM animes WHERE code LIKE ? OR caption LIKE ?",
            (f"%{query}%", f"%{query}%")
        )
        animes = db.cursor.fetchall()
        if animes:
            for anime in animes:
                code, caption, photo_id = anime
                markup = types.InlineKeyboardMarkup(row_width=5)
                db.cursor.execute(
                    "SELECT episode_number FROM anime_episodes WHERE anime_code=? ORDER BY episode_number",
                    (code,)
                )
                episodes = db.cursor.fetchall()
                if episodes:
                    for ep in episodes[:10]:
                        markup.add(types.InlineKeyboardButton(
                            text=str(ep[0]),
                            callback_data=f"anime_{code}_{ep[0]}"
                        ))
                    if len(episodes) > 10:
                        markup.add(types.InlineKeyboardButton(
                            text="➡️ Keyingi",
                            callback_data=f"anime_next_{code}_10"
                        ))
                markup.add(types.InlineKeyboardButton(
                    text="❌ Bekor Qilish",
                    callback_data="anime_cancel"
                ))
                bot.send_photo(chat_id, photo_id, caption=caption, reply_markup=markup)
        else:
            bot.send_message(chat_id, "❌ Anime topilmadi.")

    # ----------------- Holatni tozalash -----------------
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
@bot.callback_query_handler(func=lambda call: call.data.startswith("cartoon_"))
def cartoon_episode_buttons(call):
    chat_id = call.message.chat.id
    data = call.data

    # ----------------- MULTFILM QISM TANLASH -----------------
    if data.startswith("cartoon_") and not data.startswith("cartoon_next_"):
        _, code, ep = data.split("_")
        cur = db.conn.cursor()
        cur.execute(
            "SELECT file_id, caption FROM cartoon_episodes WHERE cartoon_code=? AND episode_number=?",
            (code, ep)
        )
        episode = cur.fetchone()
        cur.close()

        if episode:
            file_id, caption = episode
            bot.send_video(chat_id, file_id, caption=f"{caption}\n🧸 Multfilm {code} | Qism {ep}")

        bot.answer_callback_query(call.id, f"{ep}-qism ochildi")
        return

    # ----------------- MULTFILM KEYINGI QISMLAR -----------------
    elif data.startswith("cartoon_next_"):
        _, code, offset = data.split("_")
        offset = int(offset)

        cur = db.conn.cursor()
        cur.execute(
            "SELECT episode_number FROM cartoon_episodes WHERE cartoon_code=? ORDER BY episode_number ASC LIMIT 10 OFFSET ?",
            (code, offset)
        )
        episodes = cur.fetchall()
        cur.close()

        if episodes:
            keyboard = types.InlineKeyboardMarkup(row_width=5)
            for ep in episodes:
                keyboard.add(types.InlineKeyboardButton(
                    text=f"{ep[0]}-qism",
                    callback_data=f"cartoon_{code}_{ep[0]}"
                ))

            # Keyingi tugma
            if len(episodes) == 10:
                keyboard.add(types.InlineKeyboardButton(
                    text="➡️ Keyingi",
                    callback_data=f"cartoon_next_{code}_{offset+10}"
                ))

            # Bekor qilish tugmasi
            keyboard.add(types.InlineKeyboardButton(
                text="❌ Bekor Qilish",
                callback_data="cartoon_cancel"
            ))

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
   # ================== ANIME O'CHIRISH ==================
@bot.message_handler(func=lambda message: message.text == "🗑️ Anime o'chirish" and db.is_admin(message.from_user.id))
def anime_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_anime_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan animening **kodini** yuboring.", reply_markup=get_cancel_keyboard())


@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_anime_waiting_for_code')
def anime_delete_code(message):
    chat_id = message.chat.id
    anime_code = message.text.strip()

    # Anime mavjudligini tekshirish
    cur = db.conn.cursor()
    cur.execute("SELECT code FROM animes WHERE code=?", (anime_code,))
    if not cur.fetchone():
        bot.send_message(chat_id, f"❌ Uzr, **{anime_code}** kodli anime topilmadi.", reply_markup=get_current_keyboard(message.from_user.id))
        cur.close()
        user_states.pop(chat_id, None)
        return

    try:
        # Anime asosiy jadvaldan o'chirish
        cur.execute("DELETE FROM animes WHERE code=?", (anime_code,))
        # Anime qismlarini o'chirish
        cur.execute("DELETE FROM anime_episodes WHERE anime_code=?", (anime_code,))
        db.conn.commit()
        bot.send_message(chat_id, f"✅ **{anime_code}** kodli anime ma'lumotlar bazasidan o'chirildi.", reply_markup=get_current_keyboard(message.from_user.id))
    except Exception as e:
        db.conn.rollback()
        bot.send_message(chat_id, f"❌ Xato yuz berdi: {e}")
    finally:
        cur.close()
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

# ===================== 🎌 ANIME INLINE QIDIRUV =====================
    elif search_type == "🎌 Anime qidirish":
         query_like = f"%{query}%"
    db.cursor.execute(
        "SELECT code, caption FROM animes WHERE code LIKE ? OR caption LIKE ?",
        (query_like, query_like)
    )
    animes = db.cursor.fetchall()

    if animes:
        results = []
        for i, (code, caption) in enumerate(animes):
            keyboard = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    text="▶️ Animeni ochish",
                    url=f"https://t.me/{bot.get_me().username}?start={code}"
                )
            )

            article = types.InlineQueryResultArticle(
                id=f"anime_{i}",
                title=f"🎌 Anime | {code}",
                description=caption,
                input_message_content=types.InputTextMessageContent(message_text=code),
                reply_markup=keyboard
            )
            results.append(article)

        bot.answer_inline_query(
            inline_query_id=message.id,
            results=results,
            cache_time=300
        )
    else:
        bot.answer_inline_query(
            inline_query_id=message.id,
            results=[],
            cache_time=10,
            switch_pm_text="❌ Hech nima topilmadi",
            switch_pm_parameter="start"
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

    # ================= KINO =================
    if text == "🎬 Kino qo'shish":
        user_states[chat_id] = 'add_film'
        bot.send_message(chat_id, "🎬 Kino qo'shish: kodni kiriting.")
        return

    if text == "🗑️ Kino o'chirish":
        user_states[chat_id] = 'delete_film_waiting_for_code'
        bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan kinoning kodini kiriting.", reply_markup=get_cancel_keyboard())
        return

    # ================= DRAMA =================
    if text == "🎭 Drama qo'shish":
        user_states[chat_id] = 'add_drama'
        bot.send_message(chat_id, "🎭 Drama qo'shish: kodni kiriting.")
        return

    if text == "🗑️ Drama o'chirish":
        user_states[chat_id] = 'delete_drama_waiting_for_code'
        bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan dramaning kodini kiriting.", reply_markup=get_cancel_keyboard())
        return

    # ================= MULTFILM =================
    if text == "🧸 Multfilm qo'shish":
        user_states[chat_id] = 'add_cartoon'
        bot.send_message(chat_id, "🧸 Multfilm qo'shish: kodni kiriting.")
        return

    if text == "🗑️ Multfilm o'chirish":
        user_states[chat_id] = 'delete_cartoon_waiting_for_code'
        bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan multfilmning kodini kiriting.", reply_markup=get_cancel_keyboard())
        return

    # ================= ANIME =================
    if text == "🎌 Anime qo'shish":
        user_states[chat_id] = 'add_anime'
        bot.send_message(chat_id, "🎌 Anime qo'shish: kodni kiriting.")
        return

    if text == "🗑️ Anime o'chirish":
        user_states[chat_id] = 'delete_anime_waiting_for_code'
        bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan animening kodini kiriting.", reply_markup=get_cancel_keyboard())
        return

    # ================= REKLAMA =================
    if text == "📢 Reklama":
        user_states[chat_id] = 'send_ad'
        bot.send_message(chat_id, "📢 Reklama yuborish uchun matnni kiriting:")
        return

    # ================= STATISTIKA =================
    if text == "📊 Statistika":
        stats = db.get_stats()  # bazangizdagi statistika funksiyasi
        bot.send_message(chat_id, stats)
        return

    # ================= DEFAULT =================
    bot.send_message(chat_id, "❌ Noma'lum buyruq. Iltimos, menyudan tanlang.", reply_markup=get_super_admin_keyboard())


# ---------- SUPER ADMIN ---------- 
SUPER_ADMIN = [8165064673]

# ---------- ADMIN/USER FUNKSIYALARI ----------
def is_admin(chat_id):
    """Foydalanuvchi super admin yoki admin ekanligini tekshiradi"""
    return chat_id in SUPER_ADMIN  # Faqat super adminlar reklama/statistika ishlata oladi

# ---------- STATISTIKA FUNKSIYALARI ----------
def count_users():
    db.cursor.execute("SELECT COUNT(*) FROM users")
    return db.cursor.fetchone()[0]

def get_all_users():
    db.cursor.execute("SELECT user_id FROM users")
    return [r[0] for r in db.cursor.fetchall()]

def get_blocked_users():
    db.cursor.execute("SELECT user_id FROM users WHERE is_blocked=1")
    return [r[0] for r in db.cursor.fetchall()]

def is_online(user_id):
    db.cursor.execute("SELECT last_active FROM users WHERE user_id=?", (user_id,))
    row = db.cursor.fetchone()
    if not row:
        return False
    try:
        last_active = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    except:
        return False
    return datetime.now() - last_active < timedelta(minutes=5)  # oxirgi 5 daqiqa ichida aktiv
# ---------- REKLAMA FUNKSIYASI (ALOHIDA OQIMDA) ----------
def send_ads_thread(chat_id, data, all_users):
    count = 0

    for user in all_users:
        uid = user[0]  # database tuple qaytaradi shuning uchun [0]

        try:
            if data['type'] == 'text':
                bot.send_message(uid, data['text'])

            elif data['type'] == 'photo':
                bot.send_photo(uid, data['file_id'], caption=data.get('caption', ''))

            elif data['type'] == 'video':
                bot.send_video(uid, data['file_id'], caption=data.get('caption', ''))

            count += 1

            # Telegram bloklamasligi uchun
            if count % 25 == 0:
                time.sleep(1)

        except Exception as e:
            print(f"{uid} ga yuborilmadi: {e}")
            continue

    bot.send_message(chat_id, f"✅ Reklama yakunlandi! {count} kishiga yuborildi.")


# ---------- HANDLERLAR ----------

@bot.message_handler(func=lambda message: message.text == "📢 Reklama")
def ad_start(message):
    if not db.is_admin(message.from_user.id):
        return

    chat_id = message.chat.id
    user_states[chat_id] = 'ad_content'

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("❌ Bekor Qilish")

    bot.send_message(
        chat_id,
        "📝 Reklama xabarini yuboring (Matn, Rasm yoki Video):",
        reply_markup=markup
    )


@bot.message_handler(content_types=['text','photo','video'],
func=lambda message: user_states.get(message.chat.id) == 'ad_content')
def ad_process(message):

    chat_id = message.chat.id

    if message.text == "❌ Bekor Qilish":
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "✅ Bekor qilindi.", reply_markup=get_current_keyboard(chat_id))
        return

    content = {}

    if message.content_type == 'text':
        content = {
            'type': 'text',
            'text': message.text
        }

    elif message.content_type == 'photo':
        content = {
            'type': 'photo',
            'file_id': message.photo[-1].file_id,
            'caption': message.caption
        }

    elif message.content_type == 'video':
        content = {
            'type': 'video',
            'file_id': message.video.file_id,
            'caption': message.caption
        }

    user_data[chat_id] = content
    user_states[chat_id] = 'ad_confirm'

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Yuborish", callback_data="ad_send"),
        types.InlineKeyboardButton("❌ Bekor qilish", callback_data="ad_cancel")
    )

    bot.send_message(chat_id, "Ushbu xabar hammaga yuborilsinmi?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ['ad_send','ad_cancel'])
def ad_callback(call):

    chat_id = call.message.chat.id

    if call.data == 'ad_send':

        data = user_data.get(chat_id)

        if not data:
            bot.edit_message_text(
                "❌ Ma'lumot muddati o'tgan. Qaytadan urinib ko'ring.",
                chat_id,
                call.message.message_id
            )
            return

        all_users = db.get_all_users()

        if not all_users:
            bot.send_message(chat_id, "❌ Foydalanuvchilar bazasi bo'sh!")
            return

        bot.edit_message_text(
            f"🚀 Yuborish boshlandi (Jami: {len(all_users)} ta user)...",
            chat_id,
            call.message.message_id
        )

        threading.Thread(
            target=send_ads_thread,
            args=(chat_id, data, all_users)
        ).start()

    else:
        bot.edit_message_text(
            "❌ Reklama rad etildi.",
            chat_id,
            call.message.message_id
        )

    user_states.pop(chat_id, None)

# ---------- STATISTIKA ----------

@bot.message_handler(func=lambda message: message.text == "📊 Statistika")
def show_statistics(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        bot.send_message(chat_id, "❌ Sizda ruxsat yo'q.")
        return

    total = count_users()
    blocked = len(get_blocked_users())
    active = sum(1 for uid in get_all_users() if is_online(uid))

    text = f"📊 Bot Statistikasi:\n\n" \
           f"👤 Foydalanuvchilar: {total}\n" \
           f"⛔ Bloklanganlar: {blocked}\n" \
           f"🟢 Faol: {active}"

    bot.send_message(chat_id, text)
# --- BOTNI ISHGA TUSHIRISH ---

if __name__ == "__main__":
    keep_alive()
    logging.info("Bot ishga tushirildi...")
    bot.infinity_polling(skip_pending=True)
