"""
Telegram Bot for Paper Trading

This bot provides a Telegram interface to control trading strategies
through the Core module. Allows strategy selection, parameter configuration,
and monitoring of live paper trading.
"""

import os
import sys
import logging
import asyncio
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import json

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

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import TradingCore
from alerts.agents.alert_agent import run_agent_analysis
from lumibot.credentials import ALPACA_TEST_CONFIG
from alerts.alert_system import AlertSystem

# Handle relative import when running as script
if __name__ == "__main__":
    from strategy_integration import StrategyRunner
else:
    from .strategy_integration import StrategyRunner

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
STRATEGY_SELECT, PARAMETER_CONFIG, TIME_CONFIG, BUDGET_CONFIG, CONFIRM_START = range(5)

class TradingBot:
    """
    Telegram bot for managing paper trading strategies
    """
    
    def __init__(self, token: str):
        """
        Initialize the trading bot
        
        Args:
            token: Telegram bot token
        """
        self.token = token
        self.core = TradingCore(broker_config=ALPACA_TEST_CONFIG)
        self.user_configs: Dict[int, Dict] = {}  # user_id -> configuration
        self.strategy_runner: Optional[StrategyRunner] = None
        self.alert_system: Optional[AlertSystem] = None
        self.alerts_job = None
        self._agent = None

        # Initialize alert system if credentials available
        try:
            self.alert_system = AlertSystem()
        except Exception as exc:
            logger.warning("AlertSystem disabled: %s", exc)
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        await update.message.reply_text(
            f"🤖 Welcome to Lumibot Trading Bot, {user.mention_html()}!\n\n"
            f"I can help you run paper trading strategies.\n\n"
            f"Available commands:\n"
            f"/trade - Start a new trading strategy\n"
            f"/status - Check current strategy status\n"
            f"/stop - Stop current strategy\n"
            f"/strategies - List available strategies\n"
            f"/help - Show help message",
            parse_mode='HTML'
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
📚 *Lumibot Trading Bot Help*

*Available Commands:*
• /start - Initialize the bot
• /trade - Start a new paper trading strategy
• /strategies - List all available strategies
• /status - Check your current strategy status
• /stop - Stop your active strategy
• /portfolio - View portfolio information
• /help - Show this help message

*How to start trading:*
1. Use /trade to begin
2. Select a strategy from the list
3. Configure parameters (optional)
4. Set trading duration
5. Set budget amount
6. Confirm and start trading!

*Note:* This bot runs in paper trading mode only.
No real money is used.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def alerts_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enable periodic alert checks."""
        if not self.alert_system:
            await update.message.reply_text("❌ Alert system not configured.")
            return
        if self.alerts_job:
            await update.message.reply_text("✅ Alerts already running.")
            return
        self.alerts_job = context.job_queue.run_repeating(
            self._alerts_tick, interval=60, first=1
        )
        await update.message.reply_text("✅ Alert checks enabled (every 1 minute).")

    async def alerts_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Disable periodic alert checks."""
        if self.alerts_job:
            self.alerts_job.schedule_removal()
            self.alerts_job = None
            await update.message.reply_text("🛑 Alert checks stopped.")
        else:
            await update.message.reply_text("ℹ️ Alert checks were not running.")

    async def alerts_run(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Run alerts immediately."""
        if not self.alert_system:
            await update.message.reply_text("❌ Alert system not configured.")
            return
        summary = self.alert_system.run_and_notify("telegram")
        await update.message.reply_text(
            f"✅ Alert run completed. Analyzed {summary.total_analyzed} symbols."
        )

    async def _alerts_tick(self, context: ContextTypes.DEFAULT_TYPE):
        """Background alert evaluation."""
        if not self.alert_system:
            return
        try:
            self.alert_system.run_and_notify("telegram")
        except Exception as exc:
            logger.error("Alert tick failed: %s", exc)

    async def alert_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List persisted alert rules."""
        if not self.alert_system:
            await update.message.reply_text("❌ Alert system not configured.")
            return
        rules = self.alert_system.list_rules()
        if not rules:
            await update.message.reply_text("No alert rules configured.")
            return
        lines = ["📌 *Alert Rules:*"]
        for r in rules:
            rid = r.get("id", "?")
            sym = r.get("symbol", "?")
            rtype = r.get("type", "?")
            active = "on" if r.get("active", True) else "off"
            lines.append(f"- `{rid}` {sym} {rtype} ({active})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def alert_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Add alert rule.
        """
        if not self.alert_system:
            await update.message.reply_text("❌ Alert system not configured.")
            return
        args = context.args
        if len(args) < 3:
            await update.message.reply_text("Usage: /alert_add SYMBOL TYPE VALUE")
            return
        symbol, rtype, value = args[0].upper(), args[1], args[2]
        rule_id = f"{symbol}-{int(datetime.now().timestamp())}"
        rule = {"id": rule_id, "symbol": symbol, "type": rtype, "active": True}
        if rtype == "target_price":
            rule["target"] = float(value)
        elif rtype in ("percent_drop", "percent_rise"):
            rule["threshold"] = float(value)
            current = self.alert_system.data_service.get_latest_price(symbol)
            if current:
                rule["reference_price"] = float(current)
        else:
            await update.message.reply_text("Unknown type. Use target_price|percent_drop|percent_rise")
            return
        self.alert_system.add_rule(rule)
        await update.message.reply_text(f"✅ Alert rule added: `{rule_id}`", parse_mode="Markdown")

    async def alert_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove alert rule by id."""
        if not self.alert_system:
            await update.message.reply_text("❌ Alert system not configured.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /alert_remove RULE_ID")
            return
        rid = context.args[0]
        ok = self.alert_system.remove_rule(rid)
        if ok:
            await update.message.reply_text(f"✅ Removed `{rid}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("Rule not found.")
    
    async def list_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /strategies command - List available strategies"""
        strategies = self.core.list_strategies()
        
        if not strategies:
            await update.message.reply_text("❌ No strategies available.")
            return
        
        message = "📋 *Available Strategies:*\n\n"
        for name, info in strategies.items():
            description = info.get('description', 'No description')[:100]
            params = ', '.join(info.get('parameters', {}).keys())[:50]
            
            message += f"*{name}*\n"
            message += f"├─ Class: `{info.get('class', 'Unknown')}`\n"
            if params:
                message += f"├─ Parameters: {params}\n"
            message += f"└─ {description}\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def start_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trade command - Start trading conversation"""
        user_id = update.effective_user.id
        
        # Initialize strategy runner if not done
        if not self.strategy_runner:
            self.strategy_runner = StrategyRunner(self.core, context)
        
        # Check if user already has active strategy
        if self.strategy_runner.is_user_trading(user_id):
            await update.message.reply_text(
                "⚠️ You already have an active strategy running.\n"
                "Use /stop to stop it first."
            )
            return ConversationHandler.END
        
        # Get available strategies
        strategies = self.core.list_strategies()
        if not strategies:
            await update.message.reply_text("❌ No strategies available.")
            return ConversationHandler.END
        
        # Create inline keyboard with strategies
        keyboard = []
        for strategy_name in strategies.keys():
            keyboard.append([InlineKeyboardButton(
                strategy_name, 
                callback_data=f"strategy_{strategy_name}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "📊 *Select a Strategy:*\n\n"
            "Choose the strategy you want to run:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Initialize user config
        self.user_configs[user_id] = {}
        
        return STRATEGY_SELECT
    
    async def strategy_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle strategy selection"""
        query = update.callback_query
        user_id = query.from_user.id
        
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Trading setup cancelled.")
            return ConversationHandler.END
        
        strategy_name = query.data.replace("strategy_", "")
        self.user_configs[user_id]['strategy'] = strategy_name
        
        # Get strategy info
        strategies = self.core.list_strategies()
        strategy_info = strategies.get(strategy_name, {})
        default_params = strategy_info.get('parameters', {})
        
        # Store default parameters
        self.user_configs[user_id]['parameters'] = default_params.copy()
        
        # Ask if user wants to customize parameters
        keyboard = [
            [InlineKeyboardButton("✅ Use Default", callback_data="params_default")],
            [InlineKeyboardButton("⚙️ Customize", callback_data="params_custom")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        params_text = json.dumps(default_params, indent=2) if default_params else "None"
        
        await query.edit_message_text(
            f"✅ Strategy selected: *{strategy_name}*\n\n"
            f"Default parameters:\n```\n{params_text}\n```\n\n"
            f"Would you like to customize parameters?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return PARAMETER_CONFIG
    
    async def parameter_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle parameter configuration"""
        query = update.callback_query
        user_id = query.from_user.id
        
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Trading setup cancelled.")
            return ConversationHandler.END
        
        if query.data == "params_custom":
            # For simplicity, we'll skip custom parameter input in this version
            await query.edit_message_text(
                "⚙️ Custom parameters coming soon!\n"
                "Using default parameters for now."
            )
        
        # Move to time configuration
        keyboard = [
            [InlineKeyboardButton("1 Hour", callback_data="time_1h")],
            [InlineKeyboardButton("6 Hours", callback_data="time_6h")],
            [InlineKeyboardButton("1 Day", callback_data="time_1d")],
            [InlineKeyboardButton("1 Week", callback_data="time_1w")],
            [InlineKeyboardButton("Continuous", callback_data="time_continuous")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⏱️ *Select Trading Duration:*\n\n"
            "How long should the strategy run?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return TIME_CONFIG
    
    async def time_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle time configuration"""
        query = update.callback_query
        user_id = query.from_user.id
        
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Trading setup cancelled.")
            return ConversationHandler.END
        
        # Parse time selection
        time_mapping = {
            "time_1h": ("1 hour", timedelta(hours=1)),
            "time_6h": ("6 hours", timedelta(hours=6)),
            "time_1d": ("1 day", timedelta(days=1)),
            "time_1w": ("1 week", timedelta(weeks=1)),
            "time_continuous": ("Continuous", None)
        }
        
        time_label, duration = time_mapping.get(query.data, ("Unknown", None))
        self.user_configs[user_id]['duration'] = duration
        self.user_configs[user_id]['duration_label'] = time_label
        
        # Move to budget configuration
        keyboard = [
            [InlineKeyboardButton("$1,000", callback_data="budget_1000")],
            [InlineKeyboardButton("$5,000", callback_data="budget_5000")],
            [InlineKeyboardButton("$10,000", callback_data="budget_10000")],
            [InlineKeyboardButton("$25,000", callback_data="budget_25000")],
            [InlineKeyboardButton("$100,000", callback_data="budget_100000")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💰 *Select Trading Budget:*\n\n"
            "Choose the paper trading budget:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return BUDGET_CONFIG
    
    async def budget_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle budget configuration"""
        query = update.callback_query
        user_id = query.from_user.id
        
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Trading setup cancelled.")
            return ConversationHandler.END
        
        # Parse budget selection
        budget = int(query.data.replace("budget_", ""))
        self.user_configs[user_id]['budget'] = budget
        
        # Show confirmation
        config = self.user_configs[user_id]
        
        keyboard = [
            [InlineKeyboardButton("✅ Start Trading", callback_data="confirm_start")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📋 *Trading Configuration Summary:*\n\n"
            f"Strategy: *{config['strategy']}*\n"
            f"Duration: *{config['duration_label']}*\n"
            f"Budget: *${config['budget']:,}*\n\n"
            f"Ready to start paper trading?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return CONFIRM_START
    
    async def confirm_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle trading confirmation and start"""
        query = update.callback_query
        user_id = query.from_user.id
        
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Trading setup cancelled.")
            return ConversationHandler.END
        
        config = self.user_configs[user_id]
        
        await query.edit_message_text(
            "🚀 Starting paper trading strategy...\n"
            "This may take a moment..."
        )
        
        try:
            # Start the strategy using the strategy runner
            strategy_info = await self.strategy_runner.start_strategy(
                user_id=user_id,
                strategy_name=config['strategy'],
                parameters=config['parameters'],
                budget=config['budget'],
                duration=config['duration']
            )
            
            await query.edit_message_text(
                f"✅ *Trading Started Successfully!*\n\n"
                f"Strategy: {config['strategy']}\n"
                f"Budget: ${config['budget']:,}\n"
                f"Duration: {config['duration_label']}\n\n"
                f"Use /status to check progress\n"
                f"Use /stop to stop trading",
                parse_mode='Markdown'
            )
            
            # The strategy runner will handle automatic stopping based on duration
            
        except Exception as e:
            logger.error(f"Failed to start strategy: {e}")
            await query.edit_message_text(
                f"❌ Failed to start strategy:\n{str(e)}"
            )
        
        return ConversationHandler.END
    
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.effective_user.id
        
        if not self.strategy_runner or not self.strategy_runner.is_user_trading(user_id):
            await update.message.reply_text(
                "📊 No active strategy running.\n"
                "Use /trade to start a new strategy."
            )
            return
        
        status_info = self.strategy_runner.get_strategy_status(user_id)
        if not status_info:
            await update.message.reply_text(
                "❌ Could not retrieve strategy status."
            )
            return
        
        runtime = status_info['runtime']
        hours, remainder = divmod(runtime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        duration_text = "Continuous"
        if status_info['duration']:
            duration_text = str(status_info['duration'])
        
        status_text = (
            f"📊 *Strategy Status*\n\n"
            f"Strategy: *{status_info['name']}*\n"
            f"Status: 🟢 Running\n"
            f"Runtime: {runtime.days}d {hours}h {minutes}m\n"
            f"Budget: ${status_info['budget']:,}\n"
            f"Duration: {duration_text}\n"
        )
        
        await update.message.reply_text(status_text, parse_mode='Markdown')
    
    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command"""
        user_id = update.effective_user.id
        
        if not self.strategy_runner or not self.strategy_runner.is_user_trading(user_id):
            await update.message.reply_text(
                "❌ No active strategy to stop.\n"
                "Use /trade to start a new strategy."
            )
            return
        
        # Get strategy info before stopping
        status_info = self.strategy_runner.get_strategy_status(user_id)
        strategy_name = status_info['name'] if status_info else "Unknown"
        
        # Stop the strategy
        success = self.strategy_runner.stop_strategy(user_id)
        
        if success:
            await update.message.reply_text(
                f"🛑 *Strategy Stopped*\n\n"
                f"Strategy: {strategy_name}\n"
                f"Final status will be available soon.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Failed to stop strategy. Please try again."
            )
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel conversation"""
        await update.message.reply_text("❌ Operation cancelled.")
        return ConversationHandler.END

    async def handle_free_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route free-text messages to the Agno agent."""
        if not self.alert_system:
            await update.message.reply_text("❌ Alert system not configured.")
            return
        if self._agent is None:
            self._agent = self.alert_system.get_agent()
            if self._agent is None:
                await update.message.reply_text("❌ Agno agent not configured.")
                return
        user_text = update.message.text.strip()
        if not user_text:
            return
        response = run_agent_analysis(self._agent, user_text)
        await update.message.reply_text(response)

def main():
    """Main function to run the bot"""
    # Get bot token from environment
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in environment variables")
        print("Please set your bot token:")
        print("export TELEGRAM_BOT_TOKEN='your-bot-token'")
        return
    
    # Create bot instance
    bot = TradingBot(TOKEN)
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Create conversation handler for trading flow
    trade_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", bot.start_trade)],
        states={
            STRATEGY_SELECT: [CallbackQueryHandler(bot.strategy_selected)],
            PARAMETER_CONFIG: [CallbackQueryHandler(bot.parameter_config)],
            TIME_CONFIG: [CallbackQueryHandler(bot.time_config)],
            BUDGET_CONFIG: [CallbackQueryHandler(bot.budget_config)],
            CONFIRM_START: [CallbackQueryHandler(bot.confirm_start)],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("strategies", bot.list_strategies))
    application.add_handler(CommandHandler("status", bot.status))
    application.add_handler(CommandHandler("stop", bot.stop))
    application.add_handler(CommandHandler("alerts_on", bot.alerts_on))
    application.add_handler(CommandHandler("alerts_off", bot.alerts_off))
    application.add_handler(CommandHandler("alerts_run", bot.alerts_run))
    application.add_handler(CommandHandler("alert_rules", bot.alert_rules))
    application.add_handler(CommandHandler("alert_add", bot.alert_add))
    application.add_handler(CommandHandler("alert_remove", bot.alert_remove))
    application.add_handler(trade_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_free_text))
    
    # Start bot
    print("🤖 Telegram Trading Bot starting...")
    print("Press Ctrl+C to stop")
    
    application.run_polling()

if __name__ == "__main__":
    main()
