# Despliegue local con docker-compose (Sesión 15)

Cómo levantar el sistema completo — negocio (Rails), IA (FastAPI), Postgres de
negocio y Postgres+pgvector de la IA — con un único comando, reproducible, sin
pasos manuales.

## Arrancar

Desde la **raíz del repo** (no desde `estimator/` ni `estimator-web/` — eso levanta
cada subproyecto en modo desarrollo aislado, ver `CLAUDE.md`):

```bash
cp estimator/.env.example estimator/.env
cp estimator-web/.env.example estimator-web/.env
# Editar ambos: OPENAI_API_KEY/ANTHROPIC_API_KEY en estimator/.env, y elegir el
# MISMO valor de AI_SERVICE_TOKEN en los dos .env (el token que autentica las
# llamadas de Rails al servicio IA). SECRET_KEY_BASE en estimator-web/.env se
# genera con `bin/rails secret` (o `docker compose run --rm estimator-web bin/rails
# secret` si no tienes Ruby en el host).

docker compose build
docker compose up
```

## Las 5 comprobaciones del Paso 7

1. **`docker compose ps`** — los 4 servicios arriba; `estimator` y
   `estimator-postgres` en `healthy` (Redis y el Postgres de negocio también,
   de propina).
2. **`curl http://localhost:3000`** — sirve el frontend de Rails.
3. **El servicio IA no es alcanzable desde el host** — `curl http://localhost:8000/health`
   no conecta (`estimator/docker-compose.yml` no publica ningún puerto; solo
   alcanzable vía la red interna de compose, como `http://estimator:8000` desde
   Rails).
4. **Una estimación real, end-to-end**: desde `http://localhost:3000`, lanzar
   una estimación → Rails llama a `POST http://estimator:8000/api/v1/estimate`
   con el header `X-Service-Token` → el servicio IA corre el pipeline (guardrails
   + LLM + cachés) → devuelve una estimación estructurada coherente → Rails la
   persiste y la muestra.
5. **Persistencia**: `docker compose down && docker compose up` — todo vuelve a
   funcionar sin pasos manuales (los volúmenes con nombre —
   `estimator_postgres_data`, `postgres_data`, `redis_data`, `storage_data` —
   sobreviven al `down`).

## Qué NO funcionó a la primera (para el directo)

- **El Dockerfile del servicio IA solo copiaba `app/`.** Al quitar el bind mount
  de desarrollo, el comando de arranque (`alembic upgrade head && uvicorn ...`)
  se quedaba sin `alembic/`, `alembic.ini`, `data/` (catálogo de ingesta) y
  `scripts/` — ninguno estaba en la imagen. Arreglado añadiendo esos `COPY` al
  Dockerfile.
- **`force_ssl`/`assume_ssl` a pelo en `production.rb` rompían el arranque.**
  Sin un proxy TLS delante en local, Rails redirige/rechaza todo. Se pasaron a
  leer `RAILS_FORCE_SSL`/`RAILS_ASSUME_SSL` por variable de entorno (por
  defecto `true`, el comportamiento real de producción/cloud no cambia; el
  compose local las pone a `false`). **Al desplegar en el directo (con un
  proxy/load balancer TLS delante), quitar esas dos variables o ponerlas a
  `true`.**
- **Las credenciales de `production` en `database.yml` no coincidían con el
  Postgres del compose.** Tenía un usuario/contraseña propios
  (`estimator_web` / `ESTIMATOR_WEB_DATABASE_PASSWORD`) que no existen en el rol
  que crea el compose. Se simplificó para heredar las mismas
  `DATABASE_USER`/`DATABASE_PASSWORD` que ya usan `development`/`test`.
- **`docker compose up` desde la raíz vs. desde cada subproyecto son dos modos
  distintos, con volúmenes con nombre distintos** (ya documentado en
  `CLAUDE.md`) — confirmar en qué directorio se está antes de diagnosticar por
  qué "no aparecen los datos de la otra vez".

## Decisión de diseño: un solo Dockerfile para negocio (dev + conforme)

`estimator-web/Dockerfile` instala **todos** los grupos de gemas (incluidas
`development`/`test`), igual que la imagen de desarrollo anterior a esta sesión
— no se separó un segundo target de build solo con gemas de producción. La
alternativa (un Dockerfile multi-target, uno más ligero para el modo conforme y
otro con gemas de desarrollo) evita cargar `rubocop`/`debug`/etc. en la imagen
"real", pero obliga a que `docker-compose.override.yml` (el modo desarrollo,
que monta el código en bind mount sobre esta misma imagen) seleccione
explícitamente el target de desarrollo — más piezas móviles para lo que pide
este ejercicio. Se documenta aquí como trade-off consciente, no como olvido.

## Estructura del override de desarrollo

Cada subproyecto (`estimator/`, `estimator-web/`) tiene su propio
`docker-compose.override.yml` con las comodidades de desarrollo (bind mounts,
`--reload`/`bin/dev`, el puerto 8000 del servicio IA). Docker Compose carga
automáticamente el `override.yml` del directorio **desde el que se invoca**
`docker compose up`:

- Desde la **raíz** → sin overrides → el modo conforme que verifican las 5
  comprobaciones de arriba.
- Desde `estimator/` o `estimator-web/` → con su propio override → el flujo de
  desarrollo de siempre (documentado en `CLAUDE.md`), sin cambios de
  comportamiento respecto a antes de esta sesión.
