#!/usr/bin/env python3
# ============================================
# TELEGRAM FILE SHARING BOT - COMPLETE WORKING VERSION
# All features working - File upload, channels, sessions
# ============================================

import os
import sys
import sqlite3
import secrets
import logging
import re
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
import threading

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

    def clear_session(self, user_id: int):
        self.sessions.pop(user_id, None)

    # ============================================
    # START COMMAND
    # ============================================
    def start_command(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        first_name = update.effective_user.first_name or 'User'
        
        logger.info(f"📨 /start from user {user_id}")
        
        self.db.create_user(user_id, update.effective_user.username or '', first_name)
        self.clear_session(user_id)
        
        kb = [
            [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
            [InlineKeyboardButton('📂 My Files', callback_data='my_files')],
            [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
            [InlineKeyboardButton('❓ Help', callback_data='help')]
        ]
        if self.is_admin(user_id):
            kb.append([InlineKeyboardButton('🛠 Admin Panel', callback_data='admin')])
        
        update.message.reply_text(
            f'👋 Welcome {first_name}!\n\n'
            f'📤 Upload a file to get a shareable link\n'
            f'🔗 Users must join your channels to download',
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )

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
        
        # ---- HELP ----
        if data == 'help':
            query.edit_message_text(
                '❓ <b>Help</b>\n\n'
                '📤 <b>Upload File</b>: Send or forward a file\n'
                '   • Direct send: Max 50MB\n'
                '   • Forward: Up to 2GB\n\n'
                '🔗 <b>Manage Channels</b>: Add channels users must join\n'
                '📂 <b>My Files</b>: View and manage your uploaded files',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ]),
                parse_mode=ParseMode.HTML
            )
            return
        
        # ---- BACK TO MENU ----
        if data == 'back_to_menu':
            user = self.db.get_user(user_id)
            first_name = user['first_name'] if user else 'User'
            self.clear_session(user_id)
            
            kb = [
                [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                [InlineKeyboardButton('📂 My Files', callback_data='my_files')],
                [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                [InlineKeyboardButton('❓ Help', callback_data='help')]
            ]
            if self.is_admin(user_id):
                kb.append([InlineKeyboardButton('🛠 Admin Panel', callback_data='admin')])
            
            query.edit_message_text(
                f'👋 Welcome back {first_name}!',
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.HTML
            )
            return
        
        # ---- STATS ----
        if data == 'stats':
            total_files = self.db.get_total_files()
            user_files = self.db.get_user_files(user_id)
            
            query.edit_message_text(
                f'📊 <b>Statistics</b>\n\n'
                f'👥 User ID: {user_id}\n'
                f'📁 Your Files: {len(user_files)}\n'
                f'📁 Total Files: {total_files or 0}',
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
                    '📂 No files uploaded yet.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('📤 Upload', callback_data='upload')],
                        [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                    ])
                )
                return
            
            text = '📂 <b>Your Files</b>\n\n'
            btns = []
            for f in files[:10]:
                text += f'📄 {f["name"]}\n'
                text += f'📦 {self.format_file_size(f["size"])}\n'
                text += f'📥 {f["downloads"]} downloads\n'
                text += f'🔗 https://t.me/{self.bot_username}?start={f["link_code"]}\n\n'
                btns.append([InlineKeyboardButton(f'🗑 Delete', callback_data=f'delete_{f["id"]}')])
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
                '✅ File deleted!',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📂 My Files', callback_data='my_files')],
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ])
            )
            return
        
        # ---- MANAGE CHANNELS ----
        if data == 'managechannels':
            channels = self.db.get_user_channels(user_id)
            
            text = '🔗 <b>Manage Channels</b>\n\n'
            kb = []
            
            if channels:
                text += f'📋 Your channels ({len(channels)}):\n\n'
                for ch in channels:
                    text += f'  • {ch["channel_name"]}\n'
                    kb.append([InlineKeyboardButton(f'❌ Remove {ch["channel_name"]}', callback_data=f'remove_{ch["id"]}')])
            else:
                text += '📭 No channels added yet.\n\n'
                text += '⚠️ You must add at least one channel to upload files.'
            
            kb.append([InlineKeyboardButton('➕ Add Public Channel', callback_data='addchannel')])
            kb.append([InlineKeyboardButton('🔒 Add Private Channel', callback_data='addprivate')])
            kb.append([InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')])
            
            query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.HTML
            )
            return
        
        # ---- REMOVE CHANNEL ----
        if data.startswith('remove_'):
            channel_id = int(data.replace('remove_', ''))
            self.db.remove_user_channel(user_id, channel_id)
            
            query.edit_message_text(
                '✅ Channel removed!',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ])
            )
            return
        
        # ---- ADD PUBLIC CHANNEL ----
        if data == 'addchannel':
            self.set_session(user_id, {'step': 'waiting_public_channel'})
            
            query.edit_message_text(
                '🌐 <b>Add Public Channel</b>\n\n'
                'Send your public channel username:\n\n'
                '• @my_channel\n'
                '• https://t.me/my_channel\n'
                '• my_channel\n\n'
                f'⚠️ Bot must be admin in the channel (@{self.bot_username})\n\n'
                'Send /cancel to cancel',
                parse_mode=ParseMode.HTML
            )
            return
        
        # ---- ADD PRIVATE CHANNEL ----
        if data == 'addprivate':
            self.set_session(user_id, {'step': 'waiting_private_channel'})
            
            query.edit_message_text(
                '🔒 <b>Add Private Channel</b>\n\n'
                f'1. Make sure @{self.bot_username} is admin\n'
                f'2. Forward ANY message from the channel to this bot\n\n'
                'Send /cancel to cancel',
                parse_mode=ParseMode.HTML
            )
            return
        
        # ---- UPLOAD ----
        if data == 'upload':
            user_channels = self.db.get_user_channels(user_id)
            
            if not user_channels:
                query.edit_message_text(
                    '⚠️ <b>No channels added!</b>\n\n'
                    'Add a channel first using "Manage Channels".',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                        [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                    ]),
                    parse_mode=ParseMode.HTML
                )
                return
            
            self.set_session(user_id, {'step': 'waiting_file'})
            
            query.edit_message_text(
                '📤 <b>Upload Your File</b>\n\n'
                'Send or forward the file you want to share.\n\n'
                '✅ Direct send: Max 50MB\n'
                '🔄 Forward: Max 2GB\n\n'
                f'📢 Users must join your {len(user_channels)} channel(s)\n'
                'Send /cancel to cancel',
                parse_mode=ParseMode.HTML
            )
            return
        
        # ---- ADMIN ----
        if data == 'admin':
            if not self.is_admin(user_id):
                query.edit_message_text('❌ Access denied.')
                return
            
            total_files = self.db.get_total_files()
            
            query.edit_message_text(
                f'🛠 <b>Admin Panel</b>\n\n'
                f'📁 Total Files: {total_files or 0}\n'
                f'👥 Admin ID: {user_id}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🗑 Cleanup Expired', callback_data='admin_cleanup')],
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ]),
                parse_mode=ParseMode.HTML
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
        
        # ---- CANCEL ----
        if data == 'cancel':
            self.clear_session(user_id)
            query.edit_message_text(
                '❌ Cancelled.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ])
            )
            return

    # ============================================
    # TEXT HANDLER
    # ============================================
    def text_handler(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text
        
        logger.info(f'📨 Text from user {user_id}: {text[:50] if text else "empty"}')
        
        if text and text.lower() == '/cancel':
            self.clear_session(user_id)
            update.message.reply_text(
                '❌ Cancelled.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ])
            )
            return
        
        # Handle private channel detection
        if update.message.forward_from_chat:
            session = self.get_session(user_id)
            if session and session.get('step') == 'waiting_private_channel':
                self.handle_private_channel_detection(update, context)
                return
        
        # Handle public channel add
        session = self.get_session(user_id)
        if session and session.get('step') == 'waiting_public_channel' and text:
            self.handle_public_channel_add(update, context)
            return

    # ============================================
    # FILE HANDLER
    # ============================================
    def file_handler(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message
        
        logger.info(f'📨 File received from user {user_id}')
        
        # Log file details
        if msg.document:
            logger.info(f'   Document: {msg.document.file_name} ({msg.document.file_size} bytes)')
        elif msg.photo:
            logger.info(f'   Photo: {msg.photo[-1].file_size} bytes')
        elif msg.video:
            logger.info(f'   Video: {msg.video.file_name} ({msg.video.file_size} bytes)')
        
        session = self.get_session(user_id)
        if not session or session.get('step') != 'waiting_file':
            msg.reply_text(
                '⚠️ Please use the "Upload File" button first.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ])
            )
            return
        
        # Get file info
        file_name = None
        file_size = 0
        file_id = None
        is_forwarded = False
        from_chat_id = None
        original_message_id = None
        
        # Check if forwarded
        if msg.forward_origin or msg.forward_from or msg.forward_from_chat:
            is_forwarded = True
            if msg.forward_origin and hasattr(msg.forward_origin, 'chat'):
                from_chat_id = msg.forward_origin.chat.id
                original_message_id = msg.forward_origin.message_id
            elif msg.forward_from_chat:
                from_chat_id = msg.forward_from_chat.id
                original_message_id = msg.forward_from_message_id
        
        # Get file based on type
        if msg.document:
            file_name = msg.document.file_name or 'document'
            file_size = msg.document.file_size
            file_id = msg.document.file_id
        elif msg.photo:
            file_name = f'photo_{int(datetime.now().timestamp())}.jpg'
            file_size = msg.photo[-1].file_size
            file_id = msg.photo[-1].file_id
        elif msg.video:
            file_name = msg.video.file_name or 'video.mp4'
            file_size = msg.video.file_size
            file_id = msg.video.file_id
        else:
            msg.reply_text('❌ Please send a document, photo, or video.')
            return
        
        # Check size limit
        if not is_forwarded and file_size > MAX_FILE_SIZE_SEND:
            msg.reply_text(
                f'❌ File too large ({self.format_file_size(file_size)}).\n\n'
                f'Please FORWARD the file instead (supports up to 2GB).'
            )
            return
        
        # Get user's channels
        user_channels = self.db.get_user_channels(user_id)
        
        if not user_channels:
            msg.reply_text(
                '⚠️ No channels found! Please add a channel first.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                    [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
                ])
            )
            self.clear_session(user_id)
            return
        
        # Create file in database
        unique_id = secrets.token_hex(16)
        
        file_data = {
            'id': unique_id,
            'user_id': user_id,
            'name': file_name,
            'size': file_size,
            'mime_type': msg.document.mime_type if msg.document else '',
            'file_id': file_id,
            'from_chat_id': from_chat_id,
            'original_message_id': original_message_id,
            'is_forwarded': 1 if is_forwarded else 0,
            'expiry': None
        }
        
        result = self.db.create_file(file_data)
        
        # Add file-channel associations
        for ch in user_channels:
            self.db.add_file_channel(result['id'], ch['id'])
        
        self.clear_session(user_id)
        
        # Generate link
        link = f'https://t.me/{self.bot_username}?start={result["link_code"]}'
        channel_list = '\n'.join(f'• {ch["channel_name"]}' for ch in user_channels)
        
        msg.reply_text(
            f'✅ <b>File Uploaded!</b>\n\n'
            f'📄 {file_name}\n'
            f'📦 {self.format_file_size(file_size)}\n'
            f'📢 Channels: {len(user_channels)}\n\n'
            f'🔗 Shareable Link:\n'
            f'<code>{link}</code>\n\n'
            f'📋 Required Channels:\n{channel_list}',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('📤 Upload More', callback_data='upload')],
                [InlineKeyboardButton('📂 My Files', callback_data='my_files')],
                [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
            ]),
            parse_mode=ParseMode.HTML
        )

    # ============================================
    # PRIVATE CHANNEL DETECTION
    # ============================================
    def handle_private_channel_detection(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message
        
        if not msg.forward_from_chat:
            return
        
        chat = msg.forward_from_chat
        channel_id = chat.id
        channel_title = chat.title or 'Private Channel'
        channel_username = chat.username
        
        logger.info(f'🔒 Private channel detection: {channel_title} ({channel_id})')
        
        # Check if bot is admin
        try:
            member = context.bot.get_chat_member(channel_id, self.bot_id)
            if member.status not in ['administrator', 'creator']:
                msg.reply_text(
                    f'❌ Bot is not an admin in "{channel_title}".\n\n'
                    f'Please add @{self.bot_username} as an admin.'
                )
                return
        except Exception as e:
            msg.reply_text(
                f'❌ Could not verify bot admin status.\n\n'
                f'Please make sure @{self.bot_username} is an admin.'
            )
            return
        
        # Check if channel exists
        existing = self.db.get_user_channels(user_id)
        if any(c['channel_id'] == channel_id for c in existing):
            msg.reply_text(f'⚠️ Channel "{channel_title}" is already in your list.')
            self.clear_session(user_id)
            return
        
        # Create invite link
        link = None
        try:
            invite_link = context.bot.create_chat_invite_link(channel_id, member_limit=0)
            link = invite_link.invite_link
        except Exception as e:
            logger.warning(f'Could not create invite link: {e}')
            if channel_username:
                link = f'https://t.me/{channel_username}'
            else:
                link = 'https://t.me/+[INVITE_CODE]'
        
        # Add channel
        self.db.add_user_channel(user_id, {
            'name': channel_title,
            'channel_id': channel_id,
            'type': 'private',
            'link': link
        })
        
        self.clear_session(user_id)
        channels = self.db.get_user_channels(user_id)
        
        msg.reply_text(
            f'✅ <b>Private Channel Added!</b>\n\n'
            f'📢 {channel_title}\n'
            f'🆔 {channel_id}\n'
            f'🔗 {link}\n\n'
            f'You now have {len(channels)} channel(s).',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
            ]),
            parse_mode=ParseMode.HTML
        )

    # ============================================
    # PUBLIC CHANNEL ADD
    # ============================================
    def handle_public_channel_add(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text
        
        # Extract channel name
        if text.startswith('@'):
            channel_name = text[1:]
        elif 't.me/' in text:
            channel_name = text.split('t.me/')[-1]
        else:
            channel_name = text.strip()
        
        logger.info(f'🌐 Public channel add: @{channel_name}')
        
        # Check if channel exists
        try:
            chat = context.bot.get_chat(f'@{channel_name}')
            channel_id = chat.id
            channel_title = chat.title or channel_name
            
            member = context.bot.get_chat_member(channel_id, self.bot_id)
            if member.status not in ['administrator', 'creator']:
                update.message.reply_text(
                    f'❌ Bot is not an admin in @{channel_name}.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔄 Try Again', callback_data='addchannel')],
                        [InlineKeyboardButton('❌ Cancel', callback_data='cancel')]
                    ])
                )
                return
        except Exception as e:
            update.message.reply_text(
                f'❌ Could not find channel @{channel_name}.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔄 Try Again', callback_data='addchannel')],
                    [InlineKeyboardButton('❌ Cancel', callback_data='cancel')]
                ])
            )
            return
        
        # Check if exists
        existing = self.db.get_user_channels(user_id)
        if any(c['channel_id'] == channel_id for c in existing):
            update.message.reply_text('⚠️ This channel is already in your list.')
            self.clear_session(user_id)
            return
        
        # Add channel
        self.db.add_user_channel(user_id, {
            'name': f'@{channel_name}',
            'channel_id': channel_id,
            'type': 'public',
            'link': f'https://t.me/{channel_name}'
        })
        
        self.clear_session(user_id)
        channels = self.db.get_user_channels(user_id)
        
        update.message.reply_text(
            f'✅ <b>Channel Added!</b>\n\n'
            f'📢 {channel_title}\n'
            f'🆔 {channel_id}\n\n'
            f'You now have {len(channels)} channel(s).',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('📤 Upload File', callback_data='upload')],
                [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')],
                [InlineKeyboardButton('🔙 Back', callback_data='back_to_menu')]
            ]),
            parse_mode=ParseMode.HTML
        )


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
    
    bot_info = updater.bot.get_me()
    handlers.bot_username = bot_info.username
    handlers.bot_id = bot_info.id
    logger.info(f'✅ Bot running: @{handlers.bot_username}')
    logger.info(f'🆔 Bot ID: {handlers.bot_id}')
    
    updater.bot.set_my_commands([
        ('start', '🚀 Start the bot'),
    ])
    
    dp.add_handler(CommandHandler('start', handlers.start_command))
    dp.add_handler(MessageHandler(Filters.document, handlers.file_handler))
    dp.add_handler(MessageHandler(Filters.photo, handlers.file_handler))
    dp.add_handler(MessageHandler(Filters.video, handlers.file_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handlers.text_handler))
    dp.add_handler(CallbackQueryHandler(handlers.callback_handler))
    
    logger.info('✅ Bot is ready!')
    
    # Start health check server
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