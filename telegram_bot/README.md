# Telegram Trading Bot 🤖

Bot de Telegram para ejecutar estrategias de paper trading usando el Core de Lumibot. Permite seleccionar estrategias, configurar parámetros, y monitorear el trading en tiempo real desde Telegram.

## 🚀 Características

- **Selección Interactiva de Estrategias**: Menús con todas las estrategias disponibles del Core
- **Configuración de Parámetros**: Duración personalizable y presupuesto de trading
- **Monitoreo en Tiempo Real**: Actualizaciones automáticas del estado de trading
- **Control Completo**: Iniciar, detener, y monitorear estrategias desde chat
- **Solo Paper Trading**: Seguro, sin dinero real

## 📋 Comandos Disponibles

### Comandos Principales
- `/start` - Inicializar el bot y ver comandos disponibles
- `/trade` - Iniciar nueva estrategia de trading (flujo interactivo)
- `/status` - Ver estado actual de tu estrategia 
- `/stop` - Detener estrategia activa
- `/strategies` - Listar todas las estrategias disponibles
- `/help` - Mostrar ayuda detallada

### Flujo de Trading
1. **Selección**: Elegir estrategia del menú
2. **Configuración**: Parámetros (usar default o personalizar)
3. **Duración**: 1h, 6h, 1d, 1w, o continuo
4. **Presupuesto**: $1K, $5K, $10K, $25K, $100K
5. **Confirmación**: Revisar y iniciar trading

## 🛠️ Instalación

### 1. Crear Bot de Telegram

1. Contactar [@BotFather](https://t.me/BotFather) en Telegram
2. Usar comando `/newbot`
3. Seguir instrucciones y obtener token
4. Guardar el token para configuración

### 2. Instalar Dependencias

```bash
cd packages/telegram
pip install -r requirements.txt
```

### 3. Configuración

```bash
# Copiar archivo de ejemplo
cp .env.example .env

# Editar con tus credenciales
nano .env
```

Configurar en `.env`:
```env
# Token de tu bot de Telegram
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyZ

# Credenciales de Alpaca (paper trading)
ALPACA_API_KEY=tu-api-key
ALPACA_API_SECRET=tu-secret-key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

### 4. Ejecutar Bot

```bash
python telegram_bot.py
```

## 🎮 Uso del Bot

### Iniciar Trading
1. Escribir `/trade` en el chat
2. Seleccionar estrategia del menú
3. Configurar parámetros (o usar defaults)
4. Elegir duración del trading
5. Seleccionar presupuesto
6. Confirmar para iniciar

### Ejemplo de Flujo
```
👤 Usuario: /trade

🤖 Bot: 📊 Select a Strategy:
       [CarlosMeanReversionStrategy]
       [CryptoLeadLagStrategy]
       [MartinGalaStrategy]
       [Cancel]

👤 Usuario: [selecciona CarlosMeanReversionStrategy]

🤖 Bot: ✅ Strategy selected: CarlosMeanReversionStrategy
        Default parameters: { "symbol": "QQQ", ... }
        [Use Default] [Customize] [Cancel]

👤 Usuario: [Use Default]

🤖 Bot: ⏱️ Select Trading Duration:
        [1 Hour] [6 Hours] [1 Day] [1 Week] [Continuous] [Cancel]

👤 Usuario: [1 Day]

🤖 Bot: 💰 Select Trading Budget:
        [$1,000] [$5,000] [$10,000] [$25,000] [$100,000] [Cancel]

👤 Usuario: [$10,000]

🤖 Bot: 📋 Trading Configuration Summary:
        Strategy: CarlosMeanReversionStrategy
        Duration: 1 day
        Budget: $10,000
        [✅ Start Trading] [❌ Cancel]

👤 Usuario: [✅ Start Trading]

🤖 Bot: ✅ Trading Started Successfully!
        Strategy: CarlosMeanReversionStrategy
        Budget: $10,000
        Duration: 1 day
        Use /status to check progress
```

### Monitoreo
```
👤 Usuario: /status

🤖 Bot: 📊 Strategy Status
        Strategy: CarlosMeanReversionStrategy
        Status: 🟢 Running
        Runtime: 0d 2h 15m
        Budget: $10,000
        Duration: 1 day
```

## 🏗️ Arquitectura

### Componentes
```
TelegramBot
├── telegram_bot.py          # Bot principal con comandos
├── strategy_integration.py  # Integración con Core
├── requirements.txt         # Dependencias
└── README.md               # Esta documentación
```

### Flujo de Datos
```
Telegram User → Bot Commands → Strategy Runner → Core → Lumibot
                     ↑                                      ↓
              Status Updates ←─ Background Monitor ←─ Strategy
```

### Estados de Conversación
- `STRATEGY_SELECT`: Selección de estrategia
- `PARAMETER_CONFIG`: Configuración de parámetros  
- `TIME_CONFIG`: Configuración de duración
- `BUDGET_CONFIG`: Configuración de presupuesto
- `CONFIRM_START`: Confirmación final

## 🔧 Integración con Core

El bot usa el módulo Core para:

```python
from core import TradingCore

# Inicializar
core = TradingCore(broker_config=ALPACA_TEST_CONFIG)

# Listar estrategias
strategies = core.list_strategies()

# Ejecutar en paper trading
strategy = core.paper_trade(strategy="MeanReversion", params={...})
```

## 📊 Estrategias Soportadas

El bot detecta automáticamente todas las estrategias en:
- `packages/core/strategies/`

Estrategias incluidas:
- **CarlosMeanReversionStrategy**: Mean reversion con take profits
- **CryptoLeadLagStrategy**: Trading ETH/SOL basado en BTC
- **MartinGalaStrategy**: Estrategia de Martin
- **VolumeMultiplayerStrategy**: Trading basado en volumen

## 🔒 Seguridad

- **Solo Paper Trading**: Sin dinero real
- **Credenciales Seguras**: Variables de entorno
- **Validación**: Parámetros validados antes de ejecutar
- **Control de Usuario**: Un usuario = una estrategia activa

## 🚨 Limitaciones Actuales

- Un usuario puede ejecutar solo una estrategia a la vez
- Parámetros customizados pendientes (próxima versión)
- Solo funciona con broker Alpaca
- Monitoreo básico (mejoras en desarrollo)

## 📱 Comandos Avanzados

### Información
- `/strategies` - Ver todas las estrategias con descripción
- `/status` - Estado detallado con runtime y configuración

### Control
- `/stop` - Detener estrategia inmediatamente
- Duración automática - El bot para la estrategia automáticamente

## 🔮 Próximas Funcionalidades

- [ ] Parámetros custom por estrategia
- [ ] Portfolio en tiempo real
- [ ] Múltiples estrategias simultáneas
- [ ] Alertas personalizadas
- [ ] Reportes de P&L detallados
- [ ] Integración con más brokers
- [ ] Backtesting desde Telegram

## 🐛 Troubleshooting

### Bot no responde
- Verificar `TELEGRAM_BOT_TOKEN` en `.env`
- Comprobar conexión internet
- Revisar logs en consola

### Error al iniciar estrategia
- Verificar credenciales Alpaca en `.env`
- Comprobar que las estrategias estén en el directorio correcto
- Revisar logs para errores específicos

### Estrategias no aparecen
- Verificar path a `packages/core/strategies/`
- Comprobar que las estrategias hereden de `lumibot.Strategy`
- Reiniciar el bot

## 📝 Logs

El bot mantiene logs detallados:
```
2024-01-01 10:30:00 - INFO - Strategy CarlosMeanReversion started for user 12345
2024-01-01 10:35:00 - INFO - Status update sent to user 12345
2024-01-01 11:30:00 - INFO - Strategy stopped for user 12345
```

---

**¡El bot está listo para hacer paper trading desde Telegram!** 🚀

Simplemente configura tu token, inicia el bot, y comienza a tradear con `/trade`.