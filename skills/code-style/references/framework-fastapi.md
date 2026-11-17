# FastAPI style

Builds on [Python style](language-python.md); the project's own package layout wins.

## Structure

- One `APIRouter` per feature module (`invoices/router.py`), included by the application with a `prefix` and `tags` (FastAPI "Bigger Applications").
- Request/response models as Pydantic classes named for their role: `InvoiceCreateRequest`, `InvoiceResponse` — never return ORM objects directly.
- Path operation functions are named for the action (`create_invoice`, `list_overdue_invoices`) and stay thin: parse → call the service → map the response.

## Dependencies (dependency injection)

- Sessions, the current user, settings and clients come in through `Depends(...)` functions (`get_db_session`, `get_current_user`), not module-level globals, so tests can override them with `app.dependency_overrides`.
- Dependency functions are named `get_<thing>`; their return type is annotated.

## Patterns by signal

- Database access reused by several routes → a repository or query module in the feature (`invoices/repository.py`), as the project already does.
- Business rules spanning several steps → a service function or class in the feature, independent of FastAPI types so it can be tested without HTTP.

## Explicit over clever

- `async def` only when every call inside is async; blocking clients in `def` routes or `run_in_threadpool`.
- Status codes and error bodies stated explicitly (`status_code=status.HTTP_201_CREATED`, `HTTPException` with the project's error format).

## Sources

- [FastAPI — Bigger Applications (multiple files)](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [FastAPI — Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
