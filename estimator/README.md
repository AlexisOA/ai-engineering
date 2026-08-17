# Estimator — Servicio IA de estimación de software

Servicio IA en FastAPI que estima proyectos de software a partir de un formulario tipado. Es la pieza Python del programa **Master en AI Engineering**: un endpoint pensado para ser consumido por un backend de negocio (Rails, Streamlit u otro), no por un usuario final.

A partir de la **Sesión 04** el contrato es deliberadamente estrecho:
- entrada tipada (`description` + tres enums),
- salida en texto libre,
- prompt fuera del código en templates Jinja2 versionados (`app/prompts/<use_case>/<version>/`).

La inteligencia adicional (output estructurado, guardrails, cache semántico) se construye encima de esta base en directo.

## Cómo levantar

### Con Docker (recomendado)

```bash
cd estimator
cp .env.example .env  # añade al menos OPENAI_API_KEY o ANTHROPIC_API_KEY
docker compose up --build
```

El servicio queda en `http://localhost:8000` (Swagger en `/docs`, health en `/health`). Redis arranca como servicio vecino para el cache exact-match del wrapper.

### Sin Docker

```bash
cd estimator
uv sync
uv run uvicorn app.main:app --reload
```

### Probar el endpoint

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "description": "A small B2B SaaS to manage employee equipment loans across teams. Role-based access, audit trail, weekly digest.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table"
  }'
```

Respuesta:

```json
{
  "text": "| phase | duration_weeks | cost_eur | confidence_pct | …",
  "prompt_version": "v1"
}
```

### Cliente Streamlit

El cliente Streamlit es un formulario que construye el JSON y muestra el `text` recibido. Corre fuera de Docker y consume la API por HTTP:

```bash
cd estimator
uv run streamlit run streamlit_app.py
# Abrir http://localhost:8501
```

La URL del servicio se lee de `ESTIMATOR_API_BASE_URL` (default `http://localhost:8000`).

## Cómo testar

```bash
cd estimator
uv run pytest
```

La batería corre en milisegundos sin tocar APIs externas. Cubre cuatro categorías:

- `tests/test_schemas.py` — validaciones del `EstimationRequest` (longitudes, enums, campos obligatorios).
- `tests/test_prompts.py` — render del template `v1`: `description` aparece dentro de `<project_description>`, los bloques condicionales por `output_format` y `detail_level` solo se incluyen cuando aplica, y `StrictUndefined` falla early ante variables faltantes.
- `tests/test_estimate_endpoint.py` — endpoint con el wrapper LLM mockeado vía `app.dependency_overrides`: comprueba el contrato 200/422, que `system_prompt` y `user_message` viajan separados, y que la respuesta lleva `prompt_version="v1"`.
- `tests/test_llm_wrapper.py` y `tests/test_cache.py` — wrapper y cache de la Sesión 03, intactos.

## Estructura del proyecto

```
estimator/
├── app/
│   ├── main.py                        # FastAPI app, CORS, lifespan, /health
│   ├── config.py                      # Settings (Pydantic Settings, .env)
│   ├── dependencies.py                # Singletons cacheados: cache + LLMWrapper
│   ├── routers/
│   │   └── estimations.py             # POST /api/v1/estimate
│   ├── schemas/
│   │   └── estimation.py              # EstimationRequest, EstimationResponse, enums
│   ├── prompts/
│   │   ├── loader.py                  # Environment Jinja2 + render_estimation_prompt
│   │   └── estimation/
│   │       └── v1/
│   │           ├── system.j2          # rol + reglas + bloques condicionales + include
│   │           ├── user.j2            # bloque <project_description>
│   │           └── examples.j2        # few-shot examples
│   └── services/
│       ├── llm_wrapper.py             # LiteLLM Router con fallback y cost tracking
│       └── cache.py                   # Redis exact-match cache
├── tests/
│   ├── test_schemas.py
│   ├── test_prompts.py
│   ├── test_estimate_endpoint.py
│   ├── test_llm_wrapper.py
│   └── test_cache.py
├── streamlit_app.py                   # Formulario que consume /api/v1/estimate
├── Dockerfile                         # Multi-stage con uv
├── docker-compose.yml                 # Servicio IA + Redis
└── pyproject.toml
```

### Versionado de prompts

La estructura `app/prompts/<use_case>/<version>/` no es opcional: `v1/` ya existe desde el primer día porque versionar un prompt es la forma más barata de habilitar A/B testing y rollback en producción. Cuando una iteración del prompt se cocina, se crea `v2/` al lado y `render_estimation_prompt(request, version="v2")` lo recoge sin tocar router ni schemas.

Lo que vive **fuera** del template (en código): el contrato (`EstimationRequest`), el switch de versión y el wrapper. Todo lo demás (rol del modelo, reglas, ejemplos, formatos de salida, niveles de detalle) vive dentro del `.j2`. Si para cambiar el comportamiento del modelo hay que tocar Python, la separación está rota.

## Variables de entorno

| Variable | Default | Notas |
|---|---|---|
| `OPENAI_API_KEY` | — | Requerido al menos uno de los dos |
| `ANTHROPIC_API_KEY` | — | Requerido al menos uno de los dos |
| `PRIMARY_MODEL` | `gpt-4o-mini` | Modelo principal del Router |
| `FALLBACK_MODEL` | `claude-haiku-4-5-20251001` | Se usa si el primario falla |
| `REDIS_URL` | `redis://localhost:6379` | Cache exact-match |
| `CACHE_TTL` | `86400` | Segundos |
| `APP_ENV` | `development` | Controla el renderer de structlog |
| `ESTIMATOR_API_BASE_URL` | `http://localhost:8000` | Lo lee el cliente Streamlit |

`get_settings()` es un singleton cacheado con `lru_cache`: cualquier cambio en `.env` requiere reiniciar uvicorn (no basta con `--reload`).

---

## Sesión 5 — Memoria conversacional y adjuntos

A partir de la Sesión 05 el estimator deja de ser puramente transaccional y soporta **sesiones conversacionales**: el cliente puede refinar el alcance del proyecto a lo largo de varios turnos, subir documentos (PDF/Word) y el sistema recuerda el proyecto en curso entre llamadas. El endpoint `POST /api/v1/estimate` original se mantiene intacto para compatibilidad y para la demo transaccional.

### Endpoints nuevos

```
POST /sessions                              → 201 {"session_id": "<uuid>"}
GET  /sessions/{session_id}                 → 200 {session_id, message_count, max_turns, metadata}
POST /sessions/{session_id}/estimate        → 200 EstimationResponse
   (multipart/form-data: transcript, project_type, detail_level, output_format, attachments[])
```

Ejemplo end-to-end con httpie:

```bash
http POST :8000/sessions
# {"session_id": "abc-123"}

http -f POST :8000/sessions/abc-123/estimate \
  transcript="Queremos estimar un CRM llamado Nimbus en React + Postgres para el equipo de ventas." \
  project_type=web_saas detail_level=medium output_format=phases_table \
  attachments@spec.pdf

http GET :8000/sessions/abc-123
# Inspecciona el ProjectMetadata acumulado y el tamaño del historial.
```

Y un segundo turno reutilizando el mismo `session_id` sin repetir el contexto:

```bash
http -f POST :8000/sessions/abc-123/estimate \
  transcript="Añade un módulo de facturación con Stripe." \
  project_type=web_saas detail_level=medium output_format=phases_table
```

La respuesta del segundo turno integra Nimbus + React + Postgres + facturación porque el `<project_metadata>` se inyecta en el system prompt y el historial reciente viaja en el array `messages`.

### Decisiones de diseño

1. **Camino B para los adjuntos.** Extraemos el texto del PDF/Word **dentro del servicio IA** con `pypdf` y `python-docx`, lo recortamos a `MAX_ATTACHMENT_CHARS` y lo concatenamos al transcript con fences explícitos (`--- attachment: spec.pdf ---`). La alternativa (Camino A: subir el binario a la Files API de OpenAI o Anthropic) habría sido más corta de implementar pero acopla el wrapper a un proveedor multimodal concreto. Camino B mantiene `complete_structured_chat` agnóstico de proveedor (texto en, texto fuera vía LiteLLM Router + Instructor) y prepara el terreno para el chunking real de RAG en el módulo 3. La extracción es robusta a páginas corruptas (fallos por página se loguean y se ignoran) y a archivos vacíos.

2. **`project_metadata` con extractor LLM, no heurística.** Tras cada respuesta del estimador, una **segunda llamada** al LLM (modelo barato configurable vía `METADATA_EXTRACTOR_MODEL`, por defecto `gpt-4o-mini`) lee el último turno y devuelve un `ProjectMetadata` parcial vía Instructor. Lo fusionamos con el previo: campos escalares sobrescriben si vienen no-nulos, la lista de tecnologías se une case-insensitively. Se eligió el extractor LLM frente a una heurística regex porque el coste de una llamada con prompt corto es marginal y la robustez frente a paráfrasis del usuario es mucho mejor — y porque el curso enseña precisamente cómo construir estos pasos con LLMs. Si la llamada falla, se loguea y se conserva la metadata previa: la conversación no se cae por una extracción rota.

3. **Memoria en proceso, no Redis ni Postgres.** El `SessionStore` es un `dict` en memoria del worker FastAPI. La volatilidad (estado perdido al reiniciar el contenedor) es **intencional** para esta fase y está documentada en el docstring del store. La persistencia entre reinicios entra en el directo cuando hablemos de compresión de memoria con anclas.

4. **Cachés desactivadas en el path conversacional.** Cada turno depende del historial + metadata + adjuntos: dos transcripciones idénticas en sesiones distintas **no** son la misma llamada. El método nuevo `EstimationService.estimate_conversational` por tanto no consulta ni el cache exact-match ni el semántico, y `EstimationResponse.cached` siempre es `false` en este path. El endpoint transaccional original `POST /api/v1/estimate` sigue usando las dos cachés sin cambios.

5. **Ventana deslizante con `MAX_CONVERSATION_TURNS=6` por defecto.** El system prompt se regenera fresco cada turno desde el `ProjectMetadata` actual, así que no consume slot. Lo que llega al LLM en el turno N es: `[system_v2] + últimos N pares (user, assistant) + nuevo user`. Cuando el historial supera el tope, los pares más antiguos se descartan en bloque para preservar la alternancia de roles. El siguiente paso (resumen acumulativo + anclas) lo construimos en el directo.

### Variables de entorno nuevas

| Variable | Default | Notas |
|---|---|---|
| `MAX_CONVERSATION_TURNS` | `6` | Pares user+assistant que mantiene la ventana. |
| `MAX_ATTACHMENT_CHARS` | `60000` | Corte por archivo extraído. Trunca, no rechaza. |
| `METADATA_EXTRACTOR_MODEL` | `gpt-4o-mini` | Modelo de la segunda llamada por turno. |

### Tests del Paso 7

```bash
uv run pytest tests/test_sessions_metadata.py tests/test_sessions_attachments.py tests/test_sessions_window.py -v
```

Los tres tests son de integración con `TestClient`, un `FakeLLMWrapper` que captura cada llamada y devuelve resultados scripted, y un `SessionStore` aislado por test (sin singleton). Cubren los tres criterios del enunciado: dos turnos acumulan metadata, el contenido de un PDF llega al `messages` del LLM, y enviar más turnos que `MAX_CONVERSATION_TURNS` nunca infla el array de mensajes más allá del límite.

### Cliente Rails

El cliente Rails (`estimator-web/`) se adaptó al flujo conversacional con un nuevo controller `ChatSessionsController` (rutas `/chat_sessions`, root re-apuntado aquí), un panel lateral con el `ProjectMetadata` actual, multipart vía `faraday-multipart` y un botón "Nueva conversación" que destruye el mirror local y arranca una sesión limpia. El endpoint transaccional `EstimationsController` se mantiene operativo para la demo histórica.

## Sesión 7 — Pipeline mínimo de embeddings y chunking

Nuevo módulo `app/embedding_pipeline/`: convierte presupuestos históricos (JSON normalizado) en chunks embebibles y sus vectores, todo en memoria — sin persistencia todavía (eso entra en la Sesión 08 con pgvector) y sin retrieval (búsqueda semántica es tema del directo).

### Estrategia de chunking

Un componente de presupuesto (`BudgetComponent`) = un chunk. Sin overlap ni fixed-size splitting: se confía en la estructura del JSON. Cada chunk antepone el contexto del presupuesto padre (proyecto, sector, año, stack principal) al detalle del componente — un *contextual chunk header* deliberado: sin él, un componente como "Authentication backend" perdería la pista de a qué cliente pertenece.

### Endpoint

```
POST /embeddings/ingest
  body: {"budgets": [<Budget>, ...]}
  → 200 {"chunks": [<EmbeddedChunk>, ...], "stats": {total_budgets, total_chunks, total_tokens, estimated_cost_usd}}
```

Con el sample de datos incluido (`data/budgets_sample.json`, 15 presupuestos):

```bash
http POST :8000/embeddings/ingest budgets:="$(cat data/budgets_sample.json)"
```

O directamente desde `/docs` (Swagger UI), pegando el contenido de `data/budgets_sample.json` en el body de `POST /embeddings/ingest`.

### Script `compare.py` — sanity check de similitud

Calcula la similitud coseno (a mano, sin numpy) entre dos textos embebidos con `text-embedding-3-small`.

Dentro del contenedor:

```bash
docker compose exec estimator python scripts/compare.py \
  --text-a "OAuth 2.0 authentication backend for fintech" \
  --text-b "JWT-based authorization service for banking app"
```

Fuera del contenedor (con `.env` cargado y `uv sync` hecho):

```bash
uv run python scripts/compare.py \
  --text-a "OAuth 2.0 authentication backend for fintech" \
  --text-b "JWT-based authorization service for banking app"
```

Los resultados de las tres parejas de validación del enunciado, con comentario, están en [`app/embedding_pipeline/SANITY_CHECK.md`](app/embedding_pipeline/SANITY_CHECK.md).

### Decisiones de diseño

1. **`tiktoken.encoding_for_model("text-embedding-3-small")` para `token_count`.** Se calcula en el chunker, no en el embedder — así un chunk anormalmente grande es visible antes de gastar una llamada a la API.
2. **Batching de 100 chunks por llamada** a `embeddings.create`, con reintento exponencial simple (1s/2s/4s) solo ante `RateLimitError`; cualquier otro error de la API se propaga tal cual.
3. **`get_embedder()` lanza si falta `OPENAI_API_KEY`** (a diferencia del cache semántico, que degrada a `None`): sin API key este módulo no tiene una versión "más pequeña" que ofrecer, simplemente no funciona.
4. **`data/budgets_sample.json`** son 15 presupuestos sintéticos que siguen el esquema del enunciado (`client_metadata`, `components[]` con `tech_stack`/`complexity`/`dependencies`) — no confundir con `data/seed/budgets/` (Sesión 06), que usa el esquema antiguo (`phases`, `total_amount`) para el pipeline de ingestión de documentos.

---

> Este proyecto forma parte del **Master en AI Engineering** y es la base sobre la que se construye en directo el resto de la Sesión 04 (output estructurado, guardrails, cache semántico) y de la Sesión 05 (compresión avanzada de memoria con anclas, tier dinámico, patrón Actor-Critic-Boss).
