# Plan: Lumiq Portfolio Autopilot

## Context

Lumiq hoy funciona como un trading companion:

- conversa por Telegram
- monitorea watchlists
- genera reportes
- consulta noticias, technicals y estado del broker
- puede ejecutar acciones puntuales sobre Alpaca

El siguiente paso no es solo "más tools". El siguiente paso es convertir a Lumiq en un sistema que pueda construir y mantener un portafolio desde chat, con una experiencia similar a una app simple de inversión asistida.

La idea central:

- el usuario habla con Lumiq como si fuera su copilot de inversión
- Lumiq entiende el perfil de riesgo
- Lumiq propone una asignación de portafolio
- Lumiq monitorea desviaciones, riesgo y eventos relevantes
- Lumiq puede ejecutar cambios, pero solo dentro de una política de seguridad clara

Esto debe vivir dentro de Lumiq, no como un experimento separado, porque ya existe:

- capa de chat
- memoria y contexto
- integración con Alpaca
- reportes y watchlists
- agentes para análisis y operaciones

## Objetivo de Producto

Construir una modalidad nueva dentro de Lumiq:

`Portfolio Advisor / Autopilot`

Capacidades esperadas:

- levantar perfil de riesgo desde conversación
- recomendar portafolios modelo
- traducir el perfil a pesos objetivo
- explicar por qué el portafolio tiene esa composición
- monitorear desviaciones y riesgo
- proponer rebalanceos
- ejecutar rebalanceos bajo confirmación o reglas preautorizadas

No debe empezar como "robo advisor regulado". Debe empezar como:

- asesor conversacional
- constructor de propuesta
- operador asistido con confirmación explícita

## Dos Modalidades

Lumiq debe separar claramente dos modos de operación.

### 1. Broker Mode

Conexión a broker custodial como Alpaca.

Uso esperado:

- leer cuenta, cash, buying power, posiciones
- proponer portafolio objetivo
- calcular delta entre portafolio actual y objetivo
- generar trade plan
- ejecutar órdenes con confirmación

Este modo es el más natural para empezar porque ya existe infraestructura en Lumiq.

### 2. Wallet Mode

Conexión a wallet crypto no-custodial.

Uso esperado:

- el usuario conecta su wallet
- Lumiq lee balances y exposición actual
- Lumiq propone asignación objetivo
- Lumiq genera plan de rebalanceo
- cualquier ejecución requiere firma explícita del usuario

Este modo no debe depender de estrategias de trading live.

Debe ser una modalidad separada orientada a:

- asset allocation
- seguimiento de portafolio
- rebalanceo
- ejecución puntual con firma

No es "trading bot". Es "portfolio autopilot".

## Decisión de Producto

Wallet Mode y Broker Mode deben compartir la capa de decisión, pero no la capa de ejecución.

Compartido:

- perfil de riesgo
- constructor de portafolio
- reglas de rebalanceo
- reportes
- explicaciones al usuario
- memoria

Separado:

- conectores de activos
- permisos
- confirmación de operaciones
- mecanismo de ejecución

## Arquitectura Objetivo

```text
User (Telegram / WhatsApp)
        |
        v
Conversation Layer
        |
        v
Portfolio Advisor Orchestrator
        |
        +--> RiskProfile Agent
        +--> Portfolio Planner Agent
        +--> Rebalance Agent
        +--> Risk Guard Agent
        |
        +--> Broker Connector (Alpaca)
        |
        +--> Wallet Connector (WalletConnect / onchain read)
```

Principio:

- un agente o team decide
- un guard valida
- un conector ejecuta

No mezclar decisión con ejecución ciega.

## Agentes Propuestos

### RiskProfileAgent

Responsabilidad:

- entender objetivo del usuario
- traducir conversación a perfil operativo

Campos mínimos:

- risk_level
- time_horizon
- liquidity_needs
- experience_level
- income_stability
- max_drawdown_tolerance
- target_return_style
- restrictions

Salida esperada:

```json
{
  "risk_level": "moderate",
  "time_horizon": "5y+",
  "max_drawdown_tolerance": 0.18,
  "liquidity_needs": "medium",
  "restrictions": ["no_options", "crypto_max_15pct"]
}
```

### PortfolioPlannerAgent

Responsabilidad:

- construir portafolio objetivo desde perfil + universo disponible

Debe responder:

- qué assets usar
- qué pesos asignar
- cuál es el benchmark
- por qué ese portafolio es coherente con el perfil

No debe ejecutar operaciones.

### RebalanceAgent

Responsabilidad:

- comparar portafolio actual vs objetivo
- calcular rebalanceo
- generar trade plan

Salida esperada:

- pesos actuales
- pesos objetivo
- drift por activo
- acciones sugeridas

### RiskGuardAgent

Responsabilidad:

- validar que lo sugerido o ejecutado cumple políticas

Ejemplos de políticas:

- no más de X por activo
- no más de Y en crypto
- no usar margin
- no ejecutar si falta confirmación
- no rebalancear si el drift es menor al umbral

### Connector Agents

No deben "pensar". Deben actuar como adaptadores.

Tipos:

- `BrokerOpsAgent`
- `WalletOpsAgent`

Su trabajo es:

- leer posiciones
- leer balances
- preparar operaciones
- ejecutar cuando el guard lo permite

## Flujos Principales

### Flujo 1: Onboarding de perfil

Ejemplo:

`I want a long-term portfolio. I am okay with medium risk. I want some crypto but not too much.`

Pasos:

1. RiskProfileAgent construye perfil.
2. Se persiste en DB.
3. PortfolioPlannerAgent propone primer portafolio.
4. Lumiq responde con propuesta + explicación.

### Flujo 2: Crear portafolio en Broker Mode

Ejemplo:

`Build me a moderate portfolio with ETFs and some AI exposure.`

Pasos:

1. leer perfil
2. construir portafolio objetivo
3. leer holdings actuales en Alpaca
4. generar trade plan
5. pedir confirmación
6. ejecutar si el usuario confirma

### Flujo 3: Crear portafolio en Wallet Mode

Ejemplo:

`Use my wallet and create a conservative crypto portfolio.`

Pasos:

1. conectar wallet
2. leer balances
3. normalizar holdings por chain y asset
4. construir portafolio objetivo
5. proponer cambios
6. si hay ejecución, requerir firma explícita

### Flujo 4: Rebalanceo periódico

Ejemplo:

`Rebalance my portfolio.`

Pasos:

1. leer estado actual
2. comparar contra objetivo
3. aplicar reglas de drift y costo mínimo
4. generar plan
5. confirmar / ejecutar

## Universo Inicial Recomendado

Para no complicar la primera versión, el universo debe ser pequeño.

Broker Mode:

- ETFs core: `SPY`, `VTI`, `QQQ`, `VXUS`, `BND`
- diversificadores: `GLD`, `TLT`
- growth concentrado opcional: `NVDA`, `MSFT`, `AMZN`
- crypto exposure vía ETFs si aplica: `IBIT`, `ETHA` o equivalentes disponibles

Wallet Mode:

- `BTC`
- `ETH`
- `SOL`
- stablecoins (`USDC`, `USDT`) si se decide usar cash-like allocation

No abrir el universo desde el día 1.

## Construcción de Portafolio v1

La versión 1 no necesita optimización cuantitativa compleja.

Puede arrancar con plantillas.

Ejemplos:

Conservative:

- 50% broad equity ETFs
- 30% bonds / cash-like
- 10% gold
- 10% optional growth or zero crypto

Moderate:

- 60% broad equity ETFs
- 15% international
- 10% bonds
- 10% thematic / growth
- 5% crypto

Aggressive:

- 60% growth / tech / thematic
- 20% broad ETFs
- 10% crypto
- 10% cash / optional hedge

Luego se puede evolucionar a:

- mean-variance simplificada
- volatility targeting
- risk budgets por sleeve

## Reglas de Rebalanceo

Primera versión:

- rebalanceo mensual
- rebalanceo si drift absoluto > 20% del peso objetivo
- ignorar cambios pequeños bajo costo mínimo

Ejemplo:

- target `BTC = 10%`
- rebalancear si baja de `8%` o sube de `12%`

Reglas adicionales:

- no vender por completo un activo sin explicación
- no comprar activos fuera del universo permitido
- no usar margin

## Integración con Chat

Lumiq debe seguir sintiéndose como chat, no como formulario.

Ejemplos válidos:

- `Build me a low-risk portfolio`
- `I want more growth but not too much volatility`
- `Reduce my crypto exposure`
- `Use my Alpaca account and rebalance`
- `Connect my wallet and show me what I hold`

Comandos explícitos opcionales:

- `/profile`
- `/portfolio`
- `/rebalance`
- `/autopilot on`
- `/autopilot off`

Pero el objetivo es soportar lenguaje natural primero.

## Wallet Mode: Investigación Técnica

La parte crypto debe diseñarse como integración no-custodial.

Opciones a evaluar:

- WalletConnect / Reown para sesión y firma
- lectura onchain vía proveedor indexado
- conectores multi-chain

Capacidades mínimas:

- connect wallet
- read balances
- read token metadata
- normalize positions
- estimate current allocation

Capacidades posteriores:

- build swap plan
- request signature
- execute rebalance

Importante:

- Lumiq no debe custodiar fondos
- Lumiq no debe guardar private keys
- cada ejecución debe ser firmada por el usuario

## Por Qué Esto Sí Vale la Pena en Lumiq

Lumiq ya tiene piezas que Mastra sola no te da resueltas:

- trading domain model
- integración con broker
- reporting operativo
- watchlists
- alertas
- P&L
- contexto conversacional ya acoplado al dominio

Mastra puede servir como runtime agentic si en el futuro conviene, pero reemplazar Lumiq completo por Mastra hoy perdería ventaja de dominio.

Conclusión práctica:

- mantener Lumiq como core del producto
- mejorar su capa advisor/autopilot
- tratar wallet mode como una modalidad nueva dentro del mismo producto

## Fases

### Fase 1: Advisor sin ejecución automática

Objetivo:

- levantar perfil
- construir portafolio
- mostrar propuesta
- persistir objetivo

Entregables:

- esquema `risk_profile`
- esquema `portfolio_target`
- PortfolioPlannerAgent
- prompts y tools base
- respuestas por chat en lenguaje natural

### Fase 2: Broker Mode con ejecución asistida

Objetivo:

- conectar propuesta a Alpaca real

Entregables:

- lector de holdings
- cálculo de drift
- generador de trade plan
- confirmación explícita
- ejecución por lotes simples

### Fase 3: Wallet Mode read-only

Objetivo:

- conectar wallets sin custodiar

Entregables:

- autenticación wallet
- lectura de balances
- consolidación de portafolio crypto
- propuesta de asignación

### Fase 4: Wallet Mode con firma

Objetivo:

- rebalanceo crypto con confirmación real

Entregables:

- plan de swaps
- solicitud de firma
- tracking de ejecución

### Fase 5: Autopilot controlado

Objetivo:

- permitir rebalanceos bajo reglas claras

Reglas mínimas:

- universo limitado
- umbrales de drift
- límites por activo
- máxima exposición crypto
- kill switch del usuario

## Riesgos

- riesgo regulatorio si se comunica como asesor financiero formal
- riesgo operativo si se mezcla análisis con ejecución sin guardrails
- riesgo UX si el onboarding de perfil es demasiado largo
- riesgo técnico si wallet mode se mezcla con estrategias live

Decisión importante:

Wallet Mode no debe lanzar estrategias live de trading.

Debe ser una modalidad distinta de:

- lectura de holdings
- asset allocation
- rebalanceo
- ejecución con firma

## Criterio de Éxito

El plan está bien implementado cuando:

- el usuario puede definir su perfil desde chat
- Lumiq puede proponer un portafolio coherente
- Lumiq puede explicar el portafolio en lenguaje simple
- Lumiq puede comparar portafolio actual vs objetivo
- Lumiq puede proponer rebalanceos sin alucinar datos
- Broker Mode ejecuta solo con confirmación
- Wallet Mode opera sin custodia y con firma explícita

## Siguiente Documento Recomendado

Después de este plan, el siguiente documento debería ser:

`agents-guides/wallet-autopilot-technical-plan.md`

Ese documento debe cubrir:

- proveedor wallet
- session model
- chain support
- read model de balances
- plan de ejecución y firma
- límites de seguridad
