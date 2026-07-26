// ============================================
// TELEGRAM FILE SHARING BOT - PRODUCTION READY
// Fixed: Invite links never expire (unlimited uses)
// ============================================

const TelegramBot = require('node-telegram-bot-api');
const dotenv = require('dotenv');
const fs = require('fs');
const crypto = require('crypto');
const sqlite3 = require('sqlite3').verbose();

dotenv.config();

// ============================================
// CONFIG
// ============================================
const BOT_TOKEN = process.env.BOT_TOKEN;
const ADMIN_IDS = (process.env.ADMIN_IDS || '').split(',').map(id => parseInt(id.trim()));
const DB_PATH = './bot_database.db';

// ============================================
// REQUIRED CHANNELS
// ============================================
const REQUIRED_CHANNELS = [
  {
    name: '@NCK_Dev',
    type: 'public',
    identifier: '@NCK_Dev',
    link: 'https://t.me/NCK_Dev',
    channelId: null
  },
  {
    name: '+Yl4nKkthd1ExZWVk',
    type: 'private',
    identifier: '-1004266231051',
    link: 'https://t.me/+Yl4nKkthd1ExZWVk',
    channelId: -1004266231051
  }
];

// ============================================
// DATABASE
// ============================================
class Database {
  constructor() {
    this.db = new sqlite3.Database(DB_PATH);
    this.initTables();
  }

  initTables() {
    this.db.serialize(() => {
      this.db.run(`
        CREATE TABLE IF NOT EXISTS users (
          user_id INTEGER PRIMARY KEY,
          username TEXT,
          first_name TEXT,
          joined_required INTEGER DEFAULT 0,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
      `);

      this.db.run(`
        CREATE TABLE IF NOT EXISTS required_channels (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          channel_name TEXT,
          channel_id INTEGER,
          channel_type TEXT,
          link TEXT,
          verified INTEGER DEFAULT 1,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
      `);

      this.db.run(`
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
      `);

      this.db.run(`
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
      `);

      this.db.run(`
        CREATE TABLE IF NOT EXISTS file_channels (
          file_id TEXT,
          channel_id INTEGER,
          FOREIGN KEY (file_id) REFERENCES files(id),
          FOREIGN KEY (channel_id) REFERENCES user_channels(id)
        )
      `);

      this.saveRequiredChannels();
    });

    console.log('✅ SQLite Database initialized');
  }

  saveRequiredChannels() {
    for (const channel of REQUIRED_CHANNELS) {
      if (channel.channelId) {
        this.db.run(
          `INSERT OR REPLACE INTO required_channels 
           (channel_name, channel_id, channel_type, link) 
           VALUES (?, ?, ?, ?)`,
          [channel.name, channel.channelId, channel.type, channel.link],
          (err) => {
            if (err) console.error('Error saving channel:', err);
          }
        );
      } else {
        this.db.run(
          `INSERT OR IGNORE INTO required_channels 
           (channel_name, channel_type, link) 
           VALUES (?, ?, ?)`,
          [channel.name, channel.type, channel.link],
          (err) => {
            if (err) console.error('Error saving channel:', err);
          }
        );
      }
    }
  }

  getRequiredChannels() {
    return new Promise((resolve, reject) => {
      this.db.all(
        'SELECT * FROM required_channels WHERE verified = 1',
        [],
        (err, rows) => {
          if (err) reject(err);
          else resolve(rows || []);
        }
      );
    });
  }

  updateRequiredChannelId(channelName, channelId) {
    return new Promise((resolve, reject) => {
      this.db.run(
        'UPDATE required_channels SET channel_id = ? WHERE channel_name = ?',
        [channelId, channelName],
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });
  }

  updateChannelLink(channelName, link) {
    return new Promise((resolve, reject) => {
      this.db.run(
        'UPDATE required_channels SET link = ? WHERE channel_name = ?',
        [link, channelName],
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });
  }

  getUser(userId) {
    return new Promise((resolve, reject) => {
      this.db.get('SELECT * FROM users WHERE user_id = ?', [userId], (err, row) => {
        if (err) reject(err);
        else resolve(row);
      });
    });
  }

  createUser(userId, username, firstName) {
    return new Promise((resolve, reject) => {
      this.db.run(
        'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
        [userId, username, firstName],
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });
  }

  markRequiredJoined(userId) {
    return new Promise((resolve, reject) => {
      this.db.run(
        'UPDATE users SET joined_required = 1 WHERE user_id = ?',
        [userId],
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });
  }

  addUserChannel(userId, channelInfo) {
    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO user_channels 
         (user_id, channel_name, channel_id, channel_type, link) 
         VALUES (?, ?, ?, ?, ?)`,
        [userId, channelInfo.name, channelInfo.channelId, channelInfo.type, channelInfo.link],
        function(err) {
          if (err) reject(err);
          else resolve({ id: this.lastID, ...channelInfo });
        }
      );
    });
  }

  getUserChannels(userId) {
    return new Promise((resolve, reject) => {
      this.db.all(
        'SELECT * FROM user_channels WHERE user_id = ? AND verified = 1',
        [userId],
        (err, rows) => {
          if (err) reject(err);
          else resolve(rows || []);
        }
      );
    });
  }

  removeUserChannel(userId, channelId) {
    return new Promise((resolve, reject) => {
      this.db.run(
        'DELETE FROM user_channels WHERE user_id = ? AND id = ?',
        [userId, channelId],
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });
  }

  createFile(fileData) {
    return new Promise((resolve, reject) => {
      const linkCode = crypto.randomBytes(16).toString('hex');
      this.db.run(
        `INSERT INTO files 
         (id, user_id, name, size, mime_type, file_id, from_chat_id, 
          original_message_id, is_forwarded, link_code, expiry) 
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          fileData.id,
          fileData.userId,
          fileData.name,
          fileData.size,
          fileData.mimeType,
          fileData.fileId,
          fileData.fromChatId || null,
          fileData.originalMessageId || null,
          fileData.isForwarded ? 1 : 0,
          linkCode,
          fileData.expiry || null
        ],
        function(err) {
          if (err) reject(err);
          else resolve({ id: fileData.id, linkCode });
        }
      );
    });
  }

  getFileByLink(linkCode) {
    return new Promise((resolve, reject) => {
      this.db.get(
        `SELECT f.*, 
         GROUP_CONCAT(uc.id) as channel_ids,
         GROUP_CONCAT(uc.channel_name) as channel_names
         FROM files f
         LEFT JOIN file_channels fc ON f.id = fc.file_id
         LEFT JOIN user_channels uc ON fc.channel_id = uc.id
         WHERE f.link_code = ? AND f.is_active = 1
         GROUP BY f.id`,
        [linkCode],
        (err, row) => {
          if (err) reject(err);
          else resolve(row);
        }
      );
    });
  }

  getFileById(fileId) {
    return new Promise((resolve, reject) => {
      this.db.get(
        'SELECT * FROM files WHERE id = ? AND is_active = 1',
        [fileId],
        (err, row) => {
          if (err) reject(err);
          else resolve(row);
        }
      );
    });
  }

  getUserFiles(userId) {
    return new Promise((resolve, reject) => {
      this.db.all(
        'SELECT * FROM files WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC',
        [userId],
        (err, rows) => {
          if (err) reject(err);
          else resolve(rows || []);
        }
      );
    });
  }

  getTotalFiles() {
    return new Promise((resolve, reject) => {
      this.db.get(
        'SELECT COUNT(*) as count FROM files WHERE is_active = 1',
        [],
        (err, row) => {
          if (err) reject(err);
          else resolve(row ? row.count : 0);
        }
      );
    });
  }

  incrementDownloads(fileId) {
    return new Promise((resolve, reject) => {
      this.db.run(
        'UPDATE files SET downloads = downloads + 1 WHERE id = ?',
        [fileId],
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });
  }

  deleteFile(fileId) {
    return new Promise((resolve, reject) => {
      this.db.run(
        'UPDATE files SET is_active = 0 WHERE id = ?',
        [fileId],
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });
  }

  cleanupExpiredFiles() {
    return new Promise((resolve, reject) => {
      this.db.run(
        'UPDATE files SET is_active = 0 WHERE expiry IS NOT NULL AND expiry < datetime("now")',
        [],
        function(err) {
          if (err) reject(err);
          else resolve(this.changes || 0);
        }
      );
    });
  }

  close() {
    return new Promise((resolve, reject) => {
      this.db.close((err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }
}

// ============================================
// MAIN BOT CLASS
// ============================================
class FileSharingBot {
  constructor() {
    this.bot = new TelegramBot(BOT_TOKEN, { polling: true });
    this.db = new Database();
    this.BOT_USERNAME = '';
    this.BOT_ID = 0;
    this.sessions = {};
    
    this.setupHandlers();
    this.init();
  }

  async init() {
    try {
      const info = await this.bot.getMe();
      this.BOT_USERNAME = info.username;
      this.BOT_ID = info.id;
      console.log(`✅ Bot running: @${this.BOT_USERNAME}`);
      console.log(`🆔 Bot ID: ${this.BOT_ID}`);
      
      console.log(`\n🔐 Required Channels (Bot-wide):`);
      for (const ch of REQUIRED_CHANNELS) {
        if (ch.channelId) {
          console.log(`  ✅ ${ch.name} (${ch.type}) - ID: ${ch.channelId}`);
        } else {
          console.log(`  ⏳ ${ch.name} (${ch.type}) - Will auto-detect`);
        }
      }
      
      setInterval(() => this.cleanupExpiredFiles(), 300000);
      
      await this.bot.setMyCommands([
        { command: 'start', description: 'Start the bot' }
      ]);
      
      console.log('\n✅ Bot is ready!');
    } catch (error) {
      console.error('❌ Bot init error:', error);
    }
  }

  // ============================================
  // CREATE INVITE LINK - NEVER EXPIRES
  // ============================================
  async createInviteLink(channelId) {
    try {
      // Create invite link with unlimited uses (0 = unlimited)
      const inviteLink = await this.bot.createChatInviteLink(channelId, {
        member_limit: 0,        // 0 = unlimited uses
        expire_date: null       // No expiry
      });
      console.log(`✅ Created invite link: ${inviteLink.invite_link}`);
      return inviteLink.invite_link;
    } catch (error) {
      console.log(`⚠️ Could not create invite link: ${error.message}`);
      return null;
    }
  }

  // ============================================
  // GET CHANNEL LINK
  // ============================================
  async getChannelLink(channelName, channelInfo) {
    // If channel has a stored link, use it
    if (channelInfo && channelInfo.link && 
        channelInfo.link !== 'https://t.me/+[INVITE_CODE]' &&
        !channelInfo.link.includes('[INVITE_CODE]')) {
      return channelInfo.link;
    }
    
    // If it's a private channel, create a new invite link
    if (channelName.startsWith('+') && channelInfo && channelInfo.channelId) {
      const inviteLink = await this.createInviteLink(channelInfo.channelId);
      if (inviteLink) {
        // Save the link to the database
        await this.db.updateChannelLink(channelName, inviteLink);
        return inviteLink;
      }
      // Fallback: use invite code format
      return `https://t.me/${channelName}`;
    }
    
    // If it's a public channel (starts with @), use username
    if (channelName.startsWith('@')) {
      return `https://t.me/${channelName.replace('@', '')}`;
    }
    
    // Fallback: use as is
    return `https://t.me/${channelName}`;
  }

  // ============================================
  // CHECK IF BOT IS ADMIN IN CHANNEL
  // ============================================
  async isBotAdminInChannel(channelId) {
    try {
      const botMember = await this.bot.getChatMember(channelId, this.BOT_ID);
      return ['administrator', 'creator'].includes(botMember.status);
    } catch (e) {
      return false;
    }
  }

  // ============================================
  // CHECK IF USER IS MEMBER OF CHANNEL
  // ============================================
  async isUserMemberOfChannel(userId, channelId) {
    try {
      const member = await this.bot.getChatMember(channelId, userId);
      return ['member', 'administrator', 'creator'].includes(member.status);
    } catch (e) {
      return false;
    }
  }

  // ============================================
  // DETECT PRIVATE CHANNEL FROM FORWARD
  // ============================================
  async detectPrivateChannelFromForward(msg) {
    if (!msg.forward_from_chat) {
      return { success: false, error: 'Not a forwarded message' };
    }
    
    const chat = msg.forward_from_chat;
    const channelId = chat.id;
    const channelTitle = chat.title || 'Private Channel';
    const channelUsername = chat.username || null;
    
    const isAdmin = await this.isBotAdminInChannel(channelId);
    
    if (!isAdmin) {
      return { 
        success: false, 
        error: `Bot is not an admin in "${channelTitle}".\n\nPlease add @${this.BOT_USERNAME} as an admin.`
      };
    }
    
    // Create permanent invite link
    let link = await this.createInviteLink(channelId);
    
    if (!link) {
      if (channelUsername) {
        link = `https://t.me/${channelUsername}`;
      } else {
        link = 'https://t.me/+[INVITE_CODE]';
      }
    }
    
    return {
      success: true,
      channelId: channelId,
      title: channelTitle,
      username: channelUsername,
      type: 'private',
      link: link
    };
  }

  // ============================================
  // DETECT PUBLIC CHANNEL
  // ============================================
  async detectPublicChannel(identifier) {
    try {
      let chatInfo = null;
      let cleanId = identifier.replace('@', '').trim();
      
      try {
        chatInfo = await this.bot.getChat(`@${cleanId}`);
      } catch (e) {
        try {
          chatInfo = await this.bot.getChat(cleanId);
        } catch (e2) {
          const linkMatch = identifier.match(/t\.me\/(.+)/);
          if (linkMatch) {
            const username = linkMatch[1];
            chatInfo = await this.bot.getChat(`@${username}`);
            cleanId = username;
          }
        }
      }
      
      if (!chatInfo || !chatInfo.id) {
        return { success: false, error: 'Channel not found.' };
      }
      
      const isAdmin = await this.isBotAdminInChannel(chatInfo.id);
      if (!isAdmin) {
        return { 
          success: false, 
          error: `Bot is not an admin in @${cleanId}. Please add @${this.BOT_USERNAME} as admin.` 
        };
      }
      
      return {
        success: true,
        channelId: chatInfo.id,
        title: chatInfo.title || cleanId,
        type: 'public',
        link: `https://t.me/${cleanId}`
      };
    } catch (error) {
      return { success: false, error: `Error: ${error.message}` };
    }
  }

  // ============================================
  // CHECK ALL REQUIRED CHANNELS
  // ============================================
  async checkAllRequiredChannels(userId) {
    const results = [];
    
    for (const channel of REQUIRED_CHANNELS) {
      let joined = false;
      let channelId = channel.channelId;
      
      if (channel.type === 'public' && !channelId) {
        try {
          const detection = await this.detectPublicChannel(channel.identifier);
          if (detection.success) {
            channelId = detection.channelId;
            channel.channelId = channelId;
            await this.db.updateRequiredChannelId(channel.name, channelId);
          }
        } catch (e) {}
      }
      
      if (channelId) {
        joined = await this.isUserMemberOfChannel(userId, channelId);
      }
      
      results.push({
        channel: channel.name,
        joined,
        link: channel.link,
        channelId,
        type: channel.type
      });
    }
    
    return results;
  }

  // ============================================
  // FORCE JOIN REQUIRED CHANNELS
  // ============================================
  async forceJoinRequiredChannels(chatId, userId) {
    const channelStatus = await this.checkAllRequiredChannels(userId);
    const allJoined = channelStatus.every(c => c.joined);
    
    if (allJoined) {
      await this.db.markRequiredJoined(userId);
      return true;
    }
    
    const kb = { inline_keyboard: [] };
    const missingChannels = [];
    
    for (const ch of channelStatus) {
      if (!ch.joined) {
        const link = await this.getChannelLink(ch.channel, {
          channelId: ch.channelId,
          link: ch.link
        });
        kb.inline_keyboard.push([
          { text: `📢 Join ${ch.channel}`, url: link }
        ]);
        missingChannels.push(ch.channel);
      }
    }
    
    kb.inline_keyboard.push([
      { text: '✅ I\'ve Joined All', callback_data: 'check_required_join' }
    ]);
    
    const channelList = missingChannels.map(c => `• ${c}`).join('\n');
    
    await this.sendMessage(chatId,
      `🔐 <b>Channels Required</b>\n\n` +
      `You must join <b>ALL</b> these channels to use this bot:\n\n` +
      `${channelList}\n\n` +
      `Join all channels and click "I've Joined All".`,
      kb
    );
    return false;
  }

  // ============================================
  // SEND MESSAGE
  // ============================================
  async sendMessage(chatId, text, kb = null, retries = 3) {
    for (let i = 0; i < retries; i++) {
      try {
        return await this.bot.sendMessage(chatId, text, { 
          reply_markup: kb, 
          parse_mode: 'HTML' 
        });
      } catch (e) {
        if (i === retries - 1) return null;
        await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)));
      }
    }
  }

  // ============================================
  // CLEANUP
  // ============================================
  async cleanupExpiredFiles() {
    try {
      const count = await this.db.cleanupExpiredFiles();
      if (count > 0) {
        console.log(`🧹 Cleaned up ${count} expired files`);
      }
    } catch (e) {
      console.error('❌ Cleanup error:', e);
    }
  }

  // ============================================
  // HELPERS
  // ============================================
  formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1073741824).toFixed(2) + ' GB';
  }

  getExpiry(opt) {
    const map = { 
      '5min': 5 * 60 * 1000, 
      '10min': 10 * 60 * 1000, 
      '15min': 15 * 60 * 1000, 
      '30min': 30 * 60 * 1000,
      '1hr': 60 * 60 * 1000, 
      '2hr': 2 * 60 * 60 * 1000, 
      '24hr': 24 * 60 * 60 * 1000, 
      'permanent': null 
    };
    return map[opt] || null;
  }

  formatExpiry(ms) {
    if (!ms) return '♾️ Permanent';
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    const d = Math.floor(h / 24);
    if (d) return `${d}d`;
    if (h) return `${h}h`;
    if (m) return `${m}m`;
    return `${s}s`;
  }

  isAdmin(userId) {
    return ADMIN_IDS.includes(userId);
  }

  // ============================================
  // SHOW MAIN MENU
  // ============================================
  async showMainMenu(chatId, userId, firstName) {
    const userChannels = await this.db.getUserChannels(userId);
    const isAdmin = this.isAdmin(userId);
    
    const kb = {
      inline_keyboard: [
        [{ text: '📤 Upload File', callback_data: 'upload' }],
        [{ text: '📂 My Files', callback_data: 'my_files' }],
        [{ text: '📊 Stats', callback_data: 'stats' }],
        [{ text: '🔗 Manage Channels', callback_data: 'managechannels' }]
      ]
    };
    if (isAdmin) kb.inline_keyboard.push([{ text: '🛠 Admin', callback_data: 'admin' }]);
    kb.inline_keyboard.push([{ text: '❓ Help', callback_data: 'help' }]);

    let msg = `👋 Welcome ${firstName}!\n\n`;
    msg += `✅ Required channels joined!\n`;
    msg += `📤 Upload files (up to 2GB via forward)\n`;
    msg += `🔗 Users must join YOUR channels to download\n`;
    msg += `⏰ Set expiry time\n\n`;
    
    if (userChannels.length) {
      msg += `✅ Your Channels (${userChannels.length}):\n`;
      msg += userChannels.map(c => `  • ${c.channel_name}`).join('\n');
      msg += `\n\n💡 Users must join ALL these channels to download your files.`;
    } else {
      msg += `⚠️ No channels added!\n`;
      msg += `Use "Manage Channels" to add channels.\n`;
    }
    
    await this.sendMessage(chatId, msg, kb);
  }

  // ============================================
  // SHOW MANAGE CHANNELS
  // ============================================
  async showManageChannels(chatId, userId) {
    const channels = await this.db.getUserChannels(userId);
    let text = `🔗 Manage Your Channels\n\n`;
    
    if (channels.length) {
      text += `📋 Your channels (${channels.length}):\n\n`;
      const btns = [];
      for (const ch of channels) {
        const typeIcon = ch.channel_type === 'private' ? '🔒' : '🌐';
        text += `  ${typeIcon} ${ch.channel_name}\n`;
        text += `    ID: ${ch.channel_id}\n`;
        if (ch.link && ch.link !== 'https://t.me/+[INVITE_CODE]') {
          text += `    Link: ${ch.link}\n`;
        }
        btns.push([{ text: `❌ Remove ${ch.channel_name}`, callback_data: `remove_${ch.id}` }]);
      }
      text += `\n⚠️ Users must join ALL these channels to download your files.\n\n`;
      
      const kb = { inline_keyboard: btns };
      kb.inline_keyboard.push([{ text: '➕ Add Public Channel', callback_data: 'addchannel' }]);
      kb.inline_keyboard.push([{ text: '🔒 Add Private Channel', callback_data: 'addprivate' }]);
      kb.inline_keyboard.push([{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]);
      
      await this.sendMessage(chatId, text, kb);
    } else {
      text += `No channels added yet.\n\n`;
      text += `Add channels that users must join to download your files.\n\n`;
      text += `⚠️ You must add at least one channel to upload files.`;
      
      const kb = {
        inline_keyboard: [
          [{ text: '➕ Add Public Channel', callback_data: 'addchannel' }],
          [{ text: '🔒 Add Private Channel', callback_data: 'addprivate' }],
          [{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]
        ]
      };
      
      await this.sendMessage(chatId, text, kb);
    }
  }

  // ============================================
  // SHOW EXPIRY OPTIONS
  // ============================================
  async showExpiryOptions(chatId) {
    const kb = {
      inline_keyboard: [
        [{ text: '5 min', callback_data: 'exp_5min' }, { text: '10 min', callback_data: 'exp_10min' }],
        [{ text: '15 min', callback_data: 'exp_15min' }, { text: '30 min', callback_data: 'exp_30min' }],
        [{ text: '1 hour', callback_data: 'exp_1hr' }, { text: '2 hours', callback_data: 'exp_2hr' }],
        [{ text: '24 hours', callback_data: 'exp_24hr' }, { text: '♾️ Permanent', callback_data: 'exp_permanent' }],
        [{ text: '❌ Cancel', callback_data: 'cancel' }]
      ]
    };
    await this.sendMessage(chatId, '⏰ Set expiry time:', kb);
  }

  // ============================================
  // HANDLE PRIVATE CHANNEL DETECTION
  // ============================================
  async handlePrivateChannelDetection(msg) {
    const userId = msg.from.id;
    const chatId = msg.chat.id;
    
    if (!msg.forward_from_chat) {
      return false;
    }
    
    if (!this.sessions[userId] || this.sessions[userId].step !== 'waiting_private_channel') {
      return false;
    }
    
    const detection = await this.detectPrivateChannelFromForward(msg);
    
    if (!detection.success) {
      await this.sendMessage(chatId, `❌ ${detection.error}`, {
        inline_keyboard: [
          [{ text: '🔄 Try Again', callback_data: 'addprivate' }],
          [{ text: '❌ Cancel', callback_data: 'cancel' }]
        ]
      });
      return false;
    }
    
    const existing = await this.db.getUserChannels(userId);
    const exists = existing.some(c => c.channel_id === detection.channelId);
    
    if (exists) {
      await this.sendMessage(chatId,
        `⚠️ This channel is already in your list.\n\n` +
        `📢 ${detection.title}\n` +
        `🆔 ${detection.channelId}`,
        {
          inline_keyboard: [
            [{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]
          ]
        }
      );
      delete this.sessions[userId];
      return true;
    }
    
    await this.db.addUserChannel(userId, {
      name: detection.title,
      channelId: detection.channelId,
      type: 'private',
      link: detection.link
    });
    
    const channels = await this.db.getUserChannels(userId);
    
    await this.sendMessage(chatId,
      `✅ <b>Private Channel Added!</b>\n\n` +
      `📢 ${detection.title}\n` +
      `🆔 ${detection.channelId}\n` +
      `🔗 ${detection.link}\n\n` +
      `You now have ${channels.length} channel(s).`,
      {
        inline_keyboard: [
          [{ text: '📤 Upload File', callback_data: 'upload' }],
          [{ text: '🔗 Manage Channels', callback_data: 'managechannels' }],
          [{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]
        ]
      }
    );
    
    delete this.sessions[userId];
    return true;
  }

  // ============================================
  // HANDLE PUBLIC CHANNEL ADD
  // ============================================
  async handlePublicChannelAdd(userId, chatId, channelInput) {
    const detection = await this.detectPublicChannel(channelInput);
    if (!detection.success) {
      await this.sendMessage(chatId, 
        `❌ ${detection.error}`,
        {
          inline_keyboard: [
            [{ text: '🔄 Try Again', callback_data: 'addchannel' }],
            [{ text: '❌ Cancel', callback_data: 'cancel' }]
          ]
        }
      );
      return;
    }
    
    const existing = await this.db.getUserChannels(userId);
    const exists = existing.some(c => c.channel_id === detection.channelId);
    
    if (exists) {
      await this.sendMessage(chatId, '⚠️ This channel is already in your list.');
      delete this.sessions[userId];
      await this.showManageChannels(chatId, userId);
      return;
    }
    
    await this.db.addUserChannel(userId, {
      name: detection.title,
      channelId: detection.channelId,
      type: 'public',
      link: detection.link
    });
    
    delete this.sessions[userId];
    const channels = await this.db.getUserChannels(userId);
    
    await this.sendMessage(chatId,
      `✅ <b>Channel Added!</b>\n\n` +
      `📢 ${detection.title}\n` +
      `🆔 ${detection.channelId}\n\n` +
      `You now have ${channels.length} channel(s).`,
      {
        inline_keyboard: [
          [{ text: '📤 Upload File', callback_data: 'upload' }],
          [{ text: '🔗 Manage Channels', callback_data: 'managechannels' }],
          [{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]
        ]
      }
    );
  }

  // ============================================
  // HANDLE FILE UPLOAD
  // ============================================
  async handleFileUpload(msg, type) {
    const userId = msg.from.id;
    const chatId = msg.chat.id;
    
    if (!this.sessions[userId] || this.sessions[userId].step !== 'waiting_file') {
      return;
    }
    
    let file, fileName, mimeType, fileSize;
    let isForwarded = false;
    let fromChatId = null;
    let originalMessageId = null;
    let fileId = null;
    
    if (msg.forward_origin || msg.forward_from || msg.forward_from_chat) {
      isForwarded = true;
      if (msg.forward_origin) {
        if (msg.forward_origin.type === 'channel') {
          fromChatId = msg.forward_origin.chat.id;
          originalMessageId = msg.forward_origin.message_id;
        }
      } else if (msg.forward_from_chat) {
        fromChatId = msg.forward_from_chat.id;
        originalMessageId = msg.forward_from_message_id;
      }
    }
    
    if (type === 'document') {
      file = msg.document;
      fileName = file.file_name || 'document';
      mimeType = file.mime_type || 'application/octet-stream';
      fileSize = file.file_size;
      fileId = file.file_id;
    } else if (type === 'photo') {
      file = msg.photo[msg.photo.length - 1];
      fileName = `photo_${Date.now()}.jpg`;
      mimeType = 'image/jpeg';
      fileSize = file.file_size;
      fileId = file.file_id;
    } else if (type === 'video') {
      file = msg.video;
      fileName = file.file_name || 'video.mp4';
      mimeType = file.mime_type || 'video/mp4';
      fileSize = file.file_size;
      fileId = file.file_id;
    }
    
    if (!isForwarded && fileSize > 50 * 1024 * 1024) {
      await this.sendMessage(chatId,
        `❌ File too large (${this.formatFileSize(fileSize)}).\n\n` +
        `Please FORWARD the file instead (supports up to 2GB).`
      );
      return;
    }
    
    const uniqueId = crypto.randomBytes(16).toString('hex');
    this.sessions[userId] = {
      step: 'waiting_channels',
      fileId: uniqueId,
      info: {
        name: fileName,
        size: fileSize,
        mimeType: mimeType,
        fileId: fileId,
        fromChatId: fromChatId,
        originalMessageId: originalMessageId,
        isForwarded: isForwarded
      },
      selectedChannels: []
    };
    
    await this.showChannelSelection(chatId, userId);
  }

  // ============================================
  // SHOW CHANNEL SELECTION
  // ============================================
  async showChannelSelection(chatId, userId) {
    const session = this.sessions[userId];
    if (!session) return;
    
    if (session.msgId) {
      try {
        await this.bot.deleteMessage(chatId, session.msgId);
      } catch (e) {}
      session.msgId = null;
    }
    
    const channels = await this.db.getUserChannels(userId);
    const selected = session.selectedChannels || [];
    const kb = { inline_keyboard: [] };
    
    kb.inline_keyboard.push([{ text: `📢 ALL Channels (${channels.length})`, callback_data: 'ch_all' }]);
    
    for (const ch of channels) {
      const isSelected = selected.includes(ch.id);
      kb.inline_keyboard.push([{ 
        text: `${isSelected ? '✅' : '⬜'} ${ch.channel_name}`, 
        callback_data: `ch_${ch.id}` 
      }]);
    }
    
    kb.inline_keyboard.push([{ text: '⏭️ Skip (No Channels)', callback_data: 'ch_skip' }]);
    kb.inline_keyboard.push([{ text: '✅ Done Selecting', callback_data: 'ch_done' }]);
    kb.inline_keyboard.push([{ text: '❌ Cancel', callback_data: 'cancel' }]);
    
    const msg = await this.sendMessage(chatId, 
      `✅ File Received!\n\n` +
      `📄 ${session.info.name}\n` +
      `📦 ${this.formatFileSize(session.info.size)}\n\n` +
      `Select channels users must join (click to toggle):\n` +
      `• Selected: ${selected.length} channel(s)`,
      kb
    );
    
    if (msg) {
      session.msgId = msg.message_id;
    }
  }

  // ============================================
  // FORCE JOIN USER CHANNELS
  // ============================================
  async forceJoinUserChannels(chatId, userId, file) {
    const channelIds = file.channel_ids ? file.channel_ids.split(',').map(Number) : [];
    const channelNames = file.channel_names ? file.channel_names.split(',') : [];
    
    if (!channelIds.length) {
      await this.sendMessage(chatId, '❌ No channels required for this file.');
      return;
    }
    
    const kb = { inline_keyboard: [] };
    const channelList = [];
    const userChannels = await this.db.getUserChannels(file.user_id);
    
    for (let i = 0; i < channelIds.length; i++) {
      const cid = channelIds[i];
      const name = channelNames[i] || `Channel ${i+1}`;
      const channel = userChannels.find(c => c.id === cid);
      
      if (channel) {
        const link = await this.getChannelLink(name, {
          channelId: channel.channel_id,
          link: channel.link
        });
        kb.inline_keyboard.push([
          { text: `📢 Join ${name}`, url: link }
        ]);
        channelList.push(`• ${name}`);
      }
    }
    
    kb.inline_keyboard.push([
      { text: '✅ I\'ve Joined All', callback_data: `joined_channels_${file.id}` }
    ]);
    
    await this.sendMessage(chatId,
      `🔐 <b>Channels Required</b>\n\n` +
      `You must join <b>ALL</b> these channels to download this file:\n\n` +
      `${channelList.join('\n')}\n\n` +
      `📄 ${file.name}\n` +
      `📦 ${this.formatFileSize(file.size)}\n\n` +
      `Join all channels and click "I've Joined All".`,
      kb
    );
  }

  // ============================================
  // SETUP HANDLERS
  // ============================================
  setupHandlers() {
    // ---- /START ----
    this.bot.onText(/\/start(?:\s+(.+))?/, async (msg, match) => {
      const chatId = msg.chat.id;
      const userId = msg.from.id;
      const name = msg.from.first_name || 'User';
      const link = match ? match[1] : null;

      await this.db.createUser(userId, msg.from.username || '', name);

      const channelStatus = await this.checkAllRequiredChannels(userId);
      const allJoined = channelStatus.every(c => c.joined);
      
      if (!allJoined) {
        await this.forceJoinRequiredChannels(chatId, userId);
        return;
      }
      
      await this.db.markRequiredJoined(userId);

      if (link) {
        const file = await this.db.getFileByLink(link);
        if (!file) {
          await this.sendMessage(chatId, '❌ Invalid or expired link.');
          return;
        }
        
        if (file.expiry && new Date(file.expiry) < new Date()) {
          await this.db.deleteFile(file.id);
          await this.sendMessage(chatId, '❌ This file has expired.');
          return;
        }
        
        if (file.channel_ids) {
          const channelIds = file.channel_ids.split(',').map(Number);
          let allJoinedChannels = true;
          for (const cid of channelIds) {
            const joined = await this.isUserMemberOfChannel(userId, cid);
            if (!joined) {
              allJoinedChannels = false;
              break;
            }
          }
          if (!allJoinedChannels) {
            await this.forceJoinUserChannels(chatId, userId, file);
            return;
          }
        }
        
        await this.db.incrementDownloads(file.id);
        
        try {
          if (file.file_id) {
            await this.bot.sendDocument(chatId, file.file_id, {
              caption: `📄 ${file.name}\n📦 ${this.formatFileSize(file.size)}`
            });
          } else if (file.from_chat_id && file.original_message_id) {
            await this.bot.forwardMessage(chatId, file.from_chat_id, file.original_message_id);
          }
        } catch (e) {
          await this.sendMessage(chatId, '❌ Failed to send file.');
        }
        return;
      }

      await this.showMainMenu(chatId, userId, name);
    });

    // ---- FILE UPLOADS ----
    this.bot.on('document', async (msg) => {
      await this.handleFileUpload(msg, 'document');
    });

    this.bot.on('photo', async (msg) => {
      await this.handleFileUpload(msg, 'photo');
    });

    this.bot.on('video', async (msg) => {
      await this.handleFileUpload(msg, 'video');
    });

    // ---- MESSAGE HANDLER ----
    this.bot.on('message', async (msg) => {
      const userId = msg.from.id;
      const chatId = msg.chat.id;
      
      if (msg.forward_from_chat) {
        if (this.sessions[userId] && this.sessions[userId].step === 'waiting_private_channel') {
          await this.handlePrivateChannelDetection(msg);
          return;
        }
        return;
      }
      
      if (this.sessions[userId] && this.sessions[userId].step === 'waiting_public_channel') {
        const channelInput = msg.text;
        if (!channelInput) return;
        await this.handlePublicChannelAdd(userId, chatId, channelInput);
        return;
      }
    });

    // ---- CALLBACK QUERY ----
    this.bot.on('callback_query', async (cq) => {
      const userId = cq.from.id;
      const chatId = cq.message.chat.id;
      const msgId = cq.message.message_id;
      const data = cq.data;

      await this.bot.answerCallbackQuery(cq.id);
      await this.handleCallback(data, userId, chatId, msgId);
    });

    // ---- ERROR HANDLING ----
    this.bot.on('polling_error', (error) => {
      console.error('❌ Polling Error:', error.message);
    });

    this.bot.on('error', (error) => {
      console.error('❌ Bot Error:', error.message);
    });
  }

  // ============================================
  // HANDLE CALLBACK
  // ============================================
  async handleCallback(data, userId, chatId, msgId) {
    console.log(`📨 Callback: ${data} from user ${userId}`);
    
    // ---- CHECK REQUIRED JOIN ----
    if (data === 'check_required_join') {
      const channelStatus = await this.checkAllRequiredChannels(userId);
      const allJoined = channelStatus.every(c => c.joined);
      
      if (allJoined) {
        await this.db.markRequiredJoined(userId);
        await this.bot.deleteMessage(chatId, msgId).catch(() => {});
        await this.sendMessage(chatId, '✅ Thank you for joining all required channels!');
        const user = await this.db.getUser(userId);
        await this.showMainMenu(chatId, userId, user ? user.first_name : 'User');
      } else {
        const missing = channelStatus.filter(c => !c.joined);
        const kb = { inline_keyboard: [] };
        
        for (const ch of missing) {
          const link = await this.getChannelLink(ch.channel, {
            channelId: ch.channelId,
            link: ch.link
          });
          kb.inline_keyboard.push([
            { text: `📢 Join ${ch.channel}`, url: link }
          ]);
        }
        
        kb.inline_keyboard.push([
          { text: '🔄 I\'ve Joined All (Retry)', callback_data: 'check_required_join' }
        ]);
        
        const missingList = missing.map(c => c.channel).join(', ');
        
        await this.bot.editMessageText(
          `❌ You haven't joined all channels yet.\n\n` +
          `Missing: ${missingList}\n\n` +
          `Join all channels and click "I've Joined All (Retry)".`,
          { chat_id: chatId, message_id: msgId, reply_markup: kb, parse_mode: 'HTML' }
        );
      }
      return;
    }

    // ---- BACK TO MENU ----
    if (data === 'back_to_menu') {
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      const user = await this.db.getUser(userId);
      await this.showMainMenu(chatId, userId, user ? user.first_name : 'User');
      return;
    }

    // ---- HELP ----
    if (data === 'help') {
      await this.bot.editMessageText(
        `❓ Help\n\n` +
        `📤 Upload: Send or forward files\n` +
        `🔄 Forward: Up to 2GB\n` +
        `📤 Send: Up to 50MB\n\n` +
        `🔗 Manage Channels: Add/remove your own channels\n` +
        `   Users must join ALL your channels to download\n` +
        `⏰ Expiry: Set how long files stay active\n` +
        `📂 My Files: View & delete your files\n\n` +
        `🔐 Required Channels (Bot-wide): ${REQUIRED_CHANNELS.map(c => c.name).join(', ')}\n\n` +
        `🔙 Back to menu`,
        { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back', callback_data: 'back_to_menu' }]] }, parse_mode: 'HTML' }
      );
      return;
    }

    // ---- STATS ----
    if (data === 'stats') {
      const totalFiles = await this.db.getTotalFiles();
      const userFiles = await this.db.getUserFiles(userId);
      await this.bot.editMessageText(
        `📊 Statistics\n\n` +
        `👥 User ID: ${userId}\n` +
        `📁 Your Files: ${userFiles.length}\n` +
        `📁 Total Files: ${totalFiles || 0}\n\n` +
        `🔐 Required Channels: ${REQUIRED_CHANNELS.map(c => c.name).join(', ')}`,
        { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back', callback_data: 'back_to_menu' }]] }, parse_mode: 'HTML' }
      );
      return;
    }

    // ---- MY FILES ----
    if (data === 'my_files') {
      const files = await this.db.getUserFiles(userId);
      if (!files.length) {
        await this.bot.editMessageText(
          '📂 No files uploaded.',
          { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back', callback_data: 'back_to_menu' }]] } }
        );
        return;
      }
      
      let text = '📂 Your Files:\n\n';
      const btns = [];
      for (const f of files.slice(0, 10)) {
        text += `📄 ${f.name}\n`;
        text += `📦 ${this.formatFileSize(f.size)} | ⏰ ${f.expiry ? this.formatExpiry(new Date(f.expiry) - new Date(f.created_at)) : 'Permanent'}\n`;
        text += `📥 ${f.downloads} downloads\n`;
        text += `🔗 https://t.me/${this.BOT_USERNAME}?start=${f.link_code}\n\n`;
        btns.push([{ text: `🗑 Delete: ${f.name.substring(0, 15)}`, callback_data: `delete_${f.id}` }]);
      }
      btns.push([{ text: '🔙 Back', callback_data: 'back_to_menu' }]);
      await this.bot.editMessageText(
        text,
        { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: btns }, parse_mode: 'HTML' }
      );
      return;
    }

    // ---- DELETE FILE ----
    if (data.startsWith('delete_')) {
      const id = data.replace('delete_', '');
      await this.db.deleteFile(id);
      await this.bot.editMessageText(
        '✅ File deleted.',
        { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back', callback_data: 'my_files' }]] } }
      );
      return;
    }

    // ---- MANAGE CHANNELS ----
    if (data === 'managechannels') {
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      await this.showManageChannels(chatId, userId);
      return;
    }

    // ---- ADD PUBLIC CHANNEL ----
    if (data === 'addchannel') {
      this.sessions[userId] = { step: 'waiting_public_channel' };
      await this.bot.editMessageText(
        `🌐 Add Public Channel\n\n` +
        `Send your public channel username:\n\n` +
        `• @my_channel\n` +
        `• https://t.me/my_channel\n` +
        `• my_channel\n\n` +
        `⚠️ Requirements:\n` +
        `• Bot must be an admin in the channel\n` +
        `• Channel must be public\n\n` +
        `❌ Send /cancel to cancel`,
        { chat_id: chatId, message_id: msgId }
      );
      return;
    }

    // ---- ADD PRIVATE CHANNEL ----
    if (data === 'addprivate') {
      this.sessions[userId] = { step: 'waiting_private_channel' };
      await this.bot.editMessageText(
        `🔒 Add Private Channel\n\n` +
        `To add a private channel:\n\n` +
        `1. Make sure @${this.BOT_USERNAME} is an admin in the channel\n` +
        `2. Forward ANY message from the channel to this bot\n` +
        `3. The bot will auto-detect the channel ID and create a permanent invite link\n\n` +
        `This is the ONLY way to add private channels.\n\n` +
        `❌ Send /cancel to cancel`,
        { chat_id: chatId, message_id: msgId }
      );
      return;
    }

    // ---- REMOVE CHANNEL ----
    if (data.startsWith('remove_')) {
      const channelId = parseInt(data.replace('remove_', ''));
      await this.db.removeUserChannel(userId, channelId);
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      await this.showManageChannels(chatId, userId);
      return;
    }

    // ---- UPLOAD ----
    if (data === 'upload') {
      const userChannels = await this.db.getUserChannels(userId);
      if (!userChannels.length) {
        await this.sendMessage(chatId, 
          `⚠️ No channels added!\n\n` +
          `Add at least one channel first using "Manage Channels".`,
          { inline_keyboard: [[{ text: '🔗 Manage Channels', callback_data: 'managechannels' }]] }
        );
        return;
      }
      
      this.sessions[userId] = { step: 'waiting_file' };
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      await this.sendMessage(chatId, 
        `📤 Upload Your File\n\n` +
        `Send or forward the file you want to share.\n\n` +
        `✅ Direct send: Max 50MB\n` +
        `🔄 Forward: Max 2GB\n\n` +
        `📢 Users must join your ${userChannels.length} channel(s) to download.\n` +
        `Channels: ${userChannels.map(c => c.channel_name).join(', ')}\n\n` +
        `❌ Send /cancel to cancel`,
        null
      );
      return;
    }

    // ---- ADMIN ----
    if (data === 'admin') {
      if (!this.isAdmin(userId)) {
        await this.sendMessage(chatId, '❌ Access denied. Admin only.');
        return;
      }
      
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      const totalFiles = await this.db.getTotalFiles();
      
      await this.sendMessage(chatId,
        `🛠 <b>Admin Panel</b>\n\n` +
        `📁 Total Files: ${totalFiles || 0}\n` +
        `👥 Admin ID: ${userId}\n` +
        `🔐 Required Channels: ${REQUIRED_CHANNELS.map(c => c.name).join(', ')}\n\n`,
        {
          inline_keyboard: [
            [{ text: '📁 All Files', callback_data: 'admin_files' }],
            [{ text: '🗑 Cleanup Expired', callback_data: 'admin_cleanup' }],
            [{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]
          ]
        }
      );
      return;
    }

    // ---- ADMIN FILES ----
    if (data === 'admin_files') {
      if (!this.isAdmin(userId)) return;
      const files = await this.db.getUserFiles(userId);
      if (!files.length) {
        await this.bot.editMessageText(
          '📂 No files.',
          { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back', callback_data: 'admin' }]] } }
        );
        return;
      }
      let text = '📁 All Files:\n\n';
      const btns = [];
      for (const f of files) {
        text += `📄 ${f.name}\n`;
        text += `📥 ${f.downloads} downloads\n`;
        text += `⏰ ${f.expiry ? this.formatExpiry(new Date(f.expiry) - new Date(f.created_at)) : 'Permanent'}\n\n`;
        btns.push([{ text: `🗑 ${f.name.substring(0, 15)}`, callback_data: `admin_delete_${f.id}` }]);
      }
      btns.push([{ text: '🔙 Back', callback_data: 'admin' }]);
      await this.bot.editMessageText(
        text,
        { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: btns }, parse_mode: 'HTML' }
      );
      return;
    }

    // ---- ADMIN DELETE ----
    if (data.startsWith('admin_delete_')) {
      if (!this.isAdmin(userId)) return;
      const id = data.replace('admin_delete_', '');
      await this.db.deleteFile(id);
      await this.bot.editMessageText(
        '✅ File deleted.',
        { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back', callback_data: 'admin_files' }]] } }
      );
      return;
    }

    // ---- ADMIN CLEANUP ----
    if (data === 'admin_cleanup') {
      if (!this.isAdmin(userId)) return;
      const count = await this.db.cleanupExpiredFiles();
      await this.bot.editMessageText(
        `✅ Cleanup complete!\n\nRemoved ${count} expired files.`,
        { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back', callback_data: 'admin' }]] } }
      );
      return;
    }

    // ---- CHANNEL SELECTION ----
    if (data === 'ch_all') {
      const session = this.sessions[userId];
      if (!session) return;
      const channels = await this.db.getUserChannels(userId);
      session.selectedChannels = channels.map(c => c.id);
      await this.showChannelSelection(chatId, userId);
      return;
    }

    if (data.startsWith('ch_') && data !== 'ch_done' && data !== 'ch_skip' && data !== 'ch_all') {
      const channelId = parseInt(data.replace('ch_', ''));
      const session = this.sessions[userId];
      if (!session) return;
      
      const index = session.selectedChannels.indexOf(channelId);
      if (index > -1) {
        session.selectedChannels.splice(index, 1);
      } else {
        session.selectedChannels.push(channelId);
      }
      
      await this.showChannelSelection(chatId, userId);
      return;
    }

    // ---- CH_DONE ----
    if (data === 'ch_done') {
      const session = this.sessions[userId];
      if (!session) return;
      
      console.log(`✅ Done selecting. Selected: ${session.selectedChannels.length} channels`);
      
      if (session.msgId) {
        try {
          await this.bot.deleteMessage(chatId, session.msgId);
        } catch (e) {}
        session.msgId = null;
      }
      
      session.step = 'waiting_expiry';
      await this.showExpiryOptions(chatId);
      return;
    }

    // ---- CH_SKIP ----
    if (data === 'ch_skip') {
      const session = this.sessions[userId];
      if (!session) return;
      
      console.log(`⏭️ Skipping channel selection`);
      
      session.selectedChannels = [];
      
      if (session.msgId) {
        try {
          await this.bot.deleteMessage(chatId, session.msgId);
        } catch (e) {}
        session.msgId = null;
      }
      
      session.step = 'waiting_expiry';
      await this.showExpiryOptions(chatId);
      return;
    }

    // ---- EXPIRY ----
    if (data.startsWith('exp_')) {
      const opt = data.replace('exp_', '');
      const expiryMs = this.getExpiry(opt);
      const expiry = expiryMs ? new Date(Date.now() + expiryMs).toISOString() : null;
      const session = this.sessions[userId];
      if (!session || !session.fileId) return;

      const fileData = {
        id: session.fileId,
        userId: userId,
        name: session.info.name,
        size: session.info.size,
        mimeType: session.info.mimeType,
        fileId: session.info.fileId,
        fromChatId: session.info.fromChatId,
        originalMessageId: session.info.originalMessageId,
        isForwarded: session.info.isForwarded,
        expiry: expiry
      };

      const result = await this.db.createFile(fileData);
      
      for (const cid of session.selectedChannels) {
        await this.db.db.run(
          'INSERT INTO file_channels (file_id, channel_id) VALUES (?, ?)',
          [result.id, cid]
        );
      }

      // Store the file ID for pending downloads
      const fileLink = result.linkCode;
      
      delete this.sessions[userId];
      
      const link = `https://t.me/${this.BOT_USERNAME}?start=${fileLink}`;
      
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      await this.sendMessage(chatId,
        `✅ <b>File Uploaded!</b>\n\n` +
        `📄 ${fileData.name}\n` +
        `📦 ${this.formatFileSize(fileData.size)}\n` +
        `⏰ ${expiry ? this.formatExpiry(expiryMs) : 'Permanent'}\n` +
        `📢 Channels: ${session.selectedChannels.length > 0 ? session.selectedChannels.length + ' channel(s)' : 'None'}\n\n` +
        `🔗 Shareable Link:\n` +
        `${link}\n\n` +
        `⚠️ Users must join ALL required channels to download.`,
        {
          inline_keyboard: [
            [{ text: '📤 Upload More', callback_data: 'upload' }],
            [{ text: '📂 My Files', callback_data: 'my_files' }],
            [{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]
          ]
        }
      );
      return;
    }

    // ---- JOINED CHANNELS ----
    if (data.startsWith('joined_channels_')) {
      const fileId = data.replace('joined_channels_', '');
      
      // Get the file from database
      const file = await this.db.getFileById(fileId);
      if (!file) {
        await this.bot.editMessageText(
          '❌ File not found. It may have been deleted or expired.',
          { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]] } }
        );
        return;
      }
      
      // Check if file is expired
      if (file.expiry && new Date(file.expiry) < new Date()) {
        await this.db.deleteFile(file.id);
        await this.bot.editMessageText(
          '❌ This file has expired.',
          { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [[{ text: '🔙 Back to Menu', callback_data: 'back_to_menu' }]] } }
        );
        return;
      }
      
      // Get channel IDs from the file
      const channelIds = file.channel_ids ? file.channel_ids.split(',').map(Number) : [];
      
      // Check if user has joined all channels
      let allJoined = true;
      for (const cid of channelIds) {
        const joined = await this.isUserMemberOfChannel(userId, cid);
        if (!joined) {
          allJoined = false;
          break;
        }
      }
      
      if (!allJoined) {
        // Show join buttons for missing channels
        const kb = { inline_keyboard: [] };
        const userChannels = await this.db.getUserChannels(file.user_id);
        
        for (const cid of channelIds) {
          const channel = userChannels.find(c => c.id === cid);
          if (channel) {
            const link = await this.getChannelLink(channel.channel_name, {
              channelId: channel.channel_id,
              link: channel.link
            });
            kb.inline_keyboard.push([
              { text: `📢 Join ${channel.channel_name}`, url: link }
            ]);
          }
        }
        kb.inline_keyboard.push([
          { text: '✅ I\'ve Joined All', callback_data: `joined_channels_${fileId}` }
        ]);
        
        await this.bot.editMessageText(
          `❌ You haven't joined all channels yet.\n\n` +
          `Please join all channels and click "I've Joined All".`,
          { chat_id: chatId, message_id: msgId, reply_markup: kb, parse_mode: 'HTML' }
        );
        return;
      }
      
      // All channels joined - send the file
      await this.db.incrementDownloads(file.id);
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      
      try {
        if (file.file_id) {
          await this.bot.sendDocument(chatId, file.file_id, {
            caption: `📄 ${file.name}\n📦 ${this.formatFileSize(file.size)}\n📥 ${file.downloads + 1} downloads`
          });
        } else if (file.from_chat_id && file.original_message_id) {
          await this.bot.forwardMessage(chatId, file.from_chat_id, file.original_message_id);
        } else {
          await this.sendMessage(chatId, '❌ Failed to send file. The file data is incomplete.');
        }
      } catch (e) {
        console.error('❌ Send file error:', e);
        await this.sendMessage(chatId, '❌ Failed to send file. Please try again.');
      }
      return;
    }

    // ---- CANCEL ----
    if (data === 'cancel') {
      delete this.sessions[userId];
      await this.bot.deleteMessage(chatId, msgId).catch(() => {});
      await this.sendMessage(chatId, '❌ Cancelled.');
      const user = await this.db.getUser(userId);
      await this.showMainMenu(chatId, userId, user ? user.first_name : 'User');
      return;
    }
  }
}

// ============================================
// START THE BOT
// ============================================
const bot = new FileSharingBot();

process.on('SIGINT', async () => {
  console.log('\n🛑 Shutting down...');
  await bot.db.close();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  console.log('\n🛑 Shutting down...');
  await bot.db.close();
  process.exit(0);
});

console.log('\n🚀 Bot started successfully!');
console.log('🔐 Bot-wide Required Channels:');
console.log('  📢 @NCK_Dev (Public)');
console.log('  🔒 Private Channel (ID: -1004266231051)');
console.log('\n📤 Users can add their own channels:');
console.log('  • Public: Send @username or link');
console.log('  • Private: Forward a message (bot creates permanent invite link)');
console.log('\n👑 Admins: ' + (ADMIN_IDS.length ? ADMIN_IDS.join(', ') : 'None'));