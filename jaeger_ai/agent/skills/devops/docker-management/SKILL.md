---
name: docker-management
description: "Manage Docker containers, images, volumes, networks, and Compose stacks — run/stop/debug containers, build images, free disk space, review Dockerfiles. Load this for 'start a postgres container', 'why is my container crashing', 'docker is eating my disk', or any docker/compose CLI work."
version: 1.1.0
platforms: [linux, macos, windows]
requires_tools: [terminal, read_file, write_file]
metadata:
  jros:
    tags: [docker, containers, devops, compose, images, volumes, networks, debugging]
    category: devops
    related_skills: [opencode, spike]
---

# DOCKER MANAGEMENT

Everything runs through the `terminal` tool with the standard `docker` CLI.
No pip installs, no SDK — the CLI is the whole interface.

## TOOLS

- `terminal(command="docker ...")` — every docker / docker compose operation.
- `read_file(path)` — inspect an existing Dockerfile / compose.yml before advising.
- `write_file(path, content)` — author or fix a Dockerfile / compose.yml.

## SOP

1. PRECHECK: `terminal(command="docker --version && docker compose version")`.
   If the daemon is down ("Cannot connect to the Docker daemon") stop and tell
   the user to start Docker Desktop / dockerd — don't retry.
2. CLASSIFY the request: lifecycle (run/stop/rm) | interaction (logs/exec/cp) |
   images (build/pull/prune) | compose | volumes+networks | disk cleanup |
   Dockerfile review.
3. LOOK BEFORE YOU ACT: `docker ps -a` (state), `docker images` (what exists),
   or `read_file` the Dockerfile/compose.yml. Never guess a container name.
4. ACT with the commands below. One command per terminal call so failures are
   attributable.
5. VERIFY (see DONE WHEN) before reporting success.

## CORE COMMANDS

Run:      docker run -d --name web -p 8080:80 nginx
Env:      docker run -d -e POSTGRES_PASSWORD=secret --name db postgres:16
Volume:   docker run -d -v pgdata:/var/lib/postgresql/data --name db postgres:16
Limits:   docker run -d --memory=512m --cpus=1.5 --restart=unless-stopped --name app my-app
Debug:    docker run -it --rm ubuntu:22.04 /bin/bash
Stop/rm:  docker stop NAME && docker rm NAME     (rm -f forces a running one)
Logs:     docker logs --tail 100 -f NAME         (--since 2h also works)
Shell:    docker exec -it NAME /bin/sh
Copy:     docker cp NAME:/path/file ./local
Inspect:  docker inspect NAME | docker stats --no-stream | docker top NAME
Build:    docker build -t my-app:latest .        (--no-cache for clean rebuild)
Push:     docker tag my-app:latest reg/my-app:v1 && docker push reg/my-app:v1

Key run flags: -d detached, -it interactive, --rm auto-remove, -p host:container,
-e env, -v volume, --name, --restart.

## COMPOSE

Up:       docker compose up -d          (--build to rebuild first)
Down:     docker compose down           (-v ALSO DELETES VOLUMES — data loss)
Status:   docker compose ps
Logs:     docker compose logs -f api
Shell:    docker compose exec api /bin/sh
One-off:  docker compose run --rm api npm test
Validate: docker compose config
Services reach each other by SERVICE NAME as hostname, not localhost.
Full compose.yml example with healthcheck: read_file("references/reference.md").

## DISK CLEANUP — diagnose, then targeted prune

1. `docker system df -v` — see what's actually using space.
2. Safe prunes: `docker container prune`, `docker image prune`,
   `docker volume prune`, `docker network prune`.
3. `docker system prune -a --volumes` DELETES NAMED VOLUMES. Never run it
   without the user explicitly confirming this exact command.

## VOLUMES + NETWORKS

docker volume ls | create NAME | inspect NAME | rm NAME
docker network ls | create NAME | inspect NAME | connect NET CONTAINER

## TROUBLESHOOTING MAP

- Exits immediately → `docker logs NAME`; then
  `docker run -it --entrypoint /bin/sh IMAGE` to poke inside.
- "port is already allocated" → `docker ps` or `lsof -i :PORT` to find the holder.
- "no space left on device" → DISK CLEANUP section above.
- Can't reach the app → app must bind 0.0.0.0 inside the container (not
  127.0.0.1); check the -p mapping with `docker port NAME`.
- Volume permission denied → UID mismatch; `--user $(id -u):$(id -g)`.
- Compose services can't see each other → wrong service name / network;
  `docker compose config` shows the resolved truth.

## DOCKERFILE REVIEW

`read_file` the Dockerfile, then check: multi-stage build; deps copied before
source (cache order); combined RUN layers; .dockerignore exists; pinned base
tag (node:20-alpine, never :latest); slim/alpine base; non-root USER.
Rewrite with `write_file`, rebuild, compare `docker images` sizes.
Details + rationale: read_file("references/reference.md").

## ERROR HATCH

If a docker command errors twice with the same message, stop retrying —
`docker logs` / `docker inspect` the object for the real cause, and if the
syntax is in doubt run `docker COMMAND --help` instead of guessing flags.

## DONE WHEN

The requested state is VERIFIED, not assumed:
- container work → `docker ps` shows Up and `docker logs --tail 20` is clean;
- image work → the tag appears in `docker images`;
- compose work → `docker compose ps` shows every service running/healthy;
- cleanup → `docker system df` shows the space actually freed (before/after);
and the outcome is reported to the user in one or two plain sentences.
