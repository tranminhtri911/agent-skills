# Learning the project's base (CTX-009)

Goal: before writing anything new, know what the project already provides and how a finished module of the same kind is built. New code should look like it was written by the team that wrote the reference module.

## Procedure

1. Run `DS inspect --feature <words>` and read "Project conventions to reuse" in `context-map.md`:
   - **base** lines: project-owned bases first (with `defined in`), then framework bases with their count.
   - **shared modules**: `core/`, `common/`, `services/`, `hooks/`, `utils/`.
   - **custom hooks** and **decorators**: the house rules for auth, validation, error handling, data fetching.
   - **patterns in use** and **pattern libraries/tools**: the source's own roles (Repository, Service, Action, FormRequest, `selectors.py`) and tools (state machine, layer rules, store); follow them instead of a textbook architecture (DES-007).
   - **values / key constants**: enums, choices, `as const` objects and `STATUS_*` groups to use instead of literals (CODE-011).
   - **reference file/folder**: the closest finished module of the same kind.
2. Open each project-owned base and the reference module. Read them in full, not just the signatures. Follow one request end to end and read the real imports between layers (`rg -n "^(from|import) " app/services`), which tell the dependency direction to keep (ARC-007).
3. Write `conventions_to_follow` in the context map, for example:
   ```json
   ["reference: app/Http/Controllers/BankInfoController.php + its FormRequest/Resource/test",
    "errors: raise subclasses of core/error/error.py:BaseError; the handler maps them to {code, message}",
    "auth: @ApiDecorators.require_authentication + @ApiDecorators.validate_keys on every view",
    "frontend data: extend BaseRepository + BaseRequest; read state through useAppContext",
    "layers: Controller -> FormRequest -> app/Services/*; no Repository layer; enums in app/Enums",
    "values: BookingStatus/Facility/DiscountType in app/Enums (never 'confirmed'/'sbf'/'percent' literals); labels via enum label()"]
   ```
4. When the project has no written conventions and you learned non-obvious ones, propose (ask first) a short `docs/conventions.md` or a section in `CLAUDE.md`, so the next task starts from it. If `.knowledge/` exists, rebuild it afterwards.

## What to look for, per stack

| Area | Django / DRF | Laravel | React / TypeScript | .NET (EF6 / ASP.NET) |
| --- | --- | --- | --- | --- |
| Base data model | abstract `BaseModel` (timestamps, soft delete, tenant), managers/querysets | base `Model`, traits (`SoftDeletes`, `HasTenant`), scopes | types/interfaces for API payloads | base entity, `DbContext` conventions |
| Entry point | `@api_view` or `ViewSet` base, URL style, versioning | base `Controller`, route files, resource controllers | router config, page/screen folders | base `ApiController`/`Controller`, attribute routes |
| Validation | serializer base, custom validators, house decorators | `FormRequest` classes, rule objects | form library (react-hook-form, Formik), schema (zod, yup) | model attributes, FluentValidation |
| Auth/permission | permission classes, decorators, tenant filters | policies, gates, middleware | route guards, auth context | `[Authorize]` filters, custom attributes |
| Errors | custom exception base + handler, error envelope | exception handler, `abort()` style, API resources for errors | error boundary, toast/alert hook | exception filter, result wrapper |
| Data access | service/repository layer location, `transaction.atomic` usage | services, repositories, `DB::transaction` usage | API client/repository layer, query hooks and keys | repository/unit of work, `TransactionScope` |
| Responses | serializer/response helper, pagination class | API Resources, paginator shape | response mappers, loading/error components | DTOs, AutoMapper profiles |
| Background work | Celery tasks/management commands base | jobs, queues, scheduler | polling hooks, websockets | WebJobs, Functions, Hangfire |
| Layering / patterns | views → `services.py`/`selectors.py`, QuerySet methods, `import-linter` contracts | Controller → FormRequest → Service/Action, scopes, `deptrac.yaml` | page → hook → API/repository layer, store, eslint boundaries | Controller → service/repository, NetArchTest |
| Domain values | `TextChoices`/`IntegerChoices`, `Enum`, `*_CHOICES`, settings | backed `enum` + model `casts`, `config/*.php`, `lang/` | `enum`, `as const` objects, generated API types, i18n | `enum`, `const` classes, `appsettings.json`, resources |
| Tests | test base/factories, fixtures, mock style | `TestCase`, factories, seeders | test utils, render helpers, MSW handlers | test base, fakes |

## Rules

- Extend the existing base or helper; add the missing capability there once, not a parallel copy.
- Use the existing enum/constant/config value instead of a literal; a missing one is added where the project keeps them (CODE-011).
- Consistency with the reference module beats a "better" pattern from elsewhere. Propose improvements separately (design-change), not inside a feature diff.
- The project's vocabulary wins (`*Repository` vs `*Repo`, `*Request` vs `*Dto`, `get_` vs `fetch_`).
- A new base, library or pattern needs a stated reason in the design: nothing existing fits, and why.
- If two conflicting conventions exist (old and new style), follow the one used by the most recent modules near your change and say so in the report.
