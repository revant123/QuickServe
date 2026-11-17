# Docker for the QuickServe API

A beginner's guide to the API's `Dockerfile`, written as questions and answers.
This is Phase 5. Only the API image is covered here; the database already runs
in Docker through `docker-compose.yml`.

---

## The basics

### What is a Docker image, and what is a container?

An **image** is a packed box with everything the app needs to run: a small
Linux system, Python, our libraries and our code. A **container** is that box
running. You build one image and can start many containers from it, on your
laptop, in CI, or on a server in the cloud, and they all behave the same.

### Why does QuickServe need an image at all? It already runs with `uvicorn`.

On your Mac, the app depends on *your* Python, *your* `venv` and *your* settings.
A server in the cloud has none of that. The image carries all of it, so "it
works on my machine" becomes "it works on every machine". Cloud services such
as AWS ECS, Cloud Run and Kubernetes all run images, so this is the step that
makes the app deployable.

### What is a Dockerfile?

A recipe. Each line is one step: "start from this base", "copy these files",
"run this command". `docker build` follows the recipe and produces an image.

---

## The Dockerfile, line by line

### `FROM python:3.11-slim AS builder`

Start from the official Python 3.11 image, the **slim** variant: Debian Linux
with Python and very little else. It is much smaller than the full `python:3.11`
image, which ships compilers and tools we do not need at runtime. 3.11 is the
same version our CI tests on, so what passes in CI is what we ship.
`AS builder` gives this stage a name so the next stage can copy from it.

### `ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1`

`pip` normally keeps a cache of everything it downloads. Inside an image that
cache is dead weight, so we turn it off. The version check is just noise in
the build log.

### `RUN python -m venv /opt/venv` and `ENV PATH="/opt/venv/bin:$PATH"`

Create a virtual environment in one known folder, and put it first on `PATH`
so `pip` and `python` mean the ones inside it. Having all libraries in one
folder is what lets the next stage copy them in a single step.

### `COPY requirements.lock .` then `RUN pip install -r requirements.lock`

Install our runtime libraries (FastAPI, SQLAlchemy, psycopg and so on). Only
runtime packages are installed, not pytest, ruff or other test tools: they
have no place in production.

Why the `.lock` file and not `requirements.txt`? `requirements.txt` pins the
libraries we chose, but not *their* dependencies. Build the same commit next
month and pip could pick a newer sub-dependency that the tests never saw.
`requirements.lock` pins all 37 packages, so every build of a commit gets the
packages that commit was tested with. CI checks that its versions match
`requirements-dev.lock`, which is what the tests ran on.

Why copy the lock file *on its own, before the code*? Docker caches every
step. If `requirements.lock` has not changed, Docker reuses the installed
libraries from last time and skips the slow install, even when you changed
the app code. Copying the code first would break that cache on every edit.

### `FROM python:3.11-slim AS runtime`

The second `FROM` starts a **brand-new, empty** stage. Nothing from the builder
comes along unless we copy it explicitly. See "What is a multi-stage build?"
below.

### `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=...`

- `PYTHONDONTWRITEBYTECODE=1`: don't write `.pyc` cache files. They only help
  start-up a little and the app user cannot write to the code folder anyway.
- `PYTHONUNBUFFERED=1`: print log lines immediately instead of holding them in
  a buffer, so `docker logs` shows them live, and none are lost if the
  container crashes.
- `PATH`: use the venv we are about to copy in.

### `RUN groupadd ... && useradd ... app`

Create an ordinary user called `app` (user id 10001) that cannot log in and has
no home folder. See "Why run as a non-root user?" below.

### `WORKDIR /srv/quickserve`

The folder the app lives in and runs from (created if missing). Same idea as
`cd ~/quickserve` before you run `uvicorn`.

### `COPY --from=builder /opt/venv /opt/venv`

Take the finished virtual environment out of the builder stage. This is the
only thing the runtime stage takes from the builder.

### `COPY app/`, `COPY migrations/`, `COPY alembic.ini`, `COPY scripts/`

Copy only what the running API needs:

| Copied | Why |
|---|---|
| `app/` | The FastAPI application itself |
| `migrations/` and `alembic.ini` | So the same image can run `alembic upgrade head` to create or update tables |
| `scripts/` | So the same image can run `python -m scripts.seed` |

Tests, docs, `.git` and your `venv` are not copied. The files are owned by root,
so the `app` user can read them but cannot change them.

### `USER app`

From here on, everything, including the running server, runs as `app`
instead of `root`.

### `EXPOSE 8000`

Documentation for humans and tools: "this container listens on port 8000".
It does **not** open the port to your Mac by itself. That is what
`-p 8001:8000` in `docker run` does.

### `HEALTHCHECK ... CMD ["python", "-c", "...urlopen('http://127.0.0.1:8000/health')..."]`

Every 30 seconds Docker calls `/health` inside the container. Three failures
in a row mark the container **unhealthy**, and orchestrators like ECS or
Kubernetes can restart it automatically. `--start-period=10s` gives the app
time to boot before failures count.

The slim image has no `curl`, so the check uses Python's built-in `urllib`
instead of installing an extra tool.

It checks `/health` (is the process alive?) rather than `/health/ready` (can
it reach the database?). If the database has a short outage, we don't want
every API container killed and restarted. That would make things worse, not
better.

### `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`

The command the container runs when it starts.

- `--host 0.0.0.0`: listen on all network interfaces. The default,
  `127.0.0.1`, would only accept connections from *inside* the container,
  so `-p` port mapping would reach nothing.
- **No `--reload`.** Reload watches files and restarts on every edit. That is
  handy on your laptop, but an image's code never changes, and the file
  watcher wastes CPU.
- The JSON-list form (called "exec form") makes uvicorn the container's main
  process, so `docker stop` reaches it directly and it shuts down cleanly.

---

## Concepts

### What is a multi-stage build?

A Dockerfile with more than one `FROM`. Each `FROM` starts a separate stage,
and only the **last** stage becomes the image you ship.

Think of a kitchen: the builder stage is where you chop, cook and make a mess;
the runtime stage is the clean plate that goes to the customer. Whatever
`pip install` leaves behind (downloaded archives, temporary build files, pip's
own tooling) stays in the builder. The final image gets only the finished
`/opt/venv` and our code.

Benefits: a smaller image, and less software inside it that could have
security bugs.

### Why run as a non-root user?

By default, a container runs everything as `root`, the all-powerful admin
user. If an attacker found a bug in our app (or in a library we use) that let
them run commands, they would be root inside the container, which makes it
much easier to tamper with files or try to escape to the host machine.

As the `app` user, they can't install software, change the app's code or read
other users' files. This is the "least privilege" principle: give a program
only the rights it needs. Many companies and platforms (Kubernetes
`runAsNonRoot`, for example) refuse to run root containers at all.

Check it yourself:

```bash
docker run --rm quickserve-api:dev whoami     # prints: app
```

### Why is there a `.dockerignore`?

When you run `docker build .`, Docker first sends the whole folder (the "build
context") to the Docker engine. `.dockerignore` lists what to leave out:

- **Secrets.** `.env` holds passwords and keys. Excluding it means a
  careless `COPY . .` can never bake them into an image that gets pushed to
  a registry.
- **Speed.** `venv/` and `.git/` can be hundreds of MB. Sending them on
  every build is slow, and they're useless in the image.
- **Cache hits.** Fewer files means fewer unrelated changes that make Docker
  think it has to rebuild.
- **No surprises.** Your local `__pycache__` or test files can't leak into
  production.

### How does image size relate to cost?

You pay for an image every time it is stored or moved:

| Where | Why size costs money |
|---|---|
| **Registry storage** | Registries such as Amazon ECR charge per GB per month, for *every* version you keep. Ten versions of a 1 GB image cost about ten times more than ten versions of a 100 MB one. |
| **Pull time** | Every new server or container must download the image before it can start. A smaller image starts faster, which matters most during autoscaling: when traffic spikes, slow pulls mean customers wait. |
| **Data transfer** | Pulling across regions or over the internet is billed per GB, and NAT gateways charge for traffic passing through them. |
| **CI minutes** | Building and pushing a big image takes longer, and CI time is billed per minute. |
| **Security work** | More packages means more vulnerability alerts to look into. That costs engineer time. |

This image takes **about 387 MB on disk** once unpacked, and the compressed
download is **about 82 MB**. Roughly 130 MB of the unpacked size is our
Python libraries, and our own code is only about 0.3 MB. The rest is the
Python base image. Run `docker images quickserve-api` to see the current
numbers.

---

## Commands

### How do I build the image?

```bash
cd ~/quickserve
docker build -t quickserve-api:dev .
docker images quickserve-api        # shows the image size
```

`-t quickserve-api:dev` names (tags) the image; `.` means "use this folder".

### How do I run it against my local database and Redis?

The containers from `docker-compose.yml` listen on your Mac: the database on
port 5434 and Redis on port 6380. Inside a container, `localhost` means *the
container itself*, so we use `host.docker.internal`, Docker Desktop's name for
"the Mac running Docker".

```bash
docker compose up -d                # make sure the database and Redis are running

docker run --rm -d --name quickserve-api-test -p 8001:8000 \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@host.docker.internal:5434/quickserve \
  -e REDIS_URL=redis://host.docker.internal:6380/0 \
  quickserve-api:dev

curl http://127.0.0.1:8001/health/ready
# {"status":"ready","database":"ok","redis":"ok"}

docker stop quickserve-api-test
```

- `--rm`: delete the container when it stops.
- `-d`: run in the background ("detached").
- `-p 8001:8000`: your Mac's port 8001 → the container's port 8000. We use
  8001 so it doesn't clash with your `uvicorn --reload` dev server on 8000.
- `-e DATABASE_URL=...`: settings come from environment variables, the same
  as `.env` on your laptop. The image itself contains no settings or secrets.
- `-e REDIS_URL=...`: where Redis is (menu cache, login rate limits, logout).

### How do I run the background worker with the same image?

The worker (`python -m app.worker`) runs the order timeout job every 30
seconds. It uses the **same image** as the API. Only the command at the end
changes, and that replaces the Dockerfile's `CMD`:

```bash
docker run --rm -d --name quickserve-worker-test \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@host.docker.internal:5434/quickserve \
  -e REDIS_URL=redis://host.docker.internal:6380/0 \
  quickserve-api:dev python -m app.worker

docker logs -f quickserve-worker-test   # {"message": "worker started", ...}
docker stop quickserve-worker-test      # "worker stopped cleanly" in under a second
```

**Why one image for two jobs?** You build, scan and store a single image, and
the API and worker can never end up running different versions of the code.

**Why no `-p` for the worker?** Nobody connects to the worker. It only makes
outgoing connections to the database and Redis.

**What does `docker stop` do to it?** Docker sends `SIGTERM`. The worker
catches it, finishes the pass it's in the middle of, and exits. If it hasn't
exited after 10 seconds, Docker kills it with `SIGKILL`. Because the Dockerfile
uses the exec form, Python is process 1 and receives that signal directly.

To run a single pass and exit (handy for testing):
`docker run --rm -e DATABASE_URL=... -e REDIS_URL=... quickserve-api:dev python -m app.worker --once`

### How do I see logs, health, and which user it runs as?

```bash
docker logs quickserve-api-test                                  # the app's output
docker inspect -f '{{.State.Health.Status}}' quickserve-api-test # starting / healthy / unhealthy
docker run --rm quickserve-api:dev whoami                        # app (not root)
```

### How do I run migrations or the seed script with the image?

The same image can run a one-off command instead of the server:

```bash
docker run --rm \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@host.docker.internal:5434/quickserve \
  quickserve-api:dev alembic upgrade head

docker run --rm \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@host.docker.internal:5434/quickserve \
  quickserve-api:dev python -m scripts.seed
```

### Anything to change before deploying it for real?

Yes. Outside local development the app refuses to start with the built-in
development JWT secret. Set real values through your platform's secrets
manager, never in the Dockerfile or in Git:

```bash
-e ENVIRONMENT=production
-e JWT_SECRET_KEY=<long random secret>
-e DATABASE_URL=<real database URL>
-e REDIS_URL=<real Redis URL>
```

## Running it all with Docker Compose

The `docker run` commands above are the manual way, good for seeing what each
flag does. Day to day, `docker-compose.yml` does the same with one command.
Its `app` profile builds this image and runs it three ways (migration job,
API, worker) next to the database and Redis:

```bash
docker compose --profile app up -d --build
docker compose --profile app exec api python -m scripts.seed
open http://127.0.0.1:8001/docs
docker compose --profile app down
```

Inside Compose's network the containers use `db:5432` and `redis:6379`
instead of `host.docker.internal`. The README's Docker Q&A explains why.
