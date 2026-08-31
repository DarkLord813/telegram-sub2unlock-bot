#!/usr/bin/env python3
# ============================================
# TELEGRAM FILE SHARING BOT - PRODUCTION READY
# Full Complete Code - Fixed for Render Deployment
# ============================================

import os
import sys
import sqlite3
import secrets
import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================
# CONFIG
# ============================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
DB_PATH = os.getenv('DB_PATH', './data/bot_database.db')
MAX_FILE_SIZE_SEND = 50 * 1024 * 1024  # 50MB for direct send

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
        """Initialize database connection and create tables"""
        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        self.conn.execute('PRAGMA journal_mode=WAL')
        cursor = self.conn.cursor()

        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_required INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Required channels table
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

        # User channels table
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

        # Files table
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

        # File channels junction table
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
        """Save required channels to database"""
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
        """Get all required channels"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM required_channels WHERE verified = 1')
        return [dict(row) for row in cursor.fetchall()]

    def update_required_channel_id(self, channel_name: str, channel_id: int):
        """Update required channel ID"""
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE required_channels SET channel_id = ? WHERE channel_name = ?',
            (channel_id, channel_name)
        )
        self.conn.commit()

    def update_channel_link(self, channel_name: str, link: str):
        """Update required channel link"""
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE required_channels SET link = ? WHERE channel_name = ?',
            (link, channel_name)
        )
        self.conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def create_user(self, user_id: int, username: str, first_name: str):
        """Create or update user"""
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
            (user_id, username or '', first_name)
        )
        self.conn.commit()

    def mark_required_joined(self, user_id: int):
        """Mark user as having joined required channels"""
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE users SET joined_required = 1 WHERE user_id = ?',
            (user_id,)
        )
        self.conn.commit()

    def add_user_channel(self, user_id: int, channel_info: Dict) -> Dict:
        """Add a user channel"""
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
        """Get all user channels"""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM user_channels WHERE user_id = ? AND verified = 1',
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def remove_user_channel(self, user_id: int, channel_id: int):
        """Remove a user channel"""
        cursor = self.conn.cursor()
        cursor.execute(
            'DELETE FROM user_channels WHERE user_id = ? AND id = ?',
            (user_id, channel_id)
        )
        self.conn.commit()

    def create_file(self, file_data: Dict) -> Dict:
        """Create a file record"""
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
        """Get file by link code"""
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
        """Get file by ID"""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM files WHERE id = ? AND is_active = 1',
            (file_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_files(self, user_id: int) -> List[Dict]:
        """Get all user files"""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM files WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC',
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_total_files(self) -> int:
        """Get total active files"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM files WHERE is_active = 1')
        row = cursor.fetchone()
        return row['count'] if row else 0

    def increment_downloads(self, file_id: str):
        """Increment download count"""
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE files SET downloads = downloads + 1 WHERE id = ?',
            (file_id,)
        )
        self.conn.commit()

    def delete_file(self, file_id: str):
        """Soft delete a file"""
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE files SET is_active = 0 WHERE id = ?',
            (file_id,)
        )
        self.conn.commit()

    def cleanup_expired_files(self) -> int:
        """Clean up expired files"""
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE files SET is_active = 0 WHERE expiry IS NOT NULL AND expiry < datetime("now")'
        )
        self.conn.commit()
        return cursor.rowcount

    def add_file_channel(self, file_id: str, channel_id: int):
        """Add file-channel association"""
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO file_channels (file_id, channel_id) VALUES (?, ?)',
            (file_id, channel_id)
        )
        self.conn.commit()

    def close(self):
        """Close database connection"""
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
        self.application = None

    # ============================================
    # HELPER METHODS
    # ============================================
    def format_file_size(self, bytes: int) -> str:
        """Format file size in human readable format"""
        if bytes < 1024:
            return f'{bytes} B'
        if bytes < 1048576:
            return f'{bytes / 1024:.1f} KB'
        if bytes < 1073741824:
            return f'{bytes / 1048576:.1f} MB'
        return f'{bytes / 1073741824:.2f} GB'

    def get_expiry(self, opt: str) -> Optional[int]:
        """Get expiry in seconds"""
        return EXPIRY_MAP.get(opt)

    def format_expiry(self, seconds: int) -> str:
        """Format expiry time"""
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
        """Check if user is admin"""
        return user_id in ADMIN_IDS

    async def is_user_member_of_channel(self, user_id: int, channel_id: int) -> bool:
        """Check if user is member of channel"""
        try:
            member = await self.application.bot.get_chat_member(channel_id, user_id)
            return member.status in ['member', 'administrator', 'creator']
        except Exception:
            return False

    async def create_invite_link(self, channel_id: int) -> Optional[str]:
        """Create an invite link for a channel"""
        try:
            invite_link = await self.application.bot.create_chat_invite_link(
                channel_id, member_limit=0
            )
            return invite_link.invite_link
        except Exception as e:
            logger.warning(f'⚠️ Could not create invite link: {e}')
            return None

    async def get_channel_link(self, channel_name: str, channel_info: Dict) -> str:
        """Get channel link"""
        if (channel_info and channel_info.get('link') and
            channel_info['link'] != 'https://t.me/+[INVITE_CODE]' and
            '[INVITE_CODE]' not in channel_info['link']):
            return channel_info['link']

        if channel_name.startswith('+') and channel_info and channel_info.get('channel_id'):
            invite_link = await self.create_invite_link(channel_info['channel_id'])
            if invite_link:
                await self.db.update_channel_link(channel_name, invite_link)
                return invite_link
            return f'https://t.me/{channel_name}'

        if channel_name.startswith('@'):
            return f'https://t.me/{channel_name[1:]}'

        return f'https://t.me/{channel_name}'

    async def is_bot_admin_in_channel(self, channel_id: int) -> bool:
        """Check if bot is admin in channel"""
        try:
            member = await self.application.bot.get_chat_member(channel_id, self.bot_id)
            return member.status in ['administrator', 'creator']
        except Exception:
            return False

    # ============================================
    # DETECT CHANNELS
    # ============================================
    async def detect_private_channel_from_forward(self, msg) -> Dict:
        """Detect private channel from forwarded message"""
        forward_from_chat = msg.forward_from_chat
        if not forward_from_chat:
            return {'success': False, 'error': '❌ Not a forwarded message'}

        channel_id = forward_from_chat.id
        channel_title = forward_from_chat.title or 'Private Channel'
        channel_username = forward_from_chat.username

        is_admin = await self.is_bot_admin_in_channel(channel_id)

        if not is_admin:
            return {
                'success': False,
                'error': f'❌ Bot is not an admin in "{channel_title}".\n\nPlease add @{self.bot_username} as an admin.'
            }

        link = await self.create_invite_link(channel_id)

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

    async def detect_public_channel(self, identifier: str) -> Dict:
        """Detect public channel from identifier"""
        try:
            chat_info = None
            clean_id = identifier.replace('@', '').strip()

            try:
                chat_info = await self.application.bot.get_chat(f'@{clean_id}')
            except Exception:
                try:
                    chat_info = await self.application.bot.get_chat(clean_id)
                except Exception:
                    match = re.search(r't\.me/(.+)', identifier)
                    if match:
                        username = match.group(1)
                        chat_info = await self.application.bot.get_chat(f'@{username}')
                        clean_id = username

            if not chat_info or not chat_info.id:
                return {'success': False, 'error': '❌ Channel not found.'}

            is_admin = await self.is_bot_admin_in_channel(chat_info.id)
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
    async def check_all_required_channels(self, user_id: int) -> List[Dict]:
        """Check if user has joined all required channels"""
        results = []

        for channel in REQUIRED_CHANNELS:
            joined = False
            channel_id = channel['channel_id']

            if channel['type'] == 'public' and not channel_id:
                try:
                    detection = await self.detect_public_channel(channel['identifier'])
                    if detection['success']:
                        channel_id = detection['channel_id']
                        channel['channel_id'] = channel_id
                        await self.db.update_required_channel_id(channel['name'], channel_id)
                        logger.info(f'✅ Detected channel ID for {channel["name"]}: {channel_id}')
                except Exception as e:
                    logger.warning(f'⚠️ Could not detect {channel["name"]}: {e}')

            if channel_id:
                joined = await self.is_user_member_of_channel(user_id, channel_id)

            results.append({
                'channel': channel['name'],
                'joined': joined,
                'link': channel['link'],
                'channel_id': channel_id,
                'type': channel['type']
            })

        return results

    async def force_join_required_channels(self, chat_id: int, user_id: int) -> bool:
        """Force user to join required channels"""
        channel_status = await self.check_all_required_channels(user_id)
        all_joined = all(c['joined'] for c in channel_status)

        if all_joined:
            await self.db.mark_required_joined(user_id)
            return True

        kb = []
        missing_channels = []

        for ch in channel_status:
            if not ch['joined']:
                link = await self.get_channel_link(ch['channel'], {
                    'channel_id': ch['channel_id'],
                    'link': ch['link']
                })
                kb.append([InlineKeyboardButton(f'📢 Join {ch["channel"]}', url=link)])
                missing_channels.append(ch['channel'])

        kb.append([InlineKeyboardButton("✅ I've Joined All", callback_data='check_required_join')])

        channel_list = '\n'.join(f'• {c}' for c in missing_channels)

        await self.application.bot.send_message(
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
    async def force_join_user_channels(self, chat_id: int, user_id: int, file: Dict):
        """Force user to join file owner's channels"""
        channel_ids = file.get('channel_ids', '').split(',') if file.get('channel_ids') else []
        channel_names = file.get('channel_names', '').split(',') if file.get('channel_names') else []

        if not channel_ids or not channel_ids[0]:
            await self.application.bot.send_message(chat_id, '❌ No channels required for this file.')
            return

        kb = []
        channel_list = []
        user_channels = await self.db.get_user_channels(file['user_id'])

        for i, cid in enumerate(channel_ids):
            cid = int(cid) if isinstance(cid, str) else cid
            name = channel_names[i] if i < len(channel_names) else f'Channel {i+1}'
            channel = next((c for c in user_channels if c['id'] == cid), None)

            if channel:
                link = await self.get_channel_link(name, {
                    'channel_id': channel['channel_id'],
                    'link': channel['link']
                })
                kb.append([InlineKeyboardButton(f'📢 Join {name}', url=link)])
                channel_list.append(f'• {name}')

        if not kb:
            await self.application.bot.send_message(chat_id, '❌ No channels found for this file.')
            return

        kb.append([InlineKeyboardButton("✅ I've Joined All", callback_data=f'joined_channels_{file["id"]}')])

        await self.application.bot.send_message(
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
    async def show_main_menu(self, update, chat_id: int, user_id: int, first_name: str):
        """Show main menu"""
        user_channels = await self.db.get_user_channels(user_id)
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

        await update.message.reply_text(
            msg,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML
        )

    async def show_manage_channels(self, chat_id: int, user_id: int):
        """Show manage channels menu"""
        channels = await self.db.get_user_channels(user_id)
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

        await self.application.bot.send_message(
            chat_id,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    async def show_channel_selection(self, chat_id: int, user_id: int):
        """Show channel selection for file upload"""
        session = self.sessions.get(user_id)
        if not session:
            return

        if session.get('msg_id'):
            try:
                await self.application.bot.delete_message(chat_id, session['msg_id'])
            except Exception:
                pass
            session['msg_id'] = None

        channels = await self.db.get_user_channels(user_id)
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

        msg = await self.application.bot.send_message(
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

    async def show_expiry_options(self, chat_id: int):
        """Show expiry options"""
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
        await self.application.bot.send_message(
            chat_id,
            '⏰ Set expiry time:',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ============================================
    # COMMAND HANDLERS
    # ============================================
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        name = update.effective_user.first_name or 'User'
        args = context.args
        link = args[0] if args else None

        await self.db.create_user(user_id, update.effective_user.username or '', name)

        # Check required channels
        channel_status = await self.check_all_required_channels(user_id)
        all_joined = all(c['joined'] for c in channel_status)

        if not all_joined:
            await self.force_join_required_channels(chat_id, user_id)
            return

        await self.db.mark_required_joined(user_id)

        # Handle file link if provided
        if link:
            file = await self.db.get_file_by_link(link)
            if not file:
                await update.message.reply_text('❌ Invalid or expired link.')
                return

            if file.get('expiry') and datetime.fromisoformat(file['expiry']) < datetime.now():
                await self.db.delete_file(file['id'])
                await update.message.reply_text('❌ This file has expired.')
                return

            # Check if user needs to join channels
            if file.get('channel_ids'):
                channel_ids = [int(cid) for cid in file['channel_ids'].split(',') if cid]
                all_joined_channels = True
                for cid in channel_ids:
                    joined = await self.is_user_member_of_channel(user_id, cid)
                    if not joined:
                        all_joined_channels = False
                        break
                if not all_joined_channels:
                    await self.force_join_user_channels(chat_id, user_id, file)
                    return

            await self.db.increment_downloads(file['id'])

            try:
                if file.get('file_id'):
                    await context.bot.send_document(
                        chat_id, file['file_id'],
                        caption=f'📄 {file["name"]}\n📦 {self.format_file_size(file["size"])}'
                    )
                elif file.get('from_chat_id') and file.get('original_message_id'):
                    await context.bot.forward_message(
                        chat_id, file['from_chat_id'], file['original_message_id']
                    )
            except Exception as e:
                logger.error(f'Failed to send file: {e}')
                await update.message.reply_text('❌ Failed to send file.')
            return

        await self.show_main_menu(update, chat_id, user_id, name)

    # ============================================
    # CALLBACK HANDLER
    # ============================================
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        chat_id = query.message.chat.id
        data = query.data

        logger.info(f'📨 Callback: {data} from user {user_id}')

        # ---- CHECK REQUIRED JOIN ----
        if data == 'check_required_join':
            channel_status = await self.check_all_required_channels(user_id)
            all_joined = all(c['joined'] for c in channel_status)

            if all_joined:
                await self.db.mark_required_joined(user_id)
                try:
                    await context.bot.delete_message(chat_id, query.message.message_id)
                except Exception:
                    pass
                await context.bot.send_message(chat_id, '✅ Thank you for joining all required channels!')
                user = await self.db.get_user(user_id)
                # Create a fake update for show_main_menu
                class FakeUpdate:
                    def __init__(self, chat_id):
                        self.message = FakeMessage(chat_id)
                class FakeMessage:
                    def __init__(self, chat_id):
                        self.chat = FakeChat(chat_id)
                        self.reply_text = lambda *args, **kwargs: None
                class FakeChat:
                    def __init__(self, id):
                        self.id = id
                fake_update = FakeUpdate(chat_id)
                await self.show_main_menu(
                    fake_update, 
                    chat_id, 
                    user_id, 
                    user['first_name'] if user else 'User'
                )
            else:
                missing = [c for c in channel_status if not c['joined']]
                kb = []

                for ch in missing:
                    link = await self.get_channel_link(ch['channel'], {
                        'channel_id': ch['channel_id'],
                        'link': ch['link']
                    })
                    kb.append([InlineKeyboardButton(f'📢 Join {ch["channel"]}', url=link)])

                kb.append([InlineKeyboardButton('🔄 I\'ve Joined All (Retry)', callback_data='check_required_join')])

                missing_list = ', '.join(c['channel'] for c in missing)

                await query.edit_message_text(
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
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            user = await self.db.get_user(user_id)
            # Create a fake update for show_main_menu
            class FakeUpdate:
                def __init__(self, chat_id):
                    self.message = FakeMessage(chat_id)
            class FakeMessage:
                def __init__(self, chat_id):
                    self.chat = FakeChat(chat_id)
                    self.reply_text = lambda *args, **kwargs: None
            class FakeChat:
                def __init__(self, id):
                    self.id = id
            
            fake_update = FakeUpdate(chat_id)
            await self.show_main_menu(
                fake_update, 
                chat_id, 
                user_id, 
                user['first_name'] if user else 'User'
            )
            return

        # ---- HELP ----
        if data == 'help':
            await query.edit_message_text(
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
            total_files = await self.db.get_total_files()
            user_files = await self.db.get_user_files(user_id)
            await query.edit_message_text(
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
            files = await self.db.get_user_files(user_id)
            if not files:
                await query.edit_message_text(
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
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(btns),
                parse_mode=ParseMode.HTML
            )
            return

        # ---- DELETE FILE ----
        if data.startswith('delete_'):
            file_id = data.replace('delete_', '')
            await self.db.delete_file(file_id)
            await query.edit_message_text(
                '✅ File deleted.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='my_files')]
                ])
            )
            return

        # ---- MANAGE CHANNELS ----
        if data == 'managechannels':
            try:
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            await self.show_manage_channels(chat_id, user_id)
            return

        # ---- ADD PUBLIC CHANNEL ----
        if data == 'addchannel':
            self.sessions[user_id] = {'step': 'waiting_public_channel'}
            await query.edit_message_text(
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
            self.sessions[user_id] = {'step': 'waiting_private_channel'}
            await query.edit_message_text(
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
            await self.db.remove_user_channel(user_id, channel_id)
            try:
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            await self.show_manage_channels(chat_id, user_id)
            return

        # ---- UPLOAD ----
        if data == 'upload':
            user_channels = await self.db.get_user_channels(user_id)
            if not user_channels:
                await context.bot.send_message(
                    chat_id,
                    f'⚠️ No channels added!\n\n'
                    f'Add at least one channel first using "Manage Channels".',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔗 Manage Channels', callback_data='managechannels')]
                    ])
                )
                return

            self.sessions[user_id] = {'step': 'waiting_file'}
            try:
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            await context.bot.send_message(
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
                await context.bot.send_message(chat_id, '❌ Access denied. Admin only.')
                return

            try:
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            total_files = await self.db.get_total_files()

            await context.bot.send_message(
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
            files = await self.db.get_user_files(user_id)
            if not files:
                await query.edit_message_text(
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
            await query.edit_message_text(
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
            await self.db.delete_file(file_id)
            await query.edit_message_text(
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
            await query.edit_message_text(
                f'✅ Cleanup complete!\n\nRemoved {count} expired files.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back', callback_data='admin')]
                ])
            )
            return

        # ---- CHANNEL SELECTION ----
        if data == 'ch_all':
            session = self.sessions.get(user_id)
            if not session:
                return
            channels = await self.db.get_user_channels(user_id)
            session['selected_channels'] = [c['id'] for c in channels]
            await self.show_channel_selection(chat_id, user_id)
            return

        if data.startswith('ch_') and data not in ['ch_done', 'ch_skip', 'ch_all']:
            channel_id = int(data.replace('ch_', ''))
            session = self.sessions.get(user_id)
            if not session:
                return

            if channel_id in session['selected_channels']:
                session['selected_channels'].remove(channel_id)
            else:
                session['selected_channels'].append(channel_id)

            await self.show_channel_selection(chat_id, user_id)
            return

        # ---- CH_DONE ----
        if data == 'ch_done':
            session = self.sessions.get(user_id)
            if not session:
                return

            logger.info(f'✅ Done selecting. Selected: {len(session["selected_channels"])} channels')

            if session.get('msg_id'):
                try:
                    await context.bot.delete_message(chat_id, session['msg_id'])
                except Exception:
                    pass
                session['msg_id'] = None

            session['step'] = 'waiting_expiry'
            await self.show_expiry_options(chat_id)
            return

        # ---- CH_SKIP ----
        if data == 'ch_skip':
            session = self.sessions.get(user_id)
            if not session:
                return

            logger.info('⏭️ Skipping channel selection')

            session['selected_channels'] = []

            if session.get('msg_id'):
                try:
                    await context.bot.delete_message(chat_id, session['msg_id'])
                except Exception:
                    pass
                session['msg_id'] = None

            session['step'] = 'waiting_expiry'
            await self.show_expiry_options(chat_id)
            return

        # ---- EXPIRY ----
        if data.startswith('exp_'):
            opt = data.replace('exp_', '')
            expiry_seconds = self.get_expiry(opt)
            expiry = (datetime.now() + timedelta(seconds=expiry_seconds)).isoformat() if expiry_seconds else None
            session = self.sessions.get(user_id)
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
                'is_forwarded': session['info']['is_forwarded'],
                'expiry': expiry
            }

            result = await self.db.create_file(file_data)

            # Add file-channel associations
            for cid in session['selected_channels']:
                await self.db.add_file_channel(result['id'], cid)

            file_link = result['link_code']

            self.sessions.pop(user_id, None)

            link = f'https://t.me/{self.bot_username}?start={file_link}'

            try:
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass

            await context.bot.send_message(
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

            file = await self.db.get_file_by_id(file_id)
            if not file:
                await query.edit_message_text(
                    '❌ File not found. It may have been deleted or expired.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                    ])
                )
                return

            if file.get('expiry') and datetime.fromisoformat(file['expiry']) < datetime.now():
                await self.db.delete_file(file['id'])
                await query.edit_message_text(
                    '❌ This file has expired.',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                    ])
                )
                return

            channel_ids = [int(cid) for cid in file.get('channel_ids', '').split(',') if cid] if file.get('channel_ids') else []

            all_joined = True
            for cid in channel_ids:
                joined = await self.is_user_member_of_channel(user_id, cid)
                if not joined:
                    all_joined = False
                    break

            if not all_joined:
                kb = []
                user_channels = await self.db.get_user_channels(file['user_id'])

                for cid in channel_ids:
                    channel = next((c for c in user_channels if c['id'] == cid), None)
                    if channel:
                        link = await self.get_channel_link(channel['channel_name'], {
                            'channel_id': channel['channel_id'],
                            'link': channel['link']
                        })
                        kb.append([InlineKeyboardButton(f'📢 Join {channel["channel_name"]}', url=link)])
                kb.append([InlineKeyboardButton('✅ I\'ve Joined All', callback_data=f'joined_channels_{file_id}')])

                await query.edit_message_text(
                    f'❌ You haven\'t joined all channels yet.\n\n'
                    f'Please join all channels and click "I\'ve Joined All".',
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.HTML
                )
                return

            await self.db.increment_downloads(file['id'])
            try:
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass

            try:
                if file.get('file_id'):
                    await context.bot.send_document(
                        chat_id, file['file_id'],
                        caption=f'📄 {file["name"]}\n📦 {self.format_file_size(file["size"])}\n📥 {file["downloads"] + 1} downloads'
                    )
                elif file.get('from_chat_id') and file.get('original_message_id'):
                    await context.bot.forward_message(
                        chat_id, file['from_chat_id'], file['original_message_id']
                    )
                else:
                    await context.bot.send_message(chat_id, '❌ Failed to send file. The file data is incomplete.')
            except Exception as e:
                logger.error(f'❌ Send file error: {e}')
                await context.bot.send_message(chat_id, '❌ Failed to send file. Please try again.')
            return

        # ---- CANCEL ----
        if data == 'cancel':
            self.sessions.pop(user_id, None)
            try:
                await context.bot.delete_message(chat_id, query.message.message_id)
            except Exception:
                pass
            await context.bot.send_message(chat_id, '❌ Cancelled.')
            user = await self.db.get_user(user_id)
            # Create a fake update for show_main_menu
            class FakeUpdate:
                def __init__(self, chat_id):
                    self.message = FakeMessage(chat_id)
            class FakeMessage:
                def __init__(self, chat_id):
                    self.chat = FakeChat(chat_id)
                    self.reply_text = lambda *args, **kwargs: None
            class FakeChat:
                def __init__(self, id):
                    self.id = id
            
            fake_update = FakeUpdate(chat_id)
            await self.show_main_menu(
                fake_update, 
                chat_id, 
                user_id, 
                user['first_name'] if user else 'User'
            )
            return

    # ============================================
    # TEXT HANDLER
    # ============================================
    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message

        if not msg.text:
            return

        if msg.text == '/cancel':
            self.sessions.pop(user_id, None)
            await msg.reply_text('❌ Cancelled.')
            user = await self.db.get_user(user_id)
            # Create a fake update for show_main_menu
            class FakeUpdate:
                def __init__(self, chat_id):
                    self.message = FakeMessage(chat_id)
            class FakeMessage:
                def __init__(self, chat_id):
                    self.chat = FakeChat(chat_id)
                    self.reply_text = lambda *args, **kwargs: None
            class FakeChat:
                def __init__(self, id):
                    self.id = id
            
            fake_update = FakeUpdate(chat_id)
            await self.show_main_menu(
                fake_update, 
                chat_id, 
                user_id, 
                user['first_name'] if user else 'User'
            )
            return

        # Handle private channel detection via forwarded message
        if msg.forward_from_chat:
            session = self.sessions.get(user_id)
            if session and session.get('step') == 'waiting_private_channel':
                await self.handle_private_channel_detection(update, context)
                return
            return

        # Handle public channel add
        session = self.sessions.get(user_id)
        if session and session.get('step') == 'waiting_public_channel':
            channel_input = msg.text.strip()
            await self.handle_public_channel_add(user_id, chat_id, channel_input, context)

    # ============================================
    # PRIVATE CHANNEL DETECTION
    # ============================================
    async def handle_private_channel_detection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle private channel detection from forwarded message"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message

        if not msg.forward_from_chat:
            return

        session = self.sessions.get(user_id)
        if not session or session.get('step') != 'waiting_private_channel':
            return

        detection = await self.detect_private_channel_from_forward(msg)

        if not detection['success']:
            await context.bot.send_message(
                chat_id,
                f'❌ {detection["error"]}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔄 Try Again', callback_data='addprivate')],
                    [InlineKeyboardButton('❌ Cancel', callback_data='cancel')]
                ])
            )
            return

        existing = await self.db.get_user_channels(user_id)
        exists = any(c['channel_id'] == detection['channel_id'] for c in existing)

        if exists:
            await context.bot.send_message(
                chat_id,
                f'⚠️ This channel is already in your list.\n\n'
                f'📢 {detection["title"]}\n'
                f'🆔 {detection["channel_id"]}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ])
            )
            self.sessions.pop(user_id, None)
            return

        await self.db.add_user_channel(user_id, {
            'name': detection['title'],
            'channel_id': detection['channel_id'],
            'type': 'private',
            'link': detection['link']
        })

        channels = await self.db.get_user_channels(user_id)

        await context.bot.send_message(
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

        self.sessions.pop(user_id, None)

    # ============================================
    # PUBLIC CHANNEL ADD
    # ============================================
    async def handle_public_channel_add(self, user_id: int, chat_id: int, channel_input: str, context):
        """Handle public channel addition"""
        detection = await self.detect_public_channel(channel_input)
        if not detection['success']:
            await context.bot.send_message(
                chat_id,
                f'❌ {detection["error"]}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🔄 Try Again', callback_data='addchannel')],
                    [InlineKeyboardButton('❌ Cancel', callback_data='cancel')]
                ])
            )
            return

        existing = await self.db.get_user_channels(user_id)
        exists = any(c['channel_id'] == detection['channel_id'] for c in existing)

        if exists:
            await context.bot.send_message(chat_id, '⚠️ This channel is already in your list.')
            self.sessions.pop(user_id, None)
            await self.show_manage_channels(chat_id, user_id)
            return

        await self.db.add_user_channel(user_id, {
            'name': detection['title'],
            'channel_id': detection['channel_id'],
            'type': 'public',
            'link': detection['link']
        })

        self.sessions.pop(user_id, None)
        channels = await self.db.get_user_channels(user_id)

        await context.bot.send_message(
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
    async def file_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file uploads"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        msg = update.message

        session = self.sessions.get(user_id)
        if not session or session.get('step') != 'waiting_file':
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

        # Check if forwarded
        if msg.forward_origin or msg.forward_from or msg.forward_from_chat:
            is_forwarded = True
            if msg.forward_origin:
                if hasattr(msg.forward_origin, 'chat'):
                    from_chat_id = msg.forward_origin.chat.id
                    original_message_id = msg.forward_origin.message_id
            elif msg.forward_from_chat:
                from_chat_id = msg.forward_from_chat.id
                original_message_id = msg.forward_from_message_id

        # Get file based on type
        if msg.document:
            file = msg.document
            file_name = file.file_name or 'document'
            mime_type = file.mime_type or 'application/octet-stream'
            file_size = file.file_size
            file_id = file.file_id
        elif msg.photo:
            file = msg.photo[-1]
            file_name = f'photo_{int(datetime.now().timestamp())}.jpg'
            mime_type = 'image/jpeg'
            file_size = file.file_size
            file_id = file.file_id
        elif msg.video:
            file = msg.video
            file_name = file.file_name or 'video.mp4'
            mime_type = file.mime_type or 'video/mp4'
            file_size = file.file_size
            file_id = file.file_id
        else:
            await msg.reply_text('❌ Please send a document, photo, or video.')
            return

        # Check size limit for direct sends
        if not is_forwarded and file_size > MAX_FILE_SIZE_SEND:
            await msg.reply_text(
                f'❌ File too large ({self.format_file_size(file_size)}).\n\n'
                f'Please FORWARD the file instead (supports up to 2GB).'
            )
            return

        # Create file in database
        unique_id = secrets.token_hex(16)
        
        # Check if user has channels, if not, use a default
        user_channels = await self.db.get_user_channels(user_id)
        
        # Store in session for channel selection
        self.sessions[user_id] = {
            'step': 'waiting_channels',
            'file_id': unique_id,
            'info': {
                'name': file_name,
                'size': file_size,
                'mime_type': mime_type,
                'file_id': file_id,
                'from_chat_id': from_chat_id,
                'original_message_id': original_message_id,
                'is_forwarded': is_forwarded
            },
            'selected_channels': [ch['id'] for ch in user_channels]  # Auto-select all channels
        }

        # If user has channels, go to expiry directly
        if user_channels:
            # Create file directly with all channels
            file_data = {
                'id': unique_id,
                'user_id': user_id,
                'name': file_name,
                'size': file_size,
                'mime_type': mime_type,
                'file_id': file_id,
                'from_chat_id': from_chat_id,
                'original_message_id': original_message_id,
                'is_forwarded': is_forwarded,
                'expiry': None
            }

            result = await self.db.create_file(file_data)

            # Add file-channel associations
            for ch in user_channels:
                await self.db.add_file_channel(result['id'], ch['id'])

            self.sessions.pop(user_id, None)

            link = f'https://t.me/{self.bot_username}?start={result["link_code"]}'

            await msg.reply_text(
                f'✅ <b>File Uploaded!</b>\n\n'
                f'📄 {file_name}\n'
                f'📦 {self.format_file_size(file_size)}\n'
                f'⏰ ♾️ Permanent\n'
                f'📢 Channels: {len(user_channels)} channel(s)\n\n'
                f'🔗 Shareable Link:\n'
                f'{link}',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📤 Upload More', callback_data='upload')],
                    [InlineKeyboardButton('📂 My Files', callback_data='my_files')],
                    [InlineKeyboardButton('🔙 Back to Menu', callback_data='back_to_menu')]
                ]),
                parse_mode=ParseMode.HTML
            )
        else:
            # No channels, show channel selection
            await self.show_channel_selection(chat_id, user_id)


# ============================================
# MAIN - FIXED VERSION
# ============================================
async def main():
    """Main entry point"""
    logger.info('🚀 Starting bot...')

    db = Database()
    handlers = BotHandlers(db)

    # Build application
    application = Application.builder().token(BOT_TOKEN).build()

    # Store application reference in handlers
    handlers.application = application

    # Add handlers
    application.add_handler(CommandHandler('start', handlers.start_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers.file_handler))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.file_handler))
    application.add_handler(MessageHandler(filters.VIDEO, handlers.file_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_handler))
    application.add_handler(CallbackQueryHandler(handlers.callback_handler))

    # Get bot info
    bot_info = await application.bot.get_me()
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
    await application.bot.set_my_commands([
        ('start', '🚀 Start the bot'),
    ])

    logger.info('\n✅ Bot is ready!')
    logger.info(f'\n👑 Admins: {", ".join(str(a) for a in ADMIN_IDS) if ADMIN_IDS else "None"}')

    # Start the bot using run_polling()
    await application.run_polling()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('🛑 Bot stopped by user')
    except Exception as e:
        logger.error(f'❌ Fatal error: {e}')
        sys.exit(1)