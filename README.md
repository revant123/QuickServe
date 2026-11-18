# QuickServe

[![CI](https://github.com/revant123/quickserve/actions/workflows/ci.yml/badge.svg)](https://github.com/revant123/quickserve/actions/workflows/ci.yml)

A cloud-native food ordering and delivery platform built using Python, FastAPI, SQLAlchemy, and PostgreSQL. Developed with a modular monolith architecture, gradually incorporating Docker, CI/CD, AWS, Kubernetes, Terraform, monitoring, and FinOps practices.

It is built to learn three things properly:

1. **How an ORM works**: what SQLAlchemy writes for you, what it hides, and where you still need SQL.
2. **DevOps**: migrations, real-database tests, CI, health checks, connection pools, and later Docker, AWS, Terraform and Kubernetes.
3. **FinOps**: measuring what each order costs to serve, and spotting waste before it becomes a bill.

The business logic is modelled on how Zomato and Swiggy behave: restaurants must accept orders within a time limit, items can be switched off "until 6 pm", every bill is itemised with fees and GST, and payments are safe to retry. The centrepiece is the **stock / consumed / cycle** inventory design, which makes best sellers, sell-through, waste tracking and restock suggestions possible.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x (2.0-style API, pinned at 2.1.9), PostgreSQL 16, Redis 7, Alembic, pytest, Docker, Kubernetes (Gateway API, Envoy Gateway, cert-manager), Terraform, Prometheus, Grafana, GitHub Actions. **204 tests**, all run against real PostgreSQL and Redis, including concurrency tests with real threads, attacks on the login system and Redis outages.

---

## Contents

1. [Run it (step by step)](#1-run-it-step-by-step)
2. [What it does: the requirements checklist](#2-what-it-does-the-requirements-checklist)
3. [Architecture](#3-architecture)
4. [The inventory design: stock, consumed and cycles](#4-the-inventory-design-stock-consumed-and-cycles)
5. [ORM vs writing SQL by hand](#5-orm-vs-writing-sql-by-hand)
6. [Business rules borrowed from Zomato and Swiggy](#6-business-rules-borrowed-from-zomato-and-swiggy)
7. [Login, tokens and permissions](#7-login-tokens-and-permissions)
8. [Redis, the background worker and logs (Phase 4)](#8-redis-the-background-worker-and-logs-phase-4)
   - [Docker: the app in containers (Phase 5)](#docker-the-app-in-containers-phase-5)
   - [AWS and Terraform (Phase 6)](#aws-and-terraform-phase-6)
   - [Kubernetes (Phase 7)](#kubernetes-phase-7)
   - [Monitoring (Phase 7b)](#monitoring-phase-7b)
   - [Notifications and the outbox pattern (Phase 8)](#notifications-and-the-outbox-pattern-phase-8)
   - [Alert emails and rightsizing (Phase 8b: FinOps)](#alert-emails-and-rightsizing-phase-8b-finops)
   - [HTTPS front door: Gateway API (Phase 9)](#https-front-door-gateway-api-phase-9)
   - [Network policies (Phase 10)](#network-policies-phase-10)
   - [Pricing like Zomato and Swiggy (Phase 11)](#pricing-like-zomato-and-swiggy-phase-11)
   - [Discovery: near me, search and ratings (Phase 12)](#discovery-near-me-search-and-ratings-phase-12)
9. [DevOps already in the project](#9-devops-already-in-the-project)
10. [FinOps: thinking in cost per order](#10-finops-thinking-in-cost-per-order)
11. [Bugs the tests caught while building this](#11-bugs-the-tests-caught-while-building-this)
12. [Project structure and API](#12-project-structure-and-api)
13. [Roadmap](#13-roadmap)
14. [Interview cheat sheet](#14-interview-cheat-sheet)
15. [References](#15-references)

---

## 1. Run it (step by step)

There are two ways to run QuickServe:

- **Steps 1 to 9 (developer mode):** PostgreSQL and Redis run in Docker, the API runs on your machine with `--reload`, so code edits apply instantly. Use this while changing code.
- **[Shortcut: everything in Docker](#shortcut-everything-in-docker-no-python-setup)** (below step 9): one command builds the image and starts the database, Redis, migrations, API and worker. No Python setup needed. Use this to see it run the way a server runs it.

**You need:** Python 3.11 or newer, Git, and either **Docker Desktop** (easiest) or **PostgreSQL 16** installed on your machine.

### Step 1: Get the code

```bash
git clone https://github.com/revant123/quickserve.git
cd quickserve
```

### Step 2: Start PostgreSQL

**Option A: with Docker (recommended)**

```bash
docker compose up -d       # starts PostgreSQL 16 and Redis 7; on first start it also creates quickserve and quickserve_test
docker compose ps          # wait until STATUS shows "healthy" and PORTS shows 0.0.0.0:5434->5432/tcp
```

QuickServe's database listens on port **5434** on your machine, not the usual 5432. That way it runs at the same time as QuickKart, whose databases already use 5432 and 5433.

**Ports used on the machine:**

| Project | Ports |
|---|---|
| QuickKart | 5432 (database), 5433 (test database), 8080, 1025, 8025 |
| QuickServe | 5434 (database), 6380 (Redis), 8000 (API in developer mode), 8001 (API in Docker) |

**Option B: without Docker.** Install PostgreSQL 16, make sure user `postgres` has password `postgres`, then create the two databases. Your own PostgreSQL normally listens on 5432, so in step 4 change the port in `DATABASE_URL` from `5434` to `5432`.

```bash
psql -U postgres -c "CREATE DATABASE quickserve;"
psql -U postgres -c "CREATE DATABASE quickserve_test;"
```

### Step 3: Create a virtual environment and install dependencies

```bash
python -m venv venv                 # on Mac/Linux you may need: python3 -m venv venv
source venv/bin/activate            # Windows PowerShell: venv\Scripts\Activate.ps1
                                    # Windows cmd:        venv\Scripts\activate.bat
pip install -r requirements-dev.txt
```

### Step 4: Create your `.env`

```bash
cp .env.example .env                # Windows: copy .env.example .env
```

### Step 5: Create the tables (run the migrations)

```bash
alembic upgrade head
```

### Step 6: Load demo data

```bash
python -m scripts.seed
```

This creates two restaurants with menus and four demo accounts (customer, restaurant owner, rider, admin), and prints their emails and passwords.

### Step 7: Start the API and the worker

```bash
uvicorn app.main:app --reload       # terminal 1: the API
python -m app.worker                # terminal 2 (venv active): runs the order timeout job every 30 seconds
```

### Step 8: Check it works

| Open or run | You should see |
|---|---|
| http://127.0.0.1:8000/health/ready | `{"status":"ready","database":"ok","redis":"ok"}` |
| http://127.0.0.1:8000/docs | Swagger UI with every endpoint |
| `pytest -q` (in another terminal, venv active) | `204 passed` |

### Step 9: Place your first order in Swagger

In Swagger, every step works the same way: click the endpoint, click **Try it out**, fill in the fields, click **Execute**.

**As the customer:**

1. Click **Authorize** (top right). Username `customer@quickserve.dev`, password `customer-pass-123`. Click **Authorize**, then **Close**.
2. `GET /api/v1/restaurants`: copy the `id` of Pal Dhaba.
3. `GET /api/v1/restaurants/{restaurant_id}/menu`: copy the `id` of a dish.
4. `POST /api/v1/orders`. No customer id needed: the order belongs to whoever is logged in.
   ```json
   {
     "restaurant_id": "PASTE_RESTAURANT_ID",
     "delivery_address": "House 5, Sector 15, Chandigarh",
     "items": [{"menu_item_id": "PASTE_MENU_ITEM_ID", "quantity": 2}]
   }
   ```
   The response has the itemised bill. Copy the order `id`.
5. `POST /api/v1/orders/{order_id}/payments` with `Idempotency-Key: my-first-payment`. Execute it twice: the second time you get `200` and `idempotent-replayed: true`, not a second charge.

**As the restaurant owner:**

6. Click **Authorize**, then **Logout**, and log in as `owner@quickserve.dev` / `owner-pass-123`.
7. `PATCH /api/v1/orders/{order_id}/status` with `{"status": "ACCEPTED"}`. There's no "actor" field: the server knows you're the owner from your token.
8. `GET /api/v1/orders/{order_id}/timeline`: every status change, who made it and when.
9. `POST /api/v1/menu/{menu_item_id}/restock` with `{"quantity": 40}`. The response shows the archived cycle and `consumed` reset to 0.
10. `GET /api/v1/restaurants/{restaurant_id}/best-sellers` and `GET /api/v1/menu/{menu_item_id}/restock-suggestion`.

**See the permissions work:** log out and try `POST /api/v1/orders` (you get `401`), or log in as the customer and try the restock (you get `403`). [Section 7](#7-login-tokens-and-permissions) explains every rule.

### Shortcut: everything in Docker (no Python setup)

Needs only Docker Desktop and the code (step 1). Open the **Terminal** app, `cd` into the `quickserve` folder, and run:

```bash
docker compose --profile app up -d --build                # build the image, start all five containers
docker compose --profile app ps                           # wait until api shows "healthy"; migrate shows "Exited (0)"
docker compose --profile app exec api python -m scripts.seed   # load the demo restaurants and accounts
```

Then open **http://127.0.0.1:8001/docs** (note **8001**, not 8000) and follow step 9. What starts:

| Container | What it does | Port on your Mac |
|---|---|---|
| `quickserve-db` | PostgreSQL 16 | 5434 |
| `quickserve-redis` | Redis 7 | 6380 |
| `migrate` | Runs `alembic upgrade head`, then exits | none |
| `quickserve-api` | The API (`uvicorn`) | **8001** |
| `quickserve-worker` | The order timeout job, every 30 seconds | none |
| `quickserve-notifier` | Turns order events from the outbox into notifications (Phase 8) | none |

The API uses **8001** so it can run at the same time as the developer-mode server on 8000, and none of these ports clash with QuickKart.

```bash
docker compose --profile app logs -f api worker   # watch the JSON logs (Ctrl+C stops watching, not the app)
docker compose --profile app down                 # stop everything (add -v to also delete the data)
```

Keep `--profile app` in the `down` command too. A plain `docker compose down` only stops the services without a profile (the database and Redis) and leaves the API and worker running [34].

Changed some code? Run the `up -d --build` command again: Docker rebuilds only what changed (usually a few seconds) and replaces the containers. How the image is built, line by line, is in [docs/docker.md](docs/docker.md); why it's set up this way is in [the Docker Q&A](#docker-the-app-in-containers-phase-5).

### Other useful commands

```bash
python -m scripts.race_demo        # watch a naive stock counter oversell, next to the atomic one
python -m scripts.show_sql         # print the SQL the ORM generates for our key queries
ruff check . && ruff format --check .
alembic upgrade head --sql         # print a migration's SQL without running it
docker compose down                # stop PostgreSQL and Redis (add -v to also delete the data)
docker compose exec redis redis-cli --scan   # list what's in Redis right now
python -m app.worker --once        # run the timeout job one time
```

Set `SQL_ECHO=true` in `.env` and restart uvicorn to see every SQL statement in the terminal. It's the fastest way to learn what the ORM is doing.

### If something goes wrong

| Error | Fix |
|---|---|
| `Connection refused` on port 5434 | PostgreSQL isn't running. `docker compose ps`, or start your local PostgreSQL service (and set port 5432 in `.env`) |
| `password authentication failed` | The user or password in `DATABASE_URL` (in `.env`) doesn't match your PostgreSQL |
| `password authentication failed for user "postgres"` | The app is reaching a different PostgreSQL than QuickServe's. Check that `.env` uses port **5434** (copy `.env.example` again if you made `.env` earlier) and that `docker compose ps` shows `0.0.0.0:5434->5432/tcp` |
| `port is already allocated` (Docker) | Something else already uses 5434. Pick a free port, e.g. `"5435:5432"` in `docker-compose.yml`, and the same number in `.env` |
| `database "quickserve_test" does not exist` | The Docker init script runs only on the very first start. Run `docker compose exec db psql -U postgres -c "CREATE DATABASE quickserve_test;"` |
| `/health/ready` says `"redis": "down ..."` | The app still works without Redis (no cache, no login limits). Check `docker compose ps` shows `quickserve-redis` healthy with `0.0.0.0:6380->6379/tcp`, and that `.env` has `REDIS_URL=redis://localhost:6380/0` (copy it from `.env.example`) |
| `ModuleNotFoundError: No module named 'app'` | Run commands from the repository root with the venv activated |
| PowerShell won't run `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again |
| `docker compose --profile app up` says `port is already allocated` for 8001 | Another container from an earlier test still holds it: `docker ps` to find it, `docker stop <name>` |
| `docker compose down` says a network is `still in use` | The API and worker are still running. Use `docker compose --profile app down` |
| `quickserve-api` stays `unhealthy` or keeps restarting | `docker compose --profile app logs api` shows why. If `migrate` failed, `docker compose --profile app logs migrate` |
| Tests say `Refusing to run tests ...` | Safety guard: tests empty their database, so they only run on a database whose name ends in `_test` and on Redis database number 15. Unset any `DATABASE_URL` or `REDIS_URL` you exported in your shell |

---

## 2. What it does: the requirements checklist

| Requirement | Where it lives |
|---|---|
| Focus on how the ORM compares with writing SQL by hand | [Section 5](#5-orm-vs-writing-sql-by-hand); `app/modules/menu/analytics.py` (same report in ORM and raw SQL, tested equal); `scripts/show_sql.py`; `scripts/race_demo.py`; `tests/test_orm_behaviour.py` |
| DevOps and FinOps as the top priority | [Section 9](#9-devops-already-in-the-project) and [Section 10](#10-finops-thinking-in-cost-per-order); `.github/workflows/ci.yml`; `docker-compose.yml`; health checks; connection pool settings; lock file |
| Real business logic from Zomato / Swiggy | [Section 6](#6-business-rules-borrowed-from-zomato-and-swiggy): accept timeout, out-of-stock-until, itemised bill with platform fee and GST, cancellation rules, idempotent payments. [Phase 11](#pricing-like-zomato-and-swiggy-phase-11): distance-based delivery fee, free delivery rules, small order fee, peak/late-night/rain surge, coupons with race-safe limits, quotes with price-change protection. [Phase 12](#discovery-near-me-search-and-ratings-phase-12): restaurants near me with delivery time, ranking by rating, typo-tolerant search, reviews only for delivered orders |
| Stock + consumer logic instead of QuickKart's `stock - 1` | [Section 4](#4-the-inventory-design-stock-consumed-and-cycles); `app/modules/menu/model.py` |
| Restock resets the consumer counter to zero | `restock()` in `app/modules/menu/service.py`, which archives the cycle first so no data is lost |
| Use it to find and showcase the best seller | `GET /restaurants/{id}/best-sellers`; ranking explained in Section 4 |
| Any other benefits of this design | The 11-point list in Section 4: sell-through, sold-out time, waste, badges, restock suggestion, audit trail and more |
| Login, roles and permissions (Phase 3) | [Section 7](#7-login-tokens-and-permissions); `app/modules/auth/`, `app/core/security.py`, `tests/test_auth.py` |
| Discovery: near me, search, ratings (Phase 12) | [Discovery Q&A](#discovery-near-me-search-and-ratings-phase-12); `app/modules/discovery/` (near me, ETA, Bayesian rating, search), `app/modules/reviews/`, `app/modules/pricing/geo.py` (bounding box), `tests/test_discovery.py`, `tests/test_reviews.py` |
| Pricing, coupons and surge (Phase 11) | [Pricing Q&A](#pricing-like-zomato-and-swiggy-phase-11); `app/modules/pricing/` (calculator, geo, rain switch), `app/modules/coupons/`, `POST /orders/quote`, `tests/test_pricing.py`, `tests/test_checkout.py` |
| Network policies (Phase 10) | [Network policy Q&A](#network-policies-phase-10); `infra/k8s/network-policies/`, `infra/k8s/netpol_check.sh`, `infra/k8s/smoke.sh` |
| HTTPS front door (Phase 9) | [Gateway Q&A](#https-front-door-gateway-api-phase-9); `infra/k8s/gateway/` (certificates, Gateway, routes, policies), `infra/k8s/addons.sh`, `infra/k8s/gateway_check.sh`, `app/core/client_ip.py`, `tests/test_client_ip.py` |
| Alert emails and rightsizing (Phase 8b: FinOps) | [Phase 8b Q&A](#alert-emails-and-rightsizing-phase-8b-finops); `infra/k8s/monitoring/alertmanager.yml` + `alertmanager.yaml` (Alertmanager, Mailpit), the Watchdog and rightsizing rules in `rules.yml`, `infra/k8s/rightsizing.py`, `tests/test_rightsizing.py` |
| Notification service with the outbox pattern (Phase 8) | [Outbox Q&A](#notifications-and-the-outbox-pattern-phase-8); `app/modules/outbox/`, `app/modules/notifications/`, `app/notifier.py`, `infra/k8s/base/notifier.yaml`, `tests/test_notifications.py` |
| Monitoring and alerts (Phase 7b) | [Monitoring Q&A](#monitoring-phase-7b); `app/core/metrics.py`; `infra/k8s/monitoring/` (Prometheus config, `rules.yml` + `rules_test.yml`, Grafana dashboard); worker `--healthcheck`; `tests/test_metrics.py` |
| Kubernetes (Phase 7) | [Kubernetes Q&A](#kubernetes-phase-7); `infra/k8s/` (Kustomize base + overlays, `deploy.sh`, `smoke_test.py`); `scripts/wait_for_migrations.py`; the `kubernetes` job in CI (kind cluster, zero-downtime rollout check) |
| AWS infrastructure as code (Phase 6) | [AWS and Terraform Q&A](#aws-and-terraform-phase-6); `infra/` with [infra/README.md](infra/README.md); 18 `terraform test` checks; the `terraform` job in CI |
| Image published to a registry (Phase 5b) | [Registry Q&A](#q-where-does-the-image-go-after-ci-builds-it); the `publish` job in `.github/workflows/ci.yml`; `ghcr.io/revant123/quickserve` |
| Dockerfile and the whole stack in Docker (Phase 5) | [Docker Q&A](#docker-the-app-in-containers-phase-5); `Dockerfile`, `.dockerignore`, `docker-compose.yml` (profile `app`), `requirements.lock`, [docs/docker.md](docs/docker.md), the `docker` job in CI |
| Redis cache, rate limiting, logout, worker, JSON logs (Phase 4) | [Section 8](#8-redis-the-background-worker-and-logs-phase-4); `app/core/redis.py`, `app/core/logging.py`, `app/worker.py`, `app/modules/menu/cache.py` |
| Everything in the README, as natural questions and answers | This file |

**What's built so far, and what isn't:**

| Area | Done | Not yet |
|---|---|---|
| Users and login | Registration, login with JWT access tokens, logout, login rate limiting (Redis), four roles (customer, restaurant owner, rider, admin), ownership checks on every restaurant and order, Argon2 password hashing via pwdlib as FastAPI's docs recommend [4] (passlib stopped working on Python 3.13 [23]) | Refresh tokens |
| Restaurants | Create, list with pagination, packaging charge | Opening hours, delivery radius |
| Menu and stock | Stock/consumed counters, stock cycles with archive, restock with or without carry-over, "out of stock until" timer, customer badges ("Only 3 left", "Selling fast") | Add-ons and variants (half/full plate) |
| Orders | All-or-nothing placement, itemised bill, price snapshots, status machine with actor rules, cancellation rules, full timeline | Rider assignment, ETA |
| Payments | Mock gateway, idempotency keys, one-success-per-order rule, refunds on rejection/cancellation | Real gateway, webhooks |
| Background jobs | A separate worker (`python -m app.worker`) expires unpaid orders and auto-rejects orders the restaurant didn't accept, every 30 seconds; safe to run several (`FOR UPDATE SKIP LOCKED`); graceful shutdown | |
| Caching, logs and metrics | Redis cache for the customer menu with invalidation; JSON logs with a request ID on every line; safe 500 responses; Prometheus metrics (RED + business), 6 tested alert rules, a Grafana dashboard with cost per order; Alertmanager emails with grouping, inhibition and a Watchdog; a rightsizing report priced in USD | Tracing, real cost data (OpenCost) |
| Analytics | Best sellers ranked by sales rate while in stock, sell-through, restock suggestion that corrects for sold-out cycles | Revenue reports, dashboards |
| DevOps | Alembic migrations (tested up and down), multi-stage Dockerfile running as a non-root user, the whole stack in Docker Compose (database, Redis, migration job, API, worker), CI that tests the code, smoke-tests the built containers and publishes a two-chip image tagged by commit to ghcr.io, AWS infrastructure in Terraform (tested with mocks, not yet applied), Kubernetes manifests deployed and tested on a kind cluster in every CI run (rolling update with zero failed requests), liveness/readiness checks, pinned and locked dependencies, an HTTPS front door (Gateway API with Envoy Gateway, certificates from cert-manager, host routing, an edge rate limit), network policies (default deny, one allow-list per component, enforcement proven in CI) | Applying the Terraform to a real AWS account, mTLS between pods |

Everything except browsing restaurants and menus needs a login. Orders belong to the logged-in customer, and who may change an order's status is decided by the login token, never by the request body. See [section 7](#7-login-tokens-and-permissions).

---

## 3. Architecture

### 3.1 The big picture: a modular monolith

One FastAPI application, one deployment, one PostgreSQL database, but split into **modules** with clear boundaries. Modules call each other only through small public functions, never by reaching into each other's tables. That keeps today's code simple, and it's what will let us lift a module (notifications, payments) out into its own service later without rewriting its callers.

```mermaid
flowchart TB
    client["Client: mobile app, web app or Swagger UI"] -->|"HTTPS + JSON"| router

    subgraph app["QuickServe API: one FastAPI process"]
        router["api/router.py, mounted at /api/v1"]
        authdep["auth: login, JWT check, current user"]
        subgraph modules["app/modules"]
            users["users: registration, profile"]
            rest["restaurants: create, list"]
            menu["menu: stock, cycles, availability, analytics"]
            orders["orders: placement, bill, state machine, timeout job"]
            pay["payments: mock gateway, idempotency, refunds"]
        end
        core["core: config, security, redis, logging, exceptions, money"]
        dbl["database: engine, connection pool, sessions"]
    end

    router -->|"every protected request"| authdep
    authdep --> users
    router --> users
    router --> rest
    router --> menu
    router --> orders
    router --> pay
    orders -->|"reserve and release stock"| menu
    orders -->|"refunds.refund_for_order()"| pay
    pay -->|"orders.mark_paid()"| orders
    users --> dbl
    rest --> dbl
    menu --> dbl
    orders --> dbl
    pay --> dbl
    dbl -->|"pooled connections"| pg[("PostgreSQL 16")]
    menu -->|"menu cache"| redisdb[("Redis 7")]
    authdep -->|"rate limits, logged-out tokens"| redisdb
    worker["app/worker.py: separate process, runs the timeout job every 30 s"] --> orders
    orders -->|"outbox event, same transaction"| outboxt[("outbox_events table")]
    notifier["app/notifier.py: separate process, the notifications service"] -->|"claims events"| outboxt
    notifier --> notif["notifications module"]
```

### 3.2 Inside every module: four layers

```mermaid
flowchart LR
    R["router.py: HTTP in and out, input checked by schema.py"] --> S["service.py: business rules and transactions"]
    S --> P["repository.py: queries"]
    P --> M["model.py: SQLAlchemy tables"]
```

| Layer | Knows about | Never does |
|---|---|---|
| `router.py` | HTTP, status codes, request/response schemas | Business decisions |
| `schema.py` | Pydantic validation, what the API accepts and returns | Touch the database |
| `service.py` | Business rules, transactions, calling other modules | Raise `HTTPException` (so the same code works from a job or a script) |
| `repository.py` | SQL and ORM queries, locks | Business decisions |
| `model.py` | Tables, columns, constraints, relationships | Anything else |

### 3.3 Data model

```mermaid
erDiagram
    USERS ||--o{ RESTAURANTS : owns
    USERS ||--o{ ORDERS : places
    RESTAURANTS ||--o{ MENU_ITEMS : offers
    RESTAURANTS ||--o{ ORDERS : receives
    MENU_ITEMS ||--o{ INVENTORY_CYCLES : "has history"
    MENU_ITEMS ||--o{ ORDER_ITEMS : "sold as"
    ORDERS ||--|{ ORDER_ITEMS : contains
    ORDERS ||--o{ ORDER_STATUS_EVENTS : "timeline"
    ORDERS ||--o{ PAYMENTS : "attempts"
    COUPONS ||--o{ COUPON_REDEMPTIONS : "used in"
    ORDERS ||--o| COUPON_REDEMPTIONS : "discounted by"
    RESTAURANTS ||--o{ COUPONS : "funds (optional)"
    ORDERS ||--o| REVIEWS : "rated in"
    RESTAURANTS ||--o{ REVIEWS : receives

    USERS {
        uuid id PK
        string email UK
        string password_hash
        enum role
    }
    RESTAURANTS {
        uuid id PK
        uuid owner_id FK
        numeric packaging_charge
        bool is_open
        numeric latitude
        numeric longitude
        numeric delivery_radius_km
        string cuisines
        int avg_prep_minutes
        int rating_count
        int rating_sum
    }
    REVIEWS {
        uuid id PK
        uuid order_id FK,UK
        uuid restaurant_id FK
        uuid customer_id FK
        smallint rating
        string comment
        timestamptz created_at
    }
    MENU_ITEMS {
        uuid id PK
        uuid restaurant_id FK
        numeric price
        bool is_available
        timestamptz unavailable_until
        bool track_stock
        int stock
        int consumed
        int cycle_no
        timestamptz sold_out_at
        tsvector search_vector
    }
    INVENTORY_CYCLES {
        uuid id PK
        uuid menu_item_id FK
        int cycle_no
        int units_stocked
        int units_consumed
        int units_returned
        int units_wasted
        int leftover
        timestamptz started_at
        timestamptz sold_out_at
        timestamptz closed_at
    }
    ORDERS {
        uuid id PK
        uuid customer_id FK
        uuid restaurant_id FK
        enum status
        numeric distance_km
        numeric delivery_fee
        numeric surge_fee
        numeric discount
        numeric grand_total
        timestamptz pay_by
        timestamptz accept_by
    }
    ORDER_ITEMS {
        uuid id PK
        uuid order_id FK
        uuid menu_item_id FK
        numeric unit_price
        int quantity
        int cycle_no
    }
    PAYMENTS {
        uuid id PK
        uuid order_id FK
        enum status
        string idempotency_key UK
    }
    ORDER_STATUS_EVENTS {
        uuid id PK
        uuid order_id FK
        enum from_status
        enum to_status
        string actor
    }
    COUPONS {
        uuid id PK
        string code UK
        enum kind
        numeric value
        uuid restaurant_id FK
        enum funded_by
        int max_uses_total
        int times_used
    }
    COUPON_REDEMPTIONS {
        uuid id PK
        uuid coupon_id FK
        uuid order_id FK, UK
        enum status
    }
```

The orders table shows only some of its bill columns; every line of the bill is stored. `surge_flags` (the rain switch, Phase 11) and the outbox tables (Phase 8) aren't drawn.

Rules the **database itself** enforces, so a bug in Python can't break them:

| Constraint | Rule |
|---|---|
| `ck_menu_items_stock_consistent` | `consumed <= stock` for tracked items; `stock` is NULL for untracked ones |
| `uq_inventory_cycles_one_open` (partial unique index) | At most one open stock cycle per item |
| `uq_payments_one_success_per_order` (partial unique index) | At most one successful payment per order |
| `uq_payments_idempotency_key` | A retried payment can't create a second charge |
| `uq_users_email` | No duplicate accounts, even with simultaneous sign-ups |
| `ck_order_items_quantity_positive`, `ck_menu_items_price_positive` | No zero/negative quantities or prices |
| `ck_coupons_uses_within_limit` | A coupon can never be recorded as used more times than its limit, even under a race or a bug (Phase 11) |
| `uq_coupon_redemptions_order_id` | At most one coupon per order; a retried request can't apply it twice |
| `uq_reviews_order_id` | One review per order, even if "Submit" is tapped twice at once (Phase 12) |
| `ck_restaurants_rating_totals_consistent` | `rating_sum` is between `rating_count` and 5 × `rating_count`: the running totals can't describe impossible reviews (Phase 12) |
| `ck_reviews_rating_1_to_5` | Stars are 1 to 5, whatever the API layer lets through |

### 3.4 What happens when a customer places and pays for an order

```mermaid
sequenceDiagram
    autonumber
    participant C as Customer app
    participant API as FastAPI router
    participant OS as orders.service
    participant DB as PostgreSQL

    C->>API: POST /api/v1/orders with Authorization: Bearer token
    API->>API: check the token, load the customer
    API->>OS: place_order(customer)
    OS->>DB: BEGIN
    loop each dish, in sorted id order (no deadlocks)
        OS->>DB: conditional UPDATE: consumed + qty, only if it stays within stock
        DB-->>OS: a row (reserved) or nothing (not enough left)
    end
    alt any dish short
        OS->>DB: ROLLBACK, earlier reservations are undone
        API-->>C: 409 Only 1 left of Dal Makhani
    else every dish reserved
        OS->>DB: INSERT order with bill, order_items with price and cycle snapshot, status event
        OS->>DB: COMMIT
        API-->>C: 201 order PLACED with itemised bill
    end

    C->>API: POST /api/v1/orders/{id}/payments with Idempotency-Key
    API->>DB: lock order row, re-check the key, insert payment, set PAID and accept_by
    API-->>C: 201 payment (a retry with the same key gets 200 and the same payment)
```

### 3.5 Order lifecycle

```mermaid
stateDiagram-v2
    [*] --> PLACED: order placed, stock reserved
    PLACED --> PAID: payment succeeds
    PLACED --> PAYMENT_FAILED: pay_by passes, stock released
    PLACED --> CANCELLED: customer cancels, stock released
    PAID --> ACCEPTED: restaurant accepts
    PAID --> REJECTED: restaurant rejects or 4 minute timeout, stock released and refund
    PAID --> CANCELLED: customer cancels, stock released and refund
    ACCEPTED --> PREPARING: restaurant starts cooking
    ACCEPTED --> CANCELLED: support only, stock released and refund
    PREPARING --> READY: packed
    PREPARING --> CANCELLED: support only, counted as waste and refund
    READY --> OUT_FOR_DELIVERY: rider picks up
    OUT_FOR_DELIVERY --> DELIVERED: rider delivers
    DELIVERED --> [*]
    CANCELLED --> [*]
    REJECTED --> [*]
    PAYMENT_FAILED --> [*]
```

### 3.6 The stock cycle

```mermaid
flowchart LR
    A["Cycle 1 opens: stock 20, consumed 0"] --> B["Orders: consumed 0 to 20, one atomic UPDATE each"]
    B --> C["consumed = stock: sold_out_at recorded"]
    C --> D["Restaurant restocks with 30"]
    D --> E["Archive cycle 1 in inventory_cycles: stocked 20, consumed 20, leftover 0, sold-out time"]
    E --> F["Cycle 2 opens: stock 30, consumed reset to 0"]
    E --> G[("Best sellers, sell-through, waste, restock suggestion")]
```

### 3.7 CI pipeline (runs on every push and pull request)

`test`, `docker`, `terraform` and `kubernetes` run side by side, so new jobs don't make CI slower. `publish` waits for `test` and `docker`.

```mermaid
flowchart LR
    push["git push or pull request"] --> pg
    push --> lock

    subgraph test["job: test"]
        pg["Start PostgreSQL 16 and Redis 7 service containers"] --> inst["pip install -r requirements-dev.lock"]
        inst --> lint["ruff check and ruff format --check"]
        lint --> mig["alembic upgrade head and alembic check"]
        mig --> pyt["pytest: 204 tests"]
    end

    subgraph docker["job: docker"]
        lock["requirements.lock matches the tested lock"] --> build["docker compose --profile app up --build"]
        build --> ready["wait for /health/ready"]
        ready --> smoke["seed, log in, call /users/me, check non-root user and worker"]
        smoke --> stop["SIGTERM the worker: stops cleanly?"]
        stop --> size["write image size to the run summary"]
    end

    pyt --> pub
    size --> pub

    subgraph publish["job: publish (needs test and docker)"]
        pub{"push to main?"} -->|"yes"| push["build amd64 + arm64, push to ghcr.io as sha-xxxxxxx and main"]
        pub -->|"pull request"| only["build amd64 only, don't push"]
    end

    push2["git push or pull request"] --> tf

    subgraph terraform["job: terraform (no AWS account needed)"]
        tf["terraform fmt -check"] --> val["init -backend=false and validate, every stack and module"]
        val --> tftest["terraform test: 18 checks with mock AWS"]
    end

    push3["git push or pull request"] --> kc

    subgraph kubernetes["job: kubernetes (throwaway kind cluster)"]
        kc["kubeconform: manifests match the API schema"] --> kp["promtool: config valid, alert rules unit-tested"]
        kp --> kb["build image, create kind cluster, load image"]
        kb --> kd["deploy.sh: postgres, redis, migrate Job, api, worker"]
        kd --> ks["seed, log in, non-root check"]
        ks --> kr["rolling restart: zero failed requests"]
        kr --> kh["delete a pod: replaced, still answering"]
        kh --> km["Prometheus scrapes every pod, no alerts firing; Grafana dashboard loaded"]
    end
```

### 3.8 The whole stack in Docker Compose (Phase 5)

```mermaid
flowchart LR
    you["You: browser or curl"] -->|"localhost:8001"| api

    subgraph net["Compose network: containers find each other by name"]
        migrate["migrate: alembic upgrade head, then exits"]
        api["api: uvicorn, port 8000 inside"]
        worker["worker: python -m app.worker"]
        db[("db: PostgreSQL 16")]
        redis[("redis: Redis 7")]
    end

    migrate -->|"db:5432"| db
    api -->|"db:5432"| db
    api -->|"redis:6379"| redis
    worker -->|"db:5432"| db
    worker -->|"redis:6379"| redis
```

Start order, enforced by `depends_on`: `db` healthy → `migrate` finishes with exit code 0 → `api` and `worker` start. If the migration fails, the API never starts with a half-updated schema.

### 3.9 Where it's heading (planned, Phases 6 to 8)

```mermaid
flowchart TB
    user["Customers and restaurants"] --> lb

    subgraph aws["AWS, built with Terraform"]
        subgraph public["Public subnet"]
            lb["Load balancer / Nginx, HTTPS"]
        end
        subgraph private["Private subnets"]
            app1["QuickServe container"]
            app2["QuickServe container"]
            redis[("Redis: menu cache")]
            rds[("RDS PostgreSQL")]
        end
        secrets["Secrets Manager"]
        budgets["AWS Budgets and Cost Explorer"]
    end

    lb --> app1
    lb --> app2
    app1 --> redis
    app2 --> redis
    app1 --> rds
    app2 --> rds
    app1 -.-> secrets
    app2 -.-> secrets
    prom["Prometheus and Grafana"] -.->|"scrape metrics"| app1
    prom -.->|"scrape metrics"| app2
```

The app already runs in containers (3.8); the AWS part of this diagram is the plan for the phases in the [roadmap](#13-roadmap).

---

## 4. The inventory design: stock, consumed and cycles

### Q: In QuickKart we did `stock -= 1` on every sale and stopped at 0. What's wrong with that?

It works for "can I sell one more?", but it throws away information:

- After a few sales you can't tell how many were prepared. `stock = 4` could mean "made 5, sold 1" or "made 50, sold 46".
- When you restock, you overwrite the number, and that cycle's sales are gone.
- So you can't compute a best seller fairly, can't measure waste, and can't learn how much to prepare tomorrow.

It also has a concurrency trap if the code reads the stock into Python, subtracts, and writes it back. That trap is covered further down.

### Q: So what does QuickServe do instead?

It keeps two numbers per item, which is your "consumer and stock" idea. In code the counter is called `consumed` because it counts units consumed:

```
stock      = units prepared for the current cycle   (fixed during the cycle)
consumed   = units ordered so far in this cycle     (goes up with each order)
available  = stock - consumed                       (computed, never stored)
```

A **cycle** runs from one restock to the next. Restocking closes the current cycle, starts a new one, sets the new stock and resets `consumed` to 0:

```
   cycle 1 (stock = 20)                          cycle 2 (stock = 30)
 |-------------------------------------------| |------------------------- ...
 restock   consumed: 0 -> 5 -> 12 -> 20      restock   consumed: 0 -> 4 -> ...
 09:00                          ^ 13:10      18:00
                           sold_out_at       |
                                             +-- cycle 1 archived in inventory_cycles:
                                                 stocked 20, consumed 20, leftover 0,
                                                 sold out at 13:10, closed at 18:00
```

### Q: If consumed is reset to 0, isn't the sales history deleted?

It would be, and that's the one change needed to make your idea work. **Before resetting, the restock archives the closing cycle** into an `inventory_cycles` table: units stocked, units consumed, leftover, whether the leftover was carried forward, when it sold out, and when the cycle opened and closed. The live counter on `menu_items` stays small and fast for ordering; the history lives in its own table for analytics.

This is the classic split between **operational data** (the hot row every order touches) and **historical data** (append-only rows reports read).

### Q: What do we gain from this? The full list

1. **Fair best sellers.** Ranking by units sold rewards whatever you prepare most of. QuickServe ranks by *units sold per hour while the item was actually on sale* (more below).
2. **Sell-through rate** = units sold / units stocked. It's a standard retail metric: units sold divided by units received [5]. Retail guides treat about 75% or more as strong [6]. For food it reads directly: 40% means too much was cooked; 100% by lunchtime means too little.
3. **Sold-out time.** `sold_out_at` records the first moment a cycle hit zero. Sold out at 1 pm and sold out at 9 pm are very different signals that a plain counter can't tell apart.
4. **Restock suggestions that understand stock-outs.** When an item sells out, sales show only that demand was *at least* that much. Forecasting literature calls this **censored demand**: stock-outs cut off the sales you can observe, and models trained on that cut-off data underestimate demand, which leads to more stock-outs and more waste [7][9]. Estimating demand straight from sales is biased even when stock-outs are rare [8]. The suggestion endpoint corrects for this.
5. **Waste tracking.** Each cycle records the `leftover` at close and `units_wasted` (orders cancelled after cooking started). Multiply by food cost and you have the money lost to waste.
6. **Customer badges.** "Only 4 left" comes from `available`. "Selling fast" comes from the cycle's sales rate: at the current pace, will it sell out within the hour?
7. **An audit trail.** "On 17 Nov we made 20 biryanis, sold 18, 1 order was cancelled after the restock, 1 was cancelled while cooking." Each part of that sentence is a column.
8. **Made-to-order items still count.** A plain dosa might not be counted (`track_stock = false`, `stock = NULL`), but `consumed` still goes up, so it still appears in best-seller reports.
9. **Carry-over for packaged goods.** Cooked food is usually discarded at close, while a sealed lassi can roll into the next cycle. `carry_over_leftover` handles both, and the cycle records which happened.
10. **Correct cancellations across restocks.** Every order line remembers the `cycle_no` it was sold from (next question).
11. **A database-level guarantee.** A `CHECK (consumed <= stock)` constraint means PostgreSQL itself refuses an oversold value, even if a future bug slips through the code.

### Q: An order is placed, then the restaurant restocks, then the customer cancels. What happens to the stock?

This is the subtle case. If cancelling did `consumed -= 3` on the new cycle, it would hand out 3 phantom units that were never prepared in this cycle.

So each `order_items` row stores `cycle_no`, and releasing stock is a conditional update:

```sql
UPDATE menu_items SET consumed = consumed - 3
 WHERE id = :item AND cycle_no = :cycle_the_order_came_from AND consumed >= 3
RETURNING id
```

- **Same cycle:** the row matches and the 3 units go back on sale.
- **Item restocked since:** zero rows match. The service records the 3 units as `units_returned` on the *archived* cycle and leaves the new cycle untouched.

Test: `test_cancel_after_restock_credits_the_old_cycle`.

### Q: And a cancellation after cooking started?

The food exists but can't be resold, so the units are **not** released. They're counted as `units_wasted` on their cycle, and the customer is refunded. Customers can cancel only before the restaurant accepts; after that only support can.

### Q: Forty customers want the last ten biryanis at the same moment. What stops overselling?

One **conditional UPDATE** that checks and writes in the same statement:

```sql
UPDATE menu_items
   SET consumed = consumed + 1
 WHERE id = :item
   AND (NOT track_stock OR consumed + 1 <= stock)
RETURNING id, name, price, cycle_no
```

If it returns a row, the unit is reserved; if it returns nothing, the item can't cover the order. Two orders racing for the last unit can't both win. In PostgreSQL's default Read Committed level, the second UPDATE waits for the first to commit. It then **re-evaluates its WHERE clause against the updated row** and proceeds only if the row still matches [1]. It no longer matches, so it gets no row back.

You can watch the difference yourself with `python -m scripts.race_demo`. On the machine that built this project, both runs went like this every time:

```
NAIVE : 40 orders accepted for 10 biryanis | consumed counter says  3
        oversold by 30; the counter missed 37 sales (lost updates)
ATOMIC: 10 orders accepted for 10 biryanis | consumed counter says 10
```

The naive version reads `consumed` into Python, checks it, and writes `consumed + 1` back. Forty requests all read a small number, all pass the check, and overwrite each other's writes. Notice that the `CHECK (consumed <= stock)` constraint **didn't stop it**: every write stored a small, valid-looking number. It was just the wrong number. Constraints catch impossible values; only atomic updates or locks prevent **lost updates**.

Tests: `test_forty_customers_ten_biryanis`, plus the demo script.

### Q: What if a restock happens in the middle of a lunch rush?

Restocking has to read `consumed`, archive it and reset it, with no order sneaking in between. If one did, its sale would land in a cycle that had already been archived, or vanish. So restock takes a **row lock** first:

```sql
SELECT ... FROM menu_items WHERE id = :item FOR UPDATE
```

Orders for that item wait a few milliseconds and then land cleanly in the new cycle. The test fires 29 orders and 1 restock at the same instant, then checks that every unit sold is counted in exactly one cycle, and that the per-cycle totals match the `cycle_no` stored on each order line.

Test: `test_restock_in_the_middle_of_a_rush_loses_nothing`.

### Q: An order has paneer and naan, another has naan and paneer. Can they deadlock?

They could. If order A locks paneer then waits for naan, while order B locks naan then waits for paneer, each waits for the other forever. PostgreSQL detects this and kills one of them, which means a failed order. QuickServe **always reserves items in sorted ID order**, so two orders can never hold each other's next lock. It's a one-line fix that's easy to forget, and a common interview question.

### Q: Why rank best sellers by rate instead of units sold?

Take the numbers from `test_best_seller_is_ranked_by_rate_not_raw_volume`:

| | Prepared | Sold | On sale for | Units sold | Rate while available |
|---|---|---|---|---|---|
| Samosa | 200 | 120 | 10 h (never sold out) | **120** | about 11.7 per hour |
| Chicken Biryani | 20 | 20 | 1 h (then sold out) | 20 | **16 per hour** |

(Both items were then restocked, and the new, still-empty cycle counts for its 15-minute minimum: 120 / 10.25 h and 20 / 1.25 h. The test asserts these exact figures.)

By units sold, samosa "wins". But biryani ran out after an hour; after that nobody *could* buy it. Counting those empty hours would punish it for being popular. So for a sold-out cycle the clock stops at `sold_out_at`. Each cycle counts for at least 15 minutes, so one very early sell-out can't produce an absurd rate. Biryani ranks first. Sell-through is reported alongside the rate, because it says whether you prepared the right amount.

Platforms do tag best sellers. One published implementation tags items above the 97th percentile of order volume within a restaurant [18]. That's a volume rule; the rate-while-available rule here is the correction for stock-outs that the cycle data makes possible.

### Q: How does the restock suggestion work?

`GET /api/v1/menu/{id}/restock-suggestion` looks at the last 3 closed cycles:

- **Didn't sell out:** demand ≈ units sold.
- **Sold out:** sales are censored, so demand is estimated from the selling rate stretched over the whole cycle, capped at 2× sales. Example: 20 sold in the first 4 hours of an 8-hour cycle gives an estimate of about 40.
- The suggestion is the average of those estimates, rounded up, with an explanation for each cycle.

This is a deliberately simple teaching heuristic, not a production forecaster. Real systems use statistical models built for censored data [9]. The point is that **without archived cycles and `sold_out_at` you couldn't even begin**, because a plain stock counter has no way to tell "sold 20 because 20 people wanted it" from "sold 20 because we only made 20".

---

## 5. ORM vs writing SQL by hand

### Q: Is the ORM better than writing SQL queries manually?

For most of an application, yes. But "better" doesn't mean "you can forget SQL". The race demo above makes the point: **the ORM can generate both the wrong SQL and the right SQL, and only knowing SQL tells you which one you wrote.**

```python
# Python arithmetic on a value read earlier -> sends a literal: SET consumed = 4
item.consumed = item.consumed + 1

# A column expression -> sends SET consumed = consumed + 1 (atomic, done inside PostgreSQL)
update(MenuItem).values(consumed=MenuItem.consumed + 1)
```

Both look almost identical in Python. The first loses updates under concurrency; the second doesn't.

### Q: What does the ORM give us in this project? Concrete examples

| ORM feature | Where it's used | What you'd do by hand |
|---|---|---|
| **Unit of work**: you change objects, the session works out the INSERT/UPDATE order and runs them in one transaction | `place_order` creates an order, its items and a status event, all committed together | Order every statement yourself, manage `BEGIN`/`COMMIT`/`ROLLBACK` |
| **Relationships and loading strategies** | `selectinload(Restaurant.menu_items)` loads 3 restaurants and 9 dishes in exactly 2 queries (tested) | Write the join or the `IN (...)` query and stitch results into objects |
| **`lazy="raise"`** | Accessing `restaurant.menu_items` without asking for it raises an error instead of quietly running one query per restaurant (the N+1 problem) | No equivalent safety net |
| **Hybrid methods**: one rule, two worlds | `MenuItem.switched_on_at(now)` runs as Python on the menu page and becomes a SQL `WHERE` inside the order UPDATE, so they can never disagree | Write the rule twice and hope they stay in sync |
| **Column defaults and `onupdate`** | `updated_at` is set on every UPDATE automatically. `scripts/show_sql.py` shows the ORM adding `updated_at=now()` to the reservation UPDATE | Remember it in every UPDATE you write |
| **Bound parameters** | Every value is sent separately from the SQL text | Easy to slip into string formatting, the classic SQL-injection hole |
| **Migrations from models** | `alembic revision --autogenerate` wrote the first migration from the model classes; `alembic check` in CI fails if models and migrations drift apart | Write and maintain every `CREATE`/`ALTER` by hand |
| **Typed results** | `Mapped[Decimal]` columns come back as `Decimal`, `Mapped[OrderStatus]` as an enum | Convert types from raw rows yourself |

### Q: Where is raw SQL as good, or better?

- **Reports.** The best-seller report is written twice in `app/modules/menu/analytics.py`: once with SQLAlchemy (a CTE, `GROUP BY`, `RANK() OVER`) and once as plain SQL. A test proves they return identical rows. Be honest about it: for a report like this, many people find the SQL version easier to read. SQLAlchemy can express it, but the expression API is a second language. A reasonable rule: **ORM for business logic, raw SQL (or SQLAlchemy Core) for analytics.**
- **Bulk work.** Loading 100,000 rows as Python objects is slow; a single `INSERT ... SELECT` or `COPY` is far faster.
- **Database-specific features.** Partial indexes, `SKIP LOCKED` and `CHECK` constraints are all used here. SQLAlchemy supports them, but you still have to know they exist, which is a SQL skill.

### Q: What does the ORM hide that can bite you?

Three things, all demonstrated in `tests/test_orm_behaviour.py`:

1. **Hidden queries (N+1).** Default lazy loading turns a loop over 50 restaurants into 51 queries. We set `lazy="raise"` so that mistake fails in development.
2. **The identity map can serve stale data.** Within one session, each row is one Python object. If you hold an object and the row changes underneath you (another request, a script), **selecting it again returns the same object with the old values**. SQLAlchemy doesn't overwrite already-loaded objects unless you ask with `populate_existing`, `refresh()` or `expire()` [2]. This is especially dangerous with `SELECT ... FOR UPDATE`: you lock the row but read stale values, a known pitfall [3]. Every locking query in QuickServe uses `populate_existing=True` for this reason. (One of our own tests once passed by accident because of this; see section 11.)
3. **Autogenerate is a draft, not the truth.** Alembic's generated migration created PostgreSQL ENUM types in `upgrade()` but didn't drop them in `downgrade()`, so downgrade-then-upgrade failed with "type already exists". The fix was added by hand, and the test suite now runs downgrade and upgrade on every run. Always read a generated migration before committing it.

### Q: How do I see the SQL the ORM generates?

- `python -m scripts.show_sql` prints the compiled SQL for the reservation UPDATE, the restock lock, `selectinload`, and the best-seller report, without needing a database.
- `SQL_ECHO=true` in `.env` logs every statement the running app sends.
- `alembic upgrade head --sql` prints migration SQL instead of running it.

---

## 6. Business rules borrowed from Zomato and Swiggy

### Q: What happens if a restaurant never responds to an order?

On Zomato, according to a POS integrator's documentation, orders not reviewed within 4 minutes are auto-rejected, and that can't be disabled [15]. QuickServe does the same:

- On payment, the order gets `accept_by = paid_at + 240 seconds` (configurable).
- A background job finds `PAID` orders past `accept_by`, moves them to `REJECTED`, releases their stock and refunds the payment.
- The job claims rows with `FOR UPDATE SKIP LOCKED`, so several job workers can run side by side without processing the same order twice.
- If the restaurant taps Accept at the same instant the job fires, they meet at the order's row lock. If the restaurant gets it first, the job skips that row (`SKIP LOCKED`) and won't pick it up again, because it's no longer `PAID`. If the job gets it first, the restaurant's request waits, then sees `REJECTED` and fails the transition check. Either way there's never a "rejected and accepted" order.

The same job expires orders that were never paid (`pay_by`, 10 minutes by default) and gives their reserved stock back. This is the standard **reservation with a time limit** pattern: stock is held for you, but not forever.

### Q: How do restaurants mark a dish unavailable?

Swiggy's partner guide tells restaurants to proactively mark unavailable items as "Out of Stock" in the Inventory section until they're next available [16]. A sold-out dish left live on the apps costs a cancelled order, a refund and a lower rating [17], which is the whole reason stock tracking matters.

QuickServe supports three states through `PATCH /menu/{id}/availability`:

| `is_available` | `unavailable_until` | Meaning |
|---|---|---|
| true | null | On |
| false | 18:00 today | Off, and back on by itself at 18:00 |
| false | null | Off until someone switches it on |

The rule is a hybrid method, so the menu page and the order UPDATE apply exactly the same logic.

### Q: How is the bill calculated?

Like the itemised bills on delivery apps. An order of Rs 250, 1 km away, at lunchtime:

```
item total            250.00     sum of unit price x quantity (2 x Rs 125)
packaging charge       20.00     set by the restaurant
delivery fee           20.00     1.0 km: the 0-2 km slab
platform fee           14.90     flat, per order
GST on food (5%)       13.50     on items + packaging
GST on fees (18%)       6.28     on delivery + platform fee
-------------------------------
grand total           324.68
```

Since Phase 11, the bill can also have a coupon discount, a small order fee and surge fees (peak, late night, rain), and the delivery fee depends on the distance. See [Pricing like Zomato and Swiggy](#pricing-like-zomato-and-swiggy-phase-11) for every rule and where it comes from.

Where the base rules come from:

- **Platform fee.** A fixed per-order charge. In March 2026 Zomato raised it to Rs 14.90 before GST [10], and Swiggy raised its fee to Rs 17.58 including GST [11]. Both platforms change it often.
- **GST on food.** For orders through delivery apps, the e-commerce operator collects and deposits GST on the restaurant service under Section 9(5), at 5% without input tax credit [12].
- **GST on the platform's own fees.** Delivery charges billed by the operator, and platform fees, are a separate supply taxed at 18% [13]. Since 22 September 2025 the platform pays GST on local delivery supplied through it [86]; from 1 November 2026 that was widened to "delivery services" [14].

That is exactly why every fee and rate lives in `.env` / `Settings` and not in code: a fee change is a config change, not a redeploy. The defaults are illustrative and none of this is tax advice. The **whole bill is stored on the order**, so if the fee changes tomorrow, yesterday's receipts don't.

### Q: If a restaurant changes a price, do old orders change?

No. Each order line stores `item_name` and `unit_price` as **snapshots**. Test: `test_price_snapshot_survives_menu_price_change`.

### Q: Who can change an order's status, and when?

The lifecycle is data in `state_machine.py`, not scattered `if` statements:

```
PLACED --pay--> PAID --accept--> ACCEPTED --> PREPARING --> READY --> OUT_FOR_DELIVERY --> DELIVERED
  |              |                  |             |
  |              +--reject/timeout--+--> REJECTED  |
  +--timeout--> PAYMENT_FAILED      |             |
  +--cancel---> CANCELLED <---------+-------------+   (after ACCEPTED: support only)

Failed ending before PREPARING  -> stock released, payment refunded if one was taken
Failed ending from PREPARING    -> stock counted as waste, payment refunded
```

Each target status also lists who may set it: only the restaurant accepts, only a rider delivers, only the system marks an order paid. Who you are comes from your login token, never from the request ([section 7](#7-login-tokens-and-permissions)). `DELIVERED -> PREPARING` is impossible because `DELIVERED` allows no next state. Every change is written to `order_status_events`, which powers the timeline endpoint today and notifications later.

### Q: The customer taps "Pay", the network drops, the app retries. Are they charged twice?

No. The client sends an `Idempotency-Key` header. A `UNIQUE` constraint on that key means a retry returns the first result (`200`, `Idempotent-Replayed: true`) instead of creating a second charge. A partial unique index enforces **at most one successful payment per order** in the database itself:

```sql
CREATE UNIQUE INDEX uq_payments_one_success_per_order ON payments (order_id) WHERE status = 'SUCCESS';
```

Failed attempts are kept, and the customer can retry with a new key until `pay_by`. A concurrency test found a real bug here; see section 11.

---

## 7. Login, tokens and permissions

Phase 3 added login. Browsing restaurants and menus is still open to everyone; everything else needs you to be logged in, and what you may do depends on **who** you are and **what you own**.

### Q: What's the difference between authentication and authorization?

They're the two questions every request has to answer, in this order:

| | Question | Fails with | Example in QuickServe |
|---|---|---|---|
| **Authentication** | Who are you? | `401 Unauthorized` | No token, an expired token, a forged token, a wrong password |
| **Authorization** | Are you allowed to do *this*? | `403 Forbidden` (or `404`, see below) | A customer trying to accept an order; owner A restocking owner B's dish |

People mix the two up constantly, including in HTTP itself, where "401 Unauthorized" really means "unauthenticated".

### Q: How does logging in work?

```mermaid
sequenceDiagram
    autonumber
    participant C as Client (app or Swagger)
    participant API as QuickServe API
    participant DB as PostgreSQL

    C->>API: POST /api/v1/auth/login, username = email, password
    API->>DB: find the user by email
    API->>API: Argon2 check of the password against the stored hash
    API-->>C: access_token (a JWT signed with the server secret, valid 30 minutes)

    C->>API: any request with header Authorization: Bearer access_token
    API->>API: check the signature, the algorithm and the expiry time
    API->>DB: load the user by the id inside the token
    API->>API: role and ownership checks in the service layer
    API-->>C: the result, or 401 / 403 / 404
```

In code: `app/modules/auth/service.py` does the login, `app/core/security.py` creates and checks tokens, and `get_current_user` in `app/modules/auth/dependencies.py` is the FastAPI dependency that every protected endpoint uses.

### Q: What's inside a token? Is it secret?

A JWT has three parts separated by dots: `header.payload.signature`. Ours carries:

```json
{"sub": "<your user id>", "role": "CUSTOMER", "type": "access", "iat": 1763371200, "exp": 1763373000}
```

**The payload is not encrypted, just base64-encoded.** Anyone holding a token can read it. `test_editing_the_role_inside_a_token_breaks_it` decodes a customer's token without any key, changes `"role"` to `"ADMIN"`, and sends it back. The server rejects it, because the **signature** no longer matches the contents and only the server has the secret to make a new one. So:

- never put anything secret in a token (passwords, phone numbers, addresses);
- the secret (`JWT_SECRET_KEY`) is the crown jewel. Whoever has it can mint a token for any user.

### Q: The token already says `"role": "CUSTOMER"`. Why look the user up in the database on every request?

Because tokens can't be taken back once issued. If we trusted the role inside the token, then demoting a user or deleting a stolen account would only take effect when their token expired. Loading the user by id (one primary-key lookup) means role changes and deletions apply on the very next request. `test_token_of_a_deleted_user_is_401` checks this. The role in the token is only informational, for example for a frontend that wants to show the right menu.

The trade-off is the classic one between **stateless** (never touch the database, scale easily, can't revoke) and **stateful** (one query, can revoke). A short expiry (30 minutes) plus a database check is a sensible middle ground for a project like this.

### Q: How are passwords stored?

As **Argon2** hashes, via `pwdlib`. Argon2id is the first choice in OWASP's password storage guidance [27] and the algorithm FastAPI's tutorial uses [4]. Hashing is one-way: we can check a password against the hash, but nobody, including us, can turn the hash back into the password. That's the difference from encryption, which is reversible with the key.

Argon2 is **slow on purpose**: about 100 ms per check on the machine that built this. That's harmless for one login, and it makes guessing billions of passwords from a stolen database impractical. It's also why the test suite hashes its shared test password once instead of once per test user.

### Q: Why does a wrong password get exactly the same answer as an email that doesn't exist?

If the login said "no such email" in one case and "wrong password" in the other, anyone could find out which emails have accounts just by trying them (**account enumeration**). OWASP's testing guide asks applications to return consistent generic error messages when the account name, password or other credentials are wrong [24]. QuickServe always answers `401 Incorrect email or password` (`test_wrong_password_and_unknown_email_look_identical`).

The **timing** gives it away too: checking a password takes about 100 ms, but "no such user" could answer in 1 ms. So when the email doesn't exist, `verify_password` still runs one full Argon2 check against a dummy hash. Measured on the machine that built this: wrong password **108 ms**, unknown email **102 ms**, correct password **112 ms**. Indistinguishable from outside.

### Q: Who can do what?

| Action | Not logged in | Customer | Restaurant owner | Rider | Admin |
|---|---|---|---|---|---|
| Browse restaurants and menus | yes | yes | yes | yes | yes |
| Sign up | as customer, owner or rider | | | | |
| Create a restaurant | | | yes (becomes its owner) | | yes |
| Add dishes, restock, switch dishes off, cycle history, restock suggestion, best sellers | | | **own restaurant only** | | any |
| Place an order | | yes (it's theirs) | | | |
| Pay for an order | | own orders only | | | |
| See an order and its timeline | | own orders | orders of own restaurant | orders that are READY or later | all |
| Accept, reject, start preparing, mark ready | | | own restaurant's orders | | |
| Picked up, delivered | | | | yes | |
| Cancel | | own order, before the restaurant accepts | | | any, before delivery |
| Run the timeout job | | | | | yes |

The order status rules from section 6 still apply on top of this: even the right person can't move an order from DELIVERED back to PREPARING.

### Q: Why isn't "you're a restaurant owner" enough to restock a dish?

Because then owner A could restock B's dishes, add dishes to B's menu or read B's sales figures, just by putting B's ids in the URL. Checking the role but forgetting **ownership of that specific object** is the number one API security risk on OWASP's 2023 list: Broken Object Level Authorization [26]. Every menu action goes through `ensure_can_manage(db, restaurant_id, user)`, which checks that the restaurant belongs to the caller (admins excepted). `test_owner_cannot_touch_another_owners_menu` tries all three attacks.

### Q: Why do I get `404 Not Found` for someone else's order, and not `403 Forbidden`?

`403` would confirm "this order exists, you just can't see it". `404` reveals nothing. The same order id answers `200` for its customer, its restaurant's owner and admins, and `404` for everyone else. Riders get `404` until the order is READY, because there's nothing for them to do before then.

### Q: Why can't I sign up as an admin? Where do riders and admins come from?

The sign-up schema only accepts `CUSTOMER`, `RESTAURANT_OWNER` or `RIDER`. If anyone could register as an admin, the role would protect nothing. Admins (and the demo rider) are created by `scripts/seed.py`. In a real system an existing admin would create them through a protected endpoint.

### Q: Adding the RIDER role needed a hand-written migration. Why?

Alembic's autogenerate **doesn't notice** a new value in a Python `Enum`. It would have produced an empty migration, and production would have crashed the first time a rider signed up. The migration (`migrations/versions/..._add_rider_role.py`) runs `ALTER TYPE user_role ADD VALUE 'RIDER'`. PostgreSQL can't remove an enum value, so the downgrade rebuilds the type, and it **refuses to run if rider accounts exist** rather than silently turning them into customers. A lesson from Phase 2 again: autogenerate is a draft.

### Q: What stops someone from forging a token?

- **The algorithm is pinned.** The server only accepts `HS256`. A famous JWT attack sends a token whose header says `"alg": "none"` (no signature at all); `test_unsigned_alg_none_token_is_401` shows it's rejected.
- **The secret must be real outside your laptop.** The app refuses to start when `ENVIRONMENT` isn't `local` and `JWT_SECRET_KEY` is still the development value from `.env.example`, or when the secret is shorter than 32 characters (`test_dev_secret_is_refused_outside_local`). Failing loudly at startup beats running in production with a secret that's published on GitHub. In Phase 6 the real secret comes from AWS Secrets Manager.
- **Tokens expire** after 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`), which limits the damage if one leaks.

### Q: What's deliberately not built yet?

| Missing | Why it matters | When |
|---|---|---|
| Refresh tokens | Today you log in again every 30 minutes | Later |
| ~~Logout / revoking a token~~ | ~~A leaked token works until it expires~~ | **Done in Phase 4** ([section 8](#8-redis-the-background-worker-and-logs-phase-4)) |
| ~~Rate limiting on login~~ | ~~Someone could try thousands of passwords~~ | **Done in Phase 4** ([section 8](#8-redis-the-background-worker-and-logs-phase-4)) |
| HTTPS | Tokens and passwords must never travel in plain text | Phase 6: TLS at the load balancer |
| Rider assignment | Any rider can deliver any READY order | Later |

### Q: How do I log in on the Swagger page?

1. Open http://127.0.0.1:8000/docs and click **Authorize** (top right, padlock icon).
2. Put the **email** in the `username` box (it's called username because that's the OAuth2 standard form) and the password in `password`. Leave the other fields empty.
3. Click **Authorize**, then **Close**. Padlocks on the endpoints now show as locked, and Swagger sends your token with every request.
4. To switch user, click **Authorize** again, then **Logout**, then log in as someone else.

The demo accounts are printed by `python -m scripts.seed`:

| Role | Email | Password |
|---|---|---|
| Customer | `customer@quickserve.dev` | `customer-pass-123` |
| Restaurant owner (owns both demo restaurants) | `owner@quickserve.dev` | `owner-pass-123` |
| Rider | `rider@quickserve.dev` | `rider-pass-123` |
| Admin | `admin@quickserve.dev` | `admin-pass-123` |

These are for local development only.

---

## 8. Redis, the background worker and logs (Phase 4)

Phase 4 added three production habits: a **cache** for the busiest page, a **background worker** so the timeout job runs by itself, and **structured logs** you can search. It also finished two items Phase 3 left open: **login rate limiting** and **logout**.

### Q: What is Redis, and what does QuickServe keep in it?

Redis is an in-memory key-value store: reads and writes take microseconds, keys can **expire on their own** (a TTL), and counters can be increased **atomically**. QuickServe uses it only for data that's fine to lose:

| Key | What it holds | Expires after |
|---|---|---|
| `menu:v1:<restaurant id>` | The customer menu, ready to send | 10 seconds (`MENU_CACHE_TTL_SECONDS`) |
| `login:fail:email:<email>` | Failed logins for one account | 15 minutes from the first failure |
| `login:fail:ip:<ip>` | Failed logins from one IP address | 15 minutes from the first failure |
| `auth:revoked:<token id>` | A token that was logged out | When that token would have expired anyway |

PostgreSQL stays the **source of truth** for everything that matters: orders, stock and money never live only in Redis. You can look inside while the app runs with `docker compose exec redis redis-cli --scan`.

### Q: How does the menu cache work?

It's the **cache-aside** pattern:

```mermaid
flowchart LR
    req["GET /restaurants/id/menu"] --> look{"Key in Redis?"}
    look -->|"yes: HIT"| ret["Return the cached menu"]
    look -->|"no: MISS"| build["Build it from PostgreSQL"]
    build --> store["Store in Redis for 10 seconds"]
    store --> ret
    owner["Owner adds a dish, restocks or switches one off"] --> commit["Commit to PostgreSQL"]
    commit --> del["Then delete the Redis key"]
```

Every menu response has an `X-Cache` header: `MISS` (built from the database), `HIT` (from Redis) or `BYPASS` (Redis unavailable). Try `curl -I http://127.0.0.1:8000/api/v1/restaurants/<id>/menu` twice.

### Q: Why delete the cache entry *after* the database commit, not before?

Because of the gap between the two. If we deleted first, another request could arrive before our commit, find the key missing, rebuild the menu from the **old** rows, and put that stale copy back in Redis for the whole TTL. Deleting after the commit means the next rebuild can only see the new data. It's the kind of ordering detail that interviewers like to ask about.

### Q: Orders don't clear the cache. So the menu can say "2 left" when there are none?

Yes, for at most 10 seconds, and that's a deliberate trade-off. A popular restaurant gets orders every few seconds; clearing the cache on each one would mean almost no cache hits. What makes it safe: **placing an order never trusts the menu**. It runs the atomic stock UPDATE in PostgreSQL, so a slightly stale "2 left" can never sell a third biryani. `test_a_stale_menu_can_never_cause_an_oversell` shows exactly that: stale menu, `HIT`, and the order is still refused.

The general rule: **cache what's allowed to be a little old; check the source of truth for anything that must be right.**

### Q: What happens when Redis goes down?

Every feature degrades on purpose, and each choice is a trade-off:

| Feature | With Redis down | Why this choice |
|---|---|---|
| Menu | Served straight from PostgreSQL (`X-Cache: BYPASS`) | Slower, but nobody notices a missing cache |
| Login rate limit | Paused (**fails open**); a warning is logged | Refusing every login would turn a cache outage into "nobody can log in". A bank might choose the opposite |
| Logout check | Paused (fails open); logged-out tokens work until they expire | Same availability argument; tokens expire in 30 minutes anyway |
| Logging out | **Refused** with `503` | Silently "succeeding" would make users believe they're logged out when they aren't |
| `/health/ready` | Still **ready**, with `"redis": "down (degraded...)"` | Pulling every instance out of the load balancer would make a small problem a total outage |

A test caught a nasty surprise here: by default the Redis client **retries a failed command several times with growing pauses**, so with Redis down every menu request took about **4 seconds**. "Degraded" had quietly become "unusable". The client now retries once, immediately, and `test_menu_still_works_when_redis_is_down_and_stays_fast` fails if a request takes longer than a second.

### Q: How does login rate limiting work?

Two counters per failed login, both in Redis: one for the **account** (5 failures per 15 minutes) and one for the **IP address** (20 per 15 minutes). The IP limit stops one machine from trying one common password against thousands of accounts ("password spraying").

- `INCR` is atomic, so two failures arriving at once can't both read "4" and both write "5".
- `EXPIRE ... NX` starts the 15-minute window on the **first** failure only, and the key deletes itself afterwards. No cleanup job.
- The check runs **before** the password check, so a locked-out attacker gets nothing, not even a wrong-password answer.
- After the limit, even the **correct** password gets `429 Too Many Requests` with a `Retry-After` header (seconds until the window ends).
- A successful login clears the account's counter.

This is a **fixed window**: simple and cheap, but someone could make 5 attempts at minute 14 and 5 more at minute 16. A sliding window fixes that at the cost of more Redis work. Good to know for interviews.

There's a FinOps angle too: a blocked attempt is answered in about **2 ms**, while a real password check takes about **110 ms** of Argon2 CPU time (both measured on the machine that built this). A guessing attack against a rate-limited login costs almost nothing to turn away.

### Q: How can logout work if tokens can't be taken back?

Each token now carries a unique id (`jti`). `POST /api/v1/auth/logout` stores that id in Redis under `auth:revoked:<jti>`, with a TTL equal to the token's remaining lifetime, and `get_current_user` rejects any token on that list. When the token would have expired anyway, the Redis key disappears too, so the deny list never holds more than 30 minutes of logouts. Logging out on one phone doesn't affect your other devices (`test_logout_kills_this_token_only`).

Tokens issued before Phase 4 have no `jti`, so they're rejected: everyone simply logs in again once.

### Q: Why is the timeout job a separate worker process instead of part of the API?

Run it next to the API:

```bash
python -m app.worker           # runs the job every WORKER_INTERVAL_SECONDS (30)
python -m app.worker --once    # one pass, then exit
```

- The API may run as several processes on several machines. A timer inside each would run the job many times over. A worker is deployed, scaled and restarted on its own.
- A slow job never steals CPU from customers' requests.
- **Running two workers is safe.** The job claims orders with `SELECT ... FOR UPDATE SKIP LOCKED`, so each worker takes different rows. `test_two_workers_never_process_the_same_order` runs two workers at once over 20 expired orders: exactly 20 rejections, never one order twice. A second worker is for resilience (one machine dies, the other keeps going), not speed.
- If one pass fails (say the database is restarting), the worker logs the error and tries again next interval instead of crashing.

### Q: What's graceful shutdown, and why does the worker care?

When Docker stops a container, it sends `SIGTERM` and, if the process hasn't exited after a timeout (10 seconds by default for Linux containers), it's forcibly killed with `SIGKILL` [28]. Kubernetes does the same, with a default grace period of 30 seconds before `SIGKILL` [29]. A process killed mid-transaction leaves work half done.

The worker catches `SIGTERM` (and Ctrl+C), finishes the pass it's in, and exits. While it's waiting between passes, it stops **immediately**, not after up to 30 seconds. Measured: worker started, `SIGTERM` sent while it was waiting, clean exit within a second. `test_stop_signal_ends_the_loop_without_waiting_out_the_interval` checks it.

### Q: Why JSON logs, and what is a request ID?

Every request now produces exactly one log line like this:

```json
{"time": "2026-11-17T09:45:50.973+00:00", "level": "INFO", "logger": "quickserve.http", "message": "request",
 "request_id": "c776e4b1ba264ee5b74211062aa5e6c2", "method": "POST", "path": "/api/v1/auth/login",
 "status": 429, "duration_ms": 2.3}
```

- **JSON**, because in production thousands of lines a second from many instances go into a log system (CloudWatch, Loki, ELK), and JSON lets it filter and count by field: "all 500s today", "logins blocked per hour". Set `LOG_JSON=false` for readable plain text while coding.
- **A request ID** links every line that one request wrote (the access line, "login blocked", "order placed"…). It's returned in the `X-Request-ID` response header, so a user reporting a problem can quote it. If the caller sends a sensible `X-Request-ID`, it's reused, so one ID can follow a request across services; anything odd (spaces, quotes, too long) is replaced, so nobody can inject fake log lines.
- **Unexpected errors** return `{"detail": "Internal server error", "request_id": "..."}`. The full stack trace goes into **our** logs and never to the client, because traces can reveal file paths, SQL and secrets (`test_unexpected_errors_return_a_request_id_not_a_stack_trace`).
- **What's never logged:** passwords, emails on failed logins (people sometimes type their password into the email box), and query strings (they can contain personal data).
- **Business events** are logged too: `order placed`, `order status changed`, `login failed`, `login blocked`, `timeout job finished`.

FinOps: log platforms bill by the volume ingested and stored. One line per request plus real events (not every SQL statement) keeps that bill sane, and uvicorn's own access log is switched off because it would duplicate ours line for line.

Two logging bugs turned up while building this, both worth remembering:

1. **All our logs vanished in the tests.** The test setup runs the Alembic migrations, and Alembic's logging setup (`fileConfig`) switches off every logger that already exists by default. Fixed with `disable_existing_loggers=False` in `migrations/env.py`.
2. **Request IDs went missing from some lines.** The ID was read when a line was *written out*, but lines can be written out later, elsewhere (a background log-shipping thread, or a test inspecting them afterwards). It's now stamped onto each log record the moment the record is created, inside the request.

### Q: Why does Redis in Docker Compose have a memory limit and `volatile-ttl`?

Redis keeps everything in RAM, and RAM is what you pay for, so `--maxmemory 64mb` caps it. When the cap is reached, the eviction policy decides what to drop. `volatile-ttl` evicts keys that have an expiry, **shortest remaining time first** [30]. That suits us: menu entries (seconds left) go before login counters and logged-out tokens (minutes left), so memory pressure throws away the cheapest data first. Snapshots to disk are switched off, because nothing in this Redis needs to survive a restart.

### Q: How do I run all of it?

`docker compose up -d` now starts PostgreSQL **and** Redis (on port **6380** on your machine, so it can't clash with any other project's Redis). Then use two terminals, both with the venv active:

```bash
# terminal 1: the API
uvicorn app.main:app --reload

# terminal 2: the worker
python -m app.worker
```

`http://127.0.0.1:8000/health/ready` should show `"database": "ok", "redis": "ok"`.

Or skip the two terminals and run everything in containers: `docker compose --profile app up -d --build`, then use port 8001 (next part).

### Docker: the app in containers (Phase 5)

The Dockerfile itself is explained line by line in [docs/docker.md](docs/docker.md). These are the questions about how it all fits together.

### Q: Why put the app in a container at all? It already runs with `uvicorn`.

On your Mac it runs because your Mac has the right Python, the right packages in a venv and the right settings. A server has none of that. An image packs the code, Python and every package into one file that runs the same everywhere: your laptop, CI, AWS, Kubernetes. "Works on my machine" stops being a sentence anyone says. Every later phase (ECS on AWS, Kubernetes) runs this exact image.

### Q: Why is the Dockerfile split into two stages?

The first stage (`builder`) installs the packages into a virtual environment. The second stage (`runtime`) starts again from a clean `python:3.11-slim` and copies in only that finished environment and our code. pip's caches, build leftovers and the tools used to install things stay behind in the first stage. Smaller image, less to download on every deploy, and fewer programs an attacker could use [31].

### Q: Why does the container run as a user called `app` and not root?

If someone finds a bug that lets them run commands inside the container, they get the powers of the user the app runs as. As root, they could change any file in the container and have an easier path to attacking the host. As `app`, a user with no home and no login shell, they can't even overwrite the app's own code. Docker's own guidance is to drop root whenever the app doesn't need it [31]. CI checks this on every run: `whoami` inside the API container must print `app`.

### Q: The image installs `requirements.lock`. Why not `requirements.txt`?

`requirements.txt` pins only the packages we chose. Build the same commit next month and pip could pull a newer version of some dependency of a dependency, one the tests never ran with (exactly what happened with `starlette`; see [section 9](#q-why-both-requirements-devtxt-and-requirements-devlock)). `requirements.lock` pins all 38 runtime packages. The tests run on `requirements-dev.lock`, so CI checks that every line of `requirements.lock` appears, at the same version, in the dev lock. The image therefore contains exactly what was tested, minus pytest and ruff.

### Q: The API, the worker and the migration job: three images?

One image, three commands. `migrate` runs `alembic upgrade head`, `api` runs the Dockerfile's default command (`uvicorn`), `worker` runs `python -m app.worker`. Compose tags it three times, but the layers are shared, so it takes the disk space of one. One image means the API and the worker can never be on different versions of the code, and there's only one thing to build, scan and store.

### Q: Why is the migration its own container instead of the first thing the API does?

Picture production with five API containers starting together during a deploy. If each one ran `alembic upgrade head` on start, five processes would try to change the same tables at once. Running the migration **once per deploy**, before the new API version starts, is the standard pattern (on Kubernetes it becomes a Job, on ECS a one-off task). Compose expresses it with `depends_on: condition: service_completed_successfully` [33]: the API waits until `migrate` has exited with code 0, and doesn't start at all if it failed.

### Q: Inside Docker the database URL says `db:5432`. On my Mac it's `localhost:5434`. Why?

Compose puts the containers on a private network where each one is reachable by its **service name** on its **normal** port. The API container connects to `db:5432`. The `5434:5432` line in `docker-compose.yml` is only a door from your Mac into that network, and it exists so that you (and the developer-mode API) can reach the database. Inside a container, `localhost` means that container itself, which is why `localhost:5434` wouldn't work there.

### Q: Why is the worker's health check switched off?

The Dockerfile's `HEALTHCHECK` asks `http://127.0.0.1:8000/health`. That's right for the API. The worker runs the same image but listens on no port, so the check would always fail and Docker would mark it `unhealthy` forever. `healthcheck: disable: true` in Compose turns it off for the worker and the migration job. A better worker check, such as a heartbeat timestamp the worker writes every pass, comes with monitoring in Phase 7.

### Q: What happens when I run `docker compose stop`?

Docker sends `SIGTERM` to process 1 in each container. Because the Dockerfile uses the exec form (`CMD ["uvicorn", ...]`, not `CMD uvicorn ...`), process 1 is Python itself and receives it directly, instead of a shell that would swallow it. Uvicorn finishes the requests in progress; the worker finishes its current pass and logs `worker stopped cleanly`. If a container is still running after its grace period (10 seconds by default, 20 for the worker), Docker sends `SIGKILL`. CI tests the worker's clean stop on every run. Kubernetes does exactly the same when it moves a pod, which is why this matters later.

### Q: What does the CI `docker` job prove that the tests don't?

The tests prove the code is right. The `docker` job proves the **image** is right: it builds, it starts, the migrations run inside it, it reaches the database and Redis by service name, the seed script and login work, it runs as non-root, and the worker stops cleanly. Many deploy failures are not code bugs but a missing file in the image, a wrong path or a setting that only exists on someone's laptop; this job catches them before merge. It also writes the image size into the run's summary page, so a sudden jump is visible in review.

### Q: What does the image cost?

Claude Code measured it on the Mac: about **387 MB** on disk and about **82 MB** compressed, which is what a registry stores and every deploy downloads. Only about 0.3 MB of that is our code; most is Python and the libraries. Amazon ECR charges about USD 0.10 per GB per month for storage, for every version kept; pulls within the same AWS region are free, but cross-region pulls are billed per GB [32]. Check current pricing for your region before relying on these numbers. So in Phase 6 we'll add a registry lifecycle rule that keeps only the last few versions. The cheap wins already taken: a `slim` base image, two stages, no test tools in the image, and a `.dockerignore` that keeps `venv/`, `.git/` and tests out of the build.

### Q: Where does the image go after CI builds it?

To a **registry**, an online store for images, like GitHub is for code. A third CI job, `publish`, pushes it to GitHub Container Registry at `ghcr.io/revant123/quickserve`. Any server (later AWS) can then download that exact image instead of building it again. Three rules decide when it runs:

- **Only after `test` and `docker` both pass** (`needs: [test, docker]`). A broken image never reaches the registry.
- **Only pushes to `main` publish.** On a pull request the job still builds the image but doesn't push it, so a mistake in the publish step shows up in review.
- **Only this job may write packages** (`permissions: packages: write`). The other jobs can't, which is the least-privilege habit you'll use again with AWS IAM.

It logs in with `GITHUB_TOKEN`, a token GitHub creates for each run and throws away afterwards, so there's no password to store or leak.

### Q: Why tag the image `sha-3073e30` and not just `latest`?

`latest` is a label that moves every time you push, so "which code is running in production?" has no clear answer, and rolling back means rebuilding. A tag made from the **commit ID** never moves: `sha-3073e30` is always exactly that commit, so a rollback is just "run the previous tag". The job also adds a `main` tag that always points at the newest build, for convenience. Deploys should always use the `sha-` tag.

### Q: Why build for two processor types (amd64 and arm64)?

Most servers and the CI machines use Intel/AMD chips (`amd64`). Apple Silicon Macs and AWS Graviton servers use ARM chips (`arm64`). Docker picks the right one automatically when you pull. This is a FinOps choice: AWS says Graviton-based containers on Fargate get up to 40% better performance at 20% lower cost than comparable x86 ones [36], and having an ARM image ready keeps that option open for Phase 6. Building ARM on an Intel CI machine uses an emulator (QEMU), which is slower, so pull requests build only `amd64` and the two-chip build runs only on `main`.

### Q: Does the registry cost anything?

Not for this project: GitHub Packages is free for public packages [35]. A new package on ghcr.io may start out **private** even when the repository is public. To let anyone pull it without logging in, open the package on GitHub (your profile → **Packages** → `quickserve` → **Package settings**) and change the visibility to public. On AWS we'll use Amazon ECR instead, which bills storage per GB per month [32], so that's when the "keep only the last N images" rule matters.

### Q: How do I run the published image instead of building it?

```bash
docker pull ghcr.io/revant123/quickserve:main
docker run --rm -p 8002:8000 \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@host.docker.internal:5434/quickserve \
  -e REDIS_URL=redis://host.docker.internal:6380/0 \
  ghcr.io/revant123/quickserve:main
```

This is exactly what a server does: download a tested image and give it settings through environment variables. Nothing is built on the server.

### AWS and Terraform (Phase 6)

The Terraform code that builds QuickServe on AWS is in [`infra/`](infra/), with step-by-step deploy and teardown instructions in [infra/README.md](infra/README.md). These are the questions behind it.

```mermaid
flowchart LR
    you["Browser"] -->|"HTTP :80"| app

    subgraph aws["AWS, ap-south-1 (Mumbai), built by Terraform"]
        subgraph vpc["VPC 10.20.0.0/16"]
            subgraph pub["Public subnet"]
                app["EC2 t4g.small: Docker running api, worker, redis"]
            end
            subgraph priv["Private subnets (2 zones), no internet route"]
                rds[("RDS PostgreSQL 16, db.t4g.micro")]
            end
        end
        ssm["Parameter Store: database_url, jwt_secret_key"]
        budget["Budget alert: email at 50%, 80%, forecast 100%"]
        s3[("S3: Terraform state, versioned, encrypted")]
    end

    ghcr["ghcr.io image (arm64)"] -->|"docker pull"| app
    app -->|"5432, TLS, only from the app's security group"| rds
    app -.->|"reads secrets at deploy"| ssm
    laptop["Your Mac: terraform apply"] -.-> s3
    laptop -.->|"Session Manager, no SSH"| app
```

### Q: Is anything running on AWS right now?

No. This phase is the code only, and it has never been applied. CI checks it on every pull request with fake ("mock") AWS, which needs no account and costs nothing. Deploying is a separate, deliberate step that starts with a budget alert ([infra/README.md](infra/README.md)).

### Q: Why Terraform instead of clicking through the AWS console?

Clicking can't be reviewed, repeated or undone reliably. With Terraform, the whole environment is text in Git: a pull request shows exactly what will change, `terraform plan` previews it before anything happens, and `terraform destroy` removes every piece it made, so nothing is forgotten and left billing. Building the same thing twice gives the same result, which is what lets a team run identical dev, staging and production environments.

### Q: What is Terraform "state", and why keep it in S3?

State is Terraform's memory: a file mapping each resource in the code to the real thing in AWS (this `aws_db_instance` is database `quickserve-dev-db`). Without it Terraform can't tell what to change or delete. Kept on one laptop, it's lost with the laptop and nobody else can work on the infrastructure. So it lives in an S3 bucket with **versioning** (every change keeps the previous copy), **encryption** and **all public access blocked**. Locking stops two people applying at once; Terraform's S3 backend now does this with a lock file in the bucket (`use_lockfile = true`), and the older DynamoDB lock table is deprecated [42].

One honest catch: the state contains the database password and the JWT secret in plain text, because Terraform generated them. That's why the bucket is private, encrypted and accessed only over HTTPS. Newer Terraform can keep some secrets out of state with "write-only" arguments; that's a later improvement.

### Q: Why is there a separate `bootstrap` stack?

Two things must exist before anything else. The **budget alert** comes first, so the very first mistake emails you. The **state bucket** can't store the state of the run that creates it, so bootstrap keeps its own tiny state on your laptop. You run it once per AWS account and keep it; `prevent_destroy` stops an accidental `destroy` from deleting the bucket. Budgets that only send alerts are free [48].

### Q: Why is the database in a private subnet, and why is there no NAT gateway?

A **private subnet** has no route to the internet in either direction, so the database can't be reached from outside even if a password leaks. On top of that, its **security group** accepts port 5432 only from the app server's security group: not from the internet, not from your laptop. The app connects with `sslmode=require`, so the traffic is encrypted even inside the VPC.

A **NAT gateway** would let private machines reach the internet. It bills for every hour it exists plus every GB through it (AWS's own example uses USD 0.045 per hour and per GB [37]), and it's the classic surprise on a learner's bill. Nothing here needs it: the database never calls out, and the app server sits in a public subnet behind a security group that only opens port 80.

### Q: How do I get a shell on the server without SSH?

**Session Manager**, part of AWS Systems Manager. The server has no SSH key and port 22 is closed. `aws ssm start-session` opens a shell through AWS, checked against your login, and every session can be logged. Session Manager has no extra charge [38]. There's no key file to lose or leak, and one fewer port for attackers to scan.

### Q: Where do the secrets live, and how does the app get them?

In **Parameter Store** as `SecureString` (encrypted) parameters under `/quickserve/dev/`. When `deploy.sh` runs, it reads them with the server's own permissions and writes a root-only env file for the containers. The secrets are never in the image, never in Git and never in the boot script (a test checks that). The server's permission policy allows reading `/quickserve/dev/*` and nothing else.

Why Parameter Store and not Secrets Manager? Standard parameters cost nothing [38]; Secrets Manager charges USD 0.40 per secret per month [39] and adds automatic rotation, which a two-secret dev environment doesn't need yet. The app runs with `ENVIRONMENT=dev`, so the check from Phase 3 applies: it refuses to start with the built-in development JWT secret.

### Q: If someone breaks into a container, can they steal the server's AWS access?

That's the classic cloud attack: from inside a compromised app, ask the instance metadata service (IMDS) at 169.254.169.254 for the server's temporary AWS keys. Two settings block it. **IMDSv2 required** means a token must be fetched first with a PUT request, which simple request-forgery bugs can't send. **Hop limit 1** means that token's reply dies after one network hop; a Docker container is one hop further away than the server itself, so only the host (and its deploy script) can get credentials [41].

### Q: Why one EC2 server with Docker, and not ECS, Kubernetes or a load balancer?

Cost and learning order. This setup runs the **same image and the same steps** as Docker Compose (migrate, then API and worker), so the only new things are AWS's network, database and permissions. A load balancer, ECS or EKS each add an always-on hourly charge before serving a single order. Phase 7 brings Kubernetes, health probes and zero-downtime rolling deploys on Minikube, for free on your Mac, and only then on a cloud cluster.

### Q: Why ARM (t4g), and what is "standard" CPU credit mode?

The `g` in `t4g` means Graviton (ARM), cheaper per hour than the comparable Intel types, which is why CI builds an ARM image (Phase 5b). The `t` means *burstable*: the server earns CPU credits while idle and spends them in bursts. AWS launches T4g in **unlimited** mode by default, where running hot for long bills extra "surplus credits" [40]. We set **standard** mode: the server slows down instead of charging more. For a demo, a slow minute is better than a surprise bill.

### Q: How do you test Terraform code without an AWS account?

With `terraform test` and **mock providers**. A mock provider stands in for AWS and invents fake IDs instead of calling it [43], so the checks run in CI for free. 18 tests check the rules that matter:

- the database isn't public and only the app's security group can reach it;
- secrets are encrypted and never baked into the boot script;
- the server requires IMDSv2 with hop limit 1, uses standard credits and only opens port 80;
- private subnets have no internet route, and the default security group allows nothing;
- the budget has three alerts;
- bad input is rejected: an Intel instance type (the image is ARM), a malformed IP range, one availability zone, or no alert email.

`terraform fmt` and `terraform validate` run first, and the provider lock files (`.terraform.lock.hcl`, Terraform's version of `requirements.lock`) pin the AWS provider version for every OS.

### Q: What will it cost to run?

| Piece | Mumbai on-demand price | If left on for a month |
|---|---|---|
| EC2 `t4g.small` | about USD 0.011 per hour [47] | ~USD 8 |
| RDS `db.t4g.micro`, single-AZ | about USD 0.021 per hour [46] | ~USD 15 |
| Public IPv4 address | USD 0.005 per hour [44] | ~USD 3.65 |
| Disks (16 GB + 20 GB gp3) | | a few dollars |
| Parameter Store, Session Manager, budget alerts | free [38] [48] | 0 |

That's roughly **USD 30 a month if forgotten**, or about **USD 0.15 for a 3-hour session** followed by `terraform destroy`. Prices change, so check the AWS Pricing Calculator before applying. The FinOps lesson: the cheapest resource is the one that doesn't exist while you're not using it.

### Q: How do I log in to AWS from the terminal without access keys?

`aws login` (AWS CLI 2.32 or newer) reuses your console sign-in and gives the CLI short-lived credentials that rotate automatically, so there's no long-lived access key saved on your Mac to leak [45]. The exact commands are in [infra/README.md](infra/README.md).

### Kubernetes (Phase 7)

The manifests are in [`infra/k8s/`](infra/k8s/). The same YAML runs on **minikube** on your Mac and on a throwaway **kind** cluster in CI, where every pull request deploys the app, tests it, restarts it and kills a pod on purpose.

```mermaid
flowchart LR
    you["Your browser"] -->|"kubectl port-forward :8003"| svc

    subgraph ns["namespace: quickserve"]
        svc["Service api"] --> a1["api pod"]
        svc --> a2["api pod"]
        hpa["HorizontalPodAutoscaler: 2 to 5 pods"] -.-> a1
        job["Job migrate: alembic upgrade head"] --> pg
        a1 --> pg[("StatefulSet postgres + its own disk")]
        a2 --> pg
        a1 --> rd[("Deployment redis")]
        w["worker pod"] --> pg
        w --> rd
        cm["ConfigMap app-config + Secret app-secrets"] -.-> a1
        cm -.-> w
    end
```

### Q: How do I run it on my Mac?

You need Docker Desktop running. QuickKart is not affected: minikube runs in its own container, and the API is reached on port **8003**. Run the commands **one at a time**, waiting for each to finish. If they're pasted all at once, `deploy.sh` can start before the cluster is up, and you get `connection refused` errors.

```bash
brew install minikube kubectl                  # one time
minikube start --cpus 4 --memory 3072 --cni=calico   # a one-machine cluster, ~1 minute; Calico enforces network policies (Phase 10)
minikube addons enable metrics-server          # lets the autoscaler see CPU use

cd ~/quickserve
infra/k8s/deploy.sh                            # database, Redis, migration Job, API, worker
kubectl -n quickserve exec deploy/api -- python -m scripts.seed
kubectl -n quickserve port-forward service/api 8003:80
# open http://127.0.0.1:8003/docs   (Ctrl+C stops the port-forward, not the app)
```

Things to try, each in a second terminal:

```bash
kubectl -n quickserve get pods -w                                     # watch pods change live
kubectl -n quickserve delete pod -l app.kubernetes.io/name=api --wait=false   # kill the API: it comes back by itself
kubectl -n quickserve rollout restart deployment/api                  # a rolling update
kubectl -n quickserve rollout undo deployment/api                     # roll back to the previous version
kubectl -n quickserve get hpa                                         # the autoscaler's view of CPU
kubectl -n quickserve logs deploy/worker -f                           # the worker's JSON logs
```

When you're done: `minikube stop` (keeps everything for next time) or `minikube delete` (removes the cluster and frees the disk and memory).

**Why 4 CPUs and 3 GB?** That's what worked on an 8 GB MacBook. Two things went wrong on the first try:

- **Memory:** Docker Desktop's memory is shared by everything running in Docker: QuickKart, QuickServe's Compose containers, other containers and minikube. With 2 GB used by an unrelated SQL Server container, Docker ran out of memory and swap, and Grafana couldn't start. Check with `docker stats --no-stream` and stop what you don't need (`docker stop <name>`; `docker start <name>` brings it back). minikube's `--memory` must be well below the memory set in Docker Desktop → Settings → Resources.
- **CPU:** with 2 CPUs, ten pods starting together kept the CPU at 100%. Health checks then took more than their 1-second default timeout, Kubernetes decided healthy pods were dead, and restarted them in a loop, which used even more CPU. With 4 CPUs (they're shared with macOS, not reserved) the deploy passes on the first try. The probes now also have longer timeouts (next question).

### Q: Why do the probes have explicit timeouts, and what's a startup probe?

Every probe has a `timeoutSeconds`, and **the default is 1 second**. That's fine on a quiet server, but on a laptop starting ten pods at once, a perfectly healthy API can take 1.5 seconds to answer `/health`. Kubernetes counts that as a failure, and after a few failures the liveness probe restarts the pod. Restarting makes the CPU even busier, so more probes fail: a **restart loop caused by the health checks themselves**.

The fix, now in the manifests:

- **Explicit timeouts** on every probe: 3 seconds for the API, PostgreSQL and Redis, 5 seconds for Prometheus and Grafana.
- **A startup probe on the API.** It allows up to 2 minutes for the first successful `/health`, and Kubernetes doesn't run the liveness probe until it passes. A slow start is no longer mistaken for a stuck process, while a process that hangs later is still restarted within 30 seconds.
- **Grafana's readiness** checks every 10 seconds with a 5-second timeout and allows a minute of failures, because its first start (database setup, loading dashboards) is slow.

The lesson for production: a probe that is too strict causes the outage it was meant to detect. Set timeouts from how long the endpoint really takes under load, not from the default.

### Q: I merged new code but minikube still runs the old version. Why?

Two traps, both about the moving `main` tag:

1. **Cached images.** Kubernetes only re-downloads an image automatically when the tag is `latest`. For any other tag the default is `imagePullPolicy: IfNotPresent`: if the node already has *an* image called `main`, it uses it, even if it's weeks old.
2. **Deploying too early.** Right after you merge, CI needs 3 to 5 minutes to build and publish the new image. Until then, `main` on ghcr.io still points to the **previous** build, so "deploy main" quietly runs the old code. This happened for real with Phase 8: deploying straight after the merge would have started a cluster with no notifier code in it.

`deploy.sh` now avoids both by deploying **the exact commit you have checked out**. It turns `git rev-parse HEAD` into the image tag CI publishes for that commit (`sha-bfe4bee`, for example) and checks on ghcr.io that it exists. If CI is still building, it waits (up to 10 minutes, checking every 20 seconds) instead of deploying something else.

That's the production habit from Phase 5b: deploy **immutable** tags. A new tag is a change in the YAML, so Kubernetes rolls the pods by itself, and the same tag means nothing changed and nothing restarts. You always know exactly which code is running.

Other cases:

- **You're on a feature branch** whose commit CI never published: `deploy.sh` stops and says so.
- **Uncommitted changes** in `app/`: it warns you that they aren't in the image.
- **You just want whatever `main` is right now:** run `IMAGE_TAG=main infra/k8s/deploy.sh`. For that moving tag, the local overlay's `imagePullPolicy: Always` and a restart of the API, worker and notifier still apply.

### Q: Docker Compose already runs everything. What does Kubernetes add?

Compose starts containers on one machine and mostly leaves them alone. Kubernetes keeps comparing **what you asked for** (2 API pods, this image, these settings) with **what is running**, and fixes the difference, on as many machines as you have. That gives you, without writing any of it yourself:

- **Self-healing.** A crashed or deleted pod is replaced. CI deletes an API pod on every run and checks the API still answers.
- **Rolling updates with no downtime**, and `rollout undo` to go back.
- **Autoscaling.** More pods under load, fewer when quiet.
- **One format for every cloud.** The same manifests run on minikube, EKS, GKE or AKS.

The cost is more concepts and more YAML. For one small app on one server, Compose (or Phase 6's single EC2 server) is simpler and cheaper.

### Q: What are all these objects? How do they map to Docker Compose?

| Kubernetes object | What it does here | Closest thing in Compose |
|---|---|---|
| **Pod** | One running copy of a container (plus its init containers) | A container |
| **Deployment** (`api`, `worker`, `redis`) | Keeps N identical pods running, replaces them one by one on updates | A service with `restart: unless-stopped` |
| **StatefulSet** (`postgres`) | Like a Deployment, but each pod has a stable name and its **own disk** that survives replacement | A service with a named volume |
| **Service** (`api`, `postgres`, `redis`) | One stable name and address in front of changing pods, with load balancing | The service name on Compose's network |
| **Job** (`migrate`) | Runs a pod to completion, retrying on failure | The `migrate` service with `restart: "no"` |
| **ConfigMap / Secret** | Settings and credentials, injected as environment variables | `environment:` |
| **HorizontalPodAutoscaler** | Changes the number of API pods based on CPU | No equivalent |
| **PodDisruptionBudget** | "Keep at least 1 API pod up" during maintenance | No equivalent |
| **Namespace** (`quickserve`) | A folder for all of the above; deleting it deletes everything | The Compose project |

The files are plain YAML combined by **Kustomize**, which is built into `kubectl`. `base/` holds the manifests. `overlays/local` points them at the ghcr.io image, and `overlays/ci` points them at the image CI just built. Run `kubectl kustomize infra/k8s/overlays/local` to see the final YAML.

### Q: How do migrations run, and why do the API pods wait?

The same rule as Compose: migrations run **once per deploy**, not in every API pod. A **Job** runs `alembic upgrade head`. If PostgreSQL isn't ready yet, the Job fails and Kubernetes retries it with a growing delay; you can see this in CI, where the first migration pod often shows `Error` and the second `Completed`.

In Compose, `depends_on` held the API back until the migration finished. Kubernetes has no such ordering between objects. So each API and worker pod has an **init container** that runs `scripts/wait_for_migrations.py`: it compares the database's Alembic revision with the newest migration in the image, and only lets the real container start when they match. That holds even if someone runs `kubectl apply` by hand, and a pod with new code never serves requests against an old schema. Five tests cover the script: schema current, schema behind, returning immediately, timing out, and a database that isn't reachable.

One catch: a Job's pod template can't be changed after it's created [53], so `deploy.sh` deletes the previous deploy's Job before applying the new one. Finished Jobs also delete themselves after 10 minutes (`ttlSecondsAfterFinished`).

### Q: What's the difference between the liveness and readiness probes?

They ask two different questions, and mixing them up causes outages.

- **Readiness** asks "should this pod get traffic right now?" We point it at `/health/ready`, which checks the database. When it fails, the pod is taken out of the Service's endpoints [49] but keeps running, and it gets traffic again once it recovers.
- **Liveness** asks "is this process stuck so badly that only a restart helps?" When it fails, Kubernetes restarts the container. We point it at `/health`, which checks only that the process answers.

Liveness must **not** check the database. If PostgreSQL goes down and liveness checked it, Kubernetes would restart every API pod over and over. That fixes nothing (the database is still down) and makes the recovery slower. This is the reason Phase 1 built two health endpoints.

### Q: How does a rolling update avoid dropping requests?

Three settings work together:

1. **`maxSurge: 1, maxUnavailable: 0`**: start a new pod, wait until its readiness probe passes, and only then stop an old one. Capacity never drops.
2. **A `preStop` hook that sleeps 5 seconds.** When a pod is stopped, removing it from the Service and sending it SIGTERM happen at the same time, not one after the other [50]. Without the pause, a request routed a moment before the removal could reach a pod that is already shutting down. The sleep lets routing catch up while the old pod still answers.
3. **Graceful shutdown in the app.** Uvicorn finishes the requests in progress, and the worker finishes its current pass. Kubernetes waits up to `terminationGracePeriodSeconds` (30) before forcing it.

CI proves it on every pull request: while `kubectl rollout restart deployment/api` replaces every API pod, a script inside the cluster calls the API 5 times a second. The first run recorded **295 successful requests and 0 failures**.

### Q: Why doesn't the API Deployment say how many replicas it wants?

Because the autoscaler owns that number. If the Deployment said `replicas: 2`, every `kubectl apply` would reset the count to 2, undoing whatever the autoscaler had decided under load. The Kubernetes docs recommend removing `spec.replicas` when an autoscaler is used [51]. The autoscaler keeps 2 to 5 API pods and aims for 70% of the CPU each pod requested.

### Q: What do `requests` and `limits` mean, and why are they FinOps?

- A **request** is what the scheduler reserves for the pod on a machine. It decides which machine the pod goes on [52], and so how many machines (nodes) the cluster needs. **On a cloud cluster, requests are what you pay for**, whether the pod uses them or not.
- A **limit** is the ceiling. A container that goes over its memory limit may be killed (OOMKilled), and one that wants more CPU than its limit is slowed down.

| Pod | CPU request | Memory request | Memory limit |
|---|---|---|---|
| api (2 to 5 of them) | 100m (a tenth of a core) | 192 Mi | 512 Mi |
| worker | 50m | 128 Mi | 256 Mi |
| postgres | 100m | 256 Mi | 512 Mi |
| redis | 50m | 64 Mi | 128 Mi |

At the minimum (2 API pods) that's about 0.4 CPU and 830 Mi reserved, which fits a small node with room to spare. The autoscaler's `maxReplicas: 5` is a cost ceiling: a traffic spike or a runaway loop can't keep adding pods forever. Requests set too high waste money; set too low, pods get squeezed or killed. Measuring real use (`kubectl top pods`) and adjusting is called **rightsizing**. Phase 8b measures it and prices the difference: see [rightsizing](#q-what-is-rightsizing).

### Q: How are the pods locked down?

Every QuickServe container runs with:

- **`runAsNonRoot` and `runAsUser: 10001`.** This is the `app` user from the Dockerfile. It has to be the number, not the name: Kubernetes can only check a numeric user is non-root.
- **`readOnlyRootFilesystem: true`.** The app never writes to its own files, so an attacker can't either.
- **`allowPrivilegeEscalation: false`, all Linux capabilities dropped, and the default seccomp profile.** These remove the kernel-level powers a web app never needs.

CI checks that `id -u` inside the API pod prints `10001`.

### Q: Why is PostgreSQL a pod here, when Phase 6 used RDS?

For learning on a laptop, a StatefulSet with its own 1 GiB disk is enough, and it's free. In production, a managed database (RDS) handles backups, patching and failover far better than one pod can, and that's what the cloud setup uses. A real cluster would then drop `postgres.yaml` and point `DATABASE_URL` at RDS.

### Q: The database password is in `kustomization.yaml`. Isn't that a leak?

It's the same local-only `postgres` password as `docker-compose.yml`, and the file says so. Kustomize turns it into a Secret whose name includes a hash of the contents, so changing a value creates a new Secret and the pods restart with it. On a real cluster, secrets come from outside Git, for example the External Secrets Operator syncing them from AWS Parameter Store (Phase 6). Kubernetes Secrets are only base64-encoded, not encrypted, unless the cluster turns on encryption at rest.

### Q: Why kind in CI but minikube on the Mac?

Both run a real Kubernetes cluster inside Docker. **minikube** has handy add-ons (metrics-server, dashboard, ingress), which suit learning. **kind** ("Kubernetes in Docker") starts quickly and is built for disposable test clusters, including in CI [54]. The CI job creates a kind cluster, loads the image built from that commit, runs `deploy.sh`, and then:

- seeds the demo data and logs in from inside the cluster;
- checks the pods run as non-root;
- does a rolling restart and requires zero failed requests;
- deletes a pod and checks it's replaced.

The cluster disappears when the job ends. Before any of that, `kubeconform` checks every manifest against the Kubernetes API schema.

### Q: What's not done yet?

- **Ingress with HTTPS.** Done in Phase 9, with Gateway API instead of Ingress: see [HTTPS front door](#https-front-door-gateway-api-phase-9).
- **NetworkPolicies** ("only the API may talk to PostgreSQL"). Done in Phase 10: see [Network policies](#network-policies-phase-10).
- **Metrics and dashboards** (Prometheus and Grafana).
- **A worker heartbeat** so Kubernetes can tell a stuck worker from a busy one.

Those are the next phases in the [roadmap](#13-roadmap).

### Monitoring (Phase 7b)

Kubernetes now also runs **Prometheus**, which collects numbers from the app every 15 seconds and checks the alert rules, and **Grafana**, which draws them. Everything is set up from files in [`infra/k8s/monitoring/`](infra/k8s/monitoring/), so a fresh cluster has the dashboard and the alerts with nothing to click.

```mermaid
flowchart LR
    subgraph app["QuickServe pods"]
        api["api pods: /metrics on port 9100"]
        worker["worker pod: /metrics on port 9101 (+ heartbeat)"]
    end
    prom["Prometheus: scrape every 15 s, keep 2 days, run rules.yml"] -->|"finds pods via the Kubernetes API"| api
    prom --> worker
    prom --> rules["Recording rules: error rate, p95, orders per hour, cost per order"]
    prom --> alerts["Alert rules: API down, errors, slow, worker failing, payments failing, login attack"]
    grafana["Grafana: QuickServe overview dashboard"] -->|"PromQL"| prom
    you["You"] -->|"port-forward :3005"| grafana
```

### Q: How do I see the dashboard?

The monitoring stack is part of the **full** setup. Since Phase 10, plain `infra/k8s/deploy.sh` deploys the lighter "lite" setup without it (see [why](#q-why-does-deploysh-deploy-a-lite-setup-on-the-mac)). So stop QuickKart first, deploy the full setup with `infra/k8s/deploy.sh infra/k8s/overlays/local`, and then open two more terminals:

```bash
kubectl -n quickserve port-forward service/grafana 3005:3000      # http://127.0.0.1:3005
kubectl -n quickserve port-forward service/prometheus 9095:9090   # http://127.0.0.1:9095 (optional)
```

Grafana opens straight on the **QuickServe overview** dashboard, and you can view it without logging in. To edit, log in as `admin` / `quickserve-admin` (a local-only password, like the database's). The numbers move once there is traffic: place and pay for a few orders in Swagger (port 8003), log in with a wrong password a few times, and watch the panels change within a minute. In Prometheus, **Alerts** shows every rule and whether it's firing, and **Status → Targets** shows the pods it scrapes.

### Q: We already have logs. What do metrics add?

A **log line** tells the story of one request: who, what, how long, which error. A **metric** is a number added up across all requests, such as "requests per second" or "orders in the last hour", and it's cheap to keep every 15 seconds for days. You look at metrics to notice that something is wrong ("errors jumped to 8% at 14:02"), then at logs to find out why (search for `"level": "ERROR"` around 14:02, then follow one `request_id`). Alerts are built on metrics, because "more than 5% of requests failed for 5 minutes" is a question about numbers.

### Q: What does QuickServe measure, and why those?

Google's SRE book names four **golden signals** for any user-facing system: latency, traffic, errors and saturation [55]. For request-driven services they're often shortened to **RED** (Rate, Errors, Duration). QuickServe measures those, plus the business numbers that Zomato or Swiggy would watch on a big screen.

| Metric | Type | Labels | The question it answers |
|---|---|---|---|
| `quickserve_http_requests_total` | counter | method, route, status | How busy are we (rate)? How many fail (errors)? |
| `quickserve_http_request_duration_seconds` | histogram | method, route | How slow are the slowest 5% (duration, p95)? |
| `quickserve_orders_placed_total` | counter | none | Orders per hour |
| `quickserve_order_value_rupees` | histogram | none | Average order value (AOV) |
| `quickserve_order_status_changes_total` | counter | to_status, actor | How many orders end delivered, cancelled, rejected or unpaid, and who caused it |
| `quickserve_payments_total` | counter | outcome | Payment success rate |
| `quickserve_menu_cache_requests_total` | counter | result (hit, miss, bypass) | Is the Redis cache earning its keep? |
| `quickserve_logins_total` | counter | outcome (success, failed, blocked) | Is someone guessing passwords? |
| `quickserve_worker_last_run_timestamp_seconds` | gauge | none | Is the worker loop alive? (its liveness probe) |
| `quickserve_worker_last_success_timestamp_seconds` | gauge | none | Is the timeout job actually succeeding? |
| `quickserve_worker_orders_timed_out_total` | counter | reason | How many orders expire unpaid or are auto-rejected |
| `quickserve_db_pool_connections_in_use` | gauge | pod | Saturation: is the connection pool running out? |

A **counter** only goes up, and Prometheus works out rates from it. A **gauge** goes up and down. A **histogram** counts values into buckets (under 10 ms, under 25 ms, and so on), which is what makes "the slowest 5%" possible.

### Q: Why "the slowest 5%" (p95) and not the average response time?

Averages hide pain. If 95 requests take 20 ms and 5 take 3 seconds, the average is 169 ms, which looks fine, but one customer in twenty waits 3 seconds. The **95th percentile** (p95) says "95% of requests were faster than this", so it shows exactly those 5 slow ones. The `QuickServeSlowResponses` alert watches p95, not the average.

### Q: Why is `/metrics` on a separate port and not on the API?

Orders per hour and payment success rate are business data, and competitors would love them. The API's public port (8000, behind the `api` Service) doesn't serve `/metrics` at all, and a test checks that it answers 404. The numbers are on port 9100 (API) and 9101 (worker). Those ports are declared on the pod but **not** in the Service, so only Prometheus, from inside the cluster, can reach them.

### Q: Why is the label `/api/v1/orders/{order_id}` and not the real URL?

Every distinct combination of label values is a separate **time series** that Prometheus stores and indexes. Labelled with the real path, each order ID would create a new series: a million orders, a million series, and Prometheus runs out of memory. The Prometheus docs say not to use labels for unbounded values such as user IDs [56]. So the middleware labels each request with the **route template** FastAPI matched, and every URL that matched no route (bots scanning for `/wp-admin`) shares a single `unmatched` label. Tests check both.

It's also a FinOps rule. Managed Prometheus services bill per sample ingested: AWS charges USD 0.90 per 10 million samples for the first 2 billion [57]. Their own pricing example, 10 nodes with 1,000 metrics each scraped every 30 seconds, comes to about USD 81 a month for ingestion alone [58]. Each label you add multiplies the number of series, and with it the bill.

### Q: How do you stop a failed order from being counted?

This one is an ORM lesson. The status-change code runs **inside** a database transaction. If the counter went up right there and the transaction then rolled back (stock ran out on the third item, say), the dashboard would show orders that don't exist.

So `after_commit(db, ...)` in `app/core/metrics.py` doesn't increment anything yet. It parks the increment on the SQLAlchemy session, and two **session events** finish the job. `after_commit` runs the parked increments once the commit has succeeded, and `after_rollback` throws them away. Tests check this both ways: an out-of-stock order and a refused cancellation leave the counters untouched.

### Q: How is "cost per order" calculated?

It's the FinOps **unit metric** from [section 10](#10-finops-thinking-in-cost-per-order), now live on the dashboard. Two recording rules in `rules.yml` compute it:

```
quickserve:infra_cost_usd:per_hour = 0.04          # the Phase 6 AWS estimate
quickserve:cost_per_order_usd:1h   = cost per hour / orders placed in the last hour
```

With 240 orders an hour, an order costs USD 0.000167 in infrastructure. With 24 an hour, it costs ten times more, on the same machines. That's why FinOps tracks cost **per order** and not just the monthly bill: a growing bill can be healthy if cost per order falls. The hourly cost is a constant for now. On a real cluster it would come from a cost tool such as **OpenCost**, a CNCF project that splits Kubernetes costs by namespace, workload or pod and exports them to Prometheus [59]. Phase 8b explains [why it's not used yet](#q-the-cost-per-order-still-uses-a-fixed-004-usd-an-hour-why-not-opencost) and prices pod requests instead.

### Q: Which alerts are there, and how do you know they work?

| Alert | Fires when | Severity |
|---|---|---|
| `QuickServeAPIDown` | Prometheus can't reach any API pod for 2 minutes | critical |
| `QuickServeHighErrorRate` | More than 5% of requests fail with a 5xx for 5 minutes | critical |
| `QuickServeSlowResponses` | p95 latency above 500 ms for 10 minutes | warning |
| `QuickServeWorkerFailing` | The timeout job hasn't succeeded for 5 minutes | critical |
| `QuickServePaymentsFailing` | Under 80% of payments succeed, with at least 20 attempts in the hour | critical |
| `QuickServeLoginAttack` | More than 10 blocked logins a minute for 5 minutes | warning |

The `for:` part of each rule means one bad scrape doesn't wake anyone at 3 a.m. The payments alert also needs at least 20 attempts, so two failures in a quiet hour don't count as "50% failing".

An alert rule that never fires looks exactly like a healthy system, so the rules have **unit tests**. `rules_test.yml` feeds `promtool test rules` [60] made-up metric history, such as "10 of every 70 requests fail" or "the worker's last success never moves", and checks which alerts fire, when, and with what message. Each alert is also tested in a healthy case where it must stay quiet. CI runs these tests and `promtool check config` on every pull request.

Phase 7b stopped at Prometheus's **Alerts** page. Phase 8b adds **Alertmanager**, which turns a firing alert into an email (and could just as well send a Slack message or a phone call), plus an always-firing `Watchdog` alert. See [Alert emails and rightsizing](#alert-emails-and-rightsizing-phase-8b-finops).

### Q: How does the worker's heartbeat work?

Every pass of the worker loop, successful or not, updates `quickserve_worker_last_run_timestamp_seconds`. Its Kubernetes **liveness probe** runs `python -m app.worker --healthcheck`, which reads that number from port 9101 and fails if no pass finished in the last 2 minutes. A stuck loop therefore gets the pod restarted.

A pass that **fails**, because PostgreSQL is down for example, still counts as a beat. That's the Phase 7 lesson again: restarting the worker can't fix the database. That case raises the `QuickServeWorkerFailing` alert instead, so a person looks. Four tests cover the healthcheck: fresh, stuck, failing but alive, and not running at all. CI also checks that the worker was never restarted.

### Q: What does monitoring cost, and what keeps it cheap?

| Choice | Why |
|---|---|
| Scrape every 15 s, not every 1 s | 15 times fewer samples to store, and still spots a problem within a minute |
| Keep 2 days, at most 1 GB | Enough to compare today with yesterday; disk can't fill up |
| Few labels, all with a fixed set of values | The number of series stays small and predictable |
| Recording rules for every dashboard number | Each panel reads one ready-made series instead of crunching raw data on every refresh |
| Requests and limits on Prometheus and Grafana | Monitoring can't starve the app it watches |

The trade-off is that metrics live on the pod's own disk (`emptyDir`) and vanish if Prometheus restarts. That's fine for learning; a real setup gives Prometheus a persistent disk or sends the data to a managed service.

### Q: What does CI check for monitoring?

1. `promtool check config` and `promtool test rules` (the alert unit tests above).
2. On the kind cluster, after the smoke test, a script in the cluster asks Prometheus:
   - Is every API, worker and notifier pod being scraped?
   - Was the login from the smoke test counted?
   - Is the worker heartbeat fresh?
   - Do the recording rules produce numbers?
   - Is any alert firing? (None may be, apart from the always-on `Watchdog`.)
3. It asks Grafana whether the QuickServe dashboard loaded (28 panels, including the notifications row from Phase 8 and the rightsizing row from Phase 8b).
4. It checks that the worker's liveness probe never restarted it.

### Notifications and the outbox pattern (Phase 8)

Every order step now notifies the right people, as Zomato and Swiggy do. The customer hears "Payment received", "Your food is being prepared", "On the way!". The restaurant hears "New order: ₹540, 2 item(s). Accept it within 4 minutes". The interesting part isn't the messages. It's making sure that **no notification is lost, none is sent twice, and none arrives out of order**, even when processes crash. That's the **transactional outbox** pattern, a classic system design interview topic.

```mermaid
sequenceDiagram
    participant C as Customer app
    participant API as API (orders module)
    participant DB as PostgreSQL
    participant N as Notifier (separate process)
    C->>API: POST /orders/{id}/payments
    API->>DB: BEGIN
    API->>DB: UPDATE orders SET status = 'PAID'
    API->>DB: INSERT INTO outbox_events (order.status_changed, PAID)
    API->>DB: COMMIT (both or neither)
    API-->>C: 201 Created
    loop every 2 seconds
        N->>DB: SELECT ... FOR UPDATE SKIP LOCKED (oldest waiting event per order)
        N->>DB: INSERT notifications ... ON CONFLICT DO NOTHING
        N->>DB: UPDATE outbox_events SET published_at = now()
        N->>DB: COMMIT
    end
    C->>API: GET /notifications
    API-->>C: "Payment received"
```

### Q: Why not just send the notification right after saving the order?

Because that's two writes to two different systems, and they can't be made atomic: the **dual-write problem** [61].

- **Save, then notify.** The process crashes in between, a deploy restarts it, or the push provider times out. The order is PAID, but the customer and the restaurant are never told. The restaurant never starts cooking, and the order is auto-rejected after 4 minutes.
- **Notify, then save.** The save then fails or rolls back (stock ran out, a deadlock). The restaurant was told about an order that doesn't exist.

Retrying doesn't fix either case. You just get "lost" or "sent twice" in different proportions.

### Q: So what does the outbox do?

It turns two writes into **one**. The orders code writes the event as a row in `outbox_events`, **inside the same transaction** as the status change. PostgreSQL then guarantees both are committed or neither is. A separate process, the **notifier**, reads waiting events and delivers them afterwards. If the notifier is down for an hour, events wait in the table and nothing is lost; it catches up when it's back. That's the pattern as Chris Richardson describes it [61].

In the code:

- `_publish()` in `app/modules/orders/service.py` is called from `place_order()` and from `_apply()`, which every status change goes through, so no change can skip it.
- A test checks that an order that fails (out of stock) leaves **no** event. It rolled back together with the order, so nobody is told about a phantom order.

### Q: What's in an event, and why so much?

```json
{"order_id": "…", "customer_id": "…", "owner_id": "…", "restaurant_name": "Pal Dhaba",
 "status": "PAID", "previous_status": "PLACED", "actor": "system", "note": null,
 "grand_total": "540.00", "item_count": 2}
```

Everything the notifications service needs to word its messages and pick the recipients. This is called **event-carried state transfer**. The notifications module never imports the orders module and never reads the `orders` or `restaurants` tables. That's what lets it become a truly separate service later, with its own database, without changing its logic.

### Q: The notifier can crash halfway. Can a notification be sent twice?

Delivery is **at-least-once**. Suppose the notifier handles an event and then dies before marking it published. Next time it handles the same event again. The answer is an **idempotent consumer**: handling the same message twice must have the same effect as handling it once [62].

Here that's a database constraint. `notifications` has `UNIQUE (event_id, user_id)`, and the insert is `INSERT ... ON CONFLICT DO NOTHING RETURNING id`, so a repeat creates nothing and returns nothing. A test simulates the crash by marking delivered events as undelivered: the second pass handles both events again and creates **zero** new notifications.

The same idea applies to real push or SMS providers. Send the provider an idempotency key (the event ID), and it drops the duplicate. That's the same trick QuickServe's own payments endpoint uses with `Idempotency-Key`.

### Q: How do events of one order stay in order?

The notifier only claims the **oldest waiting event of each order**. The query adds `NOT EXISTS (an earlier undelivered event for the same order)`. Suppose "PAID" fails, because the push provider timed out. Then "ACCEPTED" for that order waits behind it, so the customer can't hear "accepted" before "payment received". A test checks exactly this.

Events of **different** orders don't wait for each other, so one broken order can't hold up everyone. In Kafka terms, the order ID is the partition key.

### Q: What if two notifiers run at once?

They share the work. Events are claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, the same clause the timeout worker uses. One notifier locks a batch, and the other skips those rows and takes different ones instead of waiting. PostgreSQL's docs describe skipping locked rows as being for queue-like tables with several consumers [63]. Because of the per-order rule above, ordering still holds with several notifiers. A test runs two at once and checks that each event is delivered exactly once.

### Q: What happens to an event that keeps failing?

- **Retry with exponential backoff.** The next attempt is in 2 s, then 4, 8 and 16, up to 5 minutes. A struggling dependency gets breathing room instead of a retry storm.
- **Dead-letter after 5 attempts.** The event gets `dead_at`, and its `last_error` is kept. It stops being retried, and the `QuickServeOutboxDeadLetters` alert fires.
- **A dead event doesn't block its order forever.** Later events for that order continue.
- **One bad event doesn't spoil the batch.** Each event is handled in its own **SAVEPOINT**, so a failure undoes only that event's work.

To resend a dead event after fixing the cause, a person runs `UPDATE outbox_events SET dead_at = NULL, attempts = 0, available_at = now() WHERE id = …`.

### Q: Who is told about what?

| Order becomes | Customer | Restaurant |
|---|---|---|
| PLACED | "Order placed: pay ₹X to confirm" | nothing: an unpaid order may never happen |
| PAID | "Payment received" | "New order: ₹X, N item(s). Accept within 4 minutes" |
| ACCEPTED, PREPARING, READY, OUT_FOR_DELIVERY, DELIVERED | one message each | nothing |
| PAYMENT_FAILED | "Order cancelled: payment not completed. No money was taken" | nothing |
| REJECTED | "… couldn't take your order. Refund of ₹X started" | nothing (they rejected it) |
| CANCELLED | "Order cancelled", plus the refund if it was paid | only if it was paid: they may already be cooking |

The wording lives in `app/modules/notifications/templates.py`, with a test for each row.

### Q: Polling every 2 seconds sounds wasteful. What are the alternatives?

When idle, the notifier runs one cheap query every 2 seconds against a **partial index** that only contains waiting events. That index stays tiny no matter how many delivered events exist. A busy notifier doesn't sleep at all: a full batch means it immediately takes the next one.

Two upgrades exist:

- **PostgreSQL `LISTEN/NOTIFY`** wakes the notifier the moment an event is committed.
- **Change data capture (CDC)** with **Debezium** reads new outbox rows from PostgreSQL's write-ahead log and publishes them to Kafka, with no polling at all [64].

That's the usual path when the notifications service moves to its own database. The outbox table and the consumer stay the same, and only the relay changes.

### Q: Doesn't the outbox table grow forever?

No. Delivered events are deleted after 7 days (`outbox_retention_days`), in batches of 1,000 so each delete is short. The notifications themselves are kept. That's FinOps for databases: a table nobody reads still costs storage, backup time and slower vacuums.

### Q: How do I know the notifier is healthy?

It's a separate Deployment with the same production habits as the worker:

- **Heartbeat liveness probe.** `python -m app.notifier --healthcheck` restarts the notifier only if its loop is stuck, not when deliveries fail.
- **Metrics on port 9102**, which Prometheus scrapes:
  - events waiting, and the age of the oldest one;
  - dead letters;
  - events processed by outcome;
  - notifications by kind.
- **Three new alerts, unit-tested with promtool:**
  - `QuickServeNotifierDown`: events pile up, though none are lost;
  - `QuickServeNotificationsDelayed`: the oldest waiting event is over a minute old for 5 minutes;
  - `QuickServeOutboxDeadLetters`.
- **A new "Notifications (outbox)" row** on the Grafana dashboard.

In CI, the Kubernetes smoke test places and pays for a real order and waits until `GET /notifications` shows "Payment received" for it. That covers the whole path: API, outbox, notifier and notifications API.

### Q: Try it

With the app running (Docker Compose, minikube or `uvicorn` plus `python -m app.notifier`):

1. In Swagger, log in as `customer@quickserve.dev`, place an order and pay for it.
2. Call `GET /api/v1/notifications`: "Payment received" and "Order placed" are there within a couple of seconds.
3. Log in as `owner@quickserve.dev`: "New order: ₹…" is waiting.
4. Stop the notifier (`docker stop quickserve-notifier`, or `kubectl -n quickserve scale deploy/notifier --replicas=0`). Place another order: no notification appears. Then start the notifier again: the waiting events are delivered. Nothing was lost.

### Alert emails and rightsizing (Phase 8b: FinOps)

Phase 7b could detect problems, but nobody was told: alerts only showed on Prometheus's **Alerts** page. Phase 8b adds the missing link, **Alertmanager**, which turns firing alerts into emails, plus a local inbox (**Mailpit**) to read them. The FinOps half answers a question every cloud bill raises: *do the pods really need what they reserve?*

```mermaid
flowchart LR
    prom["Prometheus: evaluates rules.yml every 15 s"] -->|"firing alerts"| am["Alertmanager: group, inhibit, route, repeat"]
    am -->|"SMTP"| mp["Mailpit: test inbox (port-forward :8026)"]
    prom --> rs["Recording rules: CPU and memory per pod"]
    rs --> graf["Grafana: Rightsizing row"]
    rs --> script["rightsizing.py: requested vs used, in USD"]
```

### Q: How do I see the alert emails?

After the full setup, `infra/k8s/deploy.sh infra/k8s/overlays/local` (run each line on its own):

```bash
kubectl -n quickserve port-forward service/mailpit 8026:8025       # http://127.0.0.1:8026
kubectl -n quickserve port-forward service/alertmanager 9096:9093  # http://127.0.0.1:9096 (optional)
```

Port **8026**, not 8025: QuickKart's own Mailpit already uses 8025 on your Mac. Within a minute of the deploy, the inbox has an email called **"[FIRING:1] Watchdog (none)"**. That one is good news (see below). To see a real alert, stop the API:

```bash
kubectl -n quickserve scale deployment/api --replicas=0
```

After about 2 minutes, `QuickServeAPIDown` fires and an email arrives. Put it back with `kubectl -n quickserve scale deployment/api --replicas=2`, and a **[RESOLVED]** email follows, because `send_resolved: true` is set.

### Q: Prometheus already knows an alert is firing. Why is Alertmanager a separate program?

Because deciding *something is wrong* and deciding *who hears about it, how often* are different jobs. Prometheus evaluates rules; Alertmanager deduplicates, groups and routes the alerts, and also handles silencing and inhibition [65]. With several Prometheus servers (one per cluster, or two for redundancy), they all send to the same Alertmanager, which removes the duplicates. Prometheus's docs also warn not to put a load balancer between Prometheus and its Alertmanagers. Point Prometheus at all of them instead [65].

In QuickServe this is three lines in `prometheus.yml` (`alerting: alertmanagers: alertmanager:9093`) and one file, [`alertmanager.yml`](infra/k8s/monitoring/alertmanager.yml).

### Q: What do `group_by`, `group_wait`, `group_interval` and `repeat_interval` do?

They decide how many emails a bad night produces. This matters more than it sounds, because a pager that rings all the time gets ignored.

| Setting | QuickServe value | Meaning |
|---|---|---|
| `group_by: [alertname]` | per alert name | If 5 API pods fail the same check, that's **one** email listing 5, not 5 emails |
| `group_wait` | 30 s | Wait 30 s after the first alert of a new group, so its neighbours arrive in the same email |
| `group_interval` | 5 min | If a group already emailed and gains a new alert, wait at least 5 min before the update |
| `repeat_interval` | 4 h (critical: 1 h) | Something still broken is re-sent, but not every few minutes |

Critical alerts get their own **route** with a 1-hour repeat. Routes are a tree: an alert walks down it and the first matching branch decides the receiver and timings. A real team would send `critical` to PagerDuty and `warning` to Slack. Here everything goes to one email address, because the point is to see the mechanics.

### Q: What is inhibition?

Muting alerts that are only *symptoms* of another alert that's already firing. If every API pod is down, error rate and latency are meaningless, and three emails about one problem is noise. So `alertmanager.yml` says:

- while `QuickServeAPIDown` fires, don't send `QuickServeHighErrorRate` or `QuickServeSlowResponses`;
- while `QuickServeNotifierDown` fires, don't send `QuickServeNotificationsDelayed` (of course notifications are delayed: nothing is delivering them).

This was tested before merging: with both API-down and high-error-rate alerts active, Alertmanager marked the error-rate alert `suppressed, inhibited by` the API-down one, and only the API-down email was sent.

Inhibition is different from a **silence**. A silence is a person muting matching alerts for a fixed time, from the Alertmanager page or API, for example during planned maintenance [65]. It's temporary and manual; inhibition is permanent config tied to another alert. Silence an alert; don't delete the rule, or you lose it for good.

### Q: Why is there an alert that is always firing?

That's the **Watchdog**, also called a *dead man's switch*. Its expression is `vector(1)`, which is always true. If Prometheus, the rules, Alertmanager or email delivery break, the problem isn't "an alert fires". It's that **no** alert can fire, and silence looks exactly like a healthy system. The Watchdog turns silence into a signal. The prometheus-operator runbook describes it as an alert that checks the whole alerting pipeline works, so it should always be firing in Alertmanager and always reach a receiver [66].

Our Watchdog email repeats once a day. Honest caveat: in this project it lands in the same inbox as everything else, so a person has to notice it's *missing*. In production it goes to an outside service such as Dead Man's Snitch or Healthchecks.io, which pages you when the daily email *doesn't* arrive [67]. The smoke test treats it as the normal case: "no alerts firing" now means "none apart from the Watchdog".

### Q: What is Mailpit, and why not a real email address?

Mailpit is a fake mail server: it accepts SMTP on port 1025 and shows every message in a web page, but never sends anything outside the cluster. You can see real alert emails without an email account, passwords in the config, or spam filters. Changing `alertmanager.yml` to Gmail, Slack or PagerDuty is a config change; the routing and inhibition stay the same.

It's locked down like everything else (no privilege escalation, all Linux capabilities dropped, small requests) and keeps at most 500 emails, so its memory can't grow forever.

### Q: What is rightsizing?

Setting each pod's **requests** to what it really uses, plus some headroom. Phase 7 explained that requests are what the scheduler reserves, used or not, and that requests decide how many nodes you need [52]. The guesses in the manifests (API 100m CPU / 192 Mi, worker 50m / 128 Mi, notifier 25m / 128 Mi) were deliberately generous. Rightsizing replaces guesses with measurements.

Some platforms make the link to money direct. **AWS Fargate bills the vCPU and memory a task asks for**, from start to stop, however much it actually uses: USD 0.04048 per vCPU-hour and USD 0.004445 per GB-hour on Linux/x86 in us-east-1, about 20% less on ARM (Graviton) [68][69]. On your own nodes the effect is indirect but the same: over-asking means more nodes.

### Q: Where do the "used" numbers come from?

Every Python process using `prometheus_client` exports `process_cpu_seconds_total` and `process_resident_memory_bytes` for free. QuickServe already exposes them on its metrics ports. Four recording rules in `rules.yml` turn them into per-pod and per-app numbers:

```yaml
- record: quickserve:pod_cpu_cores:rate5m   # CPU-seconds per second = cores in use; 0.05 = 50m
  expr: sum by (app, pod) (rate(process_cpu_seconds_total{job="quickserve"}[5m]))
- record: quickserve:pod_memory_bytes        # resident memory right now
  expr: sum by (app, pod) (process_resident_memory_bytes{job="quickserve"})
```

They are unit-tested with promtool like the alerts: two fake API pods each burning 1.8 CPU-seconds a minute must show 0.03 cores (30m) each, and 0.06 for the app.

On a real cluster you'd use **cAdvisor** (built into the kubelet) for container usage and **kube-state-metrics** for requests, which covers every pod, PostgreSQL included. Process metrics only cover our own Python pods, but need no extra components or cluster-wide permissions, and they're enough to learn the method.

### Q: How do I run the rightsizing report?

```bash
python3 infra/k8s/rightsizing.py              # the last hour
python3 infra/k8s/rightsizing.py --window 7d  # the window you'd really decide on
```

It needs only `kubectl`. It reads the requests from the live Deployments and asks Prometheus through the Kubernetes API server's service proxy (`kubectl get --raw /api/v1/namespaces/quickserve/services/prometheus:web/proxy/...`), so no port-forward is needed [70]. Output from a test run (yours will differ):

```
app       pods  CPU req  CPU p95  CPU peak  -> CPU  MEM req  MEM peak  -> MEM
api          2     100m      18m       19m     25m    192Mi      83Mi   112Mi
notifier     1      25m       3m        3m     10m    128Mi      53Mi    80Mi
worker       1      50m       4m        4m     10m    128Mi      43Mi    64Mi

Reserved but unused (all pods): 0.23 vCPU of 0.28, 0.37 GiB of 0.62.
Priced per request (AWS Fargate, ARM, us-east-1): $8.12/month now, $2.59/month with the recommended requests (-68%).
```

The Grafana dashboard has a new **Rightsizing** row with the same CPU and memory per pod over time.

### Q: Why is CPU sized from p95 but memory from the peak?

Because they fail differently:

- **CPU is compressible.** A pod that needs more CPU than its request gets less of it: it slows down, it doesn't die. Sizing for the p95 (the busiest 5% of moments excluded) and letting the limit absorb rare spikes is a sensible trade.
- **Memory isn't.** A container that goes over its memory limit is killed (OOMKilled) and restarted [52]. One spike is enough. So memory is sized from the **highest** value seen.

Both get 25% headroom, are rounded up (CPU to 5m, memory to 16 Mi), and never go below a floor (10m, 64 Mi) where the numbers are mostly noise.

### Q: The report says I can save 68%. Should I change the requests now?

**No.** This is the most important FinOps lesson in the phase. An hour of an idle minikube with a few test orders says nothing about the dinner rush. Shrink the requests on that basis, and Friday at 8 pm the API pods are throttled and slow, the autoscaler panics, and pods get OOMKilled. The report says so itself when it has less than a day of data.

The right process:

1. Measure over at least a week that includes your busiest hours.
2. Change one service at a time, in the manifests in `infra/k8s/base/`. The files are the source of truth, so a `kubectl set resources` would be undone by the next deploy.
3. Watch latency, restarts and throttling after the change, and be ready to roll back.

So the manifests in this PR keep their original requests on purpose. The value is the method and the tool, not today's numbers.

### Q: Doesn't Kubernetes do this automatically?

Partly. The **Vertical Pod Autoscaler (VPA)** watches usage and adjusts requests from history [71]. It's not part of core Kubernetes; it's an add-on with its own components. Teams often start it in recommendation-only mode (`updateMode: "Off"`), which suggests values without restarting anything. That's exactly what `rightsizing.py` does by hand, which makes it a good way to understand what VPA computes. One caution: VPA and the HPA shouldn't both react to the same CPU metric, because they'd fight. Our API scales on CPU with the HPA, so its requests would be rightsized by hand.

### Q: The cost per order still uses a fixed 0.04 USD an hour. Why not OpenCost?

**OpenCost** (a CNCF project) splits a cluster's real bill across namespaces, deployments and pods, and exports it to Prometheus [59]. That's the next step once QuickServe runs on a cloud cluster with real prices. On minikube there's no bill to split: the "cost" is your laptop, and the numbers would be invented. OpenCost also needs cluster-wide permissions and its own Prometheus queries, which is a lot of setup for a constant. For now, the honest approach is to price **requests** with a public list price (the Fargate rates above) and keep the per-hour constant clearly labelled as an estimate.

### Q: What does CI check now?

On top of everything from Phase 7b:

1. `amtool check-config alertmanager.yml`, next to the Prometheus checks.
2. A new promtool test for the Watchdog and one for the rightsizing rules.
3. On the kind cluster, the monitoring check also confirms:
   - Prometheus has discovered Alertmanager;
   - the rightsizing rules see all three apps;
   - the Watchdog reached Alertmanager (its API at `/api/v2/alerts`);
   - the Watchdog **email** reached Mailpit (`/api/v1/messages`).

   That last one tests the whole chain: rule → Prometheus → Alertmanager → SMTP → inbox.
4. A new step runs `rightsizing.py` against the live cluster, so the report can't silently break.

### HTTPS front door: Gateway API (Phase 9)

Until now every service was reached with its own `kubectl port-forward`, over plain HTTP. Phase 9 adds what a real deployment has in front of its apps: **one front door** that ends HTTPS, sends each hostname to the right service, redirects plain HTTP, and turns away abuse before it costs CPU.

```mermaid
flowchart LR
    you["Browser / curl"] -->|"https://quickserve.localhost:8443"| envoy
    you -->|"https://grafana.quickserve.localhost:8443"| envoy
    subgraph egs["namespace envoy-gateway-system"]
        envoy["Envoy proxy (Service quickserve-gateway): TLS, routing, rate limit"]
        eg["Envoy Gateway controller"]
    end
    eg -.->|"reads Gateway + HTTPRoutes, configures"| envoy
    subgraph qs["namespace quickserve"]
        api["Service api -> API pods"]
        grafana["Service grafana"]
        cert["Secret quickserve-tls"]
    end
    cm["cert-manager"] -.->|"creates and renews"| cert
    envoy -->|"Host: quickserve.localhost"| api
    envoy -->|"Host: grafana.quickserve.localhost"| grafana
    envoy -.->|"uses"| cert
```

### Q: How do I open it?

After `infra/k8s/deploy.sh`, in its own terminal:

```bash
kubectl -n envoy-gateway-system port-forward service/quickserve-gateway 8443:443
```

Then open **https://quickserve.localhost:8443/docs** (Swagger) and **https://grafana.quickserve.localhost:8443** (Grafana) in Chrome. Names ending in `.localhost` always point to your own machine, so there's nothing to add to `/etc/hosts`.

The browser warns that the certificate isn't trusted. That's expected: it was signed by QuickServe's own small certificate authority (CA), which your Mac doesn't know. In Chrome, click **Advanced → Proceed**. To see a clean check, give curl the CA:

```bash
kubectl -n quickserve get secret quickserve-ca -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/quickserve-ca.crt
curl --cacert /tmp/quickserve-ca.crt --resolve quickserve.localhost:8443:127.0.0.1 https://quickserve.localhost:8443/health/ready
```

`--resolve` makes curl connect to 127.0.0.1 (the port-forward) while still using the real hostname for TLS and routing. To check everything at once, run `infra/k8s/gateway_check.sh`. It's the same check CI runs; see the last question.

### Q: Why Gateway API and not an Ingress?

Two reasons, one practical and one about design.

**The practical one.** The most used Ingress controller, the community **ingress-nginx**, is retired. Kubernetes announced in November 2025 that maintenance would stop in March 2026, and recommended moving to Gateway API or another controller right away [72]. After that date there are no releases, bug fixes or security patches, and the repository is archived and read-only [73]. A new project in late 2026 shouldn't start on it.

**The design one.** Ingress puts everything in one object, and anything beyond the basics goes into controller-specific annotations. Gateway API splits it by **who owns what**:

| Object | Owned by | In QuickServe |
|---|---|---|
| `GatewayClass` | the platform team: which software runs gateways | `quickserve-envoy` → Envoy Gateway |
| `Gateway` | the cluster operator: ports, TLS, which namespaces may attach | `quickserve`: port 80 (redirect only) and 443 (HTTPS) |
| `HTTPRoute` | each app team: hostnames, paths, which Service | `api`, `grafana`, `https-redirect` |

Timeouts, redirects and header changes are standard fields, not annotations. Gateway API v1.5 (2026) moved more features to the stable channel, including TLSRoute and a CORS filter [74].

**Envoy Gateway** is the implementation here. It's an Envoy project that turns these objects into a running Envoy proxy, and one of the implementations that pass the Gateway API conformance tests [75]. On AWS, the AWS Load Balancer Controller can play the same role with the same YAML.

### Q: What are the add-ons, and why aren't they in `infra/k8s/base`?

`infra/k8s/addons.sh` installs two cluster-wide components, at pinned versions, from their official release files:

- **Envoy Gateway v1.10.0**, which also brings the Gateway API CRDs (v1.6.1);
- **cert-manager v1.21.3**.

`deploy.sh` runs it first, and it skips what's already installed at that version. They're kept apart from QuickServe's own manifests because they belong to the **cluster**, not the app. Many apps would share one cert-manager, and its CRDs must exist before any `Certificate` can be created. Pinned versions mean an upgrade is a change you test, not a surprise on the next deploy.

### Q: How does HTTPS work here?

cert-manager builds a three-step chain, the same shape as the real internet ([`tls.yaml`](infra/k8s/gateway/tls.yaml); cert-manager's CA issuer and Gateway docs [77]):

1. **A self-signing issuer.** It's used once, to create...
2. **...the "QuickServe Local CA"**: a 10-year certificate authority, stored in the Secret `quickserve-ca`.
3. **The site certificate**, `quickserve-tls`, signed by that CA, for `quickserve.localhost` and `grafana.quickserve.localhost`. It lasts 90 days, like Let's Encrypt's. cert-manager renews it 30 days before it expires, with a new key each time, and Envoy picks up the new one without a restart.

Why a CA instead of one self-signed site certificate? Because you can trust the CA **once**, and every future certificate it signs is trusted too. On a public site, step 2 would instead be an **ACME issuer** (Let's Encrypt): cert-manager proves you own the domain and gets a certificate every browser already trusts. Nothing else changes.

**TLS ends at Envoy** ("TLS termination"). From Envoy to the pods, inside the cluster, traffic is plain HTTP. Encrypting that hop too (mTLS) is what service meshes do; it's the next step in a zero-trust setup.

Expired certificates are a classic cause of outages, even at big companies. Automatic renewal is the fix; the next step would be an alert on certificate age.

### Q: What does the gateway do besides HTTPS?

All of these are configured in [`routes.yaml`](infra/k8s/gateway/routes.yaml) and [`policies.yaml`](infra/k8s/gateway/policies.yaml):

| Feature | How | Why |
|---|---|---|
| HTTP → HTTPS | `RequestRedirect` filter, 301 | Nobody ends up on an unencrypted page by typing the bare name |
| Host-based routing | `hostnames:` on each HTTPRoute | One IP, one certificate, one load balancer for many apps |
| Unknown hostnames | no route matches → Envoy's 404 | Random scanners never reach the API |
| HSTS | `Strict-Transport-Security: max-age=300` | Tells browsers "only HTTPS from now on". 5 minutes while learning; a real site uses a year once HTTPS works everywhere |
| `X-Content-Type-Options: nosniff` | response header | Stops browsers guessing file types (a classic attack trick) |
| Request timeout 15 s | `timeouts.request` | A stuck request gets a 504 instead of holding a connection forever |
| Request IDs | `ClientTrafficPolicy` `requestID: PreserveOrGenerate` | One ID in Envoy's access log and in the API's log line |
| `/metrics` unreachable | the `api` Service only has port 80 | Metrics stay private; only Prometheus, inside the cluster, reads them |

A note on the redirect through a port-forward: it keeps the non-standard port, so `http://...:8081` would send you to `https://...:8081`, which is the wrong port. That's an artifact of port-forwarding. Behind a real load balancer on ports 80 and 443 it's exactly right. Just use the HTTPS address.

### Q: Why rate-limit login at the gateway, when the API already does?

They're two different layers:

- **The API** (Phase 4, Redis) counts **failed** logins **per email and per IP**. It protects *accounts*.
- **The gateway** caps login requests **in total**: 60 a minute per Envoy instance, whoever sends them. It protects *CPU and money*. Every login the API sees costs about 0.1 s of Argon2 hashing; a flood stopped by Envoy costs almost nothing.

It's Envoy Gateway's **local** rate limit: each Envoy pod counts on its own, so 2 Envoy pods allow 120 a minute in total. A local limit can't count *per client IP*. That needs the **global** rate limit, which keeps shared counters in Redis [76]. The CI check sends 75 requests to the login path and expects Envoy to answer some of them with 429 `local_rate_limited`, before they reach the API.

### Q: The gateway broke the API's per-IP login limit at first. What happened?

This is the most useful lesson of the phase, and the tests caught it before it was merged.

Behind a proxy, **every request reaches the API from Envoy's pod**. If the API reads the TCP address (`request.client.host`), every customer has Envoy's IP. The "20 failed logins per IP" rule would then lock **everyone** out of login after 20 failures from **anyone**. That makes it a denial of service, built into the security feature.

The standard answer is the `X-Forwarded-For` header. Envoy appends the address it received the request from:

```
X-Forwarded-For: <whatever the client sent>, <the address Envoy saw>
```

**The first attempt** was uvicorn's `--forwarded-allow-ips`, set to trust the pod network. uvicorn reads the header from the right and skips every *trusted* address. The CI check then sent a request from a pod with a forged `X-Forwarded-For: 6.6.6.6`, and the API logged it as coming from **6.6.6.6**. The client was itself inside the trusted range, so uvicorn skipped it too and believed the forged entry. (Setting it to `"*"`, a common tutorial answer, is worse: then uvicorn takes the left-most entry, which the client always controls.)

**The fix** ([`app/core/client_ip.py`](app/core/client_ip.py)): trust **exactly one hop**. Use only the **last** entry, the one Envoy itself wrote, and only when the request comes from the proxy's network (`TRUSTED_PROXY_CIDRS`). Anything to its left is ignored. That's the same model as Envoy's own `xff_num_trusted_hops`. Unit tests cover:

- a forged header;
- a client inside the trusted network;
- a request that bypasses the proxy;
- garbage in the header;
- the uvicorn behaviour that caused the bug.

The CI check repeats the attack end to end from a test pod inside the cluster and expects that pod's real IP in the API's log. The request log line now has `client_ip` for exactly this kind of investigation.

The remaining gap was that any pod in the cluster could call the API directly with a fake header, because the whole pod network is trusted. Phase 10 closes it: a **NetworkPolicy** lets only the gateway's Envoy pods (plus Prometheus and the smoke tests) reach the API. See [Network policies](#network-policies-phase-10).

### Q: What does the gateway cost?

On minikube, memory. The Envoy Gateway controller asks for 256 Mi; the Envoy proxy asks for 128 Mi, set in the `EnvoyProxy` object; cert-manager adds three small pods. All of QuickServe still fits in minikube's 3 GB.

On a cloud, the big item is the **load balancer**. Here the Envoy Service is `ClusterIP` and reached with `port-forward`. On AWS it would be `type: LoadBalancer`, which creates a real load balancer with an hourly charge plus a charge for traffic. That's why **one Gateway for every hostname** matters: one load balancer for the API, Grafana and any future app, not one each. The same logic makes the edge rate limit FinOps as well as security: requests stopped at Envoy never reach the pods that the autoscaler would otherwise add.

### Q: What does CI check for the gateway?

After all the earlier steps, `infra/k8s/gateway_check.sh` runs against the kind cluster from outside, the way a phone would connect:

1. HTTPS works with a certificate signed by QuickServe's CA (curl verifies it), reaches the API, and returns the HSTS and request ID headers.
2. Plain HTTP gets a 301 to HTTPS.
3. The Grafana hostname reaches Grafana through the same Gateway.
4. An unknown hostname gets 404 from Envoy.
5. A request from a test pod with a forged `X-Forwarded-For: 6.6.6.6` is logged by the API with that pod's real IP, under the same request ID.
6. Repeated requests to the login path are partly stopped with Envoy's 429.

Manifests for the new CRD types can't be checked by `kubeconform` (it has no schema for them), so they're skipped there. The API server then validates them for real when `deploy.sh` applies them on kind.

### Network policies (Phase 10)

Until now, every pod could open a connection to every other pod in the cluster. If any single pod were broken into (a dependency with a security hole, a leaked token), the attacker could connect straight to PostgreSQL, Redis or Prometheus from it. Phase 10 adds **network policies**: the default becomes "no connections at all", and each connection the system really needs is written down and allowed one by one.

```mermaid
flowchart LR
    envoy["Envoy (gateway)"] -->|8000| api
    envoy -->|3000| grafana
    api -->|5432| pg[(PostgreSQL)]
    api -->|6379| redis[(Redis)]
    worker -->|5432| pg
    notifier -->|5432| pg
    migrate["migrate Job"] -->|5432| pg
    prom["Prometheus"] -->|"9100 / 9101 / 9102"| api & worker & notifier
    prom -->|9093| am["Alertmanager"]
    grafana -->|9090| prom
    am -->|1025| mailpit["Mailpit"]
    smoke["smoke-test pods"] -.->|"tests only"| api & prom & grafana & am & mailpit
```

Every arrow is an allowed connection. Anything that isn't an arrow is blocked: the worker calling the API, the API reaching the internet, or any other namespace reaching the database.

### Q: How do I run this on my Mac?

minikube's default network plugin **ignores** network policies. The minikube docs say a vanilla install supports none of them, because its default plugin, Kindnet, doesn't by design; a plugin like Calico is needed [78]. Kubernetes stores the policies either way, so without Calico everything *looks* fine and nothing is enforced. That's why there's a check script (below).

The network plugin can only be chosen when the cluster is created, so minikube must be recreated once. This deletes the cluster's data (test orders and so on); the seed script puts the demo data back. Run each line on its own:

```bash
minikube delete
minikube start --cpus 4 --memory 3072 --cni=calico
minikube addons enable metrics-server
infra/k8s/deploy.sh
kubectl -n quickserve exec deploy/api -- python -m scripts.seed
infra/k8s/netpol_check.sh
```

The last command should end with **"Network policies enforced."**

### Q: Why does `deploy.sh` deploy a "lite" setup on the Mac?

Because the first try at the steps above ran out of memory, and it's a lesson worth keeping.

**What happened.** On an 8 GB Mac, Docker Desktop has about 3.8 GB, and minikube was given 3 GB of it. By Phase 10, the cluster had to hold:
- Kubernetes itself;
- Calico, which is heavier than minikube's default plugin;
- Envoy Gateway and cert-manager;
- PostgreSQL, Redis, the API, worker and notifier;
- Prometheus, Grafana, Alertmanager and Mailpit.

That was too much, and it failed in a chain:
1. Free memory dropped to 82 MB and the machine started swapping.
2. Everything slowed down, so health checks timed out.
3. Kubernetes restarted the "dead" pods (calico-node again and again, even the API server). Restarts cost more CPU, and the load average reached 88 on 4 cores.
4. QuickKart's API container, running in the same Docker Desktop, crashed. That was the moment to stop minikube.

None of it was a bug in the policies. It was **capacity planning**, on a laptop instead of a cloud bill.

**What lite changes** ([`infra/k8s/components/lite`](infra/k8s/components/lite/kustomization.yaml)): it leaves out the monitoring stack, and it runs one API pod (the autoscaler can still add a second). Everything else is the same: the gateway with HTTPS, the network policies, the database, Redis and all three app processes. The changes are written once as a Kustomize **component** and used by two overlays: `overlays/lite` (your Mac) and `overlays/ci-lite` (CI). That way, CI tests exactly what your Mac runs.

| Command | Setup | Has |
|---|---|---|
| `infra/k8s/deploy.sh` | lite (default) | everything except monitoring; 1 API pod |
| `infra/k8s/deploy.sh infra/k8s/overlays/local` | full | plus Prometheus, Grafana, Alertmanager, Mailpit; 2 API pods. Stop QuickKart first. |

Switching from full to lite **removes** the monitoring pods. `kubectl apply` only adds and updates; it never deletes what an overlay no longer lists, so `deploy.sh` deletes those pods explicitly. Otherwise they'd keep running and keep using the memory lite is meant to save.

CI now runs the whole Kubernetes test **twice in parallel**, once per setup. Each run also records how much memory the entire cluster uses, so the trade-off is measured, not guessed. The first measurement, on kind after all the tests (November 2026):

| Setup | Whole cluster's memory | QuickServe pods |
|---|---|---|
| full (`ci`) | **1.90 GiB** | 11 |
| lite (`ci-lite`) | **1.44 GiB** | 6 |

Lite saves about 0.46 GiB, a quarter of the total. These are numbers from a quiet, freshly tested cluster. On your Mac, add minikube's own overhead and Calico (kind's network plugin is lighter), plus the spikes while everything starts at once. That's how the full setup went past 3 GB. Lite leaves real headroom for that, and for QuickKart.

### Q: How is it written?

In [`infra/k8s/network-policies/`](infra/k8s/network-policies/):

1. **`baseline.yaml`**:
   - `default-deny-all` selects every pod (`podSelector: {}`) and blocks all traffic in **and** out.
   - `allow-dns` then lets every pod ask the cluster DNS (kube-dns, port 53) for addresses. Without it, names like `postgres` can't be looked up, and everything breaks at once. It's the classic first mistake with deny-all.
2. **`apps.yaml`** and **`monitoring.yaml`**: one policy per component, each saying who may connect to it and where it may connect.
3. **`tests.yaml`**: what the smoke-test pods may reach.

Policies only ever **add** permissions. There's no "deny" rule and no order: a connection is allowed if any policy allows it. For a connection between two pods, **both** sides must allow it: the sender's egress and the receiver's ingress. That's why the API's egress lists PostgreSQL, *and* PostgreSQL's ingress lists the API.

| Pod | Who may connect to it | Where it may connect |
|---|---|---|
| PostgreSQL | api, worker, notifier, migrate (5432) | nowhere |
| Redis | api (6379) | nowhere |
| API | the gateway's Envoy pods (8000), Prometheus (9100), smoke tests | PostgreSQL, Redis. **No internet.** |
| Worker | Prometheus (9101) | PostgreSQL |
| Notifier | Prometheus (9102) | PostgreSQL |
| Prometheus | Grafana, smoke tests (9090) | the three metrics ports, Alertmanager, the Kubernetes API |
| Grafana | the gateway (3000), smoke tests | Prometheus |
| Alertmanager | Prometheus, smoke tests (9093) | Mailpit (SMTP) |
| Mailpit | Alertmanager (1025), smoke tests (8025) | nowhere |

Two things are allowed whatever the policies say. Kubernetes allows traffic from a pod's own node, which is why the kubelet's health checks still work [79]. It also allows the replies to an allowed connection.

### Q: Why can't the API reach the internet? It's not doing anything there.

That's exactly why. A policy should describe what the code **does**, not what it might do one day. If an attacker gets code running in the API pod, the first thing they want is to send data out ("exfiltration") or download tools. With no egress except PostgreSQL and Redis, both fail. When QuickServe calls a real payment gateway or SMS provider, that one address gets added to the notifier's or API's policy, as a reviewed change in Git.

The same thinking is why the **worker can't call the API**, and the notifier can't reach Redis. They never need to.

### Q: Why do the smoke tests run in their own pods now?

Until Phase 10, `smoke_test.py` ran inside the **worker** pod (`kubectl exec deploy/worker`). Under the new policies, that would mean letting the worker reach the API, Grafana, Alertmanager and Mailpit. That's a lot of access for a background job that only needs the database, granted just so tests can run.

So [`infra/k8s/smoke.sh`](infra/k8s/smoke.sh) now starts a short-lived pod with its own label, `app.kubernetes.io/name: smoke-test`, runs the script in it, and deletes it. The policies give that label exactly what the tests need. This applies beyond tests: **every client gets its own identity**, so you can give it access without giving the same access to something else.

### Q: How does the gateway get through, from another namespace?

The API's ingress rule combines a `namespaceSelector` (the namespace `envoy-gateway-system`) and a `podSelector` (Envoy pods labelled `owning-gateway-name: quickserve`) **in one entry**. That means "those pods in that namespace".

Written as two separate list entries, it would mean "**any** pod in that namespace, **or** pods with that label in our namespace", which is much wider. This one-dash difference is one of the easiest NetworkPolicy mistakes to make. It also closes the gap left in Phase 9: only our gateway can reach the API, so a random pod can no longer send it a fake `X-Forwarded-For`.

### Q: How do we know the policies really work?

[`infra/k8s/netpol_check.sh`](infra/k8s/netpol_check.sh) makes real connections from real pods, and CI runs it on every pull request:

- **Inside the namespace**, each app's allowed connections must work and its forbidden ones must fail:
  - api → PostgreSQL and Redis: open;
  - api → Prometheus and the internet: blocked;
  - worker → API and Redis: blocked;
  - a smoke-test pod → PostgreSQL: blocked.
- **From another namespace**, a temporary namespace with no policies of its own: PostgreSQL, Redis, the API and Prometheus must all be blocked.
- **Two positive controls.** The same pod must reach the gateway (the front door is open to everyone) and the internet. That proves it really can make connections, so "blocked" above means the policy did it. Without those controls, a test that failed every connection for some other reason would look like perfect security.

Kubernetes accepts a NetworkPolicy even when the network plugin ignores it. A check like this is the only way to know.

On kind, CI's cluster, the built-in plugin enforces policies: kind's kindnet implements them with the kube-network-policies project [80]. On a Mac, that's what `--cni=calico` is for.

### Q: What would a bigger platform add?

- **Cluster-wide rules.** Admin network policies are rules a platform team sets for all namespaces, which app teams can't override. Example: "nothing may reach the cloud metadata address".
- **Policies by name instead of IP.** Calico or Cilium can allow egress to `api.razorpay.com` instead of an IP address, which changes.
- **mTLS between pods.** With a service mesh, the database checks *which service* is connecting, not just which IP.

Network policies are the first, cheapest layer: they come with Kubernetes, cost nothing to run, and are reviewed in Git like code.

### Pricing like Zomato and Swiggy (Phase 11)

Until Phase 10 the bill had a flat Rs 30 delivery fee and a flat platform fee. Real food apps price every order from its circumstances: how far it travels, how big it is, what time it is, whether it's raining, and which coupon you typed. Phase 11 adds all of that, with the same rule everywhere: **the customer sees every line before paying, and pays exactly that.**

A dinner order, 5.2 km away, at 23:30, in the rain, with a coupon:

```
Item total                400.00
Coupon WELCOME50         -100.00   50% off, capped at Rs 100
Packaging (restaurant)     20.00
Delivery fee               45.00   5.2 km (the 4-6 km slab)
Surge fee                  40.00   late night 15 + rain 25
Platform fee               14.90
GST on food (5%)           16.00   on 400 - 100 + 20
GST on fees (18%)          17.98   on 45 + 40 + 14.90
---------------------------------
Grand total               453.88
```

That exact bill is a test (`test_a_rainy_late_night_order_line_by_line`), and so is the rule that the lines add up to the total.

### Q: Where does each fee come from?

| Fee | QuickServe rule (defaults in `Settings`) | What real platforms do |
|---|---|---|
| Platform fee | Rs 14.90 on every order, before GST | Zomato raised it to Rs 14.90 before GST in March 2026, and Swiggy to Rs 17.58 including GST [10][11]. Both started at Rs 2 in 2023 [81]. |
| Delivery fee | By road distance, in slabs: up to 2 km Rs 20, 4 km Rs 30, 6 km Rs 45, 8 km Rs 60. Nothing beyond 8 km. | The fee varies with distance and demand. Zomato has charged a long-distance fee for deliveries beyond 4 km [83]. |
| Free delivery | Food worth Rs 299 or more, **and** within 4 km | Memberships offer free delivery within a distance limit. Swiggy and Zomato cut that limit from 10 km to 7 km [84]. |
| Small order fee | Rs 15 when the food is under Rs 149 | "Small cart" fees are common: Blinkit charges Rs 20 under Rs 99 [81]. |
| Surge: peak | Rs 10, 19:00–22:00 India time | Surge pricing at peak hours [81] |
| Surge: late night | Rs 15, 23:00–05:00 | Late-night surcharges [81] |
| Surge: rain | Rs 25 while "rain mode" is on | Rain surcharges, now charged even to Zomato Gold and Swiggy One members [82] |
| Coupon | Percent (with a cap) or flat, on the food only | Every app has these |
| GST | 5% on food and packaging, 18% on the platform's fees | See the GST question below |

All of these are settings, not constants in code, so a city or a season can have different numbers without a code change. The defaults are illustrative, not what any platform charges today.

### Q: How do you know how far away the customer is?

The order now carries a map pin, `delivery_location: {lat, lng}`. In a real app it comes from the phone's GPS or a map picker; the typed address is for the rider. Restaurants have a location and a delivery radius (7 km by default).

The distance is calculated in two steps ([`geo.py`](app/modules/pricing/geo.py)):

1. **The straight line** between the two points on the Earth's surface, with the haversine formula.
2. **Times 1.25**, to estimate the road distance. Roads aren't straight lines. Transport research calls the ratio between road and straight-line distance the *circuity factor* or *detour index*, and published per-country factors go back to Ballou, Rahardja and Sakai (2002) [85]. A 2026 measurement of 116 city pairs found roads 23.5% longer than the straight line at the median, and recommends multiplying by 1.2 when the straight-line distance is all you have [85]. Inside a city, with one-way streets and few direct roads, 1.25 is a reasonable middle.

A real platform asks a routing service (Google Maps, OSRM) for the true road distance and travel time. That costs money and adds a network call to every price check. Estimating like this is the usual first version, and it's free and instant. Swapping in a real routing call later would change only `geo.py`.

If the address is beyond the restaurant's radius, or beyond 8 km, the answer is `422`: "Pal Dhaba delivers up to 7.0 km; this address is 11.0 km away". This is checked **before** any stock is reserved, so a far-away order never locks dishes.

### Q: Is the surge real? Real apps raise prices when there are too many orders and too few riders.

Partly, and here's the honest version. Real surge pricing is **dynamic**: it compares demand (orders waiting) with supply (free riders nearby), zone by zone, every few minutes. QuickServe doesn't model riders' locations yet, so it can't do that. What it does instead is what platforms *also* do, alongside the dynamic part:

- **Peak and late-night fees come from the clock.** The windows are in India time (`Asia/Kolkata`), because the database works in UTC. 14:00 UTC is 19:30 in India, which is peak hour (a test checks this). A window can cross midnight (`23:00-05:00`).
- **Rain is a switch an admin flips:** `PUT /api/v1/admin/surge/rain` with `{"minutes": 120}`. It **switches itself off** after the given minutes. A forgotten switch can't overcharge everyone for a week. `GET /api/v1/pricing` shows anyone which surge fees apply right now, so an app can show a banner: "It's raining: Rs 25 extra to support delivery partners."

### Q: Why are fee amounts settings, but "it's raining" a database row?

Because they change at different speeds and for different reasons:

- **Fee amounts** are business decisions. They're reviewed, changed on purpose and kept in Git's history, so deploying a new value is fine.
- **Rain** is a fact about the world that changes within minutes, and an operations person must be able to change it right away without a deploy. So it's a row in `surge_flags`, with who set it and until when.

A real platform has one such flag per city zone. QuickServe has one for everything.

### Q: How do coupons work?

A coupon ([`coupons/model.py`](app/modules/coupons/model.py)) has:
- **A value:** a percent with an optional cap ("50% off up to Rs 100"), or a flat amount ("Rs 75 off").
- **A minimum order value.** If you're short, the message says by how much: "add Rs 9.00 more".
- **Optionally, one restaurant.** Otherwise it works everywhere.
- **First order only**, or not.
- **Limits:** a total limit ("the first 1,000 uses") and a per-customer limit.
- **A validity window**, and an on/off switch.
- **Who pays for it:**
  - **Admins** create *platform-funded* coupons: the platform's marketing cost.
  - **Restaurant owners** create coupons for *their own* restaurant only, funded from their share. An owner can't create a coupon for someone else's restaurant, or a platform-wide one.

The discount applies to the **food only**, and never exceeds it. Fees are decided on the cart value **before** the discount: a coupon shouldn't turn a free-delivery order into a paid one (a test checks this).

`seed.py` adds two demo coupons: **WELCOME50** (first order, 50% up to Rs 100, minimum Rs 149) and **FLAT75** (Rs 75 off above Rs 399, twice per customer, the first 1,000 uses).

### Q: Twenty customers try to use the last five uses of a coupon at the same moment. Who gets them?

Exactly five of them. Getting this right needs three layers, and the tests show each one is needed:

1. **An atomic update.** Using a coupon is one statement: `UPDATE coupons SET times_used = times_used + 1 WHERE id = ... AND times_used < max_uses_total`. It's the same idea as the stock in [section 4](#q-forty-customers-want-the-last-ten-biryanis-at-the-same-moment-what-stops-overselling). Checking in Python first and then saving lets two requests both see "1 left".
2. **Re-checking under the lock.** That `UPDATE` locks the coupon row until the order commits. Any other order using the same coupon waits at its own `UPDATE`. So the check *after* it ("has this customer already used it?", "is this really their first order?") can't be raced. A customer double-tapping "Pay" 8 times gets the coupon once. The mutation test, with this re-check removed, gave them **8 discounts**.
3. **A database constraint**, as the last line of defence: `CHECK (times_used <= max_uses_total)`. With the limit removed from the `UPDATE` on purpose, PostgreSQL itself refused to record a sixth use.

The tests run this with real threads: 20 customers racing for 5 uses get exactly 5, and the redemption table has exactly 5 rows.

The trade-off: the row lock means orders using **the same** coupon commit one after another. That's fine for QuickServe. For a coupon that a whole country uses during an IPL final, it becomes a hot spot. Big platforms split the counter across several rows, or hand out unique single-use codes instead.

### Q: What happens to the coupon if the order is cancelled?

It's given back. Each use is a row in `coupon_redemptions`, with status `APPLIED`. When an order ends badly (cancelled, rejected by the restaurant, or never paid), that row becomes `RELEASED` in the **same transaction** as the status change, and the coupon's counter goes down by one. The customer can use the coupon again.

For the same reason, a cancelled order doesn't count as your "first order" for a first-order coupon. Both behaviours are tested.

### Q: How does GST work when there's a discount?

A discount given at the time of sale and shown on the bill is **not part of the taxable value** (CGST Act, Section 15(3)(a)) [87]. So the 5% on food is calculated on the food *after* the discount: 5% of (400 − 100 + 20) = 16.00 in the example above.

The 18% on fees is on the delivery, small order, surge and platform fees. Since **22 September 2025**, the platform itself pays GST at 18% on local delivery services supplied through it (Notification 17/2025-Central Tax (Rate)) [86]. A further notification widened that from "local delivery" to "delivery services" from 1 November 2026 [14].

This is a simplification. How a *platform-funded* discount on a restaurant's food should be taxed is more complicated in real life. None of this is tax advice.

### Q: What's a quote, and what's `expected_total` for?

`POST /api/v1/orders/quote` takes the same body as placing an order and returns the bill line by line, **without reserving anything**. It runs the same code as the real order, so the two can only differ if something changed in between. Things that can change:
- surge started;
- it started raining;
- the coupon's last use was taken;
- a price changed.

When the customer taps "Pay", the app sends the quoted `grand_total` back as `expected_total`. If the price has changed, the order is refused with **`409 Conflict`** and the new total (`new_grand_total`), and nothing is reserved. The app shows the new bill and asks again. The alternative, charging an amount the customer never saw, is how apps lose trust and sometimes get reported to consumer forums.

One more difference: a coupon that doesn't apply **doesn't fail the quote**. The quote comes back without the discount, plus `coupon_error`: "WELCOME50 needs an order of Rs 149; add Rs 9.00 more". The checkout page can show that next to the coupon box. Placing an *order* with a coupon that doesn't apply does fail (`422`), because the customer asked for a price they can't have.

### Q: How do I try it?

Your database already has the demo data from earlier phases. Run the seed again: it adds the restaurants' locations and the demo coupons, and skips everything that exists.

```bash
kubectl -n quickserve exec deploy/api -- python -m scripts.seed      # Kubernetes
docker compose --profile app run --rm migrate python -m scripts.seed # or Docker Compose
```

Then in Swagger (`/docs`), log in as `customer@quickserve.dev` and send `POST /api/v1/orders/quote`:

```json
{
  "restaurant_id": "<Pal Dhaba's id from GET /api/v1/restaurants>",
  "delivery_address": "House 12, Sector 22, Chandigarh",
  "delivery_location": {"lat": 30.7333, "lng": 76.7794},
  "items": [{"menu_item_id": "<Dal Makhani's id>", "quantity": 1}],
  "coupon_code": "WELCOME50"
}
```

Things to try:
- **Small order:** change the quantity to see the small order fee appear or go away.
- **Distance:** move `delivery_location` further away (`{"lat": 30.70, "lng": 76.70}` is out of range).
- **Rain:** log in as the admin and turn on `PUT /api/v1/admin/surge/rain`, then quote again.
- **Price change:** place the order with the quote's `grand_total` as `expected_total`, then try an old total to see the `409`.

Restaurants created before Phase 11 (by you, not the seed) can set their location with `PUT /api/v1/restaurants/{id}/location`.

### Q: What's tested?

**57 new tests**, 204 in total:
- **`test_pricing.py`, 33 pure tests:**
  - every slab boundary (2.0 km is Rs 20, 2.1 km is Rs 30);
  - free delivery at Rs 299 vs Rs 298.99, and at 4.0 vs 4.1 km;
  - the small order fee at Rs 148.99 vs Rs 149;
  - surge windows across midnight, and India time vs UTC;
  - coupon caps and minimums;
  - GST after discount;
  - full bills that must add up line by line.
- **`test_checkout.py`, 24 tests on real PostgreSQL:**
  - every coupon rule;
  - the two race tests;
  - release on cancel and reject;
  - the quote matching the order;
  - `409` on a price change with nothing reserved;
  - rain on and off;
  - delivery areas;
  - who may create coupons;
  - the HTTP endpoints.
- **The migration** was tested up, down and up again, and on a copy of a database seeded before Phase 11.
- **The in-cluster smoke test** now checks out like an app does: quote, check that the lines add up, then order with `expected_total`.

The tests switch the surge hours off by default (`PEAK_HOURS=[]` in `conftest.py`), because otherwise a test run at 8 pm would add a peak fee and fail. Tests about surge pass their own settings. A test suite whose result depends on the time of day is a classic source of flaky CI.

### Discovery: near me, search and ratings (Phase 12)

Phase 11 priced an order once the customer had chosen a restaurant. Phase 12 is the step before that: **finding** one. That's the first screen of every food app, and it's mostly a database problem:

- `GET /api/v1/restaurants/near` lists the open restaurants that deliver to where you are, with distance, delivery time, delivery fee and rating. You can sort by distance, rating or delivery time, and filter by cuisine or minimum rating.
- `GET /api/v1/search?q=...` finds dishes and restaurants, but only from places that deliver to you. It also handles typos.
- `POST /api/v1/orders/{id}/review` lets a customer rate a **delivered** order once. `GET /api/v1/restaurants/{id}/reviews` shows the star breakdown and the newest reviews.

What the seed data shows from Sector 22, Chandigarh, sorted by rating:

```
Pal Dhaba       3.4 km  40-45 min  4.6 (10 reviews)  delivery Rs 30
Dosa Junction   2.8 km  25-30 min  New (1 review)    delivery Rs 30
Sindhi Sweets   1.0 km  15-20 min  4.0 (4 reviews)   delivery Rs 20
```

Dosa Junction's only review is 5 stars, so its plain average is 5.0. It still ranks below Pal Dhaba's 4.6, and the reason is a classic piece of statistics, explained below.

### Q: How does "restaurants near me" find restaurants without measuring the distance to every one?

It works in two steps. Cheap SQL with an index first, then exact maths on the few rows that are left:

```mermaid
flowchart LR
    A["Customer at (lat, lng)"] --> B["1. SQL + B-tree index<br/>restaurants inside a rectangle<br/>around the customer"]
    B --> C["2. Python<br/>exact road distance (geo.road_km)<br/>within the restaurant's radius<br/>and the platform's 8 km?"]
    C --> D["sort, filter, page<br/>add ETA, fee, rating"]
```

**Why not just compute the distance in SQL?** `WHERE distance(restaurant, customer) < 6 km` is a formula over each row's columns. An ordinary index is sorted by the column, not by "distance from wherever this customer happens to be", so PostgreSQL has to evaluate the formula on every row in the table. A rectangle is different: `latitude BETWEEN a AND b AND longitude BETWEEN c AND d` is a pair of ranges, and a B-tree index answers ranges directly.

The rectangle has to contain the whole delivery circle. Its height is the radius as an angle (radius ÷ Earth's radius). Its width is larger, because lines of longitude get closer together away from the equator: at Chandigarh's latitude (30.7°N) a degree of longitude is only about 96 km, compared with 111 km for a degree of latitude. `geo.bounding_box` uses Jan Philip Matuschek's formulas, including the cases near a pole and across the 180° meridian [88]. The rectangle is sized for the furthest anyone may deliver (8 km by road, which is 6.4 km in a straight line). So it can include a few restaurants too many, never too few.

**Measured.** I loaded 100,000 restaurants spread across India plus 300 around Chandigarh, and ran both versions:

| Query | Plan | Time |
|---|---|---|
| Rectangle (`BETWEEN`) | Index Scan using `ix_restaurants_location` | **0.44 ms** (283 rows in the rectangle) |
| Distance formula in `WHERE` | Seq Scan, 100,078 rows read and thrown away | **136 ms** |

That's about 300 times faster. 283 restaurants were inside the rectangle and 226 were inside the circle. That ratio is close to π/4, the share of a square that a circle inside it covers, so the rectangle wastes little.

**Honest limits of a B-tree on (latitude, longitude).** The index sorts by latitude first, so it jumps straight to the latitude band. Inside that band it still checks the longitude of every entry, which is a whole strip of the country at that latitude. That's fine for a city or a few hundred thousand rows. Real geo systems use indexes built for two dimensions: PostGIS with a GiST index, or a grid of cells (geohash, Uber's H3) where "near me" means "these 7 cells". PostGIS isn't in the `postgres:16-alpine` image we run in Docker, Kubernetes and CI. `earthdistance`, the built-in alternative, isn't a "trusted" extension, so it would need superuser rights. The rectangle needs neither, and it shows the idea those tools are built on.

### Q: Why does the list use the same distance function as checkout?

If the list said "delivers to you" and checkout then said "too far", the customer would have no reason to trust either. `nearby()` and Phase 11's `conditions_for()` both call `geo.road_km` with the same detour factor and the same rounding to 0.1 km, and both apply the restaurant's radius and the 8 km platform limit. A test (`test_the_list_and_checkout_never_disagree`) quotes an order from every listed restaurant and checks the distances match exactly. It also checks that a restaurant 8.06 km away is missing from the list **and** refused at checkout.

### Q: Where does "25-30 min" come from?

From the way Swiggy's engineering blog breaks down delivery time [89]:

```
Delivery time = max(assignment delay + first mile, prep time) + last mile
```

A rider is found and rides to the restaurant **while** the kitchen cooks, so only the slower of the two counts. QuickServe uses averages for each part, all of them settings:

| Part | QuickServe | Real platforms |
|---|---|---|
| Find a rider and ride to the restaurant | `rider_first_mile_minutes` = 8 | Predicted from live rider supply and demand in the zone |
| Prep time | `avg_prep_minutes` per restaurant (owners set it with `PUT /restaurants/{id}/profile`) | Predicted per order from the items, the kitchen's current load and the time of day |
| Last mile | road km at `rider_speed_kmph` = 20 | Predicted from historical and live traffic, plus the time to get from the gate to the door [89] |
| Handing over | `handoff_minutes` = 4 | Part of the last-mile model |

Example: Pal Dhaba takes 25 minutes to cook, and 3.4 km at 20 km/h is 11 minutes. So 25 + 11 + 4 = 40, shown as "40-45 min". The app shows a range because a promise to the minute would be broken most of the time.

### Q: Why not sort by the average rating?

Because then one lucky 5-star review beats hundreds of good ones. Evan Miller's well-known article calls sorting by the plain average a mistake for exactly this reason [90]. The fix used here is a **Bayesian average**: pretend every restaurant starts with C extra reviews at the platform's average m [91][92]:

```
score = (C × m + sum of its ratings) / (C + number of its ratings)
```

With few reviews, the score stays close to m. As real reviews pile up they outweigh the C imaginary ones, and the score moves towards the restaurant's own average. IMDb has published the same formula for its Top 250 films, where C is the minimum number of votes to be listed and m is the mean vote across all films [92]. QuickServe uses C = 10 (`rating_prior_weight`), and m is the average of every rating on the platform.

The demo numbers: m = 78 stars / 18 reviews on the platform = 4.33, so C × m = 43.3.

| Restaurant | Reviews | Plain average | Bayesian score |
|---|---|---|---|
| Pal Dhaba | 10, totalling 46 | 4.6 | (43.3 + 46) / 20 = **4.47** |
| Dosa Junction | 1, totalling 5 | 5.0 | (43.3 + 5) / 11 = **4.39** |
| Sindhi Sweets | 4, totalling 16 | 4.0 | (43.3 + 16) / 14 = **4.24** |

What customers **see** is still the plain average, because that's what people expect to read. Below 3 reviews (`rating_min_count`) they see "New" instead, like on Zomato and Swiggy. The `min_rating=4.0` filter uses the shown average, so "4.0+" never shows a 3.9. Miller's later article goes a step further and ranks by the lower bound of a confidence interval [93]. That penalises uncertainty more strictly, at the cost of more maths.

### Q: Why store `rating_count` and `rating_sum` on the restaurant, instead of `AVG(rating)` over the reviews?

Because the list is read far more often than reviews are written. A page of 20 restaurants would otherwise run an `AVG()` over each one's reviews on every app open. Storing two running totals makes reading free. The price is that **the totals must never drift from the reviews**, and there are four guards:

1. **One atomic statement.** The counters change with `UPDATE restaurants SET rating_count = rating_count + 1, rating_sum = rating_sum + 4`. PostgreSQL does the arithmetic on the latest committed value, under the row lock.
2. **Same transaction.** The review row and the counter change commit together or not at all. The `INSERT` runs first (`flush()`), so a duplicate review fails before the counters move.
3. **A CHECK constraint.** `rating_sum BETWEEN rating_count AND 5 * rating_count`, because every review is 1 to 5 stars. A bug that double-counts or loses a review usually breaks it, and then fails loudly.
4. **A recount job.** `POST /admin/jobs/recompute-ratings` recounts every restaurant from its reviews and reports how many were wrong. It should always report 0. Anything else means a bug, or someone edited the table by hand.

**The race, measured.** The tempting ORM version reads the number into Python, adds one and writes it back:

```python
r = db.get(Restaurant, order.restaurant_id)        # SELECT
r.rating_count = r.rating_count + 1                 # Python does the maths
r.rating_sum = r.rating_sum + data.rating           # UPDATE ... SET rating_count = 7 (a constant!)
```

I swapped this into the service and ran `test_ten_reviews_at_once_are_all_counted` three times: 10 customers reviewing at the same moment. The totals counted **3, 4 and 3** of the 10 reviews. The others were lost updates: two transactions read the same old count, and both wrote "old + 1". The atomic version counts all 10, every time. It's the same lesson as Phase 2's stock counter and Phase 11's coupons, and it's why the cheat sheet says "put the arithmetic in the UPDATE".

**ORM and hand-written SQL, side by side.** Posting a review uses the ORM: `update(Restaurant).values(rating_count=Restaurant.rating_count + 1)` builds exactly the atomic SQL above. The recount job is written in SQL by hand, because it's an UPDATE driven by an aggregate over another table, which reads more clearly as SQL:

```sql
WITH truth AS (
    SELECT r.id, count(v.id) AS n, coalesce(sum(v.rating), 0) AS total
    FROM restaurants r LEFT JOIN reviews v ON v.restaurant_id = r.id
    GROUP BY r.id
)
UPDATE restaurants SET rating_count = truth.n, rating_sum = truth.total
FROM truth
WHERE restaurants.id = truth.id
  AND (restaurants.rating_count, restaurants.rating_sum) IS DISTINCT FROM (truth.n, truth.total)
RETURNING restaurants.id, restaurants.name
```

`LEFT JOIN` puts a restaurant whose reviews were all removed back to 0. `IS DISTINCT FROM` touches only rows that are wrong, and `RETURNING` reports which ones they were.

### Q: Can the recount job itself get it wrong?

Yes, without care. Under PostgreSQL's default isolation level (READ COMMITTED), the job counts the reviews it can see when its statement starts. Suppose a review commits between that count and the job's write. The job would then overwrite the new total with its older count, and lose that review.

So the job first locks the restaurant rows (`SELECT ... FOR UPDATE`), then recounts in a new statement:
- A review that **finished** before the lock is already in the count.
- A review that's **halfway done** has inserted its row but can't commit yet: its counter UPDATE waits for the job's lock. When the job commits, the review adds its +1 to the corrected total.

At Swiggy's scale you would recount in batches of restaurants, not all of them under one lock.

### Q: Who may write a review?

The same rules both apps follow: you rate an **order** you received, not a restaurant you've heard of.

| Rule | How it's enforced |
|---|---|
| Only the customer who placed the order | Service check; anyone else gets `404`, which doesn't even confirm the order exists (the BOLA rule from Phase 3) |
| Only after it was `DELIVERED` | Service check, `422` |
| Only within 7 days of delivery (`review_window_days`) | Measured from the `DELIVERED` event in the order's timeline, by the database clock |
| Once per order | `UNIQUE (order_id)` on `reviews`: two taps on "Submit" at the same moment give one `201` and one `409`. There's a test for it |
| 1 to 5 stars, comment up to 500 characters | Pydantic (`422`) **and** a CHECK constraint |
| Reviewer shown by first name only | `GET /restaurants/{id}/reviews` returns "Priya", never the email or full name |

This makes fake reviews expensive, because each one needs a paid, delivered order. It doesn't make them impossible. Real platforms add fraud models on top, for example to catch many reviews from accounts linked to the restaurant.

### Q: How does search work?

PostgreSQL has three text tools, and search uses all of them:

| Tool | Finds | Index |
|---|---|---|
| **Full-text search**: `search_vector @@ websearch_to_tsquery('english', q)` | Whole words in the name **or description**, with English stemming ("biryanis" finds "Biryani", "momo" finds "Momos"). Name words weigh more than description words when ranking | GIN on a generated `tsvector` column [94] |
| **Substring**: `name ILIKE '%naan%'` | The text anywhere in the name | GIN trigram index (`gin_trgm_ops`) [95] |
| **Similarity**: `q <% name` | Close spellings: "paner" finds "Kadhai Paneer", "biriyani" finds "Biryani" | The same trigram index [95] |

`search_vector` is a **generated column**: PostgreSQL computes it from `name` and `description` on every insert and update. It can't go stale, and no code has to remember to fill it, which is the approach PostgreSQL's documentation recommends over triggers [94].

**Why are typos a second step, not always on?** Trigram similarity means "shares enough three-letter chunks" (`word_similarity`, from 0 to 1). It catches typos, and it also catches things that merely look alike. These are the real values for some queries:

| Query | Dish | `word_similarity` |
|---|---|---|
| paner | Kadhai Paneer | 0.67 |
| biriyani | Chicken Biryani | 0.55 |
| panner | Paneer Tikka | 0.43 |
| chai | Masala Chai | 1.00 |
| chai | **Butter Chicken** | **0.40** |

A threshold low enough to catch "panner" (0.4) also says "chai" looks like "Butter Chicken". So search tries the exact tools first. Only if they find **nothing** does it repeat with similarity (threshold `search_fuzzy_threshold` = 0.4, set with `set_config(..., true)` for that one transaction). The response says which happened (`"matched": "exact" | "fuzzy" | "none"`), so the app can show "Showing results for similar dishes". That's the same idea as a search engine's "Did you mean".

Searches are also counted by outcome (`quickserve_searches_total{outcome}`). Search teams watch the share of **zero-result searches** closely, because each one is a customer who wanted something and didn't find it.

Search also:
- only returns dishes from restaurants that deliver to you;
- hides dishes that are switched off or sold out;
- escapes `%` and `_`, so searching "100%" doesn't match everything.

### Q: Do the indexes actually get used?

`EXPLAIN` shows the plan PostgreSQL picks. For the exact search, it combines both GIN indexes with a BitmapOr:

```
Bitmap Heap Scan on menu_items
  Recheck Cond: ((search_vector @@ '''paneer'''::tsquery) OR ((name)::text ~~* '%paneer%'::text))
  ->  BitmapOr
        ->  Bitmap Index Scan on ix_menu_items_search_vector
        ->  Bitmap Index Scan on ix_menu_items_name_trgm
```

On 300,000 dishes, "shahi paneer" took **13 ms** with the indexes and **83 ms** with them switched off (a parallel scan of the whole table).

Two things are worth knowing:

1. **On a tiny table PostgreSQL ignores the index, and it's right to.** Reading 20 rows is faster than walking an index. So the tests switch table scans off (`SET LOCAL enable_seqscan = off`). That proves the index **can** serve the query, without pretending the planner would choose it on demo data.
2. **The real search also says "only these nearby restaurants".** With 283 restaurants nearby, the planner preferred `ix_menu_items_restaurant_id`: it fetched those restaurants' ~850 dishes and checked the text on each, in **3.5 ms**. The GIN indexes matter when the location filter isn't selective, for example in a dense city centre with thousands of restaurants nearby. The planner chooses per query, based on table statistics, which is why `ANALYZE` matters.

### Q: What would change at Zomato or Swiggy scale?

The ideas carry over, but each piece gets its own system:
- **Geo.** A grid of cells (geohash or H3). Which restaurants serve each cell is often computed ahead of time, because it also depends on live rider supply, not just distance.
- **Search.** A dedicated engine (Elasticsearch or OpenSearch) kept in sync from the database. It handles synonyms ("curd" = "dahi"), Hindi and Hinglish spellings, autocomplete and ranking by popularity.
- **Ranking.** Machine-learning models that mix distance, rating, delivery time, price, your past orders and promotions. Sponsored listings are paid placements in this list.
- **Ratings.** Rating counts updated through events (like our outbox in Phase 8) rather than in the same transaction. That gives eventual consistency, with a reconciliation job like ours as the safety net.
- **Pagination.** Our sort runs in Python, because the sort key (distance from *this* customer) isn't a column. At scale, the listing service computes and caches the ranked list per area for a short time.

### Q: How do I try it?

After merging, deploy as usual. Then run the seed again. It adds cuisines and prep times, two more restaurants (Dosa Junction in Sector 35, and Momo Point in Mohali) and demo reviews. The reviews are made **through real orders**: place, pay, cook, deliver, review, using the same code as the API. They come from five demo reviewer accounts, so the main demo customer's first order (and WELCOME50) stays unused.

```bash
kubectl -n quickserve exec deploy/api -- python -m scripts.seed      # Kubernetes
docker compose --profile app run --rm migrate python -m scripts.seed # or Docker Compose
```

Then open these in Swagger (`/docs`) or the browser. No login is needed:

```
/api/v1/restaurants/near?lat=30.7333&lng=76.7794&sort=rating     Sector 22: three restaurants
/api/v1/restaurants/near?lat=30.7046&lng=76.7179                 Mohali: Momo Point appears, Pal Dhaba is too far
/api/v1/search?q=paner&lat=30.7333&lng=76.7794                   a typo: "matched": "fuzzy"
/api/v1/search?q=south indian&lat=30.7333&lng=76.7794            a cuisine finds Dosa Junction
/api/v1/restaurants/{id}/reviews                                 the star breakdown
```

To write a review yourself, take an order through to `DELIVERED` as in Phase 3 (customer pays; owner accepts, prepares, marks it ready; rider picks it up and delivers it). Then, as the customer, call `POST /api/v1/orders/{id}/review` with `{"rating": 5, "comment": "..."}`. Call it a second time to see the `409`.

### Q: What's tested?

**40 new tests**, 244 in total:
- **`test_discovery.py`, 28 tests:**
  - the rectangle contains 2,000 random points inside the radius, at four latitudes;
  - it's twice as wide at 60° as at the equator, and covers every longitude near a pole or the 180° meridian;
  - ETA when the kitchen is slower and when the rider is;
  - the Bayesian sort;
  - which restaurants are listed (closed, no location, beyond their radius, beyond 8 km);
  - list and checkout agree, including at the 8 km edge;
  - filters and pagination;
  - search by name, description, stemming and cuisine; four typos; "chai" not finding "Butter Chicken"; sold-out dishes hidden; `%` escaped; zero results counted;
  - `EXPLAIN` showing the location and GIN indexes can serve the queries;
  - the endpoints and owner profile updates.
- **`test_reviews.py`, 12 tests:**
  - every rule in the table above;
  - the CHECK constraint;
  - 10 simultaneous reviews all counted;
  - a double-tap counted once;
  - the recount job finding and fixing drift;
  - the star breakdown, and the endpoints.
- **The migration** was tested up, down and up again, and on a database seeded with the Phase 11 code.
- **The in-cluster smoke test** now also checks the rating sort and a typo search against the real Kubernetes database, which proves the `pg_trgm` extension and the migration work there too.

---

## 9. DevOps already in the project

### Q: Why do the tests use a real PostgreSQL instead of SQLite?

Because the features that make this app correct (row locks, `SKIP LOCKED`, partial unique indexes, `RETURNING`, CHECK constraints under concurrency, Read Committed re-checks) either don't exist in SQLite or behave differently there. A test that passes on SQLite would prove nothing about production. The test suite builds its database **by running the real Alembic migrations**, down and up, so every test run also tests the migrations.

### Q: What runs in Docker Compose?

PostgreSQL 16 and Redis 7 always, the same major versions as CI and, later, AWS. With `--profile app` [34] it also builds the app image and runs the migration job, the API and the worker ([the Docker Q&A](#docker-the-app-in-containers-phase-5)). Without the profile, you run the app on your machine with `--reload` for fast edit-and-retry. The Compose file already shows two production habits: a **healthcheck** for each service (`pg_isready`, `redis-cli ping`), so dependants wait until they're truly ready, and **resource limits**, which on a laptop protect your machine and in the cloud are what you pay for.

### Q: What does the CI pipeline do, and why each step?

`.github/workflows/ci.yml` runs on every push and pull request:

| Step | Why |
|---|---|
| Install from `requirements-dev.lock` | Exact versions of every package, including dependencies of dependencies (next question) |
| `ruff check` and `ruff format --check` | Style arguments end; obvious bugs (unused imports, shadowed names) caught before review |
| `alembic upgrade head` + `alembic check` | **Fails if someone changed a model but forgot to create a migration**, a very common production incident |
| PostgreSQL 16 and Redis 7 **service containers** | Tests run against the same database and cache as production |
| `pytest` | All 204 tests, including the concurrency, login-attack and Redis-outage tests |
| `concurrency: cancel-in-progress` | Two quick pushes cancel the older run instead of paying for both |
| `timeout-minutes: 10` | A hung job can't burn CI minutes forever |
| A second job, `docker`, in parallel | Builds the image and smoke-tests the whole stack in containers ([details](#q-what-does-the-ci-docker-job-prove-that-the-tests-dont)) |

### Q: Why both `requirements-dev.txt` and `requirements-dev.lock`?

`requirements*.txt` pins the packages we chose. But those packages have their own dependencies, which aren't pinned. This bit us while building the project: a fresh install pulled a newer `starlette` (1.10.0, where another environment had 1.7.0), and the tests started printing a deprecation warning about the HTTP test client. The `.lock` file is `pip freeze` from an environment where the whole test suite passed on Python 3.11: every package at an exact version. CI installs from the lock, and the Docker image from `requirements.lock` (the runtime-only subset, checked against it in CI), so a new release of some sub-dependency can't break a build overnight. You regenerate the lock on purpose, when you upgrade.

### Q: What's the difference between `/health` and `/health/ready`?

- **Liveness** (`/health`): is the process alive? Kubernetes **restarts** the container if this fails. It deliberately doesn't touch the database: if the DB goes down, restarting every healthy app container in a loop makes things worse.
- **Readiness** (`/health/ready`): can this instance serve traffic right now? It runs `SELECT 1`. If it fails, the load balancer **stops sending requests** to this instance, but nothing gets restarted.

Mixing the two up is a classic cause of cascading outages.

### Q: What is connection pooling, and why does it matter for cost?

Opening a PostgreSQL connection costs a network round trip, authentication and a new server process. The SQLAlchemy engine keeps a **pool** of open connections (`pool_size=5`, plus up to `max_overflow=10` under bursts) and lends one to each request. `pool_pre_ping` detects connections that the database or a firewall silently dropped.

The trap comes at deploy time. PostgreSQL allows 100 connections by default. Each app process has its own pool:

```
4 uvicorn workers x (5 + 10) connections x 3 replicas = 180 possible connections  >  100
```

Scale out under load and new requests start failing to connect. You can fix it with smaller pools, a connection pooler such as PgBouncer, or a bigger database. A bigger database **just to hold idle connections** is money spent on nothing. That's where DevOps and FinOps meet: a config line becomes a monthly bill.

### Q: Why does the code use the database's clock (`now()`) instead of Python's?

With several app servers, each machine's clock drifts a little. Deadlines like `pay_by` and `accept_by`, and timestamps like `sold_out_at`, all come from one source of truth, PostgreSQL, so comparisons between them are always consistent.

### Q: How are settings and secrets handled?

All configuration comes from environment variables or `.env`, read by `pydantic-settings` (the "config in the environment" rule of twelve-factor apps). `.env` is git-ignored; `.env.example` documents every setting. The same code (and later the same Docker image) runs locally, in CI and in the cloud, and only the environment changes. In Phase 6 secrets move to AWS Secrets Manager or SSM Parameter Store. The app already guards the most important one: it refuses to start outside local development if `JWT_SECRET_KEY` is still the published development value.

### Q: What will we monitor once this is deployed?

The standard starting point is the four golden signals: latency, traffic, errors and saturation. This design also produces **business signals** that are just as useful on a dashboard:

- auto-rejected orders per restaurant (a restaurant tablet is offline, or the kitchen is overloaded)
- sell-outs per hour and time-to-sell-out (kitchen under-prepared)
- waste units per cycle (kitchen over-prepared)
- failed payment attempts (gateway trouble)
- connection pool waits (the database is the bottleneck)

These become Prometheus metrics and Grafana panels in Phase 7.

---

## 10. FinOps: thinking in cost per order

### Q: What is FinOps, in one paragraph?

Cloud costs are variable and controlled by engineers' choices (instance sizes, replicas, log volume, idle environments). FinOps is the practice of making those costs visible, owned and optimised. The FinOps Foundation's framework treats **unit economics** as a core capability: expressing cost per unit of business value, such as cost per customer or per transaction, instead of looking only at the total bill [19][20].

### Q: What's QuickServe's unit metric?

**Cost per completed order** = infrastructure cost for a period / orders delivered in that period. A worked example with **made-up round numbers**, just to show the reasoning:

```
Suppose the month's infrastructure costs Rs 3,000 and 1,500 orders are delivered.
Cost per order = 3,000 / 1,500 = Rs 2.00
```

Now compare it with revenue per order. Real platforms charge a flat platform fee per order (Zomato's was Rs 14.90 before GST as of March 2026 [10]). If infrastructure costs Rs 2 per order, that's a big chunk of a Rs 15 fee before delivery, support or marketing. Two questions follow, and that's the point of the metric:

- **Does cost grow slower than orders?** If orders double and cost per order falls, the system scales efficiently. If cost per order climbs, something is wasteful.
- **Which component dominates?** Usually the database, then compute, then logs and data transfer.

The dashboard already shows it live (Phase 7b), and Phase 8b prices what each pod reserves against what it uses. Measuring it with real AWS prices comes when the Phase 6 Terraform is applied. For a small app the single instance usually wins on cost, and seeing that with your own numbers is the lesson.

### Q: How does the inventory design connect to FinOps?

The kitchen has the same problem as the cloud, with food instead of servers:

| Kitchen (this app) | Cloud (FinOps) |
|---|---|
| Units prepared (`stock`) | Capacity provisioned (vCPUs, instances) |
| Sell-through = sold / prepared | Utilisation = used / provisioned |
| Leftover and `units_wasted` | Idle resources you still pay for |
| Sold out at 1 pm (censored demand) | Throttling, queueing, dropped requests |
| Restock suggestion | Rightsizing recommendation |
| Fixed per-cycle stock | Reserved capacity; autoscaling is "cook to order" |

Explaining the cycle data this way shows you understand FinOps as a way of thinking, not just a list of AWS tools. It works well in interviews.

### Q: What cost decisions are already in the code?

| Decision | Cost reason |
|---|---|
| `SQL_ECHO=false` by default | Logging every statement multiplies log volume, and log storage and ingestion are billed |
| Pooled connections and pool limits | Avoids buying a bigger database just to hold connections |
| Paginated list endpoints | An unbounded `SELECT` costs CPU, memory and data transfer, and grows with the table |
| Indexes matched to real queries (`status, accept_by` for the timeout job; `restaurant_id, status` for the restaurant's order queue) | Fewer full scans means a smaller database instance |
| The report reads archived cycles, not millions of order rows | Cheap analytics; later it can run on a read replica or a nightly summary |
| CI cancels superseded runs, has a timeout and caches pip | CI minutes are billed |
| Menu cached in Redis for 10 seconds | The most-read page stops hitting PostgreSQL on every view, so a smaller database handles more customers |
| Login rate limiting checked before the password | A blocked guess costs ~2 ms instead of ~110 ms of Argon2 CPU, so attacks are cheap to turn away |
| Redis capped at 64 MB with `volatile-ttl` eviction | RAM is the expensive part of a cache; the cap makes the cost fixed and predictable |
| One JSON log line per request, uvicorn's duplicate access log off | Log platforms bill by volume ingested and stored |
| Container resource limits in Compose | The habit that becomes Kubernetes requests/limits, which decide node count and therefore cost |
| Separate dev and runtime dependencies | Smaller production images: faster pulls, less registry storage |
| Slim base image, two-stage build, `.dockerignore` | About 82 MB compressed; registry storage and cross-region pulls bill per GB |
| One image for API, worker and migrations | One thing to build, scan and store instead of three |
| CI writes the image size to every run's summary | A size jump is seen in review, not on the bill |
| Image built for ARM as well as Intel | Keeps cheaper AWS Graviton servers an option [36] |
| Two-chip build only on `main`, layer cache shared between runs | The slow emulated ARM build doesn't run on every pull request; fewer CI minutes |
| Budget alert created before any other AWS resource | The first mistake costs an email, not a bill |
| No NAT gateway; database in private subnets | Avoids an always-on hourly charge plus per-GB processing [37] |
| Parameter Store instead of Secrets Manager | USD 0 instead of USD 0.40 per secret per month [38] [39] |
| `t4g` Graviton with `standard` CPU credits | Cheaper per hour, and no surplus-credit charges [40] |
| Single-AZ `db.t4g.micro`, storage autoscaling off, no final snapshot in dev | Smallest PostgreSQL; the bill can't grow by itself; nothing left billing after `destroy` |
| `default_tags` on every AWS resource (`project`, `environment`) | Cost Explorer can split the bill by project and environment |
| Old state versions expire after 90 days | Versioning without paying to keep every version forever |
| `terraform destroy` after every session | ~USD 0.15 per session instead of ~USD 30 per month |
| Kubernetes requests sized per pod (API 100m CPU / 192 Mi) | Requests decide how many nodes a cloud cluster needs, and so the bill [52] |
| Autoscaler between 2 and 5 API pods | Pays for extra pods only under load, with a hard ceiling |
| `ttlSecondsAfterFinished` on the migration Job, `revisionHistoryLimit: 5` | Finished Jobs and old ReplicaSets don't pile up |
| minikube and kind for learning Kubernetes | A real cluster for USD 0; a managed control plane bills by the hour |
| Metrics labelled by route template, no IDs; scrape every 15 s; keep 2 days / 1 GB | Managed Prometheus bills per sample [57]; fewer series, fewer samples |
| Cost per order on the dashboard | The unit metric is visible to everyone, not hidden in a spreadsheet |
| One Gateway (one load balancer on a cloud) for every hostname | Cloud load balancers bill by the hour plus traffic; one per app multiplies that |
| Edge rate limit on login, at Envoy | A flood is refused for almost no CPU instead of ~0.1 s of Argon2 per attempt |
| Envoy proxy requests set to 50m / 128 Mi | The add-on's defaults are sized for big clusters, not this one |
| Rightsizing report: requests vs measured use, priced at Fargate's per-request rates | Shows reserved-but-idle capacity in dollars; recommends CPU from p95 and memory from the peak |
| Requests NOT shrunk from an idle hour of data | Cheap today, outage on Friday night; size from a week that includes the busiest hours |
| Alerts grouped and inhibited, repeats every 4 h (critical 1 h) | Fewer, better notifications; paging tools often bill per user or per notification |
| Alertmanager and Mailpit at 10m CPU / 32 Mi each, Mailpit capped at 500 emails | The alerting stack costs almost nothing and can't grow without bound |
| Limits on every container in Compose (API 1 CPU / 512 MB, worker 0.5 CPU / 256 MB) | First guesses for the Kubernetes requests and limits that decide node count in Phase 7 |

### Q: How do I avoid a surprise AWS bill?

- **Know the free tier you actually have.** AWS changed it on 15 July 2025. New accounts get up to USD 200 in credits (USD 100 at sign-up and up to USD 100 more for exploring services) and can choose a Free plan that lasts up to 6 months or until the credits run out [21]. When a Free plan ends, AWS closes the account and keeps the content for 90 days [22]. Many tutorials still describe the old 12-month free tier.
- **Set an AWS Budget alert before creating anything.** It's an alert, not a spending cap.
- **Tag every resource** (`project=quickserve`, `env=dev`) so Cost Explorer can split the bill.
- **Destroy what you're not using.** `terraform destroy` at the end of each study session is the cheapest habit there is.
- **Watch the usual surprises:** NAT gateways, idle load balancers, RDS instances left running, unattached EBS volumes and Elastic IPs, and managed Kubernetes control-plane fees. Check current regional pricing before creating any of them.

---

## 11. Bugs the tests caught while building this

These are real, and they make better interview stories than any feature list.

**1. The double-tap payment.** Two identical payment requests with the same idempotency key arrived together. Both checked "is this key used?", saw no, and queued for the order lock. The first committed a payment. The second got the lock, saw the order was `PAID` and returned an error, when it should have returned the first payment. **Fix:** check the idempotency key *again* after acquiring the lock. Found by `test_double_tap_from_two_devices_creates_one_payment`. The general lesson: **any check made before you hold the lock may be stale once you hold it.**

**2. The test that passed by accident.** The first version of the "Selling fast" badge test passed, but for the wrong reason. The test changed `cycle_started_at` with raw SQL, while the test still held the `MenuItem` object. The identity map kept serving the old timestamp, so the badge maths used the wrong time and happened to produce the expected answer. Re-checked with fresh data, the numbers sat right on the boundary and the badge wouldn't have shown. **Fix:** `db.expire_all()` after raw SQL in tests, sturdier numbers, and `populate_existing=True` on every locking query in the app. The lesson: **a green test is a claim, not proof. Check it fails when it should.**

**3. The migration that couldn't go back.** Alembic's autogenerated downgrade forgot the PostgreSQL ENUM types, so downgrade followed by upgrade crashed. **Fix:** drop the types by hand in `downgrade()`, and the test suite now runs downgrade and upgrade on every run. The lesson: **untested rollbacks don't work when you need them.**

**4. Dependency drift.** Two environments installed the same `requirements` file and got different `starlette` versions. **Fix:** a lock file for CI. The lesson: **"pinned" isn't "reproducible" until the transitive dependencies are pinned too.**

**5. "Degraded" that was really "down".** With Redis switched off, the menu should still load from PostgreSQL, and it did, but every request took about 4 seconds, because the Redis client retries failed commands several times with growing pauses by default. **Fix:** one immediate retry, then fail fast; a test now fails if a Redis-down request takes over a second. The lesson: **test your failure modes for speed, not just correctness.**

**6. The logs that vanished.** All application logs disappeared during the test run. Alembic's `fileConfig` switches off every existing logger by default, and the tests run migrations inside the same process. **Fix:** `disable_existing_loggers=False`. The lesson: **library defaults can silently undo your setup.**

**7. Request IDs that went missing.** Log lines formatted after the request had finished lost their request ID, because it was read at formatting time. **Fix:** stamp it on each record when it's created. The lesson: **capture context when the event happens, not when you print it.**

---

## 12. Project structure and API

```
quickserve/
├── app/
│   ├── main.py                   FastAPI app, error handler, health checks
│   ├── api/router.py             mounts every module under /api/v1
│   ├── core/
│   │   ├── config.py             all settings (DB, pool, timeouts, fees, tax rates)
│   │   ├── security.py           password hashing (Argon2), JWT create/verify
│   │   ├── redis.py              shared Redis client (short timeouts, fail fast)
│   │   ├── logging.py            JSON logs, request IDs
│   │   ├── metrics.py            Prometheus metrics, counted only after commit
│   │   ├── exceptions.py         domain errors -> HTTP codes in one place
│   │   └── money.py              Decimal rounding for bills
│   ├── database/
│   │   ├── base.py               declarative Base, naming convention, UUID + timestamp mixins
│   │   ├── session.py            engine, pool, get_db(), transaction()
│   │   └── models.py             imports every model (for Alembic)
│   ├── worker.py                 background worker: runs the order timeout job
│   ├── notifier.py               notifier: delivers outbox events as notifications (Phase 8)
│   └── modules/                  one folder per business area (modular monolith)
│       ├── auth/                 login, logout, get_current_user, require_roles,
│       │                         rate_limit (Redis), revocation (Redis)
│       ├── users/                model (4 roles), schema, service, router
│       ├── restaurants/          model (location, cuisines, prep time, rating totals), profile + location updates
│       ├── discovery/            near me (bounding box + exact distance), ETA and Bayesian rating (pure), search (Phase 12)
│       ├── reviews/              one review per delivered order, atomic rating totals, recount job (Phase 12)
│       ├── menu/                 model (MenuItem, InventoryCycle), repository, service, cache,
│       │                         analytics (ORM + raw SQL versions), schema, router
│       ├── orders/               model, state_machine, repository, service (quote + place), schema, router
│       ├── pricing/              calculator (pure: every fee, GST, the itemised bill), geo (distance),
│       │                         rain switch (SurgeFlag), GET /pricing (Phase 11)
│       ├── coupons/              model (Coupon, CouponRedemption), race-safe redeem/release, router (Phase 11)
│       ├── payments/             model, service, refunds (public interface), schema, router
│       ├── outbox/               OutboxEvent model; record(), claim_batch(), retry backoff, retention
│       └── notifications/        model, templates (who is told what), service, schema, router
├── migrations/                   Alembic env + versions
├── scripts/
│   ├── seed.py                   demo data
│   ├── race_demo.py              naive vs atomic stock counter, live
│   ├── show_sql.py               print the SQL our ORM code generates
│   └── create_test_db.sql        runs on first Postgres container start
├── tests/                        244 tests, real PostgreSQL and Redis
├── infra/                        Terraform for AWS (Phase 6); start with infra/README.md
│   ├── k8s/                      Kubernetes (Phase 7): base/ manifests, overlays/ (lite = Mac default, local = full,
│   │                             ci, ci-lite), components/lite, deploy.sh,
│   │                             smoke_test.py, rightsizing.py (Phase 8b: requests vs real use)
│   │   ├── monitoring/           Prometheus config, alert rules + their tests, Grafana dashboard (Phase 7b),
│   │                             Alertmanager + Mailpit (Phase 8b)
│   │   ├── gateway/              HTTPS front door (Phase 9): certificates, Gateway, routes, policies;
│   │                             addons.sh installs Envoy Gateway + cert-manager, gateway_check.sh tests it
│   │   └── network-policies/     who may talk to whom (Phase 10); netpol_check.sh proves it, smoke.sh runs tests
│   ├── bootstrap/                budget alert + S3 state bucket, once per account
│   ├── envs/dev/                 network, database, secrets, app server (+ tests/)
│   └── modules/                  budget, network, database, app_server (each with tests/)
├── docs/docker.md                the Dockerfile explained line by line
├── .github/workflows/ci.yml      five jobs: test, docker, publish (ghcr.io), terraform, kubernetes (kind)
├── Dockerfile                    two-stage image, runs as user "app"
├── .dockerignore                 keeps venv/, .git/, tests and .env out of the image
├── docker-compose.yml            db + redis; profile "app" adds migrate, api, worker
├── requirements.txt / requirements-dev.txt / requirements-dev.lock
├── requirements.lock             runtime-only pins the image installs
├── pyproject.toml                ruff and pytest settings
└── .env.example
```

**Layering inside a module:** `router` (HTTP in and out, nothing else) → `service` (business rules, transactions) → `repository` (queries). Services raise domain errors, never `HTTPException`, so the same service works from a background job or a script. Modules talk to each other through small public functions (for example `payments/refunds.py`), never by reaching into each other's tables. That's what will let us split payments or notifications into their own services in Phase 8 without touching the callers.

**Endpoints** (all under `/api/v1` except health). "Owner" means the owner of *that* restaurant; admins can do everything an owner can:

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/auth/login` | anyone | Email + password in, access token out; `429` after too many failures |
| POST | `/auth/logout` | logged in | Invalidate the token you're using |
| POST | `/users` | anyone | Sign up as customer, restaurant owner or rider |
| GET | `/users/me` | logged in | Who am I? |
| GET | `/restaurants` | anyone | List restaurants (paginated) |
| GET | `/restaurants/near?lat=&lng=&sort=` | anyone | Restaurants that deliver here, with distance, ETA, fee and rating; sort by `distance`, `rating` or `eta`; `cuisine`, `min_rating` filters |
| GET | `/search?q=&lat=&lng=` | anyone | Dishes and restaurants that deliver here; typo-tolerant |
| PUT | `/restaurants/{id}/profile` | owner | Cuisines and usual prep time |
| GET | `/restaurants/{id}/reviews` | anyone | Rating, star breakdown, newest reviews |
| POST | `/restaurants` | restaurant owner | Create a restaurant you own |
| GET | `/restaurants/{id}/menu` | anyone | Customer menu with `orderable`, badge, units left; cached (`X-Cache` header) |
| POST | `/restaurants/{id}/menu` | owner | Add a dish (opens stock cycle 1) |
| GET | `/restaurants/{id}/menu/manage` | owner | Raw stock/consumed counters |
| POST | `/menu/{id}/restock` | owner | Close and archive the cycle, open a new one |
| PATCH | `/menu/{id}/availability` | owner | On / off / off until a time |
| GET | `/menu/{id}/cycles` | owner | Cycle history |
| GET | `/menu/{id}/restock-suggestion` | owner | Suggested quantity, with reasons |
| GET | `/restaurants/{id}/best-sellers?days=7` | owner | Ranked report |
| POST | `/orders` | customer | Place an order (reserves stock, all or nothing) |
| GET | `/orders/{id}`, `/orders/{id}/timeline` | its customer, owner, rider (once READY), admin | Order with bill; status history |
| PATCH | `/orders/{id}/status` | owner, rider, admin | Status changes allowed for your role |
| POST | `/orders/{id}/cancel` | its customer (before acceptance), admin | Cancel with a reason |
| POST | `/orders/{id}/payments` | its customer | Mock payment; needs `Idempotency-Key`; `?simulate=failure` to test failures |
| GET | `/orders/{id}/payments`, `/payments/{id}` | same as the order | Payment attempts |
| POST | `/admin/jobs/order-timeouts` | admin | Run the timeout job by hand |
| POST | `/orders/{id}/review` | its customer, once, within 7 days of delivery | Rate a delivered order 1-5 stars |
| POST | `/admin/jobs/recompute-ratings` | admin | Recount rating totals from the reviews; reports drift |
| GET | `/notifications?unread_only=true` | logged in | Your notifications, newest first |
| POST | `/notifications/{id}/read` | the notification's owner | Mark one as read (someone else's: `404`) |
| GET | `/health`, `/health/ready` | anyone | Liveness, readiness |

---

## 13. Roadmap

Each phase ends with something you can show: a passing CI run, a live URL, a dashboard screenshot.

| Phase | What we build | Concepts |
|---|---|---|
| **3. Auth** (done) | Login, JWT access tokens, four roles, ownership checks, rider role migration | Authentication vs authorization, hashing vs encryption, token expiry, object-level authorization |
| **4. Redis, jobs, logging** (done) | Redis menu cache invalidated on owner changes, worker running the timeout job every 30 seconds, login rate limiting and logout in Redis, JSON logs with request IDs | Cache invalidation, at-least-once jobs, rate limiting, log cost |
| **5. Docker and CI/CD** (done) | Multi-stage Dockerfile, non-root user, runtime lock file, Compose with `db` + `redis` + `migrate` + `api` + `worker`, CI builds the image and smoke-tests the running stack | Image layers and size, container networking, migrations as a one-off job, graceful shutdown |
| **5b. Image registry** (done) | CI publishes the image to GitHub Container Registry after both other jobs pass, tagged with the commit ID, for Intel and ARM | Immutable tags, least-privilege CI tokens, multi-architecture images |
| **6. AWS and Terraform** (code done and tested; applying it is your call) | Budget alert and S3 state bucket (bootstrap), VPC with public/private subnets and no NAT, RDS PostgreSQL 16, Parameter Store secrets, one Graviton EC2 server running the ghcr.io image, Session Manager instead of SSH, 18 mock-based `terraform test` checks in CI | IAM least privilege, public vs private subnets, remote state and locking, IMDSv2, `plan`/`apply`/`destroy` |
| **7. Kubernetes** (done) | Kustomize manifests for minikube: Deployments, StatefulSet, Services, migration Job with wait-for-migrations init containers, ConfigMap and Secret, HPA, PDB, probes wired to `/health` and `/health/ready`, locked-down pods; CI deploys to kind and checks a zero-downtime rollout and self-healing | Requests vs limits, liveness vs readiness, rolling updates, what happens when a pod dies |
| **7b. Monitoring** (done) | Prometheus metrics on a private port (RED + business + worker heartbeat), counters that move only after commit, Prometheus with recording and alert rules (unit-tested with promtool), a Grafana dashboard with cost per order, CI that checks scraping, alerts and the dashboard | The four golden signals, percentiles, cardinality, alert fatigue, unit metrics |
| **8. Notification service** (done) | Transactional outbox written with every order change, a separate notifier process (own Deployment, metrics, liveness, alerts) that turns events into notifications: per-order ordering, retries with backoff, dead letters, idempotent consumer, retention; notifications API | Dual writes, the outbox pattern, at-least-once delivery, idempotency, poison messages, event-carried state |
| **8b. FinOps and alerting** (done) | Alertmanager with routing, grouping, inhibition and a Watchdog, emailing a Mailpit inbox; CPU and memory recording rules per pod; a rightsizing report that prices requests vs real use in USD; a Grafana rightsizing row; CI checks the whole alert-to-email chain | Alert fatigue, dead man's switch, compressible vs incompressible resources, rightsizing, VPA |
| **9. HTTPS front door** (done) | Gateway API with Envoy Gateway: one Gateway for every hostname, HTTP→HTTPS redirect, TLS from a local CA with automatic renewal (cert-manager), HSTS, timeouts, an edge rate limit on login, request IDs end to end; the API trusts exactly one proxy hop for the client IP; CI tests it all from outside the cluster | Gateway API vs Ingress, TLS termination, certificate chains, X-Forwarded-For spoofing, layered rate limiting |
| **10. Network policies** (done) | Default deny in and out, DNS allowed, one allow-list per component (PostgreSQL only from the apps, Redis only from the API, the API only from the gateway, no internet for the apps); smoke tests in their own labelled pods; a check that makes real allowed and forbidden connections, with positive controls, in CI on every PR | Zero trust inside the cluster, least privilege, egress control, namespaceSelector + podSelector, proving enforcement |
| **11. Pricing** (done) | Distance-based delivery fee (haversine x detour index, slabs, radius), free delivery for big orders nearby, small order fee, peak / late-night / rain surge (rain is an admin switch that expires), coupons (percent with cap, flat, minimums, first order, per-customer and total limits, platform- or restaurant-funded) with race-safe redemption, GST after discount, `POST /orders/quote` and `expected_total` | Pure functions for business rules, atomic counters and row locks, CHECK constraints as a safety net, time zones, price-change protection |
| **12. Discovery** (done) | Restaurants near me (bounding box on an index, then the exact distance checkout uses), delivery time from Swiggy's max(first mile, prep) + last mile, sort by distance / time / Bayesian-average rating, cuisine and rating filters; dish and restaurant search with full-text, trigram and typo fallback; reviews only for delivered orders, once, with atomic running totals, a CHECK constraint and a recount job | Bounding boxes and B-trees, `EXPLAIN`, GIN indexes, generated columns, Bayesian averages, denormalised counters and reconciliation, lost updates |
| **13. Frontend: customer app** (next) | React + TypeScript (Vite): browse, search, menu, cart, the checkout bill from `/orders/quote`, pay, live order status and notifications; served through the HTTPS gateway | API client generated from OpenAPI, tokens in the browser, same origin for site and API |
| **14. Frontend: restaurant and rider screens** | Owner dashboard (incoming orders, accept/prepare, menu and stock, coupons, today's sales); rider view (assigned orders, pick up, deliver) | Role-based UI on top of the backend's role checks |
| **15. Tracing** | OpenTelemetry traces across browser, Envoy, API, SQL, outbox and notifier, viewed in Jaeger; N+1 detection; sampling | Distributed tracing, context propagation through the outbox, the cost of tracing |
| **16. Live on AWS** | Apply the Phase 6 Terraform, a real domain with a Let's Encrypt certificate, GitHub Actions deploying after each merge, a smoke test against the live URL, then `terraform destroy` | Continuous delivery, real cloud costs, why one server instead of EKS |

---

## 14. Interview cheat sheet

**How do you notify another service reliably when data changes?** The transactional outbox. Write the event to an `outbox_events` table in the same transaction as the change, so both commit or neither does. A separate relay delivers it later. Delivery is at-least-once, so the consumer must be idempotent: QuickServe uses a unique `(event_id, user_id)` constraint with `ON CONFLICT DO NOTHING`. Keep per-entity order by claiming only the oldest waiting event per order. Failures are retried with backoff and dead-lettered after 5 attempts.

**How do you prevent overselling?** A single conditional UPDATE (`consumed = consumed + q WHERE consumed + q <= stock RETURNING ...`). The check and the write happen together under the row lock; the second racer re-checks the WHERE clause against the committed row and gets nothing. A CHECK constraint guards against impossible values, but it can't prevent lost updates. Our race demo showed 40 orders accepted for 10 units with the naive version.

**Why stock + consumed instead of a single counter?** It keeps what was prepared separately from what was sold. Archived cycles then give sell-through, sold-out time, waste and fair best sellers.

**What's censored demand?** When an item sells out, sales understate demand, because people who came later are invisible. Rank by rate while in stock, and correct forecasts for sold-out cycles.

**Optimistic vs pessimistic locking?** Pessimistic: lock first, then read and write (`SELECT ... FOR UPDATE`, used for restock and order transitions). Optimistic: take no lock while you work, detect a conflict when you write (usually a version column, and retry on conflict). For a single counter there's a simpler third option, used for orders here: put the check inside the write itself (a conditional UPDATE).

**How do you avoid deadlocks?** Acquire locks in a consistent order (sorted IDs) and keep transactions short.

**What is the N+1 problem?** One query for a list plus one per item. Fix it with eager loading (`selectinload`/`joinedload`); prevent it with `lazy="raise"`.

**What's the identity map, and its catch?** One object per row per session. Repeat lookups are answered from memory, but a held object isn't refreshed by a new SELECT. Use `populate_existing` with `FOR UPDATE`.

**How do you make payments safe to retry?** An idempotency key with a UNIQUE constraint, re-checked after taking the lock, plus a partial unique index allowing one SUCCESS per order.

**What does `SKIP LOCKED` give you?** Several workers can pull jobs from the same table without double-processing and without waiting on each other.

**Liveness vs readiness?** Liveness restarts a dead process; readiness removes a struggling instance from the load balancer. Don't make liveness depend on the database.

**How would you scale database connections?** Count the pools (workers × pool size × replicas) against `max_connections`, and add PgBouncer before buying a bigger instance.

**Authentication vs authorization?** Authentication is who you are (login, token, `401`); authorization is what you may do (`403`). Both are checked on every request.

**What's in a JWT, and is it secret?** Header, payload and signature. The payload is only base64-encoded, so anyone can read it; the signature only proves it wasn't changed. Never put secrets in it, and guard the signing key.

**Why look the user up when the token already has their role?** Tokens can't be revoked, so the database is the source of truth: role changes and deleted accounts take effect immediately. Trade-off: stateless vs revocable.

**What's Broken Object Level Authorization?** Checking a user's role but not that they own the specific object, so changing an id in the URL reaches someone else's data. It's number one on OWASP's 2023 API list; we check ownership in the service layer for every restaurant and order.

**Why the same error for a wrong password and an unknown email?** To stop account enumeration. The timing must match too, so an unknown email still runs one full password-hash check.

**What's cache-aside, and when do you invalidate?** Read from the cache, and on a miss build from the database and store it with a TTL. Invalidate **after** the database commit, or a reader can re-cache the old data in the gap.

**What can you cache safely?** Anything allowed to be a little old. Our menu's stock badges can be 10 seconds stale because the order itself checks stock in PostgreSQL.

**Fail open or fail closed?** When a dependency is down, either skip the check (keep working, less protection) or refuse the request (stay protected, stop working). We fail open for rate limits and token checks, but refuse logout, because a fake success there would mislead the user.

**How does a fixed-window rate limiter work?** An atomic `INCR` per key, with an expiry set on the first hit. It's cheap; the weakness is bursts at the window edges, which a sliding window fixes.

**What's graceful shutdown?** Handle `SIGTERM`, finish the current unit of work, then exit before the orchestrator sends `SIGKILL`.

**Why request IDs?** One ID ties together every log line from one request across modules and services, and users can quote it when reporting a problem.

**Two users redeem the last coupon at the same moment. How do you stop both getting it?** Make using it one atomic statement (`UPDATE ... SET used = used + 1 WHERE used < limit`), not "read, check in code, write". That UPDATE locks the row until commit, so re-check per-user rules right after it. Add a CHECK constraint so the database refuses an overspend even if the code is wrong. For a very hot coupon, split the counter or issue unique codes.

**How do you stop a customer paying a price they didn't see?** Quote and order use the same pricing code; the client sends back the quoted total, and the server refuses (409 with the new total) if its own calculation differs. Never trust a price the client computed, and never silently charge a different one.

**What does a default-deny NetworkPolicy break first?** DNS: with egress denied, pods can't resolve Service names, so add an allow rule to kube-dns on port 53 (UDP and TCP). Then allow each real path, remembering that both the sender's egress and the receiver's ingress must allow it. And prove it with real connections, because a plugin that ignores policies still accepts them.

**Ingress or Gateway API?** Gateway API: roles are split (GatewayClass for the platform, Gateway for the operator, HTTPRoute for app teams), redirects, timeouts and header changes are standard fields instead of annotations, and the most used Ingress controller, ingress-nginx, was retired in March 2026.

**How does a service behind a proxy get the real client IP?** From X-Forwarded-For, but only the entries your own proxies wrote: trust a fixed number of hops from the right, and only when the request comes from your proxy. Anything to the left is client-controlled. Trusting "*" or a whole network can let a client choose its own IP, which breaks per-IP rate limits and audit logs.

**Where should TLS end?** Usually at the edge proxy (TLS termination), with certificates issued and renewed automatically (cert-manager, ACME). Encrypting the hop from proxy to pods as well (mTLS) is the zero-trust step, usually done with a service mesh.

**How do you stop alert fatigue?** Alert on symptoms customers feel, add a `for:` duration, group related alerts into one notification, inhibit symptoms while their cause is firing, repeat slowly, and silence (don't delete) alerts during maintenance. Plus a Watchdog, an always-firing alert, so a broken alerting pipeline is noticed.

**How do you rightsize a pod?** Measure real usage over a representative period (a week with peak hours). Set the CPU request from a high percentile, because CPU is compressible (throttled, not killed), and the memory request from the peak, because a pod over its memory limit is OOMKilled. Add headroom, change one service at a time, and watch latency and restarts. VPA in recommendation mode automates the measuring.

**How do you find restaurants within 6 km fast?** Don't compute the distance for every row. Cut a latitude/longitude rectangle around the customer that's guaranteed to contain the circle, let a B-tree index answer the `BETWEEN` ranges, then compute the exact distance only for rows inside it. On 100,000 rows that was 0.44 ms vs 136 ms. At scale, use a 2-D index (PostGIS GiST) or a grid of cells (geohash, H3).

**Why not sort by average rating?** One 5-star review would beat 400 reviews averaging 4.6. Use a Bayesian average: add C imaginary reviews at the platform's mean, so the score starts at the mean and moves to the item's own average as real reviews arrive (IMDb's Top 250 formula). Show the plain average, rank by the Bayesian score.

**You keep a count and a sum on the parent row. How do you keep them right?** Change them with one atomic UPDATE (`count = count + 1`), in the same transaction as the child row, with a CHECK constraint for impossible values, and a reconciliation job that recounts from the source and reports drift. That job must lock before counting, or it can overwrite a concurrent update with a stale count.

**Full-text search, LIKE or trigrams?** Full-text (`tsvector` + GIN) for words with stemming and ranking. Trigram GIN for `ILIKE '%x%'` and typos. Run typo matching only when the exact search finds nothing, because similarity also matches look-alikes ("chai" ~ "Butter Chicken"). Track zero-result searches.

**Why didn't PostgreSQL use my index?** On a small table a sequential scan is cheaper, and the planner is right. With other filters, another index may narrow more. Check with `EXPLAIN (ANALYZE)` on realistic data and statistics (`ANALYZE`), not on 10 demo rows.

**What's unit economics in FinOps?** Cost per unit of business value. For us: infrastructure cost per completed order, tracked as orders grow.

---

## 15. References

Business and tax figures change often; the dates show when each was reported.

1. PostgreSQL documentation, *Transaction Isolation* (Read Committed; re-evaluation of the WHERE clause on concurrently updated rows). https://www.postgresql.org/docs/current/transaction-iso.html
2. SQLAlchemy documentation, *ORM API Features for Querying: Populate Existing*. https://docs.sqlalchemy.org/en/21/orm/queryguide/api.html
3. SQLAlchemy issue #3917, *Stale data from with_for_update query* (fixed with populate_existing). https://bitbucket.org/zzzeek/sqlalchemy_old/issues/3917/stale-data-from-with_for_update-query-on
4. FastAPI documentation, *OAuth2 with Password (and hashing), Bearer with JWT tokens* (pwdlib with Argon2). https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
5. Shopify, *Inventory formulas* (sell-through = units sold / units received x 100). https://shopify.com/retail/inventory-formulas
6. Lightspeed, *Sell-through rate* (75% or more considered strong). https://lightspeedhq.co.uk/blog/sell-through-rate
7. Wang et al., *FreshRetailNet-50K: A Stockout-Annotated Censored Demand Dataset for Latent Demand Recovery and Forecasting in Fresh Retail*, arXiv:2505.16319, 2025. https://arxiv.org/html/2505.16319v1
8. *Demand Estimation When There Are Unobservable Substitutions Amongst Choice Alternatives*, International Journal of Information Systems and Supply Chain Management, 2019 (discusses Anupindi et al., 1998, on bias in naive demand estimates). https://www.igi-global.com/article/demand-estimation-when-there-are-unobservable-substitutions-amongst-choice-alternatives/219312
9. *Tobit Exponential Smoothing, towards an enhanced demand planning in the presence of censored data*, arXiv:2407.17920 (lost sales make sales an underestimate of demand). https://arxiv.org/pdf/2407.17920
10. Business Today, *Zomato hikes platform fee to Rs 14.90 per order*, 20 March 2026. https://www.businesstoday.in/amp/technology/story/zomato-hikes-platform-fee-to-rs-15-per-order-521610-2026-03-20
11. Business Today, *Swiggy hikes platform fee to Rs 17.58 per order*, 24 March 2026. https://www.businesstoday.in/technology/story/swiggy-hikes-platform-fee-to-rs-1758-per-order-follows-zomatos-recent-increase-522031-2026-03-24
12. TallySolutions, *GST on Restaurant Services: Dine-in vs Takeaway vs Delivery Apps*. https://tallysolutions.com/gst/gst-on-restaurant-services-dine-in-vs-takeaway-vs-delivery-apps/
13. LegalSuvidha, *GST on food items rate list* (delivery charges and platform fees at 18%). https://legalsuvidha.com/blog/gst-on-food-items-rate-list
14. A2Z Taxcorp, *E-commerce operators made liable under Section 9(5) for delivery services, w.e.f. 01.11.2026*. https://a2ztaxcorp.net/?p=41053
15. Sapaad Knowledge Base, *Zomato Connect: auto-reject for orders not reviewed within 4 minutes*. https://www-dr.sapaad.com/?p=66903
16. Swiggy Partner digital guide (Scribd copy), on marking items "Out of Stock" until next available. https://www.scribd.com/document/535641853/Swiggy-Digital-Book-1
17. Petpooja blog, *Item availability: stop cancelled orders*. https://blog.petpooja.com/industry-business-guides/item-availability-menu-on-off-stop-cancelled-orders/
18. Ipsator, *Item tagging* (percentile-based Best Seller and Must Try tags). https://ipsator.com/blog/item-tagging
19. FinOps Foundation, *Unit Economics capability*. https://www.finops.org/framework/capabilities/unit-economics/
20. Microsoft Learn, *Unit economics (FinOps Framework)*. https://learn.microsoft.com/en-us/cloud-computing/finops/framework/quantify/unit-economics
21. AWS, *AWS Free Tier*. https://aws.amazon.com/free
22. AWS re:Post Knowledge Center, *When does the AWS Free Tier start and expire?* https://www.repost.aws/knowledge-center/aws-free-tier-account-start-expire
23. pwdlib on PyPI (why it replaced passlib, which stopped working on Python 3.13). https://pypi.org/project/pwdlib/0.1.0
24. OWASP Web Security Testing Guide, *Testing for Account Enumeration and Guessable User Account*. https://owasp.org/www-project-web-security-testing-guide/stable/4-Web_Application_Security_Testing/03-Identity_Management_Testing/04-Testing_for_Account_Enumeration_and_Guessable_User_Account.html
25. OWASP, *Authentication Cheat Sheet*. https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
26. OWASP API Security Top 10 2023, *API1:2023 Broken Object Level Authorization*. https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/
27. OWASP, *Password Storage Cheat Sheet*. https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
28. Docker documentation, *docker container stop* (SIGTERM, then SIGKILL after the timeout; 10 seconds by default for Linux containers). https://docs.docker.com/engine/reference/commandline/stop/
29. Google Cloud blog, *Kubernetes best practices: terminating with grace* (default termination grace period of 30 seconds). https://cloud.google.com/blog/products/containers-kubernetes/kubernetes-best-practices-terminating-with-grace
30. Redis documentation, *Key eviction* (eviction policies, including volatile-ttl). https://redis.io/docs/latest/develop/reference/eviction/
31. Docker documentation, *Building best practices* (multi-stage builds, `.dockerignore`, running as a non-root user with `USER`). https://docs.docker.com/build/building/best-practices/
32. AWS, *Amazon ECR pricing* (storage per GB-month; free same-region transfer to EC2, ECS and Fargate; cross-region transfer billed). https://aws.amazon.com/ecr/pricing/
33. Docker documentation, *Control startup order in Compose* (`depends_on` with `service_healthy` and `service_completed_successfully`). https://docs.docker.com/compose/how-tos/startup-order/
34. Docker documentation, *Using profiles with Compose*. https://docs.docker.com/compose/how-tos/profiles/
35. GitHub Docs, *GitHub Packages billing* (free for public packages). https://docs.github.com/en/billing/managing-billing-for-github-packages
36. AWS, *AWS Graviton Fast Start* (Graviton on Fargate: up to 40% better performance at 20% lower cost than comparable x86). https://aws.amazon.com/ec2/graviton/fast-start
37. AWS, *Amazon VPC pricing* (NAT gateway: hourly charge plus per-GB data processing; the example uses USD 0.045 for each). https://aws.amazon.com/vpc/pricing/
38. AWS, *AWS Systems Manager pricing* (standard Parameter Store parameters and Session Manager at no additional charge). https://aws.amazon.com/systems-manager/pricing/
39. AWS, *AWS Secrets Manager pricing* (USD 0.40 per secret per month plus API calls). https://aws.amazon.com/secrets-manager/pricing/
40. AWS documentation, *Unlimited mode for burstable performance instances* (T4g, T3a and T3 launch as unlimited by default; surplus credits can be charged). https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode.html
41. AWS, *Amazon EKS now supports EC2 Instance Metadata Service v2* (IMDSv2 token via PUT; response hop limit of 1 by default). https://aws.amazon.com/about-aws/whats-new/2020/08/amazon-eks-supports-ec2-instance-metadata-service-v2
42. HashiCorp, *Terraform S3 backend* (`use_lockfile` for S3-native locking; DynamoDB locking deprecated). https://developer.hashicorp.com/terraform/language/backend/s3
43. HashiCorp, *Terraform test mocking* (mock providers generate fake data instead of calling provider APIs). https://developer.hashicorp.com/terraform/language/tests/mocking
44. AWS News Blog, *New: AWS Public IPv4 Address Charge* (USD 0.005 per IP per hour from 1 February 2024). https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/
45. AWS Security Blog, *Simplified developer access to AWS with `aws login`* (temporary, auto-rotated CLI credentials from your console sign-in; AWS CLI 2.32.0+). https://aws.amazon.com/blogs/security/simplified-developer-access-to-aws-with-aws-login
46. Spare Cores, *db.t4g.micro* (PostgreSQL, Mumbai single-zone: about USD 0.021 per hour). https://sparecores.com/database/aws/db.t4g.micro
47. DevZero, *t4g.small* (on-demand from about USD 0.0112 per hour in ap-south-1). https://www.devzero.io/instances/aws/t4g.small
48. AWS, *AWS Budgets pricing* (budgets without actions are free; first two action-enabled budgets free). https://aws.amazon.com/aws-cost-management/aws-budgets/pricing
49. Kubernetes documentation, *Liveness, Readiness, and Startup Probes* (a failed readiness probe removes the pod from the Service's endpoints; liveness restarts the container). https://kubernetes.io/docs/concepts/workloads/pods/probes/
50. Google Cloud blog, *Kubernetes best practices: terminating with grace* (pod removed from Service endpoints; preStop hook; SIGTERM; grace period; SIGKILL). https://cloud.google.com/blog/products/containers-kubernetes/kubernetes-best-practices-terminating-with-grace
51. Kubernetes documentation, *Horizontal Pod Autoscaling* (remove `spec.replicas` from the manifest when an HPA is enabled). https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
52. Kubernetes documentation, *Resource Management for Pods and Containers* (the scheduler places pods by their requests; memory limits enforced by OOM kills). https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
53. Kubernetes documentation, *Jobs* (a Job's pod template can't be updated; delete and recreate). https://kubernetes.io/docs/concepts/workloads/controllers/job/
54. kind documentation, *Initial design* (Kubernetes clusters whose nodes are Docker containers, aimed at testing). https://kind.sigs.k8s.io/docs/design/initial/
55. Google, *Site Reliability Engineering*, chapter 6 "Monitoring Distributed Systems" (the four golden signals: latency, traffic, errors, saturation). https://sre.google/sre-book/monitoring-distributed-systems/
56. Prometheus documentation, *Metric and label naming* (don't use labels for high-cardinality values such as user IDs). https://prometheus.io/docs/practices/naming/
57. AWS, *Price reduction for Amazon Managed Service for Prometheus* (USD 0.90 per 10M samples ingested for the first 2 billion). https://aws.amazon.com/about-aws/whats-new/2021/05/aws-announces-a-price-reduction-for-amazon-managed-service-for-prometheus-amp
58. AWS, *Amazon Managed Service for Prometheus pricing* (example: 10 nodes, 1,000 metrics each, every 30 s, ingestion about USD 80.93 a month). https://aws.amazon.com/prometheus/pricing/
59. OpenCost (CNCF project): real-time Kubernetes cost allocation, exported to Prometheus. https://opencost.io/
60. Prometheus documentation, *Unit testing for rules* (`promtool test rules`). https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/
61. Chris Richardson, *Pattern: Transactional outbox*, microservices.io. https://microservices.io/patterns/data/transactional-outbox.html
62. Chris Richardson, *Pattern: Idempotent Consumer*, microservices.io (at-least-once delivery means a handler can run more than once for the same message). https://microservices.io/patterns/communication-style/idempotent-consumer.html
63. PostgreSQL documentation, *SELECT: the locking clause* (SKIP LOCKED for queue-like tables with multiple consumers). https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE
64. Debezium documentation, *Outbox Event Router* (CDC-based outbox relay to Kafka). https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html
65. Prometheus documentation, *Alertmanager* (deduplication, grouping, routing, silences and inhibition; point Prometheus at all Alertmanagers, don't load-balance). https://prometheus.io/docs/alerting/latest/alertmanager/ and *Configuration*: https://prometheus.io/docs/alerting/latest/configuration/
66. prometheus-operator runbooks, *Watchdog* (an always-firing alert that checks the entire alerting pipeline). https://runbooks.prometheus-operator.dev/runbooks/general/watchdog
67. PromLabs training, *End-to-End Watchdog Alerts* (dead man's switch; an external service notices when the notifications stop). https://training.promlabs.com/training/monitoring-and-debugging-prometheus/metrics-based-meta-monitoring/end-to-end-watchdog-alerts/
68. AWS, *AWS Fargate pricing* (billed per vCPU-hour and GB-hour requested; Linux/x86 USD 0.04048 and USD 0.004445 in us-east-1; Linux/ARM USD 0.03238 and USD 0.00356). https://aws.amazon.com/fargate/pricing/
69. OpsLyft, *AWS Fargate pricing calculator* (October 2026 us-east-1 rates; memory billed as allocated, not used; ARM about 20% lower). https://www.opslyft.com/blog/aws-fargate-pricing-calculator
70. Kubernetes documentation, *Proxying traffic to services* (the API server's `/api/v1/namespaces/<ns>/services/<name>:<port>/proxy` URL). https://kubectl.docs.kubernetes.io/guides/container_debugging/proxying_traffic_to_services/
71. Kubernetes documentation, *Vertical Pod Autoscaling* (adjusts requests from historical usage). https://kubernetes.io/docs/concepts/workloads/autoscaling/vertical-pod-autoscale/
72. Kubernetes blog, *Ingress NGINX Retirement: What You Need to Know* (November 2025; maintenance stops March 2026; migrate to Gateway API or another controller). https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/
73. Fairwinds, *Kubernetes Is Moving On From ingress-nginx* (after March 2026 the repository is archived, read-only, with no releases, fixes or security patches). https://www.fairwinds.com/blog/kubernetes-ingress-nginx-2026-migration
74. Kubernetes blog, *Gateway API v1.5: Moving features to Stable* (TLSRoute, ListenerSet, HTTPRoute CORS filter and more in the Standard channel). https://kubernetes.io/blog/2026/04/21/gateway-api-v1-5/
75. Gateway API, *Implementations* (conformant implementations, including Envoy Gateway; AWS Load Balancer Controller integration). https://gateway-api.sigs.k8s.io/implementations/
76. Envoy Gateway documentation, *Local Rate Limit* (per Envoy instance; no distinct per-value matching, use Global for that). https://gateway.envoyproxy.io/latest/tasks/traffic/local-rate-limit
77. cert-manager documentation, *Securing gateway resources* (Gateway API support) and *CA issuer*. https://cert-manager.io/docs/usage/gateway/
78. minikube documentation, *Network Policy* (the default Kindnet plugin doesn't enforce them; use Calico). https://minikube.sigs.k8s.io/docs/handbook/network_policy/
79. Kubernetes documentation, *Network Policies* (pods are isolated per direction by any policy that selects them; policies are additive; traffic from the pod's node is always allowed). https://kubernetes.io/docs/concepts/services-networking/network-policies/
80. kindnet documentation, *Network Policies* (implemented with kube-network-policies; also supports Admin Network Policies). https://kindnet.sigs.k8s.io/docs/user/network-policies/
81. Inc42, *India's Convenience Economy Is Getting Expensive* (platform fees from Rs 2 in 2023 to Rs 14.9 / Rs 17.58 in March 2026; late-night, surge and rain fees; Blinkit's Rs 20 small cart fee under Rs 99). https://inc42.com/features/indias-convenience-economy-is-getting-expensive/
82. Free Press Journal, *Zomato Gold & Swiggy One members now pay rain surcharge*. https://www.freepressjournal.in/amp/business/food-delivery-loyalty-users-no-longer-get-fee-waiver-zomato-gold-swiggy-one-members-now-pay-rain-surcharge
83. Restaurant India, *Zomato introduces 'long distance service fee' for deliveries beyond 4 km*. https://www.restaurantindia.in/news/tag/food-delivery-business?page=22
84. TechEnclave forum, *The enshittification of Swiggy* (users report membership free-delivery distance cut from 10 km to 7 km; a forum, not an official source). https://techenclave.com/t/the-enshittification-of-swiggy/269349?page=5
85. MapAtlas, *As the crow flies vs by road* (116 city pairs, September 2026: roads 23.5% longer at the median; multiply by 1.2 as a rule of thumb; cites Ballou, Rahardja and Sakai, *Selected country circuity factors for road travel distance estimation*, Transportation Research Part A, 2002). https://mapatlas.eu/blog/distance-as-the-crow-flies
86. EY India, *CBIC issues notifications giving effect to the recommendations made by the GST Council* (e-commerce operators pay 18% on local delivery from 22 September 2025; Notification 17/2025-Central Tax (Rate)). https://www.ey.com/en_in/technical/alerts-hub/2025/09/cbic-issues-notifications-giving-effect-to-the-recommendations-made
87. TaxGuru, *Section 15(3) of the CGST Act* (a discount given before or at the time of supply and recorded in the invoice is not part of the value of supply). https://taxguru.in/?p=823177
88. Jan Philip Matuschek, *Finding Points Within a Distance of a Latitude/Longitude Using Bounding Coordinates* (the bounding-box formulas, including poles and the 180th meridian, and why a B-tree on latitude and longitude only narrows by one of them). http://janmatuschek.de/LatitudeLongitudeBoundingCoordinates
89. Swiggy Bytes, *The Swiggy Delivery Challenge* (series, 2019 onwards; Part One gives "Delivery Time = Max(Assignment Delay + First Mile Time, Prep Time) + Last Mile Time" and the "last last mile" from the gate to the door). https://bytes.swiggy.com/the-swiggy-delivery-challenge-part-two-f095930816e3
90. Evan Miller, *How Not To Sort By Average Rating* (2009). https://www.evanmiller.org/how-not-to-sort-by-average-rating.html
91. Evan Miller, *Bayesian Average Ratings* (2012). https://www.evanmiller.org/bayesian-average-ratings.html
92. IMDb's Top 250 "true Bayesian estimate", WR = (v ÷ (v+m)) × R + (m ÷ (v+m)) × C, as published by IMDb and collected by FXSolver. https://www.fxsolver.com/browse/formulas/Bayes+estimator
93. Evan Miller, *Ranking Items With Star Ratings* (2014; ranking by the lower bound of a credible interval). https://www.evanmiller.org/ranking-items-with-star-ratings.html
94. PostgreSQL 16 documentation, *12.2 Tables and Indexes* (a stored generated `tsvector` column with a GIN index). https://www.postgresql.org/docs/16/textsearch-tables.html
95. PostgreSQL 16 documentation, *pg_trgm* (`word_similarity`, the `<%` operator and `pg_trgm.word_similarity_threshold`, default 0.6; GIN `gin_trgm_ops` also serves `LIKE`/`ILIKE`; a trusted extension). https://www.postgresql.org/docs/16/pgtrgm.html
