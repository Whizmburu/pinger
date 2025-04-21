# bot.py

import os, re, json, time, logging
from pathlib import Path
from uuid import uuid4
from collections import defaultdict

import yt_dlp
import telebot
from telebot import types

import config

# ─── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

# ─── Ensure download folder ────────────────────────────────────
Path(config.DOWNLOAD_DIR).mkdir(exist_ok=True)

# ─── Simple JSON DB for user IDs ───────────────────────────────
def load_users():
    if os.path.exists(config.DB_FILE):
        return json.load(open(config.DB_FILE))
    return []

def save_users(u):
    json.dump(u, open(config.DB_FILE, 'w'))

users = load_users()

# ─── In‑memory rate‑limit & pending downloads ───────────────────
user_requests    = defaultdict(list)  # uid → [timestamps]
pending_downloads = {}               # key → (url, format_id, is_audio)

def cleanup_requests():
    cutoff = time.time() - 3600
    for uid, stamps in list(user_requests.items()):
        user_requests[uid] = [ts for ts in stamps if ts > cutoff]

def cleanup_downloads():
    now = time.time()
    for f in Path(config.DOWNLOAD_DIR).iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > config.FILE_TTL:
            try: f.unlink()
            except: pass

# initial cleanup
cleanup_downloads()

# ─── Inline Menu ───────────────────────────────────────────────
menu_kb = types.InlineKeyboardMarkup(row_width=2)
menu_kb.add(
    types.InlineKeyboardButton("📥 How to Use",       callback_data="how_to_use"),
    types.InlineKeyboardButton("📢 Updates Channel",  url=f"https://t.me/{config.UPDATE_CHANNEL.strip('@')}"),
    types.InlineKeyboardButton("💬 Contact Admin",    url=f"https://t.me/{config.ADMIN_USERNAME}")
)

# ─── /start with Force‑Join ────────────────────────────────────
@bot.message_handler(commands=['start'])
def handle_start(msg):
    uid, cid = msg.from_user.id, msg.chat.id

    # Force‑join check
    try:
        m = bot.get_chat_member(config.UPDATE_CHANNEL, uid)
        if m.status not in ['member','creator','administrator']:
            raise Exception()
    except:
        join_text = (
            "🚫 You must join our 📢 *Updates Channel* to use this bot.\n\n"
            f"👉 [Join Now](https://t.me/{config.UPDATE_CHANNEL.strip('@')})\n\n"
            "Then press ✅ *I’ve Joined*"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ I’ve Joined", callback_data='check_join'))
        return bot.send_message(cid, join_text, parse_mode='Markdown', reply_markup=kb)

    # Save new user
    if uid not in users:
        users.append(uid)
        save_users(users)

    # Welcome + menu
    welcome = (
        f"👋 Hello, *{msg.from_user.first_name}*!\n\n"
        "I can help you download videos/audio from:\n"
        "📺 YouTube | 🎵 TikTok | 📸 Instagram | 🐦 Twitter | 📘 Facebook\n\n"
        "👇 Paste any supported link, or pick an option:"
    )
    bot.send_message(cid, welcome, parse_mode='Markdown', reply_markup=menu_kb)

# ─── Re‑check Join ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == 'check_join')
def cb_check_join(call):
    uid = call.from_user.id
    try:
        m = bot.get_chat_member(config.UPDATE_CHANNEL, uid)
        if m.status in ['member','creator','administrator']:
            if uid not in users:
                users.append(uid); save_users(users)
            bot.answer_callback_query(call.id, "✅ You're in! Welcome.")
            return handle_start(call.message)
        else:
            bot.answer_callback_query(call.id, "🚫 Still not joined.")
    except:
        bot.answer_callback_query(call.id, "⚠️ Error checking membership.")

# ─── How to Use ────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == 'how_to_use')
def cb_how_to_use(call):
    text = (
        "📥 *How to Use:* \n\n"
        "1. Copy a link from YouTube, TikTok, Instagram, Facebook, or Twitter.\n"
        "2. Paste it here.\n"
        "3. Choose your preferred format (resolution or MP3).\n"
        "4. Receive your file right in this chat! 🎉\n\n"
        f"🔄 Limit: {config.HOURLY_LIMIT} downloads per hour."
    )
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown')

# ─── /help & /menu ─────────────────────────────────────────────
@bot.message_handler(commands=['help','menu'])
def handle_help(msg):
    text = (
        "📚 *Help & Menu*\n\n"
        "- Use /start to re-open the menu.\n"
        "- Paste a supported link to begin.\n"
        f"- Download limit: {config.HOURLY_LIMIT}× per hour.\n"
    )
    bot.send_message(msg.chat.id, text, parse_mode='Markdown', reply_markup=menu_kb)

# ─── Capture URLs & List Formats ──────────────────────────────
@bot.message_handler(regexp=r'https?://\S+')
def handle_url(msg):
    uid, cid = msg.from_user.id, msg.chat.id
    url = re.search(r'https?://\S+', msg.text).group(0)

    cleanup_requests()
    if len(user_requests[uid]) >= config.HOURLY_LIMIT:
        return bot.send_message(cid,
            f"⚠️ Hourly limit reached ({config.HOURLY_LIMIT}). Try again later.")

    status = bot.send_message(cid, "🔎 Fetching available formats…")
    try:
        with yt_dlp.YoutubeDL({'quiet':True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        bot.delete_message(cid, status.message_id)
        return bot.send_message(cid,
            "❌ Could not extract info. Make sure the link is valid & supported.")

    # Video formats by resolution
    fmts = info.get('formats', [])
    vids = [f for f in fmts if f.get('vcodec')!='none' and f.get('filesize_approx')]
    res_map = {}
    for f in vids:
        h = f.get('height') or 0
        label = f"{h}p"
        best = res_map.get(label)
        if not best or f.get('tbr',0)>best.get('tbr',0):
            res_map[label] = f

    # Best audio‑only
    auds = [f for f in fmts if f.get('acodec')!='none' and f.get('vcodec')=='none']
    best_audio = max(auds, key=lambda x: x.get('abr',0), default=None)

    # Build buttons
    buttons = []
    for label, f in sorted(res_map.items(), key=lambda x: int(x[0][:-1]), reverse=True):
        key = str(uuid4())
        pending_downloads[key] = (url, f['format_id'], False)
        buttons.append(types.InlineKeyboardButton(label, callback_data=f"dl_{key}"))
    if best_audio:
        key = str(uuid4())
        pending_downloads[key] = (url, best_audio['format_id'], True)
        buttons.append(types.InlineKeyboardButton("🎵 MP3 Audio", callback_data=f"dl_{key}"))

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(*buttons)
    bot.delete_message(cid, status.message_id)
    bot.send_message(cid, "📋 Choose a format:", reply_markup=kb)

# ─── Handle Format Selection & Download ────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith('dl_'))
def cb_download(c):
    uid, cid = c.from_user.id, c.message.chat.id
    key = c.data.split('_',1)[1]
    data = pending_downloads.pop(key, None)
    if not data:
        return bot.answer_callback_query(c.id, "⚠️ Expired request.")
    url, fmt_id, is_audio = data

    cleanup_requests()
    if len(user_requests[uid]) >= config.HOURLY_LIMIT:
        return bot.answer_callback_query(c.id,
            f"⚠️ Hourly limit reached ({config.HOURLY_LIMIT}).")

    bot.answer_callback_query(c.id, "⬇️ Downloading…")
    try:
        ydl_opts = {
            'format': fmt_id,
            'outtmpl': os.path.join(config.DOWNLOAD_DIR, '%(id)s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
        }
        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if is_audio:
                filepath = os.path.splitext(filepath)[0] + '.mp3'

        size = os.path.getsize(filepath)
        if size > config.TELEGRAM_MAX_FILE_SIZE:
            os.remove(filepath)
            return bot.send_message(cid,
                f"⚠️ File too large ({size/1e6:.1f} MB). Limit: "
                f"{config.TELEGRAM_MAX_FILE_SIZE/1e6:.0f} MB.")

        with open(filepath, 'rb') as f:
            if not is_audio and filepath.lower().endswith(('.mp4','.mkv','.webm')):
                bot.send_video(cid, f, caption="🎬 Here’s your video!")
            else:
                bot.send_audio(cid, f, caption="🎧 Here’s your audio!")
        user_requests[uid].append(time.time())

    except Exception:
        logging.exception("Download error")
        bot.send_message(cid,
            "❌ Something went wrong. Please try again later.")
    finally:
        cleanup_downloads()

# ─── Admin Broadcast ───────────────────────────────────────────
@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(msg):
    if msg.from_user.id != config.ADMIN_ID:
        return bot.reply_to(msg, "❌ You’re not authorized.")
    text = msg.text.partition(' ')[2].strip()
    if not text:
        return bot.reply_to(msg, "Usage: /broadcast Your message here")
    sent = 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 *Update:*\n\n{text}",
                             parse_mode='Markdown')
            sent += 1
        except:
            pass
    bot.reply_to(msg, f"✅ Broadcast sent to {sent} users.")

# ─── Run ────────────────────────────────────────────────────────
if __name__ == '__main__':
    logging.info("🤖 whizsaverbot started")
    bot.infinity_polling(timeout=60)
