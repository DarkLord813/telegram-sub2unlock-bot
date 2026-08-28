# 📤 Telegram Sub 2 Unlock Bot

A powerful Telegram bot that allows users to share files with channel-based access control. Users must join specified channels before downloading files.

[![Deploy on Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)
[![Deploy on Choreo](https://img.shields.io/badge/Deploy%20on-Choreo-1a73e8?style=flat&logo=googlecloud)](https://console.choreo.dev/)

## ✨ Features

- 📤 **File Sharing**: Upload files up to 2GB (via forwarding) or 50MB (direct)
- 🔗 **Channel-Based Access**: Require users to join specific channels to download
- ⏰ **Expiry Dates**: Set file expiry from 5 minutes to permanent
- 🔒 **Private Channel Support**: Auto-detect private channels from forwarded messages
- 🔑 **Permanent Invite Links**: Create never-expiring invite links for private channels
- 📊 **Statistics**: Track downloads and file activity
- 👑 **Admin Panel**: Manage all files and cleanup expired content
- 🗄️ **SQLite Database**: Persistent storage for files and user data
- 🎯 **User-Friendly Interface**: Interactive buttons and clear navigation

## 🚀 Quick Deploy

### Deploy on Render (Recommended)
[![Deploy on Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. Click the button above
2. Connect your GitHub repository
3. Add environment variables:
   - `BOT_TOKEN`: Your bot token from BotFather
   - `ADMIN_IDS`: Your Telegram user ID (comma-separated for multiple)
4. Click "Deploy"

### Deploy on Choreo
1. Fork this repository
2. Go to [Choreo Console](https://console.choreo.dev/)
3. Create a new project and component (Service)
4. Connect your forked repository
5. Add environment variables (same as above)
6. Deploy

## 📋 Prerequisites

### Before You Start
- [Telegram Bot Token](https://t.me/botfather) from BotFather
- Your [Telegram User ID](https://t.me/userinfobot) (for admin access)
- GitHub account (for hosting)
- Bot must be admin in all required channels

### Required Channels
The bot includes two default required channels:
- `@NCK_Dev` (Public)
- Private channel (ID: `-1004266231051`)

## 🛠️ Local Development

### 1️⃣ Clone the Repository
```bash
git clone https://github.com/DarkLord813/sub2unlock-bot.git
cd sub2unlock-bot
