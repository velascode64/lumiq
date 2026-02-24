# Descripción del Proyecto Trading Masters

## Resumen del Proyecto

El proyecto "Trading Masters" tiene como objetivo desarrollar un sistema de trading automatizado y robusto que utilice estrategias cuantitativas para aprovechar oportunidades en el mercado en diversas clases de activos, incluyendo acciones, ETFs, opciones y potencialmente criptoactivos. El propósito principal es generar retornos consistentes mediante enfoques diversificados y con una gestión de riesgos sólida, combinando reversión a la media, momentum, técnicas de promediado de costos y estrategias basadas en opciones. El sistema se implementará utilizando el framework Lumibot (disponible en https://github.com/Lumiwealth/lumibot), una biblioteca de Python diseñada para backtesting y trading algorítmico en vivo.

Lumibot será el núcleo para el desarrollo de estrategias, permitiendo una integración fluida con brokers como Interactive Brokers o Webull para obtener datos en tiempo real, ejecutar órdenes y gestionar carteras. El proyecto prioriza la escalabilidad, con funcionalidades para backtesting con datos históricos, optimización de parámetros y despliegue en entornos de trading en vivo. La gestión de riesgos será integral, incluyendo dimensionamiento de posiciones, stop-loss y diversificación entre activos para mitigar drawdowns.

Objetivos clave:
- **Rentabilidad y Control de Riesgos**: Diseñar estrategias con expectativa positiva mientras se limita la exposición mediante diversificación y cobertura.
- **Automatización**: Habilitar ejecución completamente automatizada, incluyendo monitoreo en tiempo real, generación de señales y colocación de órdenes a través de APIs de brokers.
- **Backtesting y Optimización**: Utilizar las herramientas de Lumibot para simular estrategias con datos históricos, ajustar hiperparámetros y evaluar métricas de rendimiento como el ratio Sharpe, drawdown máximo y tasa de aciertos.
- **Integración de Sentimiento del Mercado**: Incorporar señales externas de redes sociales (por ejemplo, análisis de sentimiento en X/Twitter) para validar o ajustar decisiones de entrada/salida, enfocándose en cuentas con más de 10,000 seguidores para identificar tendencias relevantes.
- **Despliegue**: Ejecutar estrategias en una infraestructura basada en la nube para operación 24/7, con monitoreo de rendimiento y alertas para anomalías.

El proyecto permitirá ejecutar múltiples estrategias en paralelo dentro de un solo bot o como componentes modulares, con asignación a nivel de cartera (por ejemplo, 30% a reversión a la media, 40% a promediado de costos, 30% a opciones).

## Descripción de las Estrategias

A continuación, se detalla cada estrategia a implementar. Cada una aprovechará las funcionalidades de Lumibot para manejar datos (por ejemplo, obtener datos OHLCV), generar señales y ejecutar operaciones. Las estrategias serán sometidas a backtesting con datos históricos de fuentes como Yahoo Finance o APIs de brokers, optimizadas mediante técnicas como búsqueda en cuadrícula o algoritmos genéticos, y desplegadas con ajustes en tiempo real.

### 1. Estrategia de Reversion a la Media con Momentum

Esta estrategia combina elementos de reversión a la media (asumiendo que los precios regresan a sus promedios históricos) con momentum (aprovechando tendencias a corto plazo) para identificar puntos de entrada y salida en mercados volátiles. Se enfoca en activos como acciones o ETFs que muestren desviaciones temporales de su media, pero con momentum en la dirección de la reversión.

**Qué Queremos Lograr**:
- Generar ganancias comprando activos infravalorados (por debajo de su media) con momentum alcista y vendiendo activos sobrevalorados (por encima de su media) con momentum bajista.
- Reducir señales falsas filtrando por momentum, evitando operaciones en mercados laterales o de baja volatilidad.
- Alcanzar una alta tasa de aciertos (objetivo: 60-70%) con riesgo controlado, apuntando a un retorno anual del 15-25% según las condiciones del mercado.

**Cómo Queremos Lograrlo**:
- **Datos de Entrada**: Utilizar datos OHLCV (Apertura, Máximo, Mínimo, Cierre, Volumen) diarios o intradiarios para activos seleccionados. Calcular promedios móviles (por ejemplo, SMA de 20 días para corto plazo, SMA de 200 días para largo plazo).
- **Generación de Señales**:
  - Componente de Reversion a la Media: Identificar desviaciones usando puntajes z (por ejemplo, si el precio está a >2 desviaciones estándar por debajo de la media, señal de compra; por encima para venta).
  - Componente de Momentum: Incorporar indicadores como RSI (Índice de Fuerza Relativa) para sobreventa/sobrecompra (por ejemplo, RSI <30 para compra con momentum positivo) o MACD (Convergencia/Divergencia de Medias Móviles) para confirmar tendencias (por ejemplo, cruce alcista de MACD para momentum de compra).
  - Combinación: Solo entrar si ambas condiciones se alinean (por ejemplo, por debajo de la media + momentum positivo para posiciones largas).
- **Reglas de Entrada**: Entrar en posiciones largas con señales de compra, dimensionando posiciones según el capital de la cuenta (por ejemplo, 1-2% de riesgo por operación). Para posiciones cortas (si se habilitan), usar lógica inversa.
- **Reglas de Salida**: Establecer objetivos de ganancia en niveles de reversión (por ejemplo, cuando el precio alcanza la SMA) o stop-loss dinámicos basados en ATR (Rango Verdadero Promedio) para proteger el momentum. Incluir salidas temporales (por ejemplo, después de 5-10 días si no hay reversión).
- **Gestión de Riesgos**: Implementar stop-loss a 1-2x ATR por debajo de la entrada, diversificación de cartera (por ejemplo, máximo 10% de asignación por activo) y filtros de volatilidad para evitar períodos de alto riesgo.
- **Enfoque con Lumibot**: Definir una clase de estrategia personalizada heredando de la clase base Strategy de Lumibot. Usar on_trading_iteration() para revisiones periódicas, get_historical_prices() para datos y colocar órdenes con self.buy() o self.sell(). Realizar backtesting con datos históricos y optimizar parámetros como períodos de SMA o umbrales de puntaje z.
- **Mejoras**: Integrar aprendizaje automático para umbrales adaptativos (por ejemplo, usando pronósticos de series temporales con modelos ARIMA o LSTM) y señales de sentimiento (por ejemplo, un sentimiento positivo en X refuerza señales de compra).

### 2. Estrategia "Martin Gala" (Variante de Martingala para Promediado de Costos)

Esta estrategia, inspirada en el sistema Martingala pero adaptada al trading como "Martin Gala," se centra en promediar el costo de entrada comprando más a medida que el precio cae, reduciendo el precio promedio para obtener ganancias con pequeños rebotes. A diferencia de la Martingala pura de apuestas, incluye salvaguardas para evitar pérdidas ilimitadas.

**Qué Queremos Lograr**:
- Convertir posiciones perdedoras en ganadoras al reducir el punto de equilibrio mediante compras adicionales, ideal para activos con tendencia a revertir, como acciones de primera línea o ETFs en mercados alcistas.
- Limitar drawdowns de capital mientras se apunta a recuperaciones, enfocándose en rebotes de alta probabilidad (por ejemplo, en condiciones de sobreventa).
- Buscar un crecimiento constante, con retornos del 10-20% anual, priorizando la preservación de capital sobre un crecimiento agresivo.

**Cómo Queremos Lograrlo**:
- **Datos de Entrada**: Monitorear datos de precios en tiempo real para activos seleccionados, rastreando precios de entrada y costos promedio.
- **Generación de Señales**:
  - Entrada Inicial: Basada en un desencadenante como un indicador de momentum (por ejemplo, precio por debajo de una media móvil) o una señal fundamental (por ejemplo, relación P/E infravalorada).
  - Niveles de Promediado: Definir umbrales de caída preestablecidos (por ejemplo, comprar más al -5%, -10%, -15% del precio de entrada inicial), duplicando el tamaño de la posición cada vez (o usando un multiplicador como 1.5x para controlar el riesgo).
- **Reglas de Entrada**: Iniciar con una posición base (por ejemplo, 1% de la cartera). En cada nivel de caída, agregar cantidades incrementalmente mayores (por ejemplo, 2x, 4x la base) para promediar. Limitar a 3-5 niveles para controlar la exposición.
- **Reglas de Salida**: Vender la posición completa cuando el precio rebote por encima del costo promedio nuevo (por ejemplo, +5-10% desde el promedio) o alcance una ganancia dinámica. Incluir un stop-loss rígido en el nivel final (por ejemplo, -20% desde la entrada inicial) para cortar pérdidas.
- **Gestión de Riesgos**: Establecer una asignación máxima por activo (por ejemplo, 5-10% de la cartera), usar dimensionamiento ajustado por volatilidad y evitar activos ilíquidos. Incorporar verificaciones de sentimiento (por ejemplo, un zumbido negativo en X detiene el promediado adicional).
- **Enfoque con Lumibot**: Crear una clase de estrategia que rastree posiciones abiertas y sus precios promedio usando self.positions. En on_trading_iteration(), verificar caídas de precios y ejecutar compras adicionales con self.buy(). Usar self.get_last_price() para monitoreo y realizar backtesting para simular escenarios de drawdown. Optimizar multiplicadores y niveles para retornos ajustados por riesgo.
- **Mejoras**: Agregar filtros para tendencias generales del mercado (por ejemplo, solo promediar en mercados alcistas) y usar opciones para cobertura (por ejemplo, puts protectores en posiciones promediadas).

### 3. Estrategia de Opciones de Christian

Esta estrategia, conocida como "Opciones de Christian," es un enfoque avanzado de trading de opciones que se centra en spreads y coberturas para generar ingresos o especular con riesgo definido. Probablemente se basa en la experiencia de Christian en opciones (asumiendo una referencia a un trader conocido o un estilo que enfatiza spreads de crédito, iron condors o estrategias de rueda). El núcleo es usar opciones para exposición apalancada mientras se gestionan las griegas (delta, gamma, theta, vega) para un riesgo equilibrado.

**Qué Queremos Lograr**:
- Generar ingresos por primas mediante la venta de opciones o crear configuraciones con riesgo-recompensa asimétrico para operaciones direccionales.
- Cubrir posiciones subyacentes (por ejemplo, de otras estrategias) y aprovechar desajustes de volatilidad.
- Apuntar a retornos mensuales del 1-2% con configuraciones de alta probabilidad (por ejemplo, tasa de aciertos del 70-80%), adecuadas para mercados laterales o con tendencia.

**Cómo Queremos Lograrlo**:
- **Datos de Entrada**: Obtener datos de la cadena de opciones (strikes, vencimientos, primas, volatilidad implícita) y precios del activo subyacente.
- **Generación de Señales**:
  - Identificar oportunidades como alta volatilidad implícita para vender primas (por ejemplo, spreads de crédito) o baja volatilidad implícita para comprar (por ejemplo, spreads de débito).
  - Usar indicadores técnicos (por ejemplo, niveles de soporte/resistencia) o fundamentales (por ejemplo, eventos de ganancias) para seleccionar strikes.
  - Ejemplos: Spread de put alcista para visiones moderadamente alcistas (vender put en soporte, comprar put más bajo); Iron condor para activos en rango.
- **Reglas de Entrada**: Entrar en operaciones multi-patas con pérdida máxima definida (por ejemplo, prima recibida como límite de riesgo). Dimensionar posiciones según el 1-3% de la cartera por operación, enfocándose en opciones de corto plazo (por ejemplo, 30-45 días hasta el vencimiento) para aprovechar la decadencia theta.
- **Reglas de Salida**: Cerrar al alcanzar el 50-75% de la ganancia máxima, o ajustar/rolar si se rompe el nivel. Usar stop-loss basados en el precio del subyacente o umbrales de delta.
- **Gestión de Riesgos**: Monitorear griegas (por ejemplo, mantener delta neutral para coberturas), diversificar entre subyacentes y limitar al 20-30% de la cartera en opciones. Incorporar sentimiento (por ejemplo, publicaciones alcistas en X sobre una acción desencadenan spreads de calls).
- **Enfoque con Lumibot**: Extender la estrategia de Lumibot para manejar opciones a través de APIs de brokers (por ejemplo, Interactive Brokers para cadenas de opciones). Usar self.get_option_chain() si está disponible, o consultas personalizadas. Ejecutar órdenes complejas con self.create_order() para las patas. Realizar backtesting con datos históricos de opciones, optimizando para el rango de volatilidad implícita y selección de strikes.
- **Mejoras**: Integrar IA para pronósticos de volatilidad (por ejemplo, modelos GARCH) y automatizar ajustes basados en deltas en tiempo real.

## Integración General y Próximos Pasos

Las estrategias se ejecutarán de manera modular dentro de Lumibot, con un bot maestro que asignará capital dinámicamente según el rendimiento. Incluir registros, paneles de rendimiento y alertas. Para el sentimiento, consultar periódicamente X para palabras clave relacionadas con los activos (por ejemplo, mediante integración con API), analizando la polaridad de cuentas influyentes para refinar señales.

Esta descripción sirve como un plan detallado para la implementación, asegurando que el proyecto sea sólido, diversificado y escalable.