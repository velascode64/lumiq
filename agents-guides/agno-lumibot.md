# Plan: Agno + Lumibot - Trading Agent con Parámetros Dinámicos

## Resumen Ejecutivo

Sistema de trading donde un agente inteligente (Agno) controla y evoluciona estrategias de Lumibot mediante parámetros dinámicos, con interfaz conversacional vía Telegram.

---

## Arquitectura

```
┌─────────────────────────────────────────┐
│            Telegram Bot                 │
│   "Ajusta RSI a 12"                     │
│   "El mercado está volátil"             │
│   "¿Cómo va el portfolio?"              │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│              Agno Agent                 │
│   - Memory (recuerda conversaciones)    │
│   - Tools (ejecutar, ajustar, consultar)│
│   - Knowledge (historial de trades)     │
│   - Reflexión (aprende de resultados)   │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         Lumibot Strategy                │
│   parameters = {                        │
│     "rsi_period": 14,  ← DINÁMICO       │
│     "stop_loss": 0.02, ← DINÁMICO       │
│     "take_profit": 0.05 ← DINÁMICO      │
│   }                                     │
│   update_parameters() ← Agno lo llama   │
│   on_parameters_updated() ← Callback    │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         Alpaca API (Broker)             │
│   Paper Trading / Live Trading          │
└─────────────────────────────────────────┘
```

---

## Stack Tecnológico

| Componente | Tecnología | Propósito |
|------------|------------|-----------|
| Agente | [Agno](https://www.agno.com/) | Framework de agentes Python |
| Trading | [Lumibot](https://lumibot.lumiwealth.com/) | Ejecución de estrategias |
| Broker | [Alpaca](https://alpaca.markets/) | Ejecución de órdenes |
| Chat | Telegram | Interfaz conversacional |
| LLM | Claude / GPT | Cerebro del agente |

---

## Instalación

```bash
pip install agno lumibot alpaca-py python-telegram-bot
```

---

## Estructura de Archivos

```
lumibot-dev/
├── agent/
│   ├── __init__.py
│   ├── trading_agent.py      # Agente Agno principal
│   ├── tools.py              # Tools para el agente
│   ├── memory.py             # Sistema de memoria
│   └── prompts.py            # System prompts
├── strategies/
│   ├── __init__.py
│   ├── adaptive_strategy.py  # Estrategia con parámetros dinámicos
│   └── indicators.py         # Indicadores técnicos
├── interfaces/
│   ├── __init__.py
│   └── telegram_bot.py       # Bot de Telegram
├── config/
│   ├── credentials.py        # API keys
│   └── parameters.json       # Parámetros por defecto
└── main.py                   # Entry point
```

---

## Componente 1: Estrategia Lumibot con Parámetros Dinámicos

```python
# strategies/adaptive_strategy.py
from lumibot.strategies import Strategy
from lumibot.brokers import Alpaca
from datetime import datetime

class AdaptiveStrategy(Strategy):
    """
    Estrategia que puede ser controlada por el agente Agno.
    Los parámetros pueden ser modificados en tiempo real.
    """

    # Parámetros dinámicos - el agente puede modificarlos
    parameters = {
        # Indicadores
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "sma_fast": 10,
        "sma_slow": 50,

        # Risk Management
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.05,
        "max_position_size": 0.1,  # 10% del portfolio

        # Comportamiento
        "trading_enabled": True,
        "aggressive_mode": False,

        # Símbolos
        "symbols": ["SPY", "QQQ"],
    }

    def initialize(self):
        """Se ejecuta una vez al inicio."""
        self.sleeptime = "1M"  # Cada minuto
        self.last_check = None

    def on_parameters_updated(self, updated_params: dict):
        """
        Callback automático cuando el agente modifica parámetros.
        Lumibot llama esto automáticamente.
        """
        self.log_message(f"[AGENT] Parámetros actualizados: {updated_params}")

        # Recalcular indicadores si cambiaron períodos
        if "rsi_period" in updated_params or "sma_fast" in updated_params:
            self.log_message("[AGENT] Recalculando indicadores...")

    def on_trading_iteration(self):
        """Loop principal de la estrategia."""
        if not self.parameters["trading_enabled"]:
            return

        for symbol in self.parameters["symbols"]:
            self._evaluate_symbol(symbol)

    def _evaluate_symbol(self, symbol: str):
        """Evalúa un símbolo según los parámetros actuales."""
        # Obtener datos
        bars = self.get_historical_prices(symbol, 100, "day")
        if bars is None:
            return

        # Calcular RSI con período dinámico
        rsi = self._calculate_rsi(bars, self.parameters["rsi_period"])

        # Calcular SMAs con períodos dinámicos
        sma_fast = bars.df["close"].rolling(self.parameters["sma_fast"]).mean().iloc[-1]
        sma_slow = bars.df["close"].rolling(self.parameters["sma_slow"]).mean().iloc[-1]

        # Lógica de trading
        position = self.get_position(symbol)

        # Señal de compra
        if rsi < self.parameters["rsi_oversold"] and sma_fast > sma_slow:
            if position is None:
                self._open_position(symbol, "buy")

        # Señal de venta
        elif rsi > self.parameters["rsi_overbought"] or sma_fast < sma_slow:
            if position is not None:
                self._close_position(symbol)

    def _open_position(self, symbol: str, side: str):
        """Abre una posición con risk management."""
        cash = self.cash
        max_size = cash * self.parameters["max_position_size"]

        last_price = self.get_last_price(symbol)
        quantity = int(max_size / last_price)

        if quantity > 0:
            order = self.create_order(symbol, quantity, side)
            self.submit_order(order)
            self.log_message(f"[TRADE] {side.upper()} {quantity} {symbol} @ {last_price}")

    def _close_position(self, symbol: str):
        """Cierra una posición."""
        position = self.get_position(symbol)
        if position:
            self.sell_all(symbol)
            self.log_message(f"[TRADE] CLOSED {symbol}")

    def _calculate_rsi(self, bars, period: int) -> float:
        """Calcula RSI con período dinámico."""
        delta = bars.df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs.iloc[-1]))

    def get_status(self) -> dict:
        """Retorna estado actual para el agente."""
        return {
            "portfolio_value": self.portfolio_value,
            "cash": self.cash,
            "positions": [str(p) for p in self.get_positions()],
            "parameters": self.parameters,
            "trading_enabled": self.parameters["trading_enabled"],
        }
```

---

## Componente 2: Tools para el Agente Agno

```python
# agent/tools.py
from agno import tool
from typing import Optional

# Referencia global a la estrategia (se setea en main.py)
strategy = None

def set_strategy(s):
    global strategy
    strategy = s

@tool
def adjust_parameter(param_name: str, new_value: float) -> str:
    """
    Ajusta un parámetro de la estrategia de trading en tiempo real.

    Args:
        param_name: Nombre del parámetro (ej: "rsi_period", "stop_loss_pct")
        new_value: Nuevo valor para el parámetro

    Returns:
        Confirmación del cambio
    """
    if strategy is None:
        return "Error: Estrategia no inicializada"

    if param_name not in strategy.parameters:
        available = list(strategy.parameters.keys())
        return f"Error: Parámetro '{param_name}' no existe. Disponibles: {available}"

    old_value = strategy.parameters[param_name]
    strategy.update_parameters({param_name: new_value})

    return f"✅ {param_name}: {old_value} → {new_value}"

@tool
def get_parameters() -> dict:
    """
    Obtiene todos los parámetros actuales de la estrategia.

    Returns:
        Diccionario con todos los parámetros y sus valores
    """
    if strategy is None:
        return {"error": "Estrategia no inicializada"}
    return strategy.get_parameters()

@tool
def get_portfolio_status() -> dict:
    """
    Obtiene el estado actual del portfolio.

    Returns:
        Estado del portfolio incluyendo valor, cash, y posiciones
    """
    if strategy is None:
        return {"error": "Estrategia no inicializada"}
    return strategy.get_status()

@tool
def enable_trading() -> str:
    """Habilita el trading automático."""
    if strategy is None:
        return "Error: Estrategia no inicializada"
    strategy.update_parameters({"trading_enabled": True})
    return "✅ Trading HABILITADO"

@tool
def disable_trading() -> str:
    """Deshabilita el trading automático (modo observación)."""
    if strategy is None:
        return "Error: Estrategia no inicializada"
    strategy.update_parameters({"trading_enabled": False})
    return "⏸️ Trading DESHABILITADO (modo observación)"

@tool
def set_aggressive_mode(enabled: bool) -> str:
    """
    Activa o desactiva el modo agresivo.
    En modo agresivo: posiciones más grandes, stops más amplios.

    Args:
        enabled: True para activar, False para desactivar
    """
    if strategy is None:
        return "Error: Estrategia no inicializada"

    if enabled:
        strategy.update_parameters({
            "aggressive_mode": True,
            "max_position_size": 0.2,  # 20%
            "stop_loss_pct": 0.03,
        })
        return "🔥 Modo AGRESIVO activado (posiciones 20%, stop 3%)"
    else:
        strategy.update_parameters({
            "aggressive_mode": False,
            "max_position_size": 0.1,  # 10%
            "stop_loss_pct": 0.02,
        })
        return "🛡️ Modo CONSERVADOR activado (posiciones 10%, stop 2%)"

@tool
def analyze_performance() -> str:
    """
    Analiza el rendimiento reciente y sugiere ajustes.

    Returns:
        Análisis y sugerencias basadas en el rendimiento
    """
    if strategy is None:
        return "Error: Estrategia no inicializada"

    status = strategy.get_status()

    return f"""
📊 ANÁLISIS DE RENDIMIENTO

Portfolio: ${status['portfolio_value']:,.2f}
Cash disponible: ${status['cash']:,.2f}
Posiciones abiertas: {len(status['positions'])}

Parámetros actuales:
- RSI período: {status['parameters']['rsi_period']}
- Stop Loss: {status['parameters']['stop_loss_pct']*100}%
- Tamaño máximo posición: {status['parameters']['max_position_size']*100}%

Basándome en estos datos, puedo sugerir ajustes si lo deseas.
"""

@tool
def add_symbol(symbol: str) -> str:
    """
    Agrega un símbolo a la lista de trading.

    Args:
        symbol: Símbolo a agregar (ej: "AAPL", "TSLA")
    """
    if strategy is None:
        return "Error: Estrategia no inicializada"

    symbols = strategy.parameters["symbols"].copy()
    if symbol.upper() not in symbols:
        symbols.append(symbol.upper())
        strategy.update_parameters({"symbols": symbols})
        return f"✅ {symbol.upper()} agregado. Símbolos activos: {symbols}"
    return f"ℹ️ {symbol.upper()} ya está en la lista"

@tool
def remove_symbol(symbol: str) -> str:
    """
    Remueve un símbolo de la lista de trading.

    Args:
        symbol: Símbolo a remover
    """
    if strategy is None:
        return "Error: Estrategia no inicializada"

    symbols = strategy.parameters["symbols"].copy()
    if symbol.upper() in symbols:
        symbols.remove(symbol.upper())
        strategy.update_parameters({"symbols": symbols})
        return f"✅ {symbol.upper()} removido. Símbolos activos: {symbols}"
    return f"ℹ️ {symbol.upper()} no estaba en la lista"
```

---

## Componente 3: Agente Agno

```python
# agent/trading_agent.py
from agno import Agent
from .tools import (
    adjust_parameter,
    get_parameters,
    get_portfolio_status,
    enable_trading,
    disable_trading,
    set_aggressive_mode,
    analyze_performance,
    add_symbol,
    remove_symbol,
)

SYSTEM_PROMPT = """
Eres un asistente de trading inteligente que controla una estrategia de Lumibot.

## Tu Rol
- Ayudas al usuario a gestionar su estrategia de trading
- Puedes ajustar parámetros en tiempo real
- Analizas el rendimiento y sugieres mejoras
- Explicas tus decisiones de forma clara

## Herramientas Disponibles
- adjust_parameter: Modificar parámetros de la estrategia
- get_parameters: Ver parámetros actuales
- get_portfolio_status: Ver estado del portfolio
- enable_trading / disable_trading: Control de trading
- set_aggressive_mode: Cambiar modo de riesgo
- analyze_performance: Analizar rendimiento
- add_symbol / remove_symbol: Gestionar símbolos

## Parámetros que puedes ajustar
- rsi_period: Período del RSI (default: 14)
- rsi_oversold: Umbral de sobreventa (default: 30)
- rsi_overbought: Umbral de sobrecompra (default: 70)
- sma_fast: SMA rápida (default: 10)
- sma_slow: SMA lenta (default: 50)
- stop_loss_pct: Stop loss en % (default: 0.02 = 2%)
- take_profit_pct: Take profit en % (default: 0.05 = 5%)
- max_position_size: Tamaño máximo de posición (default: 0.1 = 10%)

## Reglas
1. Siempre explica por qué sugieres un cambio
2. Si el usuario pide algo arriesgado, advierte pero respeta su decisión
3. Usa los tools para ejecutar acciones, no solo describas
4. Mantén un tono profesional pero accesible
"""

def create_trading_agent() -> Agent:
    """Crea y retorna el agente de trading."""
    return Agent(
        name="TradingAssistant",
        model="claude-sonnet-4-20250514",  # o "gpt-4o"
        instructions=SYSTEM_PROMPT,
        tools=[
            adjust_parameter,
            get_parameters,
            get_portfolio_status,
            enable_trading,
            disable_trading,
            set_aggressive_mode,
            analyze_performance,
            add_symbol,
            remove_symbol,
        ],
        memory=True,  # Recuerda conversaciones
        show_tool_calls=True,
    )
```

---

## Componente 4: Bot de Telegram

```python
# interfaces/telegram_bot.py
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agent.trading_agent import create_trading_agent

class TradingTelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.agent = create_trading_agent()
        self.app = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("params", self.params))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.chat))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Trading Assistant activo!\n\n"
            "Comandos:\n"
            "/status - Ver estado del portfolio\n"
            "/params - Ver parámetros actuales\n\n"
            "O simplemente escríbeme lo que necesitas."
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        response = self.agent.run("Dame el estado actual del portfolio")
        await update.message.reply_text(response.content)

    async def params(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        response = self.agent.run("Muéstrame los parámetros actuales")
        await update.message.reply_text(response.content)

    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_message = update.message.text
        response = self.agent.run(user_message)
        await update.message.reply_text(response.content)

    def run(self):
        self.app.run_polling()
```

---

## Componente 5: Strategy Orchestrator (Multi-Estrategia)

El problema: cada estrategia de Lumibot normalmente corre en su propia terminal bloqueante. El `StrategyOrchestrator` resuelve esto permitiendo ejecutar múltiples estrategias concurrentemente y controladas por el agente.

```
┌─────────────────────────────────────────────────────────────┐
│                    Agno Agent                               │
│  "Inicia MeanReversion en AAPL"                             │
│  "Detén Momentum"                                           │
│  "Ajusta RSI de MeanReversion a 12"                         │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│               StrategyOrchestrator                          │
│  - start_strategy("MeanReversion", params)                  │
│  - stop_strategy("Momentum")                                │
│  - update_parameters("MeanReversion", {"rsi": 12})          │
│  - get_running_strategies() → ["MeanReversion", "Pairs"]    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  StrategyFactory                            │
│  - Registra estrategias disponibles                         │
│  - Crea instancias con configuración                        │
│  - Auto-descubre estrategias en /strategies                 │
└─────────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐    ┌──────────┐
    │ Strategy │   │ Strategy │    │ Strategy │
    │  Thread  │   │  Thread  │    │  Thread  │
    │MeanRev   │   │ Momentum │    │  Pairs   │
    └──────────┘   └──────────┘    └──────────┘
```

### Actualización de Estructura de Archivos

```
lumibot-dev/
├── packages/
│   └── core/
│       ├── strategy_factory.py    # Ya existe - registro de estrategias
│       └── strategy_orchestrator.py  # NUEVO - ejecución multi-estrategia
├── agent/
│   ├── __init__.py
│   ├── trading_agent.py
│   ├── tools.py                   # Actualizado con tools de orquestación
│   ├── memory.py
│   └── prompts.py
├── strategies/
│   ├── __init__.py
│   ├── adaptive_strategy.py
│   ├── mean_reversion.py
│   ├── momentum.py
│   └── pairs_trading.py
├── interfaces/
│   └── telegram_bot.py
├── config/
│   └── credentials.py
└── main.py
```

### StrategyOrchestrator Implementation

```python
# packages/core/strategy_orchestrator.py
import threading
from typing import Dict, Optional, List
from lumibot.traders import Trader
from lumibot.strategies import Strategy

from .strategy_factory import StrategyFactory


class StrategyOrchestrator:
    """
    Orquesta múltiples estrategias de Lumibot.
    Permite iniciar, detener y modificar estrategias en tiempo real.
    """

    def __init__(self, factory: StrategyFactory, broker):
        self.factory = factory
        self.broker = broker
        self.active_strategies: Dict[str, Strategy] = {}
        self.traders: Dict[str, Trader] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start_strategy(
        self,
        name: str,
        parameters: Optional[Dict] = None
    ) -> Dict:
        """
        Inicia una estrategia en su propio thread.

        Args:
            name: Nombre de la estrategia registrada en el factory
            parameters: Parámetros opcionales para override

        Returns:
            Dict con status y mensaje
        """
        with self._lock:
            if name in self.active_strategies:
                return {
                    "success": False,
                    "message": f"Estrategia '{name}' ya está corriendo"
                }

            try:
                # Crear estrategia via factory
                strategy = self.factory.create_strategy(
                    name=name,
                    broker=self.broker,
                    parameters=parameters
                )

                # Crear trader
                trader = Trader()
                trader.add_strategy(strategy)

                # Ejecutar en thread separado
                thread = threading.Thread(
                    target=self._run_trader,
                    args=(trader, name),
                    name=f"strategy-{name}",
                    daemon=True
                )
                thread.start()

                # Guardar referencias
                self.active_strategies[name] = strategy
                self.traders[name] = trader
                self.threads[name] = thread

                return {
                    "success": True,
                    "message": f"✅ Estrategia '{name}' iniciada",
                    "parameters": strategy.parameters
                }

            except Exception as e:
                return {
                    "success": False,
                    "message": f"Error iniciando '{name}': {str(e)}"
                }

    def _run_trader(self, trader: Trader, name: str):
        """Ejecuta el trader (bloqueante, corre en thread)."""
        try:
            trader.run_all()
        except Exception as e:
            print(f"[ERROR] Estrategia {name} terminó con error: {e}")
        finally:
            # Limpiar cuando termine
            with self._lock:
                self.active_strategies.pop(name, None)
                self.traders.pop(name, None)
                self.threads.pop(name, None)

    def stop_strategy(self, name: str) -> Dict:
        """
        Detiene una estrategia activa.

        Args:
            name: Nombre de la estrategia a detener

        Returns:
            Dict con status y mensaje
        """
        with self._lock:
            if name not in self.active_strategies:
                return {
                    "success": False,
                    "message": f"Estrategia '{name}' no está corriendo"
                }

            try:
                strategy = self.active_strategies[name]
                strategy.stop()

                # Esperar que el thread termine
                thread = self.threads.get(name)
                if thread and thread.is_alive():
                    thread.join(timeout=5.0)

                # Limpiar
                self.active_strategies.pop(name, None)
                self.traders.pop(name, None)
                self.threads.pop(name, None)

                return {
                    "success": True,
                    "message": f"⏹️ Estrategia '{name}' detenida"
                }

            except Exception as e:
                return {
                    "success": False,
                    "message": f"Error deteniendo '{name}': {str(e)}"
                }

    def update_parameters(self, name: str, params: Dict) -> Dict:
        """
        Actualiza parámetros de una estrategia activa.

        Args:
            name: Nombre de la estrategia
            params: Diccionario de parámetros a actualizar

        Returns:
            Dict con status y mensaje
        """
        with self._lock:
            if name not in self.active_strategies:
                return {
                    "success": False,
                    "message": f"Estrategia '{name}' no está corriendo"
                }

            try:
                strategy = self.active_strategies[name]
                old_params = {k: strategy.parameters.get(k) for k in params.keys()}

                # Lumibot's native method
                strategy.update_parameters(params)

                return {
                    "success": True,
                    "message": f"✅ Parámetros actualizados en '{name}'",
                    "changes": {k: f"{old_params[k]} → {v}" for k, v in params.items()}
                }

            except Exception as e:
                return {
                    "success": False,
                    "message": f"Error actualizando '{name}': {str(e)}"
                }

    def get_running_strategies(self) -> List[str]:
        """Retorna lista de estrategias activas."""
        with self._lock:
            return list(self.active_strategies.keys())

    def get_available_strategies(self) -> List[str]:
        """Retorna lista de estrategias disponibles en el factory."""
        return list(self.factory.get_available_strategies().keys())

    def get_strategy_status(self, name: str) -> Optional[Dict]:
        """
        Obtiene el status de una estrategia específica.

        Args:
            name: Nombre de la estrategia

        Returns:
            Dict con status o None si no existe
        """
        with self._lock:
            if name not in self.active_strategies:
                return None

            strategy = self.active_strategies[name]
            return {
                "name": name,
                "running": True,
                "portfolio_value": strategy.portfolio_value,
                "cash": strategy.cash,
                "positions": [str(p) for p in strategy.get_positions()],
                "parameters": strategy.parameters.copy(),
            }

    def get_all_status(self) -> Dict:
        """Obtiene status de todas las estrategias activas."""
        with self._lock:
            return {
                name: self.get_strategy_status(name)
                for name in self.active_strategies.keys()
            }

    def stop_all(self):
        """Detiene todas las estrategias activas."""
        for name in list(self.active_strategies.keys()):
            self.stop_strategy(name)
```

### Tools Adicionales para el Agente (Orquestación)

```python
# agent/tools.py - Agregar estos tools adicionales

# Referencia global al orchestrator (se setea en main.py)
orchestrator = None

def set_orchestrator(o):
    global orchestrator
    orchestrator = o

@tool
def start_strategy(strategy_name: str, parameters: dict = None) -> str:
    """
    Inicia una estrategia de trading.

    Args:
        strategy_name: Nombre de la estrategia (ej: "MeanReversion", "Momentum")
        parameters: Parámetros opcionales para la estrategia
    """
    if orchestrator is None:
        return "Error: Orchestrator no inicializado"

    result = orchestrator.start_strategy(strategy_name, parameters)
    return result["message"]

@tool
def stop_strategy(strategy_name: str) -> str:
    """
    Detiene una estrategia activa.

    Args:
        strategy_name: Nombre de la estrategia a detener
    """
    if orchestrator is None:
        return "Error: Orchestrator no inicializado"

    result = orchestrator.stop_strategy(strategy_name)
    return result["message"]

@tool
def list_running_strategies() -> str:
    """Lista todas las estrategias actualmente corriendo."""
    if orchestrator is None:
        return "Error: Orchestrator no inicializado"

    running = orchestrator.get_running_strategies()
    if not running:
        return "No hay estrategias corriendo actualmente"

    return f"📊 Estrategias activas: {', '.join(running)}"

@tool
def list_available_strategies() -> str:
    """Lista todas las estrategias disponibles para ejecutar."""
    if orchestrator is None:
        return "Error: Orchestrator no inicializado"

    available = orchestrator.get_available_strategies()
    return f"📋 Estrategias disponibles: {', '.join(available)}"

@tool
def get_strategy_status(strategy_name: str) -> str:
    """
    Obtiene el estado detallado de una estrategia específica.

    Args:
        strategy_name: Nombre de la estrategia
    """
    if orchestrator is None:
        return "Error: Orchestrator no inicializado"

    status = orchestrator.get_strategy_status(strategy_name)
    if status is None:
        return f"Estrategia '{strategy_name}' no está corriendo"

    return f"""
📈 {strategy_name}
Portfolio: ${status['portfolio_value']:,.2f}
Cash: ${status['cash']:,.2f}
Posiciones: {len(status['positions'])}
Parámetros: {status['parameters']}
"""

@tool
def update_strategy_parameters(strategy_name: str, param_name: str, new_value: float) -> str:
    """
    Actualiza un parámetro de una estrategia activa.

    Args:
        strategy_name: Nombre de la estrategia
        param_name: Nombre del parámetro
        new_value: Nuevo valor
    """
    if orchestrator is None:
        return "Error: Orchestrator no inicializado"

    result = orchestrator.update_parameters(strategy_name, {param_name: new_value})
    return result["message"]
```

---

## Componente 6: Main Entry Point

```python
# main.py
import os
import threading
from lumibot.brokers import Alpaca

from packages.core.strategy_factory import StrategyFactory
from packages.core.strategy_orchestrator import StrategyOrchestrator
from strategies.adaptive_strategy import AdaptiveStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from agent.tools import set_orchestrator
from interfaces.telegram_bot import TradingTelegramBot

# Configuración
ALPACA_CONFIG = {
    "API_KEY": os.environ.get("ALPACA_API_KEY"),
    "API_SECRET": os.environ.get("ALPACA_API_SECRET"),
    "PAPER": True,  # Paper trading
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


def setup_trading_system():
    """Configura el sistema de trading completo."""

    # 1. Crear broker
    broker = Alpaca(ALPACA_CONFIG)

    # 2. Crear factory y registrar estrategias
    factory = StrategyFactory()

    factory.register_strategy(
        name="MeanReversion",
        strategy_class=MeanReversionStrategy,
        default_config={
            "rsi_period": 14,
            "rsi_oversold": 30,
            "symbols": ["SPY", "QQQ"]
        }
    )

    factory.register_strategy(
        name="Momentum",
        strategy_class=MomentumStrategy,
        default_config={
            "lookback_period": 20,
            "symbols": ["AAPL", "MSFT", "GOOGL"]
        }
    )

    factory.register_strategy(
        name="Adaptive",
        strategy_class=AdaptiveStrategy,
        default_config={
            "rsi_period": 14,
            "sma_fast": 10,
            "sma_slow": 50,
        }
    )

    # O auto-descubrir desde carpeta
    # factory.auto_discover_strategies("strategies/")

    # 3. Crear orchestrator
    orchestrator = StrategyOrchestrator(factory=factory, broker=broker)

    # 4. Hacer orchestrator accesible al agente
    set_orchestrator(orchestrator)

    return orchestrator


def run_telegram_bot():
    """Ejecuta el bot de Telegram."""
    bot = TradingTelegramBot(TELEGRAM_TOKEN)
    bot.run()


if __name__ == "__main__":
    # Configurar sistema
    orchestrator = setup_trading_system()

    # Opcionalmente iniciar estrategia por defecto
    # orchestrator.start_strategy("MeanReversion")

    print("🚀 Sistema de Trading iniciado")
    print(f"📋 Estrategias disponibles: {orchestrator.get_available_strategies()}")
    print("💬 Bot de Telegram activo")

    # Ejecutar bot de Telegram en el main thread
    run_telegram_bot()
```

---

## Flujos de Conversación Ejemplo

### Flujo 1: Ajuste de Parámetros

```
Usuario: "El mercado está muy volátil, sé más conservador"

Agente: Entendido. Para un mercado volátil, voy a ajustar los parámetros
para ser más conservador:

[Llama set_aggressive_mode(False)]
[Llama adjust_parameter("stop_loss_pct", 0.015)]

✅ Cambios aplicados:
- Modo conservador activado
- Stop loss reducido de 2% a 1.5%
- Tamaño de posición: 10% del portfolio

Esto debería proteger mejor el capital en condiciones volátiles.
```

### Flujo 2: Consulta de Estado

```
Usuario: "¿Cómo va el portfolio?"

Agente: [Llama get_portfolio_status()]

📊 Estado actual:

Portfolio: $10,234.56
Cash disponible: $5,234.56
Posiciones abiertas: 2
- SPY: 10 acciones (+2.3%)
- QQQ: 5 acciones (-0.5%)

El portfolio está +1.2% desde el inicio.
```

### Flujo 3: Experimentación

```
Usuario: "Quiero probar con RSI más rápido, como 10"

Agente: [Llama adjust_parameter("rsi_period", 10)]

✅ RSI período cambiado: 14 → 10

Un RSI más corto reaccionará más rápido a cambios de precio,
pero también puede generar más señales falsas.
¿Quieres que también ajuste los umbrales de sobreventa/sobrecompra?
```

### Flujo 4: Gestión Multi-Estrategia

```
Usuario: "¿Qué estrategias tengo disponibles?"

Agente: [Llama list_available_strategies()]

📋 Estrategias disponibles:
- MeanReversion (reversión a la media con RSI)
- Momentum (seguimiento de tendencia)
- Adaptive (parámetros dinámicos)

¿Cuál te gustaría iniciar?
```

```
Usuario: "Inicia MeanReversion en QQQ con RSI de 12"

Agente: [Llama start_strategy("MeanReversion", {"rsi_period": 12, "symbols": ["QQQ"]})]

✅ Estrategia 'MeanReversion' iniciada
Parámetros: RSI período 12, símbolo QQQ

La estrategia está corriendo ahora. Te notificaré de cualquier trade.
```

```
Usuario: "Ahora inicia también Momentum en tech stocks"

Agente: [Llama start_strategy("Momentum", {"symbols": ["AAPL", "MSFT", "GOOGL", "NVDA"]})]

✅ Estrategia 'Momentum' iniciada

📊 Estrategias activas:
1. MeanReversion → QQQ (RSI 12)
2. Momentum → AAPL, MSFT, GOOGL, NVDA

Ambas estrategias están corriendo en paralelo.
```

```
Usuario: "Detén Momentum, el mercado está muy volátil"

Agente: [Llama stop_strategy("Momentum")]

⏹️ Estrategia 'Momentum' detenida

Solo MeanReversion sigue activa. ¿Quieres que ajuste sus
parámetros para ser más conservadora en este mercado volátil?
```

```
Usuario: "Dame el status de todas las estrategias"

Agente: [Llama list_running_strategies()]
        [Llama get_strategy_status("MeanReversion")]

📈 Status del Sistema:

MeanReversion (ACTIVA)
├── Portfolio: $10,234.56
├── Cash: $5,234.56
├── Posiciones: 1 (QQQ: 10 acciones)
└── Parámetros: RSI 12, Stop 2%

¿Necesitas ajustar algo?
```

---

## Sistema de Reflexión y Aprendizaje

```python
# agent/reflection.py
from agno import Agent
from datetime import datetime, timedelta

class TradingReflector:
    """Sistema de reflexión que analiza decisiones pasadas."""

    def __init__(self, agent: Agent, strategy):
        self.agent = agent
        self.strategy = strategy
        self.decisions_log = []

    def log_decision(self, decision: dict):
        """Guarda una decisión para análisis posterior."""
        self.decisions_log.append({
            "timestamp": datetime.now(),
            "parameters": self.strategy.get_parameters().copy(),
            "portfolio_value": self.strategy.portfolio_value,
            "decision": decision,
        })

    def reflect(self) -> str:
        """
        Analiza las últimas decisiones y sugiere mejoras.
        Se ejecuta periódicamente (ej: cada día).
        """
        if len(self.decisions_log) < 5:
            return "Insuficientes datos para reflexión"

        # Calcular métricas
        initial_value = self.decisions_log[0]["portfolio_value"]
        current_value = self.strategy.portfolio_value
        pnl_pct = (current_value - initial_value) / initial_value * 100

        prompt = f"""
        Analiza mi rendimiento reciente:

        - Valor inicial: ${initial_value:,.2f}
        - Valor actual: ${current_value:,.2f}
        - P&L: {pnl_pct:+.2f}%
        - Número de decisiones: {len(self.decisions_log)}

        Parámetros usados mayormente:
        {self.decisions_log[-1]["parameters"]}

        ¿Qué ajustes sugieres para mejorar?
        """

        response = self.agent.run(prompt)
        return response.content
```

---

## Variables de Entorno Requeridas

```bash
# .env
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ANTHROPIC_API_KEY=your_claude_key  # o OPENAI_API_KEY
```

---

## Próximos Pasos de Implementación

1. [ ] Crear estructura de carpetas
2. [ ] Implementar `StrategyFactory` (ya existe en packages/core/)
3. [ ] Implementar `StrategyOrchestrator` para multi-estrategia
4. [ ] Implementar `AdaptiveStrategy` con parámetros dinámicos
5. [ ] Implementar `MeanReversionStrategy` y `MomentumStrategy`
6. [ ] Implementar tools de Agno (incluyendo orquestación)
7. [ ] Crear agente con system prompt actualizado
8. [ ] Implementar bot de Telegram
9. [ ] Integrar todo en main.py
10. [ ] Probar en paper trading
11. [ ] Agregar sistema de reflexión
12. [ ] Agregar persistencia de resultados diarios

---

## Verificación

- [ ] El agente puede modificar parámetros via Telegram
- [ ] Los cambios se reflejan inmediatamente en la estrategia
- [ ] El portfolio status se muestra correctamente
- [ ] La estrategia ejecuta trades con los parámetros actuales
- [ ] La memoria del agente persiste entre conversaciones
