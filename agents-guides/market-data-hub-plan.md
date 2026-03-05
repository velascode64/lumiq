Plan: Centralizar Market Data Stream (MarketDataHub / StreamManager)
Estado actual
En este chat se logró una estrategia con buen resultado en backtesting:

lumiq/lumibot/strategies/backtesting/eth_aggressive_momentum_ytd_backtest.py
Resultado validado en un período: ~54% CAGR
También se creó su versión live:

lumiq/lumibot/strategies/live/eth_aggressive_momentum_live.py
Problema a resolver
Hoy la arquitectura abre conexiones de mercado duplicadas:

El sistema de alertas abre sus propios websockets (StockDataStream / CryptoDataStream)
Cada estrategia live corre en su propio proceso y puede abrir su propio stream vía Lumibot/Alpaca
Consecuencia:

connection limit exceeded
HTTP 429
reconexión agresiva
inestabilidad al correr alertas + estrategias live al mismo tiempo
Objetivo
Crear un MarketDataHub (o StreamManager) central que:

sea el único dueño del stream de Alpaca market data
comparta ese feed con múltiples consumidores internos
elimine conexiones duplicadas
permita escalar estrategias live, alertas y agentes de análisis técnico sin reventar el límite de conexiones
Principio de diseño
Lumibot debe seguir siendo el motor de:

ejecución de órdenes
gestión de posiciones
ciclo de estrategia
Pero el market data stream debe ser propiedad del core de Lumiq, no de cada estrategia de forma aislada.

Consumidores previstos
El MarketDataHub debe poder servir a:

Alertas
evaluar reglas de precio / porcentaje / technicals
eliminar la dependencia de streams propios en AlertStreamManager
Agente de technicals
consultar último precio
leer micro-ventanas recientes
calcular señales sin alucinar
Estrategias live
idealmente consumir el feed central o un cache interno derivado
evitar que cada subprocess abra su propio websocket
Dashboard / observabilidad futura
snapshots de precio
estado de subscripciones
health del stream
Fase 1 (mínimo viable, sin romper demasiado)
Objetivo: quitar duplicación inmediata entre alertas y servicios de análisis.

Entregables
Crear módulo nuevo:
lumiq/platform/market_data/
Crear clase:
MarketDataHub
Responsabilidades:
abrir streams de Alpaca de forma centralizada
suscribir dinámicamente símbolos
mantener last_price por símbolo
registrar callbacks por consumidor
exponer API interna simple:
subscribe(symbol, consumer_id, callback)
unsubscribe(symbol, consumer_id)
get_last_price(symbol)
Integración inicial:
mover alertas para que consuman MarketDataHub
el futuro agente de technicals también consumirá MarketDataHub
Restricción
En esta fase, las estrategias live pueden seguir con su stream propio si todavía no migramos su data path.

Esto no elimina todo el problema, pero reduce duplicación parcial.

Fase 2 (arquitectura correcta)
Objetivo: hacer que estrategias live también dependan del feed central.

Cambios
Las estrategias live no deben depender del stream autónomo de Lumibot para market data.

El core debe proveer:

cache de precios
pequeñas ventanas recientes (ticks / barras agregadas)
pub/sub local en memoria
Las estrategias deben leer desde:
snapshots internos del MarketDataHub
o una capa adaptadora que transforme el feed del hub en insumo utilizable por la estrategia
Resultado esperado
una sola fuente de market data
menos conexiones
comportamiento consistente entre alertas, technicals y estrategias
Fase 3 (robustez)
Requisitos
Reconexión con backoff real
evitar loops de reconexión inmediata
respetar límites de Alpaca
Suscripciones por demanda
no abrir StockDataStream si no hay símbolos de stocks
no abrir CryptoDataStream si no hay símbolos crypto
Métricas / health
número de símbolos activos
consumidores registrados
última conexión exitosa
último error
estado por feed (stock, crypto)
Logging estructurado
cuándo se abrió una conexión
quién pidió una suscripción
cuándo se reutilizó una suscripción ya existente
Diseño técnico propuesto
Módulos
lumiq/platform/market_data/hub.py
lumiq/platform/market_data/models.py
lumiq/platform/market_data/subscriptions.py
APIs internas
register_consumer(consumer_id, symbols, callback, asset_type)
unregister_consumer(consumer_id)
get_last_trade(symbol)
get_last_price(symbol)
get_recent_window(symbol, n=100)
Almacenamiento en memoria
symbol -> last trade
symbol -> ring buffer de precios/trades
symbol -> set(consumers)
Integración prevista con componentes actuales
Reemplazar / adaptar
lumiq/platform/alerts/streaming/alpaca_stream.py
dejar de abrir sus propios streams
convertirlo en evaluador de reglas consumiendo eventos del hub
lumiq/platform/runtime/app_runtime.py
crear una sola instancia de MarketDataHub
compartirla entre alertas, technical agent y otros servicios
Estrategias live
revisar cómo desacoplar data feed del subprocess actual
probablemente requiera refactor adicional en el runner
Riesgos
Lumibot no está diseñado para compartir fácilmente el market stream entre múltiples procesos.

Si se mantiene el modelo actual process-based, compartir feed con estrategias live requerirá:

IPC
cache compartido
o mover parte del ciclo de datos fuera del subprocess
Si se hace mal, puede introducir:
race conditions
inconsistencias entre precio de estrategia y precio de alerta
latencia innecesaria
Decisión de implementación
No implementar todavía.

Primero:

Consolidar las estrategias que ya funcionaron
Mantener como referencia la estrategia de ~54% CAGR
Luego abordar esta re-arquitectura del stream con calma
Criterio de éxito futuro
El plan estará bien implementado cuando:

correr alertas + múltiples estrategias live no abra conexiones duplicadas innecesarias
no aparezcan errores connection limit exceeded
alertas y agente de technicals lean del mismo feed central
el sistema pueda escalar sin depender de múltiples websockets por proceso