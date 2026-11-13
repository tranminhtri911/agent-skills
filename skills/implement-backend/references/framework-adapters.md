# Framework adapters: keep the framework's way of doing things

Detect the framework and version from manifests (`ds.py inspect`) and read the docs for that version before applying details.

| Stack | Keep | Avoid |
| --- | --- | --- |
| FastAPI | `APIRouter` per feature, `Depends` for sessions/clients, `lifespan` for engine/client setup, Pydantic models at the boundary, `async def` only with async drivers | Global `Session()`, blocking I/O (`requests`, `time.sleep`, sync DB) inside `async def` — use `def` routes or `asyncio.to_thread` |
| Django / DRF | Apps per feature, ORM querysets, serializers with explicit `fields`, permissions classes, `transaction.atomic`, `select_related/prefetch_related` | Generic repository wrappers around every ORM call, `fields = "__all__"`, logic in signals that hides side effects |
| Flask | Blueprints + application factory, extensions initialised once, `g`/request-scoped sessions | Module-level DB sessions, business logic in view functions |
| NestJS | Modules/providers/controllers, DTO + `ValidationPipe` (whitelist, forbidNonWhitelisted), interceptors for cross-cutting concerns | Singleton services holding per-request state |
| Express / Fastify | Router per feature, schema validation (zod/ajv), error middleware, `helmet`, rate limiter on auth routes | `res.send(req.query.x)`, unhandled promise rejections, `req.body` straight into models |
| Laravel | Routes → FormRequest validation → controller → service/action when logic grows; Eloquent with `$fillable`; `DB::transaction`; queues with retries/backoff; `throttle` middleware | `$request->all()` into `create()`, `DB::raw` with interpolated input, logic in Blade |
| Spring Boot | `@Service` use cases with `@Transactional` on public methods, `@Valid` DTOs, `@ControllerAdvice` errors, HikariCP pool settings | `@Transactional` on private methods (proxy ignores it), entities returned directly as JSON |
| ASP.NET Core | DI lifetimes (DbContext scoped), `IHttpClientFactory`, `CancellationToken` through async calls, ProblemDetails | `new HttpClient()` per call, `.Result`/`.Wait()` on tasks, singleton holding a DbContext |
| Go (net/http, Gin, Echo) | `context.Context` deadlines, `http.Client{Timeout: …}`, worker pools/semaphores, `database/sql` pool settings | Default `http.Get`, goroutine per item without a limit, `defer` inside long loops |

## Transaction ownership examples

```python
# FastAPI + SQLAlchemy 2.x: the use case owns the unit of work.
def create_order(session: Session, command: CreateOrder) -> Order:
    with session.begin():  # commits on success, rolls back on any exception
        order = orders.add(session, command)
        inventory.reserve(session, order.lines)  # conditional UPDATE, raises when short
        outbox.enqueue(session, "order.created", order.id)
    return order
```

```php
// Laravel: DB::transaction rolls back automatically when the closure throws.
$order = DB::transaction(function () use ($data) {
    $order = Order::create($data->validatedOrder());
    $this->inventory->reserve($order);           // conditional update, throws on shortage
    OutboxMessage::create(['type' => 'order.created', 'payload' => ['id' => $order->id]]);
    return $order;
});
```
