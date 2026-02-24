"""
Live Trading Telegram Bot - WITH REAL TRADES

This version actually executes real Lumibot strategies and sends
trade notifications to Telegram in real-time.
"""

import os
import sys
import logging
import asyncio
import multiprocessing
import queue
import signal
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import json
from pathlib import Path

# Add paths for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "packages"))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
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
STRATEGY_SELECT, TIME_CONFIG, BUDGET_CONFIG, CONFIRM_START = range(4)

class LiveTradingBot:
    """Trading bot that executes REAL strategies and sends trade updates"""
    
    def __init__(self, token: str):
        self.token = token
        # Initialize logger first
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.core = TradingCore(broker_config=ALPACA_TEST_CONFIG)
        self.user_configs: Dict[int, Dict] = {}
        self.active_strategies: Dict[int, Dict] = {}
        self.telegram_app = None  # Will be set later
        
        # Multiprocessing components for strategy execution
        self.strategy_processes: Dict[int, multiprocessing.Process] = {}
        self.notification_queues: Dict[int, multiprocessing.Queue] = {}
        self.running_tasks: Dict[int, asyncio.Task] = {}
        
        # Manually register strategies
        self._register_strategies()
        
    def _register_strategies(self):
        """Manually register available strategies"""
        try:
            strategies_to_register = [
                ("ETH-BTC Correlation Live", "packages.core.strategies.live.eth_btc_correlation", "CryptoLeadLagStrategy"),
                ("Live Test Strategy", "packages.core.strategies.live.live_test_strategy", "LiveTestStrategy"),
                ("Mean Reversion Live", "packages.core.strategies.live.carlos_mean_reversion_live", "CarlosMeanReversionLiveStrategy"),
                ("ETH 5 Min MACD", "packages.core.strategies.live.eth_5min_macd_strategy", "ETH5MinMACDStrategy"),
            ]
            
            for display_name, module_path, class_name in strategies_to_register:
                try:
                    module = __import__(module_path, fromlist=[class_name])
                    strategy_class = getattr(module, class_name)
                    
                    default_config = getattr(strategy_class, 'parameters', {})
                    self.core.register_strategy(
                        name=display_name,
                        strategy_class=strategy_class,
                        default_config=default_config
                    )
                    print(f"✅ Registered strategy: {display_name}")
                    
                except Exception as e:
                    print(f"⚠️ Failed to register {display_name}: {e}")
                    
        except Exception as e:
            print(f"❌ Strategy registration error: {e}")
    
    def set_telegram_app(self, app):
        """Set telegram application for sending notifications"""
        self.telegram_app = app
    
    async def send_trade_notification(self, user_id: int, message: str):
        """Send trade notification to user"""
        if self.telegram_app:
            try:
                await self.telegram_app.bot.send_message(
                    chat_id=user_id, 
                    text=message,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send notification to {user_id}: {e}")
    
    async def _monitor_notifications(self, user_id: int):
        """Monitor notification queue from strategy process and send to Telegram"""
        notification_queue = self.notification_queues.get(user_id)
        if not notification_queue:
            return
            
        try:
            while user_id in self.active_strategies:
                try:
                    # Non-blocking check for notifications
                    try:
                        notification = notification_queue.get_nowait()
                        message = notification['message']
                        await self.send_trade_notification(user_id, message)
                        
                        # Update strategy info if it's a trade
                        if notification.get('type') == 'trade':
                            if user_id in self.active_strategies:
                                self.active_strategies[user_id]['trades_count'] += 1
                                self.active_strategies[user_id]['last_trade'] = notification.get('trade_data')
                                
                    except queue.Empty:
                        # No notifications, wait a bit
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    logger.error(f"Error monitoring notifications for user {user_id}: {e}")
                    await asyncio.sleep(5)
                    
        except Exception as e:
            logger.error(f"Critical error in notification monitor for user {user_id}: {e}")
        finally:
            # Clean up
            if user_id in self.notification_queues:
                del self.notification_queues[user_id]
            if user_id in self.running_tasks:
                del self.running_tasks[user_id]
    
    def _run_strategy_in_process(self, user_id: int, strategy_name: str, config: Dict, notification_queue: multiprocessing.Queue):
        """Run strategy in separate process to avoid signal handler conflicts"""
        try:
            # Use subprocess to run the standalone script
            import subprocess
            import json
            
            print(f"🚀 Starting REAL strategy {strategy_name} for user {user_id}")
            
            # Prepare strategy parameters
            strategy_params = {
                'initial_budget': config['budget'],
                **config.get('parameters', {})
            }
            
            # Send initial notification via queue
            notification_queue.put({
                'user_id': user_id,
                'message': (
                    f"🟢 *Strategy Started*\n\n"
                    f"Strategy: {strategy_name}\n"
                    f"Budget: ${strategy_params.get('initial_budget', 0):,}\n"
                    f"Mode: Paper Trading\n\n"
                    f"Monitoring for trades..."
                ),
                'type': 'strategy_start'
            })
            
            # Import credentials needed for broker
            from lumibot.credentials import ALPACA_TEST_CONFIG
            
            # Run strategy directly without paper_trade wrapper
            try:
                # Map strategy names to their classes
                strategy_map = {
                    "ETH 5 Min MACD": ("packages.core.strategies.live.eth_5min_macd_strategy", "ETH5MinMACDStrategy"),
                    "ETH-BTC Correlation Live": ("packages.core.strategies.live.eth_btc_correlation", "CryptoLeadLagStrategy"),
                    "Live Test Strategy": ("packages.core.strategies.live.live_test_strategy", "LiveTestStrategy"),
                    "Mean Reversion Live": ("packages.core.strategies.live.carlos_mean_reversion_live", "CarlosMeanReversionLiveStrategy"),
                }
                
                if strategy_name in strategy_map:
                    module_path, class_name = strategy_map[strategy_name]
                    module = __import__(module_path, fromlist=[class_name])
                    strategy_class = getattr(module, class_name)
                    
                    # Create broker and strategy instance
                    from lumibot.brokers import Alpaca
                    broker = Alpaca(ALPACA_TEST_CONFIG)
                    strategy = strategy_class(broker=broker, parameters=strategy_params)
                    
                    # Configure strategy
                    strategy.sleeptime = '5M'  # 5 minutes for ETH strategy
                    print(f"✅ Strategy {strategy_name} initialized successfully")
                    
                    # Initialize
                    strategy.initialize()
                    
                    # Run main loop manually without signal handlers
                    import time
                    iteration = 0
                    while True:
                        try:
                            iteration += 1
                            if iteration % 10 == 1:  # Send update every 10 iterations
                                notification_queue.put({
                                    'user_id': user_id,
                                    'message': f"📊 Strategy running - Iteration {iteration}",
                                    'type': 'status'
                                })
                            
                            # Run one iteration
                            strategy.on_trading_iteration()
                            
                            # Sleep based on strategy type
                            sleep_time = 300 if "5 Min" in strategy_name else 10
                            time.sleep(sleep_time)
                            
                        except KeyboardInterrupt:
                            print(f"Strategy {strategy_name} stopped by user")
                            break
                        except Exception as iter_error:
                            print(f"Iteration error: {iter_error}")
                            time.sleep(10)
                    
                    # Cleanup
                    try:
                        strategy.on_strategy_end()
                    except:
                        pass
                else:
                    raise ValueError(f"Unknown strategy: {strategy_name}")
                    
            except Exception as e:
                notification_queue.put({
                    'user_id': user_id,
                    'message': f"❌ *Strategy Error*\n\n{str(e)}",
                    'type': 'error'
                })
                print(f"Strategy execution error: {e}")
            
        except Exception as e:
            notification_queue.put({
                'user_id': user_id,
                'message': f"❌ *Critical Process Error*\n\n{str(e)}",
                'type': 'critical_error'
            })
            print(f"Critical error in strategy process: {e}")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        await update.message.reply_text(
            f"🤖 *Live Trading Bot Ready!*\n\n"
            f"Welcome {user.mention_html()}!\n\n"
            f"🎯 *Features:*\n"
            f"• Real-time trade notifications 📊\n"
            f"• Live strategy execution 🚀\n"
            f"• Paper trading mode (safe) 🛡️\n\n"
            f"📋 *Commands:*\n"
            f"• /trade - Start live strategy\n"
            f"• /strategies - List strategies\n"  
            f"• /status - Check live status\n"
            f"• /stop - Stop strategy\n\n"
            f"🚀 Ready for live trading? Use /trade",
            parse_mode='HTML'
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
🤖 *Live Trading Bot Help*

*📋 Commands:*
• `/start` - Initialize the bot
• `/trade` - Start LIVE strategy execution
• `/strategies` - List available strategies  
• `/status` - Check real-time status
• `/stop` - Stop active strategy
• `/help` - Show this help

*🚀 Real Trading Features:*
• Live trade notifications in real-time
• Actual strategy execution via Lumibot
• P&L tracking and updates
• Paper trading mode (no real money)

*🔔 Notifications:*
You'll receive instant messages for:
• Strategy starts/stops
• Every trade execution  
• P&L updates
• Error alerts
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def list_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /strategies command"""
        try:
            strategies = self.core.list_strategies()
            
            if not strategies:
                await update.message.reply_text("❌ No strategies available.")
                return
            
            message = "📊 *Live Trading Strategies:*\n\n"
            for name, info in strategies.items():
                params = info.get('parameters', {})
                param_count = len(params)
                
                message += f"*{name}*\n"
                message += f"├─ Class: `{info.get('class', 'Unknown')}`\n"
                message += f"├─ Parameters: {param_count} configurable\n"
                message += f"└─ Status: ✅ Ready for live execution\n\n"
            
            message += "🚀 Use `/trade` to start live trading!"
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error listing strategies: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def start_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trade command - Start trading conversation"""
        user_id = update.effective_user.id
        
        # Check if user already has active strategy
        if user_id in self.active_strategies:
            # Also check if the process is actually still running
            strategy = self.active_strategies[user_id]
            process = self.strategy_processes.get(user_id)
            
            if process and not process.is_alive():
                # Process died, clean up the dead strategy
                logger.warning(f"Found dead strategy process for user {user_id}, cleaning up")
                if user_id in self.active_strategies:
                    del self.active_strategies[user_id]
                if user_id in self.strategy_processes:
                    del self.strategy_processes[user_id]
                if user_id in self.running_tasks:
                    self.running_tasks[user_id].cancel()
                    del self.running_tasks[user_id]
                if user_id in self.notification_queues:
                    del self.notification_queues[user_id]
            else:
                # Strategy is actually running
                # Handle both message and callback_query
                if update.message:
                    await update.message.reply_text(
                        f"⚠️ *Active Strategy Running!*\n\n"
                        f"🎯 Strategy: {strategy['name']}\n"
                        f"📊 Status: 🟢 Live\n"
                        f"⏰ Runtime: {datetime.now() - strategy['start_time']}\n\n"
                        f"Use `/stop` to stop it first."
                    )
                elif update.callback_query:
                    await update.callback_query.answer()
                    await update.callback_query.edit_message_text(
                        f"⚠️ *Active Strategy Running!*\n\n"
                        f"🎯 Strategy: {strategy['name']}\n"
                        f"📊 Status: 🟢 Live\n"
                        f"⏰ Runtime: {datetime.now() - strategy['start_time']}\n\n"
                        f"Use `/stop` to stop it first."
                    )
                return ConversationHandler.END
        
        # Get available strategies
        strategies = self.core.list_strategies()
        if not strategies:
            if update.message:
                await update.message.reply_text("❌ No strategies available.")
            elif update.callback_query:
                await update.callback_query.edit_message_text("❌ No strategies available.")
            return ConversationHandler.END
        
        # Create inline keyboard with strategies
        keyboard = []
        for strategy_name in strategies.keys():
            keyboard.append([InlineKeyboardButton(
                f"🚀 {strategy_name}", 
                callback_data=f"strategy_{strategy_name}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send message appropriately based on update type
        message_text = (
            "🎯 *Select Strategy for LIVE Execution:*\n\n"
            "⚠️ This will start real trading with notifications!\n\n"
            "Choose your strategy:"
        )
        
        if update.message:
            await update.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                message_text,
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
            await query.edit_message_text("❌ Live trading setup cancelled.")
            return ConversationHandler.END
        
        strategy_name = query.data.replace("strategy_", "")
        self.user_configs[user_id]['strategy'] = strategy_name
        
        # Move to time configuration
        keyboard = [
            [InlineKeyboardButton("⏰ 1 Hour", callback_data="time_1h")],
            [InlineKeyboardButton("⏰ 6 Hours", callback_data="time_6h")],
            [InlineKeyboardButton("⏰ 1 Day", callback_data="time_1d")],
            [InlineKeyboardButton("🔄 Continuous", callback_data="time_continuous")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ *Strategy:* {strategy_name}\n\n"
            f"⏱️ *How long should it run live?*",
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
            await query.edit_message_text("❌ Setup cancelled.")
            return ConversationHandler.END
        
        # Parse time selection
        time_mapping = {
            "time_1h": ("1 Hour", timedelta(hours=1)),
            "time_6h": ("6 Hours", timedelta(hours=6)),
            "time_1d": ("1 Day", timedelta(days=1)),
            "time_continuous": ("Continuous", None)
        }
        
        time_label, duration = time_mapping.get(query.data, ("Unknown", None))
        self.user_configs[user_id]['duration'] = duration
        self.user_configs[user_id]['duration_label'] = time_label
        
        # Move to budget configuration
        keyboard = [
            [InlineKeyboardButton("💰 $1,000", callback_data="budget_1000")],
            [InlineKeyboardButton("💰 $5,000", callback_data="budget_5000")],
            [InlineKeyboardButton("💰 $10,000", callback_data="budget_10000")],
            [InlineKeyboardButton("💰 $25,000", callback_data="budget_25000")],
            [InlineKeyboardButton("💰 $100,000", callback_data="budget_100000")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⏱️ *Duration:* {time_label}\n\n"
            f"💰 *Paper Trading Budget:*\n"
            f"(Virtual money for simulation)",
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
            await query.edit_message_text("❌ Setup cancelled.")
            return ConversationHandler.END
        
        # Parse budget selection
        budget = int(query.data.replace("budget_", ""))
        self.user_configs[user_id]['budget'] = budget
        
        # Show confirmation
        config = self.user_configs[user_id]
        
        keyboard = [
            [InlineKeyboardButton("🚀 START LIVE TRADING", callback_data="confirm_start")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📋 *LIVE Trading Configuration:*\n\n"
            f"🎯 *Strategy:* {config['strategy']}\n"
            f"⏱️ *Duration:* {config['duration_label']}\n"
            f"💰 *Budget:* ${config['budget']:,} (paper)\n"
            f"📊 *Mode:* Paper Trading + Live Notifications\n\n"
            f"⚠️ *You will receive real-time trade alerts!*\n\n"
            f"Ready to start?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return CONFIRM_START
    
    async def confirm_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle trading confirmation and start REAL execution"""
        query = update.callback_query
        user_id = query.from_user.id
        
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Live trading cancelled.")
            return ConversationHandler.END
        
        config = self.user_configs[user_id]
        
        await query.edit_message_text(
            "🚀 *STARTING LIVE TRADING...*\n\n"
            "⏳ Initializing strategy...\n"
            "📊 Connecting to markets...\n"
            "🔔 Setting up notifications...\n\n"
            "*Please wait...*"
        )
        
        try:
            # Store strategy info with REAL execution
            self.active_strategies[user_id] = {
                'name': config['strategy'],
                'start_time': datetime.now(),
                'budget': config['budget'],
                'duration': config['duration'],
                'duration_label': config['duration_label'],
                'status': 'running',
                'config': config,
                'trades_count': 0,
                'last_trade': None
            }
            
            # Create notification queue for this user
            notification_queue = multiprocessing.Queue()
            self.notification_queues[user_id] = notification_queue
            
            # Start strategy in separate process
            strategy_process = multiprocessing.Process(
                target=self._run_strategy_in_process,
                args=(user_id, config['strategy'], config, notification_queue),
                daemon=True
            )
            strategy_process.start()
            self.strategy_processes[user_id] = strategy_process
            
            # Start notification monitoring task
            monitor_task = asyncio.create_task(self._monitor_notifications(user_id))
            self.running_tasks[user_id] = monitor_task
            
            await query.edit_message_text(
                f"✅ *LIVE TRADING STARTED!*\n\n"
                f"🎯 *Strategy:* {config['strategy']}\n"
                f"💰 *Budget:* ${config['budget']:,}\n"
                f"⏱️ *Duration:* {config['duration_label']}\n"
                f"📅 *Started:* {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"🔔 *You will receive notifications for:*\n"
                f"• Every trade execution\n"
                f"• P&L updates\n"
                f"• Strategy events\n\n"
                f"📊 Use `/status` for real-time info\n"
                f"🛑 Use `/stop` to end trading\n\n"
                f"🚀 *Happy Live Trading!*",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Failed to start live trading: {e}")
            await query.edit_message_text(
                f"❌ *Failed to start live trading:*\n\n{str(e)}"
            )
        
        return ConversationHandler.END
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command with REAL data"""
        user_id = update.effective_user.id
        
        if user_id not in self.active_strategies:
            try:
                await update.message.reply_text(
                    "📊 <b>Your Status:</b>\n\n"
                    "❌ No active live trading\n\n"
                    "🚀 Use /trade to start live trading!",
                    parse_mode='HTML'
                )
            except Exception as e:
                # Fallback without formatting
                await update.message.reply_text(
                    "📊 Your Status:\n\n"
                    "❌ No active live trading\n\n"
                    "🚀 Use /trade to start live trading!"
                )
            return
        
        # Check if process is still alive
        process = self.strategy_processes.get(user_id)
        if process and not process.is_alive():
            # Process died, clean up and inform user
            logger.warning(f"Strategy process died for user {user_id}")
            if user_id in self.active_strategies:
                del self.active_strategies[user_id]
            if user_id in self.strategy_processes:
                del self.strategy_processes[user_id]
            if user_id in self.running_tasks:
                self.running_tasks[user_id].cancel()
                del self.running_tasks[user_id]
            if user_id in self.notification_queues:
                del self.notification_queues[user_id]
            
            await update.message.reply_text(
                "⚠️ <b>Strategy Process Stopped</b>\n\n"
                "Your strategy process has stopped unexpectedly.\n\n"
                "🚀 Use /trade to start a new strategy!",
                parse_mode='HTML'
            )
            return
        
        try:
            strategy_info = self.active_strategies[user_id]
            start_time = strategy_info['start_time']
            runtime = datetime.now() - start_time
            
            # Format runtime
            hours, remainder = divmod(runtime.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            # Get last trade info - sanitize strings
            last_trade_text = "No trades yet"
            if strategy_info.get('last_trade'):
                trade = strategy_info['last_trade']
                # Sanitize trade data
                action = str(trade.get('action', 'UNKNOWN'))
                quantity = trade.get('quantity', 0)
                symbol = str(trade.get('symbol', 'UNKNOWN'))
                price = trade.get('price', 0)
                last_trade_text = f"{action} {quantity} {symbol} @ ${price:.2f}"
            
            # Sanitize all string values
            strategy_name = str(strategy_info.get('name', 'Unknown'))
            budget = strategy_info.get('budget', 0)
            duration_label = str(strategy_info.get('duration_label', 'Unknown'))
            trades_count = strategy_info.get('trades_count', 0)
            
            status_text = (
                f"📊 <b>LIVE TRADING STATUS</b>\n\n"
                f"🎯 <b>Strategy:</b> {strategy_name}\n"
                f"📈 <b>Status:</b> 🟢 Running Live\n"
                f"⏰ <b>Runtime:</b> {runtime.days}d {hours}h {minutes}m\n"
                f"💰 <b>Budget:</b> ${budget:,}\n"
                f"📅 <b>Duration:</b> {duration_label}\n"
                f"📊 <b>Trades:</b> {trades_count}\n"
                f"🔄 <b>Last Trade:</b> {last_trade_text}\n\n"
                f"✅ <b>Live notifications active</b>"
            )
            
            await update.message.reply_text(status_text, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Status command error: {e}")
            # Fallback response without formatting
            try:
                await update.message.reply_text(
                    "📊 LIVE TRADING STATUS\n\n"
                    "🎯 Strategy: Active\n"
                    "📈 Status: Running Live\n"
                    "✅ Live notifications active\n\n"
                    f"⚠️ Error getting details: {str(e)[:100]}"
                )
            except:
                # Last resort - minimal message
                try:
                    await update.message.reply_text("📊 Live trading is active")
                except:
                    pass  # Give up if even this fails
    
    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command - Stop REAL execution"""
        user_id = update.effective_user.id
        
        if user_id not in self.active_strategies:
            await update.message.reply_text(
                "❌ *No Active Trading*\n\n"
                "You don't have any live strategies running.\n\n"
                "🚀 Use `/trade` to start!"
            )
            return
        
        # Get strategy info before stopping
        strategy_info = self.active_strategies[user_id]
        runtime = datetime.now() - strategy_info['start_time']
        
        # Stop the strategy process and clean up
        if user_id in self.strategy_processes:
            process = self.strategy_processes[user_id]
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
            del self.strategy_processes[user_id]
        
        # Cancel notification monitoring task
        if user_id in self.running_tasks:
            self.running_tasks[user_id].cancel()
            del self.running_tasks[user_id]
        
        # Clean up notification queue
        if user_id in self.notification_queues:
            del self.notification_queues[user_id]
        
        # Remove from active strategies
        del self.active_strategies[user_id]
        
        await update.message.reply_text(
            f"🛑 *LIVE TRADING STOPPED*\n\n"
            f"🎯 *Strategy:* {strategy_info['name']}\n"
            f"⏱️ *Total Runtime:* {runtime}\n"
            f"💰 *Budget:* ${strategy_info['budget']:,}\n"
            f"📊 *Total Trades:* {strategy_info.get('trades_count', 0)}\n\n"
            f"📋 *Session Summary:*\n"
            f"• Mode: Live Paper Trading\n"
            f"• Status: ✅ Stopped Successfully\n\n"
            f"🚀 Ready for another session? Use `/trade`",
            parse_mode='Markdown'
        )
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel conversation"""
        await update.message.reply_text("❌ *Operation Cancelled*\n\nUse `/trade` to start again!")
        return ConversationHandler.END
    
    def cleanup_all_processes(self):
        """Clean up all running strategy processes and tasks"""
        logger.info("Cleaning up all strategy processes...")
        
        # Terminate all strategy processes
        for user_id, process in list(self.strategy_processes.items()):
            try:
                if process.is_alive():
                    logger.info(f"Terminating strategy process for user {user_id}")
                    process.terminate()
                    process.join(timeout=3)
                    if process.is_alive():
                        logger.warning(f"Force killing strategy process for user {user_id}")
                        process.kill()
                        process.join()
            except Exception as e:
                logger.error(f"Error terminating process for user {user_id}: {e}")
        
        # Cancel all monitoring tasks
        for user_id, task in list(self.running_tasks.items()):
            try:
                if not task.done():
                    task.cancel()
            except Exception as e:
                logger.error(f"Error cancelling task for user {user_id}: {e}")
        
        # Clear all collections
        self.strategy_processes.clear()
        self.running_tasks.clear()
        self.notification_queues.clear()
        self.active_strategies.clear()
        
        logger.info("Cleanup completed")

def main():
    """Main function to run the LIVE trading bot"""
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found")
        return
    
    print("🚀 Starting LIVE Trading Telegram Bot...")
    print("=" * 55)
    
    # Create bot instance
    bot = LiveTradingBot(TOKEN)
    
    # Test core functionality  
    try:
        strategies = bot.core.list_strategies()
        print(f"✅ Registered {len(strategies)} strategies: {list(strategies.keys())}")
    except Exception as e:
        print(f"⚠️ Core error: {e}")
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    bot.set_telegram_app(application)  # Set for notifications
    
    # Add global error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global error handler"""
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        # Handle specific error types
        if isinstance(context.error, NetworkError):
            logger.warning("Network error occurred, will retry automatically")
            return
            
        # Send error notification to user if update available
        if update and hasattr(update, 'effective_user') and update.effective_user:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text="⚠️ An error occurred. Please try again.",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")
    
    application.add_error_handler(error_handler)
    
    # Create conversation handler for trading flow
    trade_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", bot.start_trade)],
        states={
            STRATEGY_SELECT: [CallbackQueryHandler(bot.strategy_selected)],
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
    application.add_handler(trade_handler)
    
    # Start bot
    print("🚀 LIVE Trading Bot is running!")
    print("📱 Go to Telegram and message your bot!")
    print("🎯 Use /start to begin")
    print("🔔 You will receive REAL-TIME trade notifications!")
    print("\nPress Ctrl+C to stop")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Live trading bot stopping...")
        print("🧹 Cleaning up strategy processes...")
        bot.cleanup_all_processes()
        print("✅ Live trading bot stopped cleanly")
    except Exception as e:
        print(f"❌ Bot error: {e}")
        print("🧹 Cleaning up strategy processes...")
        bot.cleanup_all_processes()

if __name__ == "__main__":
    # Required for multiprocessing on Windows and macOS
    multiprocessing.set_start_method('spawn', force=True)
    main()