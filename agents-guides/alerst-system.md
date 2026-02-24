# ✅ 1️⃣ Alertas por % cambio (2% / 5%)

### 🔹 Funciones reales que usarías

**Portfolio / posiciones:**

* `TradingClient.get_all_positions()`
* `TradingClient.get_account()`

**Precio actual:**

* `StockHistoricalDataClient.get_stock_latest_trade()`
* o `StockHistoricalDataClient.get_stock_latest_quote()`

**Cambio diario:**

* `StockHistoricalDataClient.get_stock_bars()` (TimeFrame.Day para obtener close previo)

---

### 🔹 Lógica conceptual

1. Obtener posiciones abiertas con:

   * `get_all_positions()`
     → ya devuelve:
   * avg_entry_price
   * current_price
   * unrealized_plpc (ya viene calculado)

2. Para cambio diario:

   * Pedir barra diaria más reciente con `get_stock_bars()`
   * Comparar con barra anterior

3. Si:

   * `unrealized_plpc >= 0.05`
   * o daily change >= 0.02

→ Enviar alerta Telegram.

No necesitas LLM.

---

# ✅ 2️⃣ Nuevos máximos / mínimos históricos

### 🔹 Función oficial

* `StockHistoricalDataClient.get_stock_bars()`

Con:

* `TimeFrame.Day`
* rango de 252 días (aprox 1 año)

---

### 🔹 Lógica

1. Pedir 1 año de barras.

2. Identificar:

   * `max(high)`
   * `min(low)`

3. Comparar contra:

   * `get_stock_latest_trade()` → precio actual

Si precio ≥ máximo → nuevo high
Si precio ≤ mínimo → nuevo low

Todo con funciones oficiales.

---

# ✅ 3️⃣ Sobrecompra / Sobreventa

Alpaca no calcula RSI.
Solo entrega datos.

### 🔹 Función oficial

* `get_stock_bars()` (Daily o Hourly)

Luego tú calculas RSI con pandas/ta-lib.

No hay función RSI dentro de Alpaca.

---

# ✅ 4️⃣ Empresa buena financieramente pero castigada

Aquí Alpaca **NO provee fundamentales**.

Según documentación oficial:

Alpaca ofrece:

* Market data
* Trading
* Account
* Orders
* Positions
* Assets

No ofrece:

* Balance sheet
* ROE
* PE
* Cash flow

Para fundamentales necesitas:

* FinancialModelingPrep
* Polygon (si tienes plan con fundamentals)
* O proveedor externo

---

# 📊 Resumen exacto de qué usarías de Alpaca

| Necesidad                | Función Oficial Alpaca              |
| ------------------------ | ----------------------------------- |
| Obtener posiciones       | `TradingClient.get_all_positions()` |
| Obtener cuenta           | `TradingClient.get_account()`       |
| Precio actual            | `get_stock_latest_trade()`          |
| Precio histórico         | `get_stock_bars()`                  |
| Cambio diario            | `get_stock_bars()`                  |
| Saber si mercado abierto | `TradingClient.get_clock()`         |
| Streaming en tiempo real | `StockDataStream`                   |

---

# 🎯 Arquitectura correcta sin inventos

Daily job:

1. `get_all_positions()`
2. Para cada símbolo:

   * `get_stock_latest_trade()`
   * `get_stock_bars()` (1Y y 5D)
3. Calcular:

   * % diario
   * % desde compra
   * nuevos highs/lows
   * RSI
4. Enviar resumen
