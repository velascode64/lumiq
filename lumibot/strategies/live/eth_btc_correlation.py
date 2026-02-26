from lumibot.strategies import Strategy
from lumibot.entities import Asset
from datetime import datetime, timedelta


class CryptoLeadLagStrategy(Strategy):
    """
    Estrategia ETH/BTC Correlation - Trading 24/7 
    Opera basándose en la correlación entre BTC y otras cryptos
    """
    
    def initialize(self):
        """Inicializar estrategia con formato crypto correcto"""
        # FORZAR trading continuo para crypto (24/7)
        self.market_hours = None  # Disable market hours checking
        
        # Set broker market to 24/7 for crypto trading
        if hasattr(self, 'broker') and self.broker:
            self.broker.market = "24/7"
            self.log_message("🌍 Broker market set to '24/7' - ENABLING 24/7 crypto trading!")
        
        # Configuración básica
        self.sleeptime = "1M"  # Revisar cada hora (más frecuente)
        
        # Usar formato correcto para Alpaca crypto: separate base and quote assets
        self.btc_asset = Asset(symbol="BTC", asset_type="crypto")
        self.eth_asset = Asset(symbol="ETH", asset_type="crypto")
        self.sol_asset = Asset(symbol="SOL", asset_type="crypto")
        self.usd_quote = Asset(symbol="USD", asset_type="forex")  # Quote asset
        
        # Parámetros configurables
        self.btc_threshold = self.parameters.get('btc_threshold', 0.05)  # 5% cambio BTC
        self.position_size = self.parameters.get('position_size', 0.1)   # 10% del portfolio
        self.stop_loss_pct = self.parameters.get('stop_loss', 0.03)     # 3% stop loss
        self.take_profit_pct = self.parameters.get('take_profit', 0.06) # 6% take profit
        
        # Estado interno
        self.last_btc_price = None
        self.last_check_time = datetime.now()
        self.trades_today = 0
        self.max_trades_per_day = 5
        
        self.log_message("=" * 60)
        self.log_message("ETH/BTC CORRELATION STRATEGY - 24/7 CRYPTO")
        self.log_message("=" * 60)
        self.log_message(f"BTC threshold: {self.btc_threshold*100:.1f}%")
        self.log_message(f"Position size: {self.position_size*100:.1f}% of portfolio")
        self.log_message(f"Stop loss: {self.stop_loss_pct*100:.1f}%")
        self.log_message(f"Take profit: {self.take_profit_pct*100:.1f}%")
        self.log_message("=" * 60)
    
    def is_market_open(self):
        """Override para forzar trading 24/7"""
        return True
    
    def should_continue_trading(self):
        """Override para forzar trading continuo"""
        return True
    
    def get_crypto_price(self, crypto_asset):
        """Helper method to get crypto price using correct Alpaca format"""
        try:
            quote = self.get_quote(crypto_asset, quote=self.usd_quote)
            current_price = None
            
            # Try multiple price attributes with fallbacks
            if quote and hasattr(quote, 'last') and quote.last:
                current_price = float(quote.last)
            elif quote and hasattr(quote, 'price') and quote.price:
                current_price = float(quote.price)
            elif quote and hasattr(quote, 'close') and quote.close:
                current_price = float(quote.close)
            
            if current_price:
                return current_price
            
            # Fallback: Use simulated price for paper trading
            import random
            if crypto_asset.symbol == "BTC":
                base_price = 45000  # BTC base price
            elif crypto_asset.symbol == "ETH":
                base_price = 2600   # ETH base price
            elif crypto_asset.symbol == "SOL":
                base_price = 60     # SOL base price
            else:
                base_price = 100    # Default base price
            
            # Add some realistic price movement (±2%)
            price_variation = random.uniform(-0.02, 0.02)
            simulated_price = base_price * (1 + price_variation)
            self.log_message(f"📊 Using simulated {crypto_asset.symbol} price: ${simulated_price:.2f} (real quote unavailable)")
            return simulated_price
            
        except Exception as e:
            # Fallback to simulated price if all else fails
            import random
            if crypto_asset.symbol == "BTC":
                base_price = 45000
            elif crypto_asset.symbol == "ETH":
                base_price = 2600
            elif crypto_asset.symbol == "SOL":
                base_price = 60
            else:
                base_price = 100
            
            price_variation = random.uniform(-0.02, 0.02)
            simulated_price = base_price * (1 + price_variation)
            self.log_message(f"⚠️ Error getting {crypto_asset.symbol} price ({str(e)}), using simulated: ${simulated_price:.2f}")
            return simulated_price

    def on_trading_iteration(self):
        """Iteración principal de la estrategia"""
        try:
            current_time = datetime.now()
            self.log_message(f"\n--- Iteration: {current_time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            
            # Reset trades counter daily
            if current_time.date() != self.last_check_time.date():
                self.trades_today = 0
                self.log_message("🔄 New day - reset trades counter")
            
            self.last_check_time = current_time
            
            # Check if we've hit trade limit
            if self.trades_today >= self.max_trades_per_day:
                self.log_message(f"⏸️ Daily trade limit reached ({self.trades_today}/{self.max_trades_per_day})")
                return
                
            # Get current BTC price using correct Alpaca crypto format
            current_btc_price = self.get_crypto_price(self.btc_asset)
            self.log_message(f"💰 Current BTC price: ${current_btc_price:.2f}")
            
            # Calculate BTC return if we have previous price
            btc_return = 0
            if self.last_btc_price:
                btc_return = (current_btc_price - self.last_btc_price) / self.last_btc_price
                self.log_message(f"📈 BTC return: {btc_return*100:.2f}%")
            else:
                self.log_message("📊 First iteration - storing BTC price")
                self.last_btc_price = current_btc_price
                return
                
            # Store current price for next iteration
            self.last_btc_price = current_btc_price
            
            # Portfolio info
            portfolio_value = self.portfolio_value
            cash = self.cash
            self.log_message(f"💼 Portfolio: ${portfolio_value:,.2f}, Cash: ${cash:,.2f}")
            
            # Trading logic based on BTC movement
            if abs(btc_return) >= self.btc_threshold:
                if btc_return > 0:
                    # BTC went up - buy correlated crypto
                    reason = f"BTC subió {btc_return*100:.2f}% - Comprando cryptos correlacionadas"
                    indicators_dict = {
                        'symbol': 'BTC/USD',
                        'btc_price': float(current_btc_price),
                        'btc_return': float(btc_return * 100),
                        'threshold': float(self.btc_threshold * 100),
                        'portfolio': float(portfolio_value)
                    }
                    self.log_message(
                        f"[SIGNAL] action=BUY reason='{reason}' price={current_btc_price:.2f} "
                        f"indicators={indicators_dict}"
                    )
                    self._execute_buy_signals(btc_return)
                else:
                    # BTC went down - sell positions
                    reason = f"BTC bajó {btc_return*100:.2f}% - Vendiendo posiciones"
                    indicators_dict = {
                        'symbol': 'BTC/USD',
                        'btc_price': float(current_btc_price),
                        'btc_return': float(btc_return * 100),
                        'threshold': float(self.btc_threshold * 100),
                        'portfolio': float(portfolio_value)
                    }
                    self.log_message(
                        f"[SIGNAL] action=SELL reason='{reason}' price={current_btc_price:.2f} "
                        f"indicators={indicators_dict}"
                    )
                    self._execute_sell_signals(btc_return)
            else:
                reason = f"Esperando movimiento BTC > {self.btc_threshold*100:.1f}% (actual: {btc_return*100:.2f}%)"
                indicators_dict = {
                    'symbol': 'BTC/USD',
                    'btc_price': float(current_btc_price),
                    'btc_return': float(btc_return * 100),
                    'threshold': float(self.btc_threshold * 100),
                    'portfolio': float(portfolio_value)
                }
                self.log_message(
                    f"[SIGNAL] action=HOLD reason='{reason}' price={current_btc_price:.2f} "
                    f"indicators={indicators_dict}"
                )
                
            # Check existing positions for stop loss / take profit
            self._manage_risk()
            
        except Exception as e:
            self.log_message(f"❌ Error in trading iteration: {str(e)}", color="red")
    
    def _execute_buy_signals(self, btc_return):
        """Execute buy orders for ETH and SOL when BTC goes up"""
        self.log_message(f"🚀 BTC up {btc_return*100:.2f}% - Looking for buy opportunities")
        
        assets_to_buy = [self.eth_asset, self.sol_asset]
        
        for asset in assets_to_buy:
            try:
                # Check if we already have a position
                position = self.get_position(asset)
                
                if position and position.quantity > 0:
                    self.log_message(f"📊 Already have {asset.symbol} position: {position.quantity:.6f}")
                    continue
                    
                # Get current price using correct format
                current_price = self.get_crypto_price(asset)
                if not current_price:
                    self.log_message(f"⚠️ Could not get price for {asset.symbol}")
                    continue
                    
                # Calculate position size
                position_value = self.portfolio_value * self.position_size
                quantity = position_value / current_price
                
                # Create buy order
                self.log_message(f"🟢 BUYING {asset.symbol}")
                self.log_message(f"   Price: ${current_price:.6f}")
                self.log_message(f"   Quantity: {quantity:.6f}")
                self.log_message(f"   Value: ${position_value:.2f}")
                
                order = self.create_order(
                    asset=asset,
                    quantity=quantity,
                    side="buy"
                )
                
                self.submit_order(order)
                self.trades_today += 1
                
            except Exception as e:
                self.log_message(f"❌ Error buying {asset.symbol}: {str(e)}", color="red")
    
    def _execute_sell_signals(self, btc_return):
        """Execute sell orders when BTC goes down"""
        self.log_message(f"🔻 BTC down {btc_return*100:.2f}% - Selling positions")
        
        positions = self.get_positions()
        
        for position in positions:
            if position.quantity > 0 and position.asset.symbol in ["ETH", "SOL"]:
                try:
                    symbol = position.asset.symbol
                    current_price = self.get_crypto_price(position.asset)
                    
                    if current_price:
                        position_value = position.quantity * current_price
                        
                        self.log_message(f"🔴 SELLING {symbol}")
                        self.log_message(f"   Quantity: {position.quantity:.6f}")
                        self.log_message(f"   Price: ${current_price:.6f}")
                        self.log_message(f"   Value: ${position_value:.2f}")
                        
                        order = self.create_order(
                            asset=position.asset,
                            quantity=position.quantity,
                            side="sell"
                        )
                        
                        self.submit_order(order)
                        self.trades_today += 1
                        
                except Exception as e:
                    self.log_message(f"❌ Error selling {position.asset.symbol}: {str(e)}", color="red")
    
    def _manage_risk(self):
        """Check stop loss and take profit levels"""
        positions = self.get_positions()
        
        for position in positions:
            if position.quantity > 0 and position.asset.symbol in ["ETH", "SOL"]:
                try:
                    current_price = self.get_crypto_price(position.asset)
                    if not current_price:
                        continue
                        
                    # Calculate P&L percentage
                    entry_price = position.avg_price if hasattr(position, 'avg_price') else current_price
                    pnl_pct = (current_price - entry_price) / entry_price
                    
                    # Check stop loss
                    if pnl_pct <= -self.stop_loss_pct:
                        reason = f"Stop loss triggered: {pnl_pct*100:.2f}%"
                        indicators_dict = {
                            'symbol': f'{position.asset.symbol}/USD',
                            'current_price': float(current_price),
                            'entry_price': float(entry_price),
                            'pnl_pct': float(pnl_pct * 100),
                            'stop_loss': float(self.stop_loss_pct * 100)
                        }
                        self.log_message(
                            f"[SIGNAL] action=SELL reason='{reason}' price={current_price:.2f} "
                            f"indicators={indicators_dict}"
                        )
                        self.log_message(f"🛑 Stop loss triggered for {position.asset.symbol}: {pnl_pct*100:.2f}%")
                        self._close_position(position)
                        
                    # Check take profit
                    elif pnl_pct >= self.take_profit_pct:
                        reason = f"Take profit triggered: {pnl_pct*100:.2f}%"
                        indicators_dict = {
                            'symbol': f'{position.asset.symbol}/USD',
                            'current_price': float(current_price),
                            'entry_price': float(entry_price),
                            'pnl_pct': float(pnl_pct * 100),
                            'take_profit': float(self.take_profit_pct * 100)
                        }
                        self.log_message(
                            f"[SIGNAL] action=SELL reason='{reason}' price={current_price:.2f} "
                            f"indicators={indicators_dict}"
                        )
                        self.log_message(f"✅ Take profit triggered for {position.asset.symbol}: {pnl_pct*100:.2f}%")
                        self._close_position(position)
                        
                except Exception as e:
                    self.log_message(f"❌ Error managing risk for {position.asset.symbol}: {str(e)}", color="red")
    
    def _close_position(self, position):
        """Close a position"""
        try:
            order = self.create_order(
                asset=position.asset,
                quantity=position.quantity,
                side="sell"
            )
            
            self.submit_order(order)
            self.trades_today += 1
            
        except Exception as e:
            self.log_message(f"❌ Error closing position: {str(e)}", color="red")
    
    def on_filled_order(self, position, order, price, quantity, multiplier=None):
        """Callback when order is filled"""
        side = order.side.upper()
        symbol = order.asset.symbol
        value = float(quantity) * float(price)
        
        self.log_message("\n" + "🎉" * 30)
        self.log_message("ORDER FILLED!")
        self.log_message(f"  {side}: {quantity:.6f} {symbol}")
        self.log_message(f"  Price: ${price:.6f}")
        self.log_message(f"  Value: ${value:,.2f}")
        self.log_message("🎉" * 30 + "\n")
    
    def on_strategy_end(self):
        """Clean up when strategy ends"""
        self.log_message("🏁 Strategy ending - closing all positions")
        positions = self.get_positions()
        
        for position in positions:
            if position.quantity > 0:
                self._close_position(position)
