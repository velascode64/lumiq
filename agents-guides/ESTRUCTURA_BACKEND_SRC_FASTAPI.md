# Estructura de `Backend/src` para migración a FastAPI (HTTP separado de `core`)

## Objetivo

Definir una estructura de carpetas para `Backend/src` que:

- Separe la capa HTTP (FastAPI) del `core`.
- Mantenga la lógica reusable en `core` (flujos/casos de uso).
- Permita que `agents` y otros adaptadores reutilicen el mismo `core`.
- Facilite extraer `core` como librería más adelante.
- Sirva como guía para migrar una app desordenada sin mezclar responsabilidades.

## Principio principal

La regla es:

- `http` importa `core`
- `agents` importan `core`
- `jobs` importan `core`
- `core` **no** importa FastAPI ni detalles del transporte HTTP

Esto evita que la lógica de negocio quede acoplada a endpoints, requests, responses o decorators.

## Patrón de carpetas (estilo Fastify/FastAPI con `core` modular)

La jerarquía observada en `Backend/src` ya va en esa dirección (`adapters/http` + `core/application` + `core/platform`).  
Para FastAPI en Python, la versión equivalente recomendada sería:

```text
Backend/src/
├── server.py                      # bootstrap de FastAPI (app, middlewares, startup)
├── adapters/
│   └── http/
│       ├── __init__.py
│       ├── api.py                 # registra routers
│       ├── dependencies.py        # dependencias FastAPI (auth, db session, etc.)
│       ├── middleware/
│       ├── accounts/
│       │   ├── router.py
│       │   ├── schemas.py         # request/response DTOs (Pydantic)
│       │   └── mappers.py         # opcional: DTO <-> core
│       ├── transactions/
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── mappers.py
│       └── ...                    # un router por contexto funcional
├── core/
│   ├── application/
│   │   ├── accounts/
│   │   │   ├── services.py        # casos de uso / flujos
│   │   │   └── errors.py          # opcional por módulo
│   │   ├── transactions/
│   │   │   ├── services.py
│   │   │   ├── duplicate_detection.py
│   │   │   └── cache_service.py
│   │   └── ...
│   ├── domain/                    # opcional pero recomendable si crecerá
│   │   ├── entities/
│   │   ├── value_objects/
│   │   └── exceptions.py
│   ├── ports/                     # interfaces/contratos del core
│   │   ├── repositories/
│   │   ├── notifications.py
│   │   └── auth.py
│   ├── infrastructure/            # adaptadores técnicos reutilizables
│   │   ├── db/
│   │   ├── cache/
│   │   ├── providers/
│   │   └── config.py
│   └── platform/                  # bootstrap técnico del backend (si lo mantienes)
│       ├── db.py
│       ├── config.py
│       └── plugins.py             # equivalente conceptual a setup técnico
├── agents/
│   ├── email_scanner/
│   ├── tx_classifier/
│   └── ...
├── jobs/
│   ├── __init__.py
│   ├── scheduler.py
│   └── queues/
├── scripts/
├── tests/
├── types/                         # si aplica, o reemplazar por typing local
└── utils/                         # utilidades transversales sin lógica de negocio
```

## Qué va en cada capa (y qué no)

### `adapters/http`

Responsabilidad:

- Exponer endpoints FastAPI (`APIRouter`)
- Validar entrada/salida (Pydantic)
- Traducir HTTP -> llamadas al `core`
- Mapear errores del `core` a códigos HTTP

No debe contener:

- Reglas de negocio
- Flujos complejos
- Acceso a DB directo (salvo composición mínima de dependencias)

## `core/application`

Responsabilidad:

- Casos de uso y flujos de negocio
- Orquestación entre repositorios/proveedores
- Reglas de negocio reutilizables por HTTP, jobs, agents, CLI

Debe ser:

- Independiente de FastAPI
- Testeable sin levantar servidor
- Organizado por contexto funcional (`accounts`, `transactions`, etc.)

## `core/ports` (interfaces)

Responsabilidad:

- Definir contratos que el `core` necesita (repositorios, cache, notificaciones, auth)

Ventaja:

- Permite cambiar infraestructura (Postgres, Redis, APIs externas) sin tocar los flujos del `core`.

## `core/infrastructure` / `core/platform`

Responsabilidad:

- Implementaciones técnicas concretas (DB, providers, config, clientes externos)
- Wiring técnico del backend

Nota práctica:

- Si ya existe `core/platform`, puedes mantenerlo para no romper la migración.
- Si el proyecto crece, mover implementaciones concretas a `core/infrastructure` y dejar `platform` solo para bootstrap/configuración.

## Regla de dependencias (imports)

Dirección permitida:

```text
adapters/http  -> core/application -> core/ports
agents         -> core/application -> core/ports
jobs           -> core/application -> core/ports
infrastructure -> core/ports       (implementa contratos)
```

Dirección no permitida:

```text
core/application -> fastapi
core/application -> adapters/http
core/application -> Request/Response de FastAPI
```

## Cómo se ve el flujo correcto

1. `router.py` recibe request HTTP.
2. `schemas.py` valida payload/query/path.
3. `router.py` llama a un servicio del `core/application`.
4. El servicio ejecuta el flujo y usa puertos/repositorios.
5. La infraestructura implementa esos puertos.
6. `router.py` devuelve response HTTP.

Este flujo permite que el mismo caso de uso sea llamado también desde:

- `agents/`
- `jobs/`
- `scripts/`

## Recomendación para migración desde una app desordenada

Haz la migración por capas, no por archivo:

1. Crear `adapters/http` y mover solo routers/endpoints.
2. Crear `core/application` y mover lógica de negocio ahí.
3. Identificar acceso a DB/APIs externas y encapsularlo en `infrastructure` (o `platform`).
4. Introducir `ports` cuando detectes acoplamiento fuerte.
5. Repetir por módulo funcional (`transactions`, `accounts`, etc.).

## Señales de que la separación está bien hecha

- Puedes ejecutar tests del `core` sin FastAPI.
- Un `agent` puede reutilizar un flujo sin importar código HTTP.
- Cambiar un endpoint no obliga a modificar reglas de negocio.
- El `core` puede publicarse como librería interna con pocos cambios.

## Preparar `core` para convertirse en librería

Para que después sea una librería reutilizable:

- Evita imports desde `adapters/http` dentro de `core`.
- Define contratos (`ports`) para dependencias externas.
- Centraliza tipos/errores del `core`.
- Mantén funciones/servicios con inputs/outputs claros (DTOs internos).
- Minimiza lectura directa de variables de entorno dentro de `core` (inyecta config).

## Resumen

La estructura recomendada mantiene la jerarquía tipo Fastify/FastAPI (rutas agrupadas en `adapters/http`) pero coloca el valor real del sistema en un `core` modular y reusable.  
Eso hace que la migración sea ordenada hoy y que mañana el `core` pueda extraerse como librería sin rehacer los flujos.

