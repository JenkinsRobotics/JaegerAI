# Docker reference — compose example + Dockerfile optimization detail

Overflow from SKILL.md. Fetch on demand.

## Minimal compose.yml with healthcheck + dependency ordering

```yaml
services:
  api:
    build: .
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgres://user:pass@db:5432/mydb
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: mydb
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

Notes:
- `depends_on.condition: service_healthy` gates api start on the db healthcheck.
- Services address each other by service name (`db:5432`), never localhost.
- Named volume `pgdata` survives `docker compose down` (but not `down -v`).

## Dockerfile optimization — the seven checks, with rationale

1. Multi-stage builds — build toolchain in stage one, copy only the artifact
   into a slim runtime stage. Often cuts image size 5-10x.

   ```dockerfile
   FROM node:20-alpine AS build
   WORKDIR /app
   COPY package*.json ./
   RUN npm ci
   COPY . .
   RUN npm run build

   FROM node:20-alpine
   WORKDIR /app
   COPY --from=build /app/dist ./dist
   COPY --from=build /app/node_modules ./node_modules
   USER node
   CMD ["node", "dist/main.js"]
   ```

2. Layer ordering — COPY dependency manifests and install BEFORE copying
   source. Source edits then reuse the cached dependency layer.
3. Combine RUN commands — `RUN apt-get update && apt-get install -y x y \
   && rm -rf /var/lib/apt/lists/*` in ONE layer, so the cleanup actually
   shrinks the image (a later-layer delete doesn't).
4. .dockerignore — exclude node_modules, .git, __pycache__, dist, .env.
   Smaller build context, faster builds, no secret leakage.
5. Pin base versions — `python:3.12-slim`, never `:latest` (unreproducible).
6. Non-root USER — add a `USER` instruction after setup; containers running
   as root are a lateral-movement gift.
7. Slim/alpine bases — `python:3.12-slim` not `python:3.12`; check first that
   your wheels/native deps exist for musl before choosing alpine for Python.

## Image cleanup filters

```bash
docker image prune                             # dangling only (safe)
docker image prune -a                          # ALL unused images
docker image prune -a --filter "until=168h"    # unused + older than 7 days
```

## BuildKit

`DOCKER_BUILDKIT=1 docker build -t my-app .` — parallel stages, better cache,
`--mount=type=cache` support. Default on modern Docker; set explicitly on old
installs.
