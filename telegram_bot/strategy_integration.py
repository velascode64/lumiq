"""
Strategy Integration Module

Handles the integration between Telegram bot and the Core trading system.
Manages strategy execution, monitoring, and real-time updates.
"""

import asyncio
import threading
import time
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class StrategyRunner:
    """
    Manages strategy execution in the background with real-time monitoring
    """
    
    def __init__(self, core, telegram_context):
        """
        Initialize strategy runner
        
        Args:
            core: TradingCore instance
            telegram_context: Telegram bot context for notifications
        """
        self.core = core
        self.context = telegram_context
        self.running_strategies: Dict[int, Dict] = {}  # user_id -> strategy info
        self._stop_flags: Dict[int, threading.Event] = {}
    
    async def start_strategy(
        self, 
        user_id: int, 
        strategy_name: str, 
        parameters: Dict[str, Any], 
        budget: float,
        duration: Optional[timedelta] = None
    ) -> Dict[str, Any]:
        """
        Start a paper trading strategy for a user
        
        Args:
            user_id: Telegram user ID
            strategy_name: Name of strategy to run
            parameters: Strategy parameters
            budget: Trading budget
            duration: Optional duration limit
            
        Returns:
            Strategy information dictionary
        """
        try:
            # Prepare strategy configuration
            strategy_config = {
                'initial_budget': budget,
                **parameters
            }
            
            # Create stop flag for this strategy
            stop_flag = threading.Event()
            self._stop_flags[user_id] = stop_flag
            
            # Start strategy in paper trading mode using the core
            loop = asyncio.get_event_loop()
            strategy_instance = await loop.run_in_executor(
                None,
                self._run_paper_strategy,
                strategy_name,
                strategy_config,
                user_id,
                stop_flag
            )
            
            # Store strategy information
            strategy_info = {
                'instance': strategy_instance,
                'name': strategy_name,
                'config': strategy_config,
                'start_time': datetime.now(),
                'duration': duration,
                'status': 'running',
                'budget': budget,
                'user_id': user_id
            }
            
            self.running_strategies[user_id] = strategy_info
            
            # Start monitoring thread
            monitor_thread = threading.Thread(
                target=self._monitor_strategy,
                args=(user_id, strategy_info),
                daemon=True
            )
            monitor_thread.start()
            
            logger.info(f"Strategy {strategy_name} started for user {user_id}")
            return strategy_info
            
        except Exception as e:
            logger.error(f"Failed to start strategy {strategy_name} for user {user_id}: {e}")
            raise
    
    def _run_paper_strategy(self, strategy_name: str, config: Dict, user_id: int, stop_flag: threading.Event):
        """
        Run strategy in paper trading mode (synchronous execution)
        """
        try:
            # Use the core to run paper trading
            strategy_instance = self.core.paper_trade(
                strategy=strategy_name,
                params=config
            )
            return strategy_instance
            
        except Exception as e:
            logger.error(f"Error running strategy {strategy_name}: {e}")
            raise
    
    def _monitor_strategy(self, user_id: int, strategy_info: Dict):
        """
        Monitor strategy execution and send updates
        """
        start_time = strategy_info['start_time']
        duration = strategy_info['duration']
        stop_flag = self._stop_flags.get(user_id)
        
        last_update = start_time
        update_interval = timedelta(minutes=30)  # Send updates every 30 minutes
        
        try:
            while not stop_flag.is_set():
                current_time = datetime.now()
                
                # Check if duration has elapsed
                if duration and (current_time - start_time) >= duration:
                    self.stop_strategy(user_id)
                    asyncio.run(self._send_notification(
                        user_id,
                        "⏰ Trading session completed (duration reached)"
                    ))
                    break
                
                # Send periodic updates
                if (current_time - last_update) >= update_interval:
                    asyncio.run(self._send_status_update(user_id, strategy_info))
                    last_update = current_time
                
                # Sleep for a short period
                time.sleep(30)  # Check every 30 seconds
                
        except Exception as e:
            logger.error(f"Error monitoring strategy for user {user_id}: {e}")
            asyncio.run(self._send_notification(
                user_id,
                f"❌ Monitoring error: {str(e)}"
            ))
    
    async def _send_status_update(self, user_id: int, strategy_info: Dict):
        """
        Send status update to user
        """
        try:
            runtime = datetime.now() - strategy_info['start_time']
            hours, remainder = divmod(runtime.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            message = (
                f"📊 *Strategy Update*\n\n"
                f"Strategy: {strategy_info['name']}\n"
                f"Status: 🟢 Running\n"
                f"Runtime: {runtime.days}d {hours}h {minutes}m\n"
                f"Budget: ${strategy_info['budget']:,}\n"
            )
            
            await self.context.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Failed to send status update to user {user_id}: {e}")
    
    async def _send_notification(self, user_id: int, message: str):
        """
        Send notification to user
        """
        try:
            await self.context.bot.send_message(
                chat_id=user_id,
                text=message
            )
        except Exception as e:
            logger.error(f"Failed to send notification to user {user_id}: {e}")
    
    def stop_strategy(self, user_id: int) -> bool:
        """
        Stop a running strategy
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if strategy was stopped, False if no strategy was running
        """
        if user_id not in self.running_strategies:
            return False
        
        try:
            # Set stop flag
            if user_id in self._stop_flags:
                self._stop_flags[user_id].set()
            
            # Get strategy info
            strategy_info = self.running_strategies[user_id]
            
            # Stop the strategy instance (if the instance has a stop method)
            strategy_instance = strategy_info.get('instance')
            if strategy_instance and hasattr(strategy_instance, 'stop'):
                strategy_instance.stop()
            
            # Clean up
            del self.running_strategies[user_id]
            if user_id in self._stop_flags:
                del self._stop_flags[user_id]
            
            logger.info(f"Strategy stopped for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping strategy for user {user_id}: {e}")
            return False
    
    def get_strategy_status(self, user_id: int) -> Optional[Dict]:
        """
        Get current strategy status for a user
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Strategy status dictionary or None if no strategy running
        """
        if user_id not in self.running_strategies:
            return None
        
        strategy_info = self.running_strategies[user_id]
        runtime = datetime.now() - strategy_info['start_time']
        
        return {
            'name': strategy_info['name'],
            'status': strategy_info['status'],
            'runtime': runtime,
            'budget': strategy_info['budget'],
            'start_time': strategy_info['start_time'],
            'duration': strategy_info['duration']
        }
    
    def is_user_trading(self, user_id: int) -> bool:
        """
        Check if user has an active trading strategy
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if user has active strategy
        """
        return user_id in self.running_strategies