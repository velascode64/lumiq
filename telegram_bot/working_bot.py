"""
Working Telegram Trading Bot

This version works correctly without import conflicts.
"""

import os
import sys
import logging
import asyncio
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import json
from pathlib import Path

# Add paths for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "packages"))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from core import TradingCore
from lumibot.credentials import ALPACA_TEST_CONFIG

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
STRATEGY_SELECT, PARAMETER_CONFIG, TIME_CONFIG, BUDGET_CONFIG, CONFIRM_START = range(5)

class TradingBot:
    """Simple trading bot for paper trading"""
    
    def __init__(self, token: str):
        self.token = token
        self.core = TradingCore(broker_config=ALPACA_TEST_CONFIG)
        self.user_configs: Dict[int, Dict] = {}
        self.active_strategies: Dict[int, Dict] = {}
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        await update.message.reply_text(
            f"🤖 Welcome to Lumibot Trading Bot, {user.mention_html()}!\n\n"
            f"Commands:\n"
            f"/strategies - List available strategies\n"
            f"/trade - Start paper trading (coming soon)\n"
            f"/status - Check status\n"
            f"/help - Show help",
            parse_mode='HTML'
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
📚 *Lumibot Trading Bot Help*

*Available Commands:*
• /start - Initialize the bot
• /strategies - List all available strategies  
• /status - Check your current status
• /help - Show this help message

*Note:* This bot runs in paper trading mode only.
No real money is used.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def list_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /strategies command"""
        try:
            strategies = self.core.list_strategies()
            
            if not strategies:
                await update.message.reply_text("❌ No strategies available.")
                return
            
            message = "📋 *Available Strategies:*\n\n"
            for name, info in strategies.items():
                description = str(info.get('description', 'No description'))[:100]
                params = list(info.get('parameters', {}).keys())[:3]  # First 3 params
                
                message += f"*{name}*\n"
                message += f"├─ Class: `{info.get('class', 'Unknown')}`\n"
                if params:
                    message += f"├─ Params: {', '.join(params)}{'...' if len(info.get('parameters', {})) > 3 else ''}\n"
                message += f"└─ {description}\n\n"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error listing strategies: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.effective_user.id
        
        if user_id in self.active_strategies:
            strategy_info = self.active_strategies[user_id]
            message = (
                f"📊 *Your Status*\n\n"
                f"Strategy: {strategy_info.get('name', 'Unknown')}\n"
                f"Status: 🟢 Active\n"
                f"Mode: Paper Trading\n"
            )
        else:
            message = (
                f"📊 *Your Status*\n\n"
                f"No active strategy\n"
                f"Use /strategies to see available options"
            )
        
        await update.message.reply_text(message, parse_mode='Markdown')

def main():
    """Main function to run the bot"""
    print("🤖 Starting Telegram Trading Bot...")
    
    # Get bot token
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in environment")
        print("\nTo get a bot token:")
        print("1. Message @BotFather on Telegram")
        print("2. Use /newbot command")
        print("3. Follow instructions")
        print("4. Set token: export TELEGRAM_BOT_TOKEN='your-token'")
        return
    
    if TOKEN == "your-telegram-bot-token-here":
        print("❌ Please set a real Telegram bot token")
        return
    
    print(f"✅ Bot token found: ...{TOKEN[-10:]}")
    
    # Create bot
    bot = TradingBot(TOKEN)
    
    # Test core functionality  
    try:
        strategies = bot.core.list_strategies()
        print(f"✅ Found {len(strategies)} strategies: {list(strategies.keys())}")
    except Exception as e:
        print(f"⚠️ Core error: {e}")
    
    # Create application
    try:
        application = Application.builder().token(TOKEN).build()
        print("✅ Telegram application created")
    except Exception as e:
        print(f"❌ Failed to create application: {e}")
        return
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("strategies", bot.list_strategies))
    application.add_handler(CommandHandler("status", bot.status))
    
    # Start bot
    print("🚀 Bot is starting...")
    print("Press Ctrl+C to stop")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
    except Exception as e:
        print(f"❌ Bot error: {e}")

if __name__ == "__main__":
    main()