#!/usr/bin/env python3
# ============================================
# TELEGRAM FILE SHARING BOT - COMPLETE WORKING VERSION
# With Keep-Alive Ping to prevent Render from sleeping
# ============================================

import os
import sys
import sqlite3
import secrets
import logging
import re
import requests
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ParseMode
)
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, CallbackContext
)
from dotenv import load_dotenv
from aiohttp import web
import asyncio

# Load environment variables
load_dotenv()

# ============================================
# CONFIG
# ============================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
DB_PATH = os.getenv('DB_PATH', './data/bot_database.db')
MAX_FILE_SIZE_SEND = 50 * 1024 * 1024  # 50MB for direct send
PORT = int(os.getenv('PORT', 10000))
RENDER_URL = os.getenv('RENDER_URL', '')  # Your Render URL (e.g., https://your-bot.onrender.com)

if not BOT_TOKEN:
    print('❌ BOT_TOKEN is not set in environment variables')
    sys.exit(1)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================
# REQUIRED CHANNELS
# ============================================
REQUIRED_CHANNELS = [
    {
        'name': '@NCK_Dev',
        'type': 'public',
        'identifier': '@NCK_Dev',
        'link': 'https://t.me/NCK_Dev',
        'channel_id': None
    },
    {
        'name': '+Yl4nKkthd1ExZWVk',
        'type': 'private',
        'identifier': '-1004266231051',
        'link': 'https://t.me/+Yl4nKkthd1ExZWVk',
        'channel_id': -1004266231051
    }
]

# ============================================
# EXPIRY MAPPING
# ============================================
EXPIRY_MAP = {
    '5min': 5 * 60,
    '10min': 10 * 60,
    '15min': 15 * 60,
    '30min': 30 * 60,
    '1hr': 60 * 60,
    '2hr': 2 * 60 * 60,
    '24hr': 24 * 60 * 60,
    'permanent': None
}


# ============================================
# KEEP ALIVE FUNCTION
# ============================================
def keep_alive():
    """Keep the bot alive by pinging the health endpoint periodically"""
    url = RENDER_URL or f'https://telegram-sub2unlock-bot.onrender.com/health'
    
    while True:
        try:
            response = requests.get(url, timeout=10)
            logger.info(f'💓 Keep-alive ping sent: {response.status_code}')
        except Exception as e:
            logger.error(f'❌ Keep-alive ping failed: {e}')
        time.sleep(300)  # Ping every 5 minutes


# ============================================
# DATABASE CLASS
# ============================================
class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self.init_db()

    def init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        cursor = self.conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_required INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT,
                channel_id INTEGER,
                channel_type TEXT,
                link TEXT,
                verified INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_name TEXT,
                channel_id INTEGER,
                channel_type TEXT,
                link TEXT,
                verified INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                name TEXT,
                size INTEGER,
                mime_type TEXT,
                file_id TEXT,
                from_chat_id INTEGER,
                original_message_id INTEGER,
                is_forwarded INTEGER DEFAULT 0,
                link_code TEXT UNIQUE,
                expiry DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                downloads INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_channels (
                file_id TEXT,
                channel_id INTEGER,
                FOREIGN KEY (file_id) REFERENCES files(id),
                FOREIGN KEY (channel_id) REFERENCES user_channels(id)
            )
        ''')

        self.conn.commit()
        self.save_required_channels()
        logger.info('✅ SQLite Database initialized')

    def save_required_channels(self):
        cursor = self.conn.cursor()
        for channel in REQUIRED_CHANNELS:
            if channel['channel_id']:
                cursor.execute(
                    '''INSERT OR REPLACE INTO required_channels 
                       (channel_name, channel_id, channel_type, link) 
                       VALUES (?, ?, ?, ?)''',
                    (channel['name'], channel['channel_id'], channel['type'], channel['link'])
                )
            else:
                cursor.execute(
                    '''INSERT OR IGNORE INTO required_channels 
                       (channel_name, channel_type, link) 
                       VALUES (?, ?, ?)''',
                    (channel['name'], channel['type'], channel['link'])
                )
        self.conn.commit()

    def get_required_channels(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM required_channels WHERE verified = 1')
        return [dict(row) for row in cursor.fetchall()]

    def update_required_channel_id(self, channel_name: str, channel_id: int):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE required_channels SET channel_id = ? WHERE channel_name = ?',
            (channel_id, channel_name)
        )
        self.conn.commit()

    def update_channel_link(self, channel_name: str, link: str):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE required_channels SET link = ? WHERE channel_name = ?',
            (link, channel_name)
        )
        self.conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def create_user(self, user_id: int, username: str, first_name: str):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
            (user_id, username or '', first_name)
        )
        self.conn.commit()

    def mark_required_joined(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE users SET joined_required = 1 WHERE user_id = ?',
            (user_id,)
        )
        self.conn.commit()

    def add_user_channel(self, user_id: int, channel_info: Dict) -> Dict:
        cursor = self.conn.cursor()
        cursor.execute(
            '''INSERT INTO user_channels 
               (user_id, channel_name, channel_id, channel_type, link) 
               VALUES (?, ?, ?, ?, ?)''',
            (user_id, channel_info['name'], channel_info['channel_id'],
             channel_info['type'], channel_info['link'])
        )
        self.conn.commit()
        channel_info['id'] = cursor.lastrowid
        return channel_info

    def get_user_channels(self, user_id: int) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM user_channels WHERE user_id = ? AND verified = 1',
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def remove_user_channel(self, user_id: int, channel_id: int):
        cursor = self.conn.cursor()
        cursor.execute(
            'DELETE FROM user_channels WHERE user_id = ? AND id = ?',
            (user_id, channel_id)
        )
        self.conn.commit()

    def create_file(self, file_data: Dict) -> Dict:
        link_code = secrets.token_hex(16)
        cursor = self.conn.cursor()
        cursor.execute(
            '''INSERT INTO files 
               (id, user_id, name, size, mime_type, file_id, from_chat_id, 
                original_message_id, is_forwarded, link_code, expiry) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                file_data['id'], file_data['user_id'], file_data['name'],
                file_data['size'], file_data.get('mime_type', ''),
                file_data.get('file_id'), file_data.get('from_chat_id'),
                file_data.get('original_message_id'),
                1 if file_data.get('is_forwarded') else 0,
                link_code, file_data.get('expiry')
            )
        )
        self.conn.commit()
        return {'id': file_data['id'], 'link_code': link_code}

    def get_file_by_link(self, link_code: str) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            '''SELECT f.*, 
               GROUP_CONCAT(uc.id) as channel_ids,
               GROUP_CONCAT(uc.channel_name) as channel_names
               FROM files f
               LEFT JOIN file_channels fc ON f.id = fc.file_id
               LEFT JOIN user_channels uc ON fc.channel_id = uc.id
               WHERE f.link_code = ? AND f.is_active = 1
               GROUP BY f.id''',
            (link_code,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM files WHERE id = ? AND is_active = 1',
            (file_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_files(self, user_id: int) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM files WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC',
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_total_files(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM files WHERE is_active = 1')
        row = cursor.fetchone()
        return row['count'] if row else 0

    def increment_downloads(self, file_id: str):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE files SET downloads = downloads + 1 WHERE id = ?',
            (file_id,)
        )
        self.conn.commit()

    def delete_file(self, file_id: str):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE files SET is_active = 0 WHERE id = ?',
            (file_id,)
        )
        self.conn.commit()

    def cleanup_expired_files(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE files SET is_active = 0 WHERE expiry IS NOT NULL AND expiry < datetime("now")'
        )
        self.conn.commit()
        return cursor.rowcount

    def add_file_channel(self, file_id: str, channel_id: int):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO file_channels (file_id, channel_id) VALUES (?, ?)',
            (file_id, channel_id)
        )
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()


# ============================================
# BOT HANDLERS CLASS
# ============================================
class BotHandlers:
    def __init__(self, db: Database):
        self.db = db
        self.bot_username = ''
        self.bot_id = 0
        self.sessions = {}

    def format_file_size(self, bytes: int) -> str:
        if bytes < 1024:
            return f'{bytes} B'
        if bytes < 1048576:
            return f'{bytes / 1024:.1f} KB'
        if bytes < 1073741824:
            return f'{bytes / 1048576:.1f} MB'
        return f'{bytes / 1073741824:.2f} GB'

    def get_expiry(self, opt: str) -> Optional[int]:
        return EXPIRY_MAP.get(opt)

    def format_expiry(self, seconds: int) -> str:
        if not seconds:
            return '♾️ Permanent'
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days:
            return f'{days}d'
        if hours:
            return f'{hours}h'
        if minutes:
            return f'{minutes}m'
        return f'{seconds}s'

    def is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS

    def get_session(self, user_id: int) -> Optional[Dict]:
        session = self.sessions.get(user_id)
        if session and session.get('created_at'):
            if (datetime.now() - session['created_at']).seconds > 3600:
                self.sessions.pop(user_id, None)
                return None
        return session

    def set_session(self, user_id: int, data: Dict):
        data['created_at'] = datetime.now()
        self.sessions[user_id] = data
        logger.info(f'📝 Session set for user {user_id}: {data.get("step")}')

    def clear_session(self, user_id: int):
        if user_id in self.sessions:
            logger.info(f'🗑️ Session cleared for user {user_id}')
            self.sessions.pop(user_id, None)

    # ============================================
    # CHANNEL HELPERS
    # ============================================
    def create_invite_link(self, bot, channel_id: int) -> Optional[str]:
        try:
            invite_link = bot.create_chat_invite_link(channel_id, member_limit=0)
            return invite_link.invite_link
        except Exception as e:
            logger.warning(f'⚠️ Could not create invite link: {e}')
            return None

    def get_channel_link(self, bot, channel_name: str, channel_info: Dict) -> str:
        if (channel_info and channel_info.get('link') and
            channel_info['link'] != 'https://t.me/+[INVITE_CODE]' and
            '[INVITE_CODE]' not in channel_info['link']):
            return channel_info['link']

        if channel_name.startswith('+') and channel_info and channel_info.get('channel_id'):
            invite_link = self.create_invite_link(bot, channel_info['channel_id'])
            if invite_link:
                self.db.update_channel_link(channel_name, invite_link)
                return invite_link
            return f'https://t.me/{channel_name}'

        if channel_name.startswith('@'):
            return f'https://t.me/{channel_name[1:]}'

        return f'https://t.me/{channel_name}'

    def is_bot_admin_in_channel(self, bot, channel_id: int) -> bool:
        try:
            member = bot.get_chat_member(channel_id, self.bot_id)
            return member.status in ['administrator', 'creator']
        except Exception:
            return False

    def is_user_member_of_channel(self, bot, user_id: int, channel_id: int) -> bool:
        try:
            member = bot.get_chat_member(channel_id, user_id)
            return member.status in ['member', 'administrator', 'creator']
        except Exception:
            return False

    # ============================================
    # DETECT CHANNELS
    # ============================================
    def detect_private_channel_from_forward(self, bot, msg) -> Dict:
        if not msg.forward_from_chat:
            return {'success': False, 'error': '❌ Not a forwarded message'}

        chat = msg.forward_from_chat
        channel_id = chat.id
        channel_title = chat.title or 'Private Channel'
        channel_username = chat.username

        is_admin = self.is_bot_admin_in_channel(bot, channel_id)

        if not is_admin:
            return {
                'success': False,
                'error': f'❌ Bot is not an admin in "{channel_title}".\n\nPlease add @{self.bot_username} as an admin.'
            }

        link = self.create_invite_link(bot, channel_id)

        if not link:
            if channel_username:
                link = f'https://t.me/{channel_username}'
            else:
                link = 'https://t.me/+[INVITE_CODE]'

        return {
            'success': True,
            'channel_id': channel_id,
            'title': channel_title,
            'username': channel_username,
            'type': 'private',
            'link': link
        }

    def detect_public_channel(self, bot, identifier: str) -> Dict:
        try:
            chat_info = None
            clean_id = identifier.replace('@', '').strip()

            try:
                chat_info = bot.get_chat(f'@{clean_id}')
            except Exception:
                try:
                    chat_info = bot.get_chat(clean_id)
                except Exception:
                    match = re.search(r't\.me/(.+)', identifier)
                    if match:
                        username = match.group(1)
                        chat_info = bot.get_chat(f'@{username}')
                        clean_id = username

            if not chat_info or not chat_info.id:
                return {'success': False, 'error': '❌ Channel not found.'}

            is_admin = self.is_bot_admin_in_channel(bot, chat_info.id)
            if not is_admin:
                return {
                    'success': False,
                    'error': f'❌ Bot is not an admin in @{clean_id}. Please add @{self.bot_username} as admin.'
                }

            return {
                'success': True,
                'channel_id': chat_info.id,
                'title': chat_info.title or clean_id,
                'type': 'public',
                'link': f'https://t.me/{clean_id}'
            }
        except Exception as e:
            return {'success': False, 'error': f'❌ Error: {str(e)}'}

    # ============================================
    # CHECK REQUIRED CHANNELS
    # ============================================
    def check_all_required_channels(self, bot, user_id: int) -> List[Dict]:
        results = []

        for channel in REQUIRED_CHANNELS:
            joined = False
            channel_id = channel['channel_id']

            if channel['type'] == 'public' and not channel_id:
                try:
                    detection = self.detect_public_channel(bot, channel['identifier'])
                    if detection['success']:
                        channel_id = detection['channel_id']
                        channel['channel_id'] = channel_id
                        self.db.update_required_channel_id(channel['name'], channel_id)
                        logger.info(f'✅ Detected channel ID for {channel["name"]}: {channel_id}')
                except Exception as e:
                    logger.warning(f'⚠️ Could not detect {channel["name"]}: {e}')

            if channel_id:
                joined = self.is_user_member_of_channel(bot, user_id, channel_id)

            results.append({
                'channel': channel['name'],
                'joined': joined,
                'link': channel['link'],
                'channel_id': channel_id,
                'type': channel['type']
            })

        return results

    def force_join_required_channels(self, bot, chat_id: int, user_id: int) -> bool:
        channel_status = self.check_all_required_channels(bot, user_id)
        all_joined = all(c['joined'] for c in channel_status)

        if all_joined:
            self.db.mark_required_joined(user_id)
            return True

        kb = []
        missing_channels = []

        for ch in channel_status:
            if not ch['joined']:
                link = self.get_channel_link(bot, ch['channel'], {
                    'channel_id': ch['channel_id'],
                    'link': ch['link']
                })
                kb.append([InlineKeyboardButton(f'📢 Join {ch["channel"]}', url=link)])
                missing_channels.append(ch['channel'])

        kb.append([InlineKeyboardButton("✅ I've Joined All", callback_data='check_required_join')])

        channel_list = '\n'.join(f'• {c}' for c in missing_channels)

        bot.send_message(
            chat_id,
            f'🔐 <b>Channels Required</b>\n\n'
            f'You must join <b>ALL</b> these channels to use this bot:\n\n'
            f'{channel_list}\n\n'
            f'Join all channels and click "I\'ve Joined All".',
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )
        return False

    # ============================================
    # FORCE JOIN USER CHANNELS
    # ============================================
    def force_join_user_channels(self, bot, chat_id: int, user_id: int, file: Dict):
        channel_ids = file.get('channel_ids', '').split(',') if file.get('channel_ids') else []
        channel_names = file.get('channel_names', '').split(',') if file.get('channel_names') else []

        if not channel_ids or not channel_ids[0]:
            bot.send_message(chat_id, '❌ No channels required for this file.')
            return

        kb = []
        channel_list = []
        user_channels = self.db.get_user_channels(file['user_id'])

        for i, cid in enumerate(channel_ids):
            cid = int(cid) if isinstance(cid, str) else cid
            name = channel_names[i] if i < len(channel_names) else f'Channel {i+1}'
            channel = next((c for c in user_channels if c['id'] == cid), None)

            if channel:
                link = self.get_channel_link(bot, name, {
                    'channel_id': channel['channel_id'],
                    'link': channel['link']
                })
                kb.append([InlineKeyboardButton(f'📢 Join {name}', url=link)])
                channel_list.append(f'• {name}')

        if not kb:
            bot.send_message(chat_id, '❌ No channels found for this file.')
            return

        kb.append([InlineKeyboardButton("✅ I've Joined All", callback_data=f'joined_channels_{file["id"]}')])

        bot.send_message(
            chat_id,
            f'🔐 <b>Channels Required</b>\n\n'
            f'You must join <b>ALL</b> these channels to download this file:\n\n'
            f'{chr(10).join(channel_list)}\n\n'
            f'📄 {file["name"]}\n'
            f'📦 {self.format_file_size(file["size"])}\n\n'
            f'Join all channels and click "I\'ve Joined All".',
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )

    # ============================================
    # SHOW MENUS
    # ============================================
    def show_main_menu(self, bot, chat_id: int, user_id: int, first_name: str):
        user_channels = self.db.get_user_channels(user_id)
        is_admin = self.is_admin(user_id)

        kb = [
            [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
            [InlineKeyboardButton('📂 My Files', callback_data='my_files')],
            [InlineKeyboardButton('📊 Statistics', callback_data='stats')],
            [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')]
        ]
        if is_admin:
            kb.append([InlineKeyboardButton('🛠 Admin Panel', callback_data='admin')])
        kb.append([InlineKeyboardButton('❓ Help', callback_data='help')])

        msg = f'👋 Welcome {first_name}!\n\n'
        msg += '✅ Required channels joined!\n'
        msg += '📤 Upload files (up to 2GB via forward)\n'
        msg += '🔗 Users must join YOUR channels to download\n'
        msg += '⏰ Set expiry time\n\n'

        if user_channels:
            msg += f'✅ Your Channels ({len(user_channels)}):\n'
            msg += '\n'.join(f'  • {c["channel_name"]}' for c in user_channels)
            msg += '\n\n💡 Users must join ALL these channels to download your files.'
        else:
            msg += '⚠️ No channels added!\n'
            msg += 'Use "Manage Channels" to add channels.'

        bot.send_message(
            chat_id,
            msg,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )

    def show_manage_channels(self, bot, chat_id: int, user_id: int):
        channels = self.db.get_user_channels(user_id)
        text = '🔗 Manage Your Channels\n\n'

        if channels:
            text += f'📋 Your channels ({len(channels)}):\n\n'
            btns = []
            for ch in channels:
                type_icon = '🔒' if ch['channel_type'] == 'private' else '🌐'
                text += f'  {type_icon} {ch["channel_name"]}\n'
                text += f'    🆔 ID: {ch["channel_id"]}\n'
                if ch['link'] and ch['link'] != 'https://t.me/+[INVITE_CODE]':
                    text += f'    🔗 Link: {ch["link"]}\n'
                btns.append([InlineKeyboardButton(f'❌ Remove {ch["channel_name"]}', callback_data=f'remove_{ch["id"]}')])
            text += '\n⚠️ Users must join ALL these channels to download your files.\n\n'

            kb = btns
        else:
            text += '📭 No channels added yet.\n\n'
            text += 'Add channels that users must join to download your files.\n\n'
            text += '⚠️ You must add at least one channel to upload files.'
            kb = []

        kb.append([InlineKeyboardButton('➕ Add Public Channel', callback_data='addchannel')])
        kb.append([InlineKeyboardButton('🔒 Add Private Channel', callback_data='addprivate')])
        kb.append([InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')])

        bot.send_message(
            chat_id,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    def show_channel_selection(self, bot, chat_id: int, user_id: int):
        session = self.get_session(user_id)
        if not session:
            logger.warning(f'No session found for user {user_id} in show_channel_selection')
            return

        if session.get('msg_id'):
            try:
                bot.delete_message(chat_id, session['msg_id'])
            except Exception:
                pass
            session['msg_id'] = None

        channels = self.db.get_user_channels(user_id)
        selected = session.get('selected_channels', [])
        kb = []

        kb.append([InlineKeyboardButton(f'📢 ALL Channels ({len(channels)})', callback_data='ch_all')])

        for ch in channels:
            is_selected = ch['id'] in selected
            kb.append([
                InlineKeyboardButton(
                    f"{'✅' if is_selected else '⬜'} {ch['channel_name']}",
                    callback_data=f'ch_{ch["id"]}'
                )
            ])

        kb.append([InlineKeyboardButton('⏭️ Skip (No Channels)', callback_data='ch_skip')])
        kb.append([InlineKeyboardButton('✅ Done Selecting', callback_data='ch_done')])
        kb.append([InlineKeyboardButton('❌ Cancel', callback_data='cancel')])

        msg = bot.send_message(
            chat_id,
            f'✅ File Received!\n\n'
            f'📄 {session["info"]["name"]}\n'
            f'📦 {self.format_file_size(session["info"]["size"])}\n\n'
            f'Select channels users must join (click to toggle):\n'
            f'• Selected: {len(selected)} channel(s)',
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )

        if msg:
            session['msg_id'] = msg.message_id

    def show_expiry_options(self, bot, chat_id: int):
        kb = [
            [InlineKeyboardButton('5 min', callback_data='exp_5min'),
             InlineKeyboardButton('10 min', callback_data='exp_10min')],
            [InlineKeyboardButton('15 min', callback_data='exp_15min'),
             InlineKeyboardButton('30 min', callback_data='exp_30min')],
            [InlineKeyboardButton('1 hour', callback_data='exp_1hr'),
             InlineKeyboardButton('2 hours', callback_data='exp_2hr')],
            [InlineKeyboardButton('24 hours', callback_data='exp_24hr'),
             InlineKeyboardButton('♾️ Permanent', callback_data='exp_permanent')],
            [InlineKeyboardButton('❌ Cancel', callback_data='cancel')]
        ]
        bot.send_message(
            chat_id,
            '⏰ Set expiry time:',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ============================================
    # START COMMAND
    # ============================================
    def start_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        first_name = update.effective_user.first_name or 'User'
        args = context.args
        link = args[0] if args else None

        logger.info(f'📨 /start from user {user_id} ({first_name})')

        self.db.create_user(user_id, update.effective_user.username or '', first_name)
        self.clear_session(user_id)

        # Check required channels
        channel_status = self.check_all_required_channels(context.bot, user_id)
        all_joined = all(c['joined'] for c in channel_status)

        if not all_joined:
            self.force_join_required_channels(context.bot, chat_id, user_id)
            return

        self.db.mark_required_joined(user_id)

        # Handle file link if provided
        if link:
            file = self.db.get_file_by_link(link)
            if not file:
                update.message.reply_text('❌ Invalid or expired link.')
                return

            if file.get('expiry') and datetime.fromisoformat(file['expiry']) < datetime.now():
                self.db.delete_file(file['id'])
                update.message.reply_text('❌ This file has expired.')
                return

            # Check if user needs to join channels
            if file.get('channel_ids'):
                channel_ids = [int(cid) for cid in file['channel_ids'].split(',') if cid]
                all_joined_channels = True
                for cid in channel_ids:
                    joined = self.is_user_member_of_channel(context.bot, user_id, cid)
                    if not joined:
                        all_joined_channels = False
                        break
                if not all_joined_channels:
                    self.force_join_user_channels(context.bot, chat_id, user_id, file)
                    return

            self.db.increment_downloads(file['id'])

            try:
                if file.get('file_id'):
                    context.bot.send_document(
                        chat_id, file['file_id'],
                        caption=f'📄 {file["name"]}\n📦 {self.format_file_size(file["size"])}'
                    )
                elif file.get('from_chat_id') and file.get('original_message_id'):
                    context.bot.forward_message(
                        chat_id, file['from_chat_id'], file['original_message_id']
                    )
            except Exception as e:
                logger.error(f'Failed to send file: {e}')
                update.message.reply_text('❌ Failed to send file.')
            return

        self.show_main_menu(context.bot, chat_id, user_id, first_name)

    # ============================================
    # CALLBACK HANDLER
    # ============================================
    def callback_handler(self, update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()

        user_id = query.from_user.id
        chat_id = query.message.chat.id
        data = query.data

        logger.info(f'📨 Callback: {data} from user {user_id}')

        # ---- CHECK REQUIRED JOIN ----
        if data == 'check_required_join':
            channel_status = self.check_all_required_channels(context.bot, user_id)
            all_joined = all(c['joined'] for c in channel_status)

            if all_joined:
                self.db.mark_required_joined(user_id)
                try:
                    context.bot.delete_message(chat_id, query.message.message_id)
                except Exception:
                    pass
                context.bot.send_message(chat_id, '✅ Thank you for joining all required channels!')
                user = self.db.get_user(user_id)
                self.show_main_menu(
                    context.bot, chat_id, user_id,
                    user['first_name'] if user else 'User'
                )
            else:
                missing = [c for c in channel_status if not c['joined']]
                kb = []

                for ch in missing:
                    link = self.get_channel_link(context.bot, ch['channel'], {
                        'channel_id': ch['channel_id'],
                        'link': ch['link']
                    })
                    kb.append([InlineKeyboardButton(f'📢 Join {ch["channel"]}', url=link)])

                kb.append([InlineKeyboardButton('🔄 I\'ve Joined All (Retry)', callback_data='check_required_join')])

                missing_list = ', '.join(c['channel'] for c in missing)

                query.edit_message_text(
                    f'❌ You haven\'t joined all channels yet.\n\n'
                    f'Missing: {missing_list}\n\n'
                    f'Join all channels and click "I\'ve Joined All (Retry)".',
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.HTML
                )
            return

        # ---- BACK TO MENU ----
        if data == 'back_to_menu':
            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            user = self.db.get_user(user_id)
            self.clear_session(user_id)
            self.show_main_menu(
                context.bot, chat_id, user_id,
                user['first_name'] if user else 'User'
            )
            return

        # ---- HELP ----
        if data == 'help':
            query.edit_message_text(
                f'❓ Help\n\n'
                f'📤 Upload: Send or forward files\n'
                f'🔄 Forward: Up to 2GB\n'
                f'📤 Send: Up to 50MB\n\n'
                f'🔗 Manage Channels: Add/remove your own channels\n'
                f'   Users must join ALL your channels to download\n'
                f'⏰ Expiry: Set how long files stay active\n'
                f'📂 My Files: View & delete your files\n\n'
                f'🔐 Required Channels (Bot-wide): {", ".join(c["name"] for c in REQUIRED_CHANNELS)}\n\n'
                f'🔙 Back to menu',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ]),
                parse_mode=ParseMode.HTML
            )
            return

        # ---- STATS ----
        if data == 'stats':
            total_files = self.db.get_total_files()
            user_files = self.db.get_user_files(user_id)
            query.edit_message_text(
                f'📊 Statistics\n\n'
                f'👥 User ID: {user_id}\n'
                f'📁 Your Files: {len(user_files)}\n'
                f'📁 Total Files: {total_files or 0}\n\n'
                f'🔐 Required Channels: {", ".join(c["name"] for c in REQUIRED_CHANNELS)}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ]),
                parse_mode=ParseMode.HTML
            )
            return

        # ---- MY FILES ----
        if data == 'my_files':
            files = self.db.get_user_files(user_id)
            if not files:
                query.edit_message_text(
                    '📂 No files uploaded.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                    ])
                )
                return

            text = '📂 Your Files:\n\n'
            btns = []
            for f in files[:10]:
                text += f'📄 {f["name"]}\n'
                if f.get('expiry'):
                    try:
                        expiry_delta = (datetime.fromisoformat(f['expiry']) - datetime.fromisoformat(f['created_at'])).total_seconds()
                        expiry_text = self.format_expiry(expiry_delta)
                    except:
                        expiry_text = 'Unknown'
                else:
                    expiry_text = '♾️ Permanent'
                text += f'📦 {self.format_file_size(f["size"])} | ⏰ {expiry_text}\n'
                text += f'📥 {f["downloads"]} downloads\n'
                text += f'🔗 https://t.me/{self.bot_username}?start={f["link_code"]}\n\n'
                btns.append([InlineKeyboardButton(f'🗑 Delete: {f["name"][:15]}', callback_data=f'delete_{f["id"]}')])
            btns.append([InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')])
            query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(btns),
                parse_mode=ParseMode.HTML
            )
            return

        # ---- DELETE FILE ----
        if data.startswith('delete_'):
            file_id = data.replace('delete_', '')
            self.db.delete_file(file_id)
            query.edit_message_text(
                '✅ File deleted.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='my_files')]
                ])
            )
            return

        # ---- MANAGE CHANNELS ----
        if data == 'managechannels':
            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            self.show_manage_channels(context.bot, chat_id, user_id)
            return

        # ---- ADD PUBLIC CHANNEL ----
        if data == 'addchannel':
            self.set_session(user_id, {'step': 'waiting_public_channel'})
            query.edit_message_text(
                f'🌐 Add Public Channel\n\n'
                f'Send your public channel username:\n\n'
                f'• @my_channel\n'
                f'• https://t.me/my_channel\n'
                f'• my_channel\n\n'
                f'⚠️ Requirements:\n'
                f'• Bot must be an admin in the channel\n'
                f'• Channel must be public\n\n'
                f'❌ Send /cancel to cancel'
            )
            return

        # ---- ADD PRIVATE CHANNEL ----
        if data == 'addprivate':
            self.set_session(user_id, {'step': 'waiting_private_channel'})
            query.edit_message_text(
                f'🔒 Add Private Channel\n\n'
                f'To add a private channel:\n\n'
                f'1. Make sure @{self.bot_username} is an admin in the channel\n'
                f'2. Forward ANY message from the channel to this bot\n'
                f'3. The bot will auto-detect the channel ID and create a permanent invite link\n\n'
                f'This is the ONLY way to add private channels.\n\n'
                f'❌ Send /cancel to cancel'
            )
            return

        # ---- REMOVE CHANNEL ----
        if data.startswith('remove_'):
            channel_id = int(data.replace('remove_', ''))
            self.db.remove_user_channel(user_id, channel_id)
            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            self.show_manage_channels(context.bot, chat_id, user_id)
            return

        # ---- UPLOAD ----
        if data == 'upload':
            user_channels = self.db.get_user_channels(user_id)
            if not user_channels:
                context.bot.send_message(
                    chat_id,
                    f'⚠️ No channels added!\n\n'
                    f'Add at least one channel first using "Manage Channels".',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')]
                    ])
                )
                return

            self.set_session(user_id, {'step': 'waiting_file'})
            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            context.bot.send_message(
                chat_id,
                f'📤 Upload Your File\n\n'
                f'Send or forward the file you want to share.\n\n'
                f'✅ Direct send: Max 50MB\n'
                f'🔄 Forward: Max 2GB\n\n'
                f'📢 Users must join your {len(user_channels)} channel(s) to download.\n'
                f'Channels: {", ".join(c["channel_name"] for c in user_channels)}\n\n'
                f'❌ Send /cancel to cancel'
            )
            return

        # ---- ADMIN ----
        if data == 'admin':
            if not self.is_admin(user_id):
                context.bot.send_message(chat_id, '❌ Access denied. Admin only.')
                return

            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            total_files = self.db.get_total_files()

            context.bot.send_message(
                chat_id,
                f'🛠 <b>Admin Panel</b>\n\n'
                f'📁 Total Files: {total_files or 0}\n'
                f'👥 Admin ID: {user_id}\n'
                f'🔐 Required Channels: {", ".join(c["name"] for c in REQUIRED_CHANNELS)}\n\n',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📁 All Files', callback_data='admin_files')],
                    [InlineKeyboardButton('🗑 Cleanup Expired', callback_data='admin_cleanup')],
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ]),
                parse_mode=ParseMode.HTML
            )
            return

        # ---- ADMIN FILES ----
        if data == 'admin_files':
            if not self.is_admin(user_id):
                return
            files = self.db.get_user_files(user_id)
            if not files:
                query.edit_message_text(
                    '📂 No files.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔙 Back', callback_data='admin')]
                    ])
                )
                return
            text = '📁 All Files:\n\n'
            btns = []
            for f in files:
                text += f'📄 {f["name"]}\n'
                text += f'📥 {f["downloads"]} downloads\n'
                if f.get('expiry'):
                    try:
                        expiry_delta = (datetime.fromisoformat(f['expiry']) - datetime.fromisoformat(f['created_at'])).total_seconds()
                        expiry_text = self.format_expiry(expiry_delta)
                    except:
                        expiry_text = 'Unknown'
                else:
                    expiry_text = '♾️ Permanent'
                text += f'⏰ {expiry_text}\n\n'
                btns.append([InlineKeyboardButton(f'🗑 Delete: {f["name"][:15]}', callback_data=f'admin_delete_{f["id"]}')])
            btns.append([InlineKeyboardButton('🔙 Back', callback_data='admin')])
            query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(btns),
                parse_mode=ParseMode.HTML
            )
            return

        # ---- ADMIN DELETE ----
        if data.startswith('admin_delete_'):
            if not self.is_admin(user_id):
                return
            file_id = data.replace('admin_delete_', '')
            self.db.delete_file(file_id)
            query.edit_message_text(
                '✅ File deleted.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='admin_files')]
                ])
            )
            return

        # ---- ADMIN CLEANUP ----
        if data == 'admin_cleanup':
            if not self.is_admin(user_id):
                return
            count = self.db.cleanup_expired_files()
            query.edit_message_text(
                f'✅ Cleanup complete!\n\nRemoved {count} expired files.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='admin')]
                ])
            )
            return

        # ---- CHANNEL SELECTION ----
        if data == 'ch_all':
            session = self.get_session(user_id)
            if not session:
                return
            channels = self.db.get_user_channels(user_id)
            session['selected_channels'] = [c['id'] for c in channels]
            self.show_channel_selection(context.bot, chat_id, user_id)
            return

        if data.startswith('ch_') and data not in ['ch_done', 'ch_skip', 'ch_all']:
            channel_id = int(data.replace('ch_', ''))
            session = self.get_session(user_id)
            if not session:
                return

            if channel_id in session['selected_channels']:
                session['selected_channels'].remove(channel_id)
            else:
                session['selected_channels'].append(channel_id)

            self.show_channel_selection(context.bot, chat_id, user_id)
            return

        # ---- CH_DONE ----
        if data == 'ch_done':
            session = self.get_session(user_id)
            if not session:
                return

            logger.info(f'✅ Done selecting. Selected: {len(session["selected_channels"])} channels')

            if session.get('msg_id'):
                try:
                    context.bot.delete_message(chat_id, session['msg_id'])
                except Exception:
                    pass
                session['msg_id'] = None

            session['step'] = 'waiting_expiry'
            self.show_expiry_options(context.bot, chat_id)
            return

        # ---- CH_SKIP ----
        if data == 'ch_skip':
            session = self.get_session(user_id)
            if not session:
                return

            logger.info('⏭️ Skipping channel selection')

            session['selected_channels'] = []

            if session.get('msg_id'):
                try:
                    context.bot.delete_message(chat_id, session['msg_id'])
                except Exception:
                    pass
                session['msg_id'] = None

            session['step'] = 'waiting_expiry'
            self.show_expiry_options(context.bot, chat_id)
            return

        # ---- EXPIRY ----
        if data.startswith('exp_'):
            opt = data.replace('exp_', '')
            expiry_seconds = self.get_expiry(opt)
            expiry = (datetime.now() + timedelta(seconds=expiry_seconds)).isoformat() if expiry_seconds else None
            session = self.get_session(user_id)
            if not session or not session.get('file_id'):
                return

            file_data = {
                'id': session['file_id'],
                'user_id': user_id,
                'name': session['info']['name'],
                'size': session['info']['size'],
                'mime_type': session['info']['mime_type'],
                'file_id': session['info']['file_id'],
                'from_chat_id': session['info']['from_chat_id'],
                'original_message_id': session['info']['original_message_id'],
                'is_forwarded': 1 if session['info']['is_forwarded'] else 0,
                'expiry': expiry
            }

            result = self.db.create_file(file_data)

            for cid in session['selected_channels']:
                self.db.add_file_channel(result['id'], cid)

            file_link = result['link_code']

            self.clear_session(user_id)

            link = f'https://t.me/{self.bot_username}?start={file_link}'

            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass

            context.bot.send_message(
                chat_id,
                f'✅ <b>File Uploaded!</b>\n\n'
                f'📄 {file_data["name"]}\n'
                f'📦 {self.format_file_size(file_data["size"])}\n'
                f'⏰ {self.format_expiry(expiry_seconds) if expiry_seconds else "♾️ Permanent"}\n'
                f'📢 Channels: {len(session["selected_channels"])} channel(s)\n\n'
                f'🔗 Shareable Link:\n'
                f'{link}\n\n'
                f'⚠️ Users must join ALL required channels to download.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📤 Upload More', callback_data='upload')],
                    [InlineKeyboardButton('📂 My Files', callback_data='my_files')],
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ]),
                parse_mode=ParseMode.HTML
            )
            return

        # ---- JOINED CHANNELS ----
        if data.startswith('joined_channels_'):
            file_id = data.replace('joined_channels_', '')

            file = self.db.get_file_by_id(file_id)
            if not file:
                query.edit_message_text(
                    '❌ File not found. It may have been deleted or expired.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                    ])
                )
                return

            if file.get('expiry') and datetime.fromisoformat(file['expiry']) < datetime.now():
                self.db.delete_file(file['id'])
                query.edit_message_text(
                    '❌ This file has expired.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                    ])
                )
                return

            channel_ids = [int(cid) for cid in file.get('channel_ids', '').split(',') if cid] if file.get('channel_ids') else []

            all_joined = True
            for cid in channel_ids:
                joined = self.is_user_member_of_channel(context.bot, user_id, cid)
                if not joined:
                    all_joined = False
                    break

            if not all_joined:
                kb = []
                user_channels = self.db.get_user_channels(file['user_id'])

                for cid in channel_ids:
                    channel = next((c for c in user_channels if c['id'] == cid), None)
                    if channel:
                        link = self.get_channel_link(context.bot, channel['channel_name'], {
                            'channel_id': channel['channel_id'],
                            'link': channel['link']
                        })
                        kb.append([InlineKeyboardButton(f'📢 Join {channel["channel_name"]}', url=link)])
                kb.append([InlineKeyboardButton('✅ I\'ve Joined All', callback_data=f'joined_channels_{file_id}')])

                query.edit_message_text(
                    f'❌ You haven\'t joined all channels yet.\n\n'
                    f'Please join all channels and click "I\'ve Joined All".',
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.HTML
                )
                return

            self.db.increment_downloads(file['id'])
            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass

            try:
                if file.get('file_id'):
                    context.bot.send_document(
                        chat_id, file['file_id'],
                        caption=f'📄 {file["name"]}\n📦 {self.format_file_size(file["size"])}\n📥 {file["downloads"] + 1} downloads'
                    )
                elif file.get('from_chat_id') and file.get('original_message_id'):
                    context.bot.forward_message(
                        chat_id, file['from_chat_id'], file['original_message_id']
                    )
                else:
                    context.bot.send_message(chat_id, '❌ Failed to send file. The file data is incomplete.')
            except Exception as e:
                logger.error(f'❌ Send file error: {e}')
                context.bot.send_message(chat_id, '❌ Failed to send file. Please try again.')
            return

        # ---- CANCEL ----
        if data == 'cancel':
            self.clear_session(user_id)
            try:
                context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            context.bot.send_message(chat_id, '❌ Cancelled.')
            user = self.db.get_user(user_id)
            self.show_main_menu(
                context.bot, chat_id, user_id,
                user['first_name'] if user else 'User'
            )
            return

    # ============================================
    # TEXT HANDLER
    # ============================================
    def text_handler(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message

        if not msg.text:
            return

        logger.info(f'📨 Text from user {user_id}: {msg.text[:50]}')

        if msg.text == '/cancel':
            self.clear_session(user_id)
            msg.reply_text(
                '❌ Cancelled.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ])
            )
            return

        # Handle private channel detection via forwarded message
        if msg.forward_from_chat:
            session = self.get_session(user_id)
            if session and session.get('step') == 'waiting_private_channel':
                self.handle_private_channel_detection(update, context)
                return

        # Handle public channel add
        session = self.get_session(user_id)
        if session and session.get('step') == 'waiting_public_channel':
            channel_input = msg.text.strip()
            self.handle_public_channel_add(update, context, channel_input)

    # ============================================
    # PRIVATE CHANNEL DETECTION
    # ============================================
    def handle_private_channel_detection(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message

        if not msg.forward_from_chat:
            return

        session = self.get_session(user_id)
        if not session or session.get('step') != 'waiting_private_channel':
            return

        detection = self.detect_private_channel_from_forward(context.bot, msg)

        if not detection['success']:
            context.bot.send_message(
                chat_id,
                f'❌ {detection["error"]}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔄 Try Again', callback_data='addprivate')],
                    [InlineKeyboardButton('❌ Cancel', callback_data='cancel')]
                ])
            )
            return

        existing = self.db.get_user_channels(user_id)
        exists = any(c['channel_id'] == detection['channel_id'] for c in existing)

        if exists:
            context.bot.send_message(
                chat_id,
                f'⚠️ This channel is already in your list.\n\n'
                f'📢 {detection["title"]}\n'
                f'🆔 {detection["channel_id"]}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ])
            )
            self.clear_session(user_id)
            return

        self.db.add_user_channel(user_id, {
            'name': detection['title'],
            'channel_id': detection['channel_id'],
            'type': 'private',
            'link': detection['link']
        })

        self.clear_session(user_id)
        channels = self.db.get_user_channels(user_id)

        context.bot.send_message(
            chat_id,
            f'✅ <b>Private Channel Added!</b>\n\n'
            f'📢 {detection["title"]}\n'
            f'🆔 {detection["channel_id"]}\n'
            f'🔗 {detection["link"]}\n\n'
            f'You now have {len(channels)} channel(s).',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
            ]),
            parse_mode=ParseMode.HTML
        )

    # ============================================
    # PUBLIC CHANNEL ADD
    # ============================================
    def handle_public_channel_add(self, update: Update, context: CallbackContext, channel_input: str):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        detection = self.detect_public_channel(context.bot, channel_input)
        if not detection['success']:
            context.bot.send_message(
                chat_id,
                f'❌ {detection["error"]}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔄 Try Again', callback_data='addchannel')],
                    [InlineKeyboardButton('❌ Cancel', callback_data='cancel')]
                ])
            )
            return

        existing = self.db.get_user_channels(user_id)
        exists = any(c['channel_id'] == detection['channel_id'] for c in existing)

        if exists:
            context.bot.send_message(chat_id, '⚠️ This channel is already in your list.')
            self.clear_session(user_id)
            self.show_manage_channels(context.bot, chat_id, user_id)
            return

        self.db.add_user_channel(user_id, {
            'name': detection['title'],
            'channel_id': detection['channel_id'],
            'type': 'public',
            'link': detection['link']
        })

        self.clear_session(user_id)
        channels = self.db.get_user_channels(user_id)

        context.bot.send_message(
            chat_id,
            f'✅ <b>Channel Added!</b>\n\n'
            f'📢 {detection["title"]}\n'
            f'🆔 {detection["channel_id"]}\n\n'
            f'You now have {len(channels)} channel(s).',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
            ]),
            parse_mode=ParseMode.HTML
        )

    # ============================================
    # FILE HANDLER
    # ============================================
    def file_handler(self, update: Update, context: CallbackContext, file_type: str):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message

        logger.info(f'📨 File received from user {user_id}, type: {file_type}')

        # Check if user has an active session
        session = self.get_session(user_id)
        if not session:
            logger.warning(f'No session found for user {user_id} in file_handler')
            msg.reply_text(
                '⚠️ Please use the "Upload File" button first.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ])
            )
            return

        if session.get('step') != 'waiting_file':
            logger.warning(f'User {user_id} is in step {session.get("step")}, not waiting_file')
            msg.reply_text(
                '⚠️ Please use the "Upload File" button first.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ])
            )
            return

        # Get file info
        file = None
        file_name = None
        mime_type = None
        file_size = 0
        file_id = None
        is_forwarded = False
        from_chat_id = None
        original_message_id = None

        # Check if forwarded (using forward_from_chat and forward_from)
        if msg.forward_from_chat:
            is_forwarded = True
            from_chat_id = msg.forward_from_chat.id
            original_message_id = msg.forward_from_message_id
        elif msg.forward_from:
            is_forwarded = True

        # Get file based on type
        if file_type == 'document':
            file = msg.document
            file_name = file.file_name or 'document'
            mime_type = file.mime_type or 'application/octet-stream'
            file_size = file.file_size
            file_id = file.file_id
        elif file_type == 'photo':
            file = msg.photo[-1]
            file_name = f'photo_{int(datetime.now().timestamp())}.jpg'
            mime_type = 'image/jpeg'
            file_size = file.file_size
            file_id = file.file_id
        elif file_type == 'video':
            file = msg.video
            file_name = file.file_name or 'video.mp4'
            mime_type = file.mime_type or 'video/mp4'
            file_size = file.file_size
            file_id = file.file_id
        else:
            msg.reply_text('❌ Please send a document, photo, or video.')
            return

        # Check size limit for direct sends
        if not is_forwarded and file_size > MAX_FILE_SIZE_SEND:
            msg.reply_text(
                f'❌ File too large ({self.format_file_size(file_size)}).\n\n'
                f'Please FORWARD the file instead (supports up to 2GB).'
            )
            return

        # Get user channels
        user_channels = self.db.get_user_channels(user_id)

        if not user_channels:
            msg.reply_text(
                '⚠️ No channels found! Please add a channel first.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ])
            )
            self.clear_session(user_id)
            return

        # Store file info in session and show channel selection
        unique_id = secrets.token_hex(16)
        
        # Update session with file info
        session['file_id'] = unique_id
        session['info'] = {
            'name': file_name,
            'size': file_size,
            'mime_type': mime_type,
            'file_id': file_id,
            'from_chat_id': from_chat_id,
            'original_message_id': original_message_id,
            'is_forwarded': is_forwarded
        }
        session['selected_channels'] = [ch['id'] for ch in user_channels]
        session['step'] = 'waiting_channels'
        
        # Show channel selection
        self.show_channel_selection(context.bot, chat_id, user_id)


# ============================================
# HEALTH CHECK SERVER
# ============================================
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Health check server running on port {PORT}")


def run_health_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_health_server())
    loop.run_forever()


# ============================================
# MAIN
# ============================================
def main():
    logger.info('🚀 Starting bot...')

    db = Database()
    handlers = BotHandlers(db)

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Store bot info
    bot_info = updater.bot.get_me()
    handlers.bot_username = bot_info.username
    handlers.bot_id = bot_info.id
    logger.info(f'✅ Bot running: @{handlers.bot_username}')
    logger.info(f'🆔 Bot ID: {handlers.bot_id}')

    logger.info('\n🔐 Required Channels (Bot-wide):')
    for ch in REQUIRED_CHANNELS:
        if ch['channel_id']:
            logger.info(f'  ✅ {ch["name"]} ({ch["type"]}) - ID: {ch["channel_id"]}')
        else:
            logger.info(f'  ⏳ {ch["name"]} ({ch["type"]}) - Will auto-detect')

    # Set bot commands
    updater.bot.set_my_commands([
        ('start', '🚀 Start the bot'),
    ])

    # Add handlers
    dp.add_handler(CommandHandler('start', handlers.start_command))
    dp.add_handler(MessageHandler(Filters.document, lambda u, c: handlers.file_handler(u, c, 'document')))
    dp.add_handler(MessageHandler(Filters.photo, lambda u, c: handlers.file_handler(u, c, 'photo')))
    dp.add_handler(MessageHandler(Filters.video, lambda u, c: handlers.file_handler(u, c, 'video')))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handlers.text_handler))
    dp.add_handler(CallbackQueryHandler(handlers.callback_handler))

    logger.info('\n✅ Bot is ready!')
    logger.info('📤 Users can add their own channels:')
    logger.info('  🌐 Public: Send @username or link')
    logger.info('  🔒 Private: Forward a message (bot creates permanent invite link)')
    logger.info(f'\n👑 Admins: {", ".join(str(a) for a in ADMIN_IDS) if ADMIN_IDS else "None"}')

    # Start keep-alive thread
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    logger.info('💓 Keep-alive thread started (pings every 5 minutes)')

    # Start health check server in background thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # Start polling
    updater.start_polling()
    logger.info('🔄 Polling started...')

    updater.idle()

    db.close()
    logger.info('🛑 Bot stopped')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info('🛑 Bot stopped by user')
    except Exception as e:
        logger.error(f'❌ Fatal error: {e}')
        sys.exit(1)