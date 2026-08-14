# CODING_STANDARDS.md

## Python + FastAPI + Strict Domain-Driven Design

These rules are mandatory for all code generated, modified, or refactored by the AI agent.

## 1. Project Structure

Use `src/` as the application root.

Organize code by **business domain/module**, not by global technical layers.

```text
project/
├── src/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── container.py
│   ├── exceptions.py
│   │
│   ├── users/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── models.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   ├── dependencies.py
│   │   ├── exceptions.py
│   │   └── ...
│   │
│   ├── orders/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── models.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   ├── dependencies.py
│   │   └── ...
│   │
│   └── shared/
│       ├── retry/
│       ├── storage/
│       ├── pagination/
│       └── ...
│
├── tests/
│   ├── users/
│   └── orders/
└── alembic/
```

Each domain owns its code.

Do NOT create global:

```text
controllers/
services/
repositories/
models/
```

folders.

---

## 2. Domain Responsibilities

Each module should follow:

```text
router.py       → HTTP/API layer
schemas.py      → Pydantic API schemas
models.py       → database/ORM models
service.py      → business/domain logic
repository.py   → persistence access
dependencies.py → FastAPI dependencies
exceptions.py   → domain exceptions
```

Add files only when complexity requires them.

Business logic MUST stay inside the owning domain.

---

## 3. Strict DDD Rules

The domain must be independent from HTTP concerns.

Business logic MUST NOT:

- depend on `Request`/`Response`
- return HTTP-specific responses
- raise `HTTPException`
- contain FastAPI route logic
- directly instantiate infrastructure dependencies

Use domain-specific exceptions instead.

```python
class OrderNotFound(Exception):
    pass
```

FastAPI maps domain exceptions to HTTP responses at the API boundary.

---

## 4. Service Layer

`service.py` contains business rules and use-case orchestration.

Example:

```python
class OrderService:
    def __init__(
        self,
        repository: OrderRepository,
    ) -> None:
        self.repository = repository

    async def confirm(self, order_id: UUID) -> Order:
        order = await self.repository.get_by_id(order_id)

        if order is None:
            raise OrderNotFound()

        order.confirm()

        await self.repository.save(order)

        return order
```

Keep services focused.

Split `service.py` into multiple service modules when it becomes large.

Do not create an `application/` layer.

---

## 5. Repository

Repositories handle persistence only.

They MUST NOT contain business rules.

```text
service
   ↓
repository
   ↓
database
```

Use repository abstractions where they provide meaningful decoupling and testability.

Infrastructure/database details must not leak into business logic.

---

## 6. FastAPI Routes

Routes MUST be thin.

A route should:

```text
validate → inject dependencies → call service → return response
```

Example:

```python
@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    data: CreateOrderRequest,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    return await service.create(data)
```

Do not put business logic inside routers.

Use:

- `response_model`
- correct HTTP methods
- correct status codes
- clear descriptions
- consistent REST resource naming

---

## 7. Pydantic

Use **Pydantic v2** for API boundaries.

Use `schemas.py` for:

- request models
- response models
- API validation
- serialization

Prefer Pydantic validation over manual validation.

Do not pass FastAPI request objects deep into business logic.

Use response models consistently.

---

## 8. Dependency Injection

Use:

### FastAPI `Depends`

For request-level dependencies:

- authentication
- authorization
- request validation
- database/session dependencies
- reusable endpoint dependencies

Dependencies can be chained and reused.

### `dependency-injector`

Use for application composition:

- services
- repositories
- database clients
- external clients
- storage implementations
- infrastructure services

`src/container.py` is the composition root.

Never instantiate infrastructure dependencies inside business logic.

---

## 9. Async

Use `async def` for non-blocking I/O:

- async database operations
- HTTP APIs
- Redis
- async file operations
- message brokers

Never use blocking I/O inside `async def`.

Examples of blocking operations:

```text
requests
time.sleep()
blocking file I/O
synchronous database drivers
```

If a synchronous library is unavoidable, run it in a threadpool rather than blocking the event loop.

Use normal `def` when synchronous execution is appropriate.

Do not make everything async automatically.

CPU-heavy work should run outside request processing, using an appropriate worker/task system.

---

## 10. Database

Use:

```text
SQLAlchemy 2.0
AsyncSession
Alembic
```

when applicable.

Use connection pooling.

Avoid:

- N+1 queries
- unbounded queries
- creating database connections per request
- blocking database calls
- exposing ORM models as API contracts

`models.py` contains persistence/ORM models.

`repository.py` handles database access.

`service.py` handles business behavior.

### Migrations

Use sequential, zero-padded revision IDs (`001`, `002`, `003`, ...) instead of
Alembic's default random hex IDs, for readability and to match migration
ordering to the numbering convention already used in technical designs (e.g.
`migrations/001_create_files_table.sql`).

```bash
PYTHONPATH=src alembic revision --rev-id 003 -m "add index to orders"
```

See `docs/database-migrations.md` for the full migration workflow (running
Postgres locally, applying/rolling back migrations, autogenerate caveats).

---

## 11. Errors

Use domain-specific exceptions.

```text
Domain error
     ↓
FastAPI exception handler
     ↓
HTTP response
```

Do NOT raise `HTTPException` from services or repositories.

Use guard clauses:

```python
if order is None:
    raise OrderNotFound()
```

Avoid deeply nested conditionals.

Handle unexpected errors centrally and never expose internal implementation details.

---

## 12. Shared Technical Systems

Do not create a business domain for reusable technical functionality.

Use `src/shared/` for business-agnostic components:

```text
shared/
├── retry/
├── storage/
├── pagination/
├── logging/
└── ...
```

Examples:

- retry/backoff
- file storage
- S3 clients
- caching
- pagination
- logging
- metrics
- tracing
- generic HTTP clients

If functionality contains business rules, it belongs to a domain.

---

## 13. Configuration & Lifecycle

Use Pydantic Settings for configuration.

Never hardcode:

- passwords
- API keys
- tokens
- database credentials
- secrets

Use FastAPI `lifespan` for shared resource initialization and cleanup:

- database engines
- Redis
- HTTP clients
- other application resources

Do not scatter startup/shutdown logic across modules.

---

## 14. Background Work

Do not make users wait for non-essential work.

Use FastAPI `BackgroundTasks` only for short, non-critical in-process work.

Examples:

```text
send lightweight notification
write non-critical log
```

Use a real task queue for:

- long-running work
- CPU-heavy work
- retries
- scheduling
- rate limiting
- critical jobs that must survive worker failure

---

## 15. API Documentation

Use FastAPI/OpenAPI as part of the API contract.

Define:

- `response_model`
- `status_code`
- descriptions
- summaries
- response documentation where useful

For private APIs, disable or restrict Swagger/OpenAPI documentation in production according to the project's security requirements.

---

## 16. Testing

Organize tests by domain:

```text
tests/
├── users/
├── orders/
└── ...
```

Prioritize:

```text
unit tests        → business logic
integration tests → database/external systems
API tests         → HTTP behavior
```

Most business rules should be tested without starting the complete application.

Use dependency injection to replace infrastructure during tests.

---

## 17. Python Style

- Python 3.11+
- Type hints on all function signatures.
- Lowercase `snake_case` filenames.
- Descriptive variable names.
- Prefer `is_active`, `has_permission`, `should_retry`, etc.
- Prefer functions when no state is required.
- Use classes when they provide meaningful state, identity, or dependency management.
- Prefer guard clauses and early returns.
- Avoid unnecessary abstractions.
- Avoid generic `utils.py`, `helpers.py`, or `manager.py` unless genuinely cohesive.
- Follow configured Ruff/formatter/type-checker rules.
- Use RORO when it improves clarity.

The agent chooses functional vs class-based style based on the situation.

---

## 18. REST Conventions

Use standard HTTP semantics:

```text
GET    /users
GET    /users/{user_id}
POST   /users
PUT    /users/{user_id}
PATCH  /users/{user_id}
DELETE /users/{user_id}
```

Use:

- plural nouns for collections
- lowercase URLs
- logical resource hierarchy
- consistent naming
- correct HTTP status codes

Introduce API versions such as `/v1` only when breaking compatibility requires it.

---

## 19. Agent Decision Rule

Before creating code, classify the responsibility:

```text
Business logic?
→ owning domain/service

HTTP/API?
→ router/schemas/dependencies

Persistence?
→ repository/models

Reusable technical capability?
→ shared/

Configuration?
→ config.py

Dependency composition?
→ container.py
```

Before finishing a change:

```text
[ ] Correct domain owns the feature
[ ] No business logic in router
[ ] No business logic in repository
[ ] No HTTP dependency in business logic
[ ] Dependencies are injected
[ ] No blocking I/O inside async code
[ ] Pydantic used at API boundaries
[ ] Domain exceptions mapped at HTTP boundary
[ ] New business behavior is tested
[ ] No unnecessary abstraction introduced
```

**Primary rule: organize by business domain, keep business logic cohesive and framework-independent, and use dependency injection to isolate infrastructure.**
