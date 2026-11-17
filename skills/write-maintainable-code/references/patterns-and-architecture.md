# Patterns and architecture: learn them from the source, add only for a named problem

The existing source is the specification of "how we build things here". A pattern is added because a concrete problem in this change needs it, never because a book recommends it. Most features need no new pattern at all: they need the project's existing ones applied consistently.

## 1. Learn what the source already uses (always first)

1. `DS inspect --feature <words>` → "Project conventions to reuse":
   - **patterns in use**: role suffixes counted in the source (`Repository ×12 in app/Repositories`, `Service ×20`, `FormRequest`, `Resource`, `Action`, `Policy`, `Job`, `selectors.py`, `services.py`…), with where they live and examples;
   - **pattern libraries/tools**: state-machine, DI, store, layer-rule and duplication tools found in the manifests or configs (`spatie/laravel-model-states`, `django-fsm`, `@tanstack/react-query`, `deptrac.yaml`, `.importlinter`…);
   - bases, shared modules, hooks, decorators, values and the reference module (CTX-009, CODE-011).
2. Open the reference module of the same kind and follow one request end to end: which layer validates, which authorizes, who owns the transaction, where queries live, how errors and responses are shaped, how side effects (mail, jobs, events) are triggered.
3. Read the dependency direction from real imports: `rg -n "^(from|import) " app/services | rg "views|http|request"` (Python), `rg -n "^use App\\\\Http" app/Services` (PHP), `rg -n "from ['\"].*/(pages|components)" src/api src/services` (TS). What the code never does is a rule too.
4. Write what you learned into `conventions_to_follow` (discover-codebase), e.g. `"layers: Controller → FormRequest → Action (app/Actions) → Eloquent; no Repository layer"`, `"frontend: pages call hooks in src/hooks, hooks call src/api/*Repository; no fetch in components"`.

If old and new styles coexist, follow the one used by the most recent modules near the change and say so in the report.

## 2. Use the project's pattern for each job

| Job in the change | Do what the source does | Only if the source has nothing for it |
| --- | --- | --- |
| Queries with domain meaning | the project's Repository / selector / QuerySet / scope | Django: custom QuerySet/Manager method; Laravel: model scope or a query class; no generic `BaseRepository<T>` over the ORM |
| Business rule used by several entry points | the project's Service / Action / UseCase | a plain function or small class in the feature's service module |
| Request validation and response shape | Serializer / FormRequest / API Resource / zod schema already used | the framework's standard one |
| Status with rules | the project's state library or transition function | one transition map + function: implement-backend `state-transitions.md` (BE-011) |
| External provider (payment, mail, storage) | the existing client/gateway/adapter | port + adapter + simulator (ARC-004) |
| Behaviour that varies by type, 3+ cases and growing | the project's handler map / polymorphism / enum method | dict of handlers or enum method; 2 stable cases stay `if/else` |
| Choosing an implementation by config | the existing factory/provider binding | a function or dict lookup; no abstract factory for one implementation |
| Building complex objects | factories already used (factory_boy, Laravel factories, fishery) | keyword args / dataclass / object literal; a Builder for test data with many variants, or when the language lacks named/default arguments and the object has many optional parts (code-style `references/patterns.md`) |
| Side effects after a write | the project's events/listeners, jobs, outbox | explicit call after commit (`transaction.on_commit`, `afterCommit()`); avoid hidden signals |
| Dependencies and wiring | the framework's DI (Laravel container, FastAPI `Depends`, ASP.NET DI) or plain parameters | pass dependencies as parameters; never add a DI container |
| Frontend server state / shared state | the project's query library, store, context, custom hooks | local state first; a new store library needs a design decision |
| Layering style (Clean/Hexagonal/DDD/MVC) | the project's | do not introduce a new architecture inside a feature; propose it separately (design-change) |

## 3. Over-engineering red flags (stop and simplify)

- An interface with one implementation and no simulator or test need.
- A layer or class that only forwards calls (`OrderService.get()` → `OrderRepository.get()` → `Order.objects.get()`).
- A generic base (`BaseService<T>`, `AbstractHandler`) written for one subclass; extract only at the third real case (rule of three).
- Options, hooks or extension points nobody asked for "for the future" (DES-002).
- Pattern names instead of domain names: `OrderManagerFactoryBuilder`.
- More new files/folders than responsibilities; a simple CRUD spread over 8 files.

Test for each new class/file/layer: "what would break or get harder if I inlined it?" If nothing, inline it.

## 4. Keep the boundaries the source has (ARC-007)

Typical rules learned from the source: domain/service code does not import HTTP/request/view modules; features call each other through their public module (service, `index.ts`), never internals; `shared/` imports no feature; components do not call `fetch`/`axios` directly when the project has an API layer; no import cycles (ARC-003).

Evidence, primary first:

1. The project's own boundary tool when configured: `lint-imports` (import-linter), `vendor/bin/deptrac analyse`, `depcruise` via the project's npm script, eslint `boundaries` / `no-restricted-imports` (runs with `native-checks` lint), NetArchTest/ArchUnit tests (run with the tests). Record with `DS run-tests --check-id arch.boundaries -- <command>` when it is not already part of lint or tests.
2. No tool configured: check the imports of every changed file by hand against the rules in `conventions_to_follow` and list them in the report. Proposing a boundary tool is a separate change (ask first).

## 5. New dependencies (DES-008)

Before adding a package: the framework, stdlib or an existing dependency does not already do it (two HTTP clients, two date libraries, two form libraries is a defect); license fits; actively maintained; transitive weight acceptable; known advisories checked with the project's audit tool if present (`npm audit`, `pip-audit`, `composer audit`). Add it with the project's package manager so the lockfile updates, and write the reason in the design or PR.

## 6. Duplication (CODE-012)

Before writing a helper, search for it: the function's verb and noun, the key expression (`rg -n "round\(.*tax"`), the shared modules listed by `inspect`. Two copies: note it; three: extract into the module that owns the rule (refactoring-workflow.md). If the project already runs a duplication tool (jscpd, pylint `duplicate-code`, phpcpd), run it on the changed paths.
