Descripción del Core del Bot

El objetivo es diseñar un core modular para estrategias de trading, basado en la integración con Lumibot, que permita instanciar y ejecutar estrategias de manera flexible tanto en backtesting como en live trading (con o sin paper trading).

1. Instanciación de Estrategias

Definir una clase factory/constructor que permita instanciar cualquier estrategia disponible.

Esta clase debe recibir como parámetros:

Nombre de la estrategia

Configuración específica (ejemplo: símbolos, timeframe, indicadores, tamaño de posición, etc.)

La instancia resultante debe ser capaz de ejecutar la estrategia bajo el motor de Lumibot.

2. Core de Ejecución

El core actúa como un orquestador:

Puede inicializar cualquier estrategia registrada.

Ejecuta la estrategia con los parámetros provistos.

Permite cambiar entre modos: backtesting, paper trading o live trading.

La arquitectura debe ser extensible, de forma que cualquier nueva estrategia pueda añadirse sin modificar el core, solo registrándola.

3. Interfaz de Integración (extensibilidad del Core)

Una vez que el core esté estable, se construyen adaptadores para exponer sus capacidades hacia distintos clientes:

Interfaces externas:

REST API para dashboards web o integraciones.

CLI (Command Line Interface) usando frameworks como Textual
. Initail design.



Bots de mensajería (ejemplo: Telegram) para ejecutar estrategias o monitorear resultados desde chat.

Runners parametrizables: permitir ejecutar una estrategia específica desde línea de comandos o desde un archivo de configuración (YAML/JSON).

4. Principio Central

El core debe abstraer la lógica de ejecución de Lumibot para que ejecutar estrategias a voluntad sea tan simple como:

core.run(strategy="MeanReversion", params={...}, mode="paper")


       +-------------------+
       |  Interfaces I/O   |
       |  - CLI (Typer)    |
       |  - REST (FastAPI) |
       |  - Telegram Bot   |
       +---------+---------+
                 |
                 v
        +------------------+        +-------------------+
        |   BotCore        | -----> | Broker/Exchange   |
        |  - run()         |        | (IBKR, Alpaca, ..)|
        |  - load_strategy |        +-------------------+
        +----+-------+-----+
             |       |
             |       v
             |  +-----------+
             |  | Registry  |
             |  | (Strategy |
             |  |   map)    |
             |  +-----------+
             |
             v
    +---------------------+
    | Strategy Factory    |
    | (crea instancia)   |
    +---------------------+


Ejecución 
Cada una de las estrategias se debería poder ejecutar live:
- Tiempo:por 1min, 5min, 1h, 1d,1sem,1mes.
- Monto
