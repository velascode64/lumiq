Estrategia Similar y Crítica a Tu Enfoque
Tu estrategia es esencialmente una variante de momentum trading con trailing stop o pullback entry/exit, donde vendes en retrocesos menores (2% caída) después de picos fuertes (máximo 52 semanas o >5% diario), y recompras en estabilización post-caída (precio "estático" varios días). Esto se asemeja a:

Trailing Stop Loss with Re-entry on Consolidation: Vende en pullbacks para capturar gains, espera consolidación (precio sideways) para re-entrar, asumiendo continuación de trend o reversión. Similar a estrategias de traders como Mark Minervini (momentum con pullbacks) o Turtle Trading (breakouts con re-entries post-retracements). Críticamente, esto no es único—es común en momentum, pero riesgoso: En mercados bull (e.g., 2025 AI hype en TSLA/QQQ), pullbacks de 2% son frecuentes, llevando a whipsaws (ventas prematuras) y missed gains si trends continúan. La parte de "estático varios días" es subjetiva (¿qué es "estático"—<1% variación diaria?), lo que hace difícil automatizar sin overfitting.

Otras semejanzas:

Pullback Trading: Compra en dips post-uptrends, vende en peaks con stops.
Mean Reversion on Highs: Vende en overextension, compra en stabilización.
Crítica: Funciona en rangos, pero falla en trends fuertes (e.g., NVDA 2025 surges ignoran pullbacks). Si manualmente ganas, automatizar podría rigidizar y empeorar—mejor quédate manual si no cuantificas "estático".


Original description
Mi estrategia funciona más que nada para salidas, es decir si subio las 52 semaans o tuvo un % de más del 5 en un día debería estar pendiente si baja un 2% para ejcutar la salida, así en caso de seguir subiendo no vende sino hasta que se corrige.
Una vez vendio por este minimo de 2% espera para ver cuanto baja si varios días se mantiene estatico el precio despues de la caida es momento de comprar.


## 📋 Descripción

Estrategia de trading que combina **Mean Reversion** con **Momentum Trading**, diseñada para capturar movimientos de precio en acciones volátiles como TSLA, GOOGL, y QQQ.

### 🎯 Características Principales

- **Salidas Inteligentes**: Vende cuando hay ganancia diaria >5% o el precio alcanza máximos de 52 semanas
- **Re-entradas Controladas**: Compra cuando el precio se mantiene "estático" por varios días después de una venta
- **Trailing Stop**: Protección de ganancias con trailing stop del 2%
- **Integración yfinance**: Datos históricos reales para máximos de 52 semanas
- **Paper Trading**: Compatible con Alpaca API para trading en vivo
- **Alerts en Tiempo Real**: Notificaciones impresas para todas las operaciones

## 🔧 Parámetros Configurables

| Parámetro | Defecto | Descripción |
|-----------|---------|-------------|
| `daily_gain_threshold` | 0.05 (5%) | Umbral de ganancia diaria para activar lógica de salida |
| `pullback_pct` | 0.02 (2%) | Pullback desde high reciente para vender |
| `static_days` | 3 | Días para considerar precio "estático" |
| `static_sd` | 0.01 (1%) | Desviación estándar para considerar precio "estático" |
| `trailing_stop_pct` | 0.02 (2%) | Porcentaje del trailing stop |
| `paper_trade_qty` | 10 | Cantidad fija para paper trading |