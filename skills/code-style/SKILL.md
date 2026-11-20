---
name: code-style
description: "Use when writing, modifying or reviewing source code in any language or framework — naming variables, functions, classes, files and constants, laying out if/else and loops, lambdas, comprehensions and chains, static members, or choosing repository, builder, interface, abstract class, strategy or factory. Triggers (vi): đặt tên biến/hàm/class, coding style, convention, code dễ đọc, tường minh, if một dòng, lambda, static, interface, abstract, repository pattern, builder pattern. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.5"
  suite: devskills
---

# Code Style

Code is written for the next developer, whatever their level: a junior must understand it on the first read and a senior must find the structure the problem calls for. **Explicit beats short.** Fewer characters is never the goal; fewer surprises is.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Detect the stack automatically

The references to read come from the source, not from guessing:

- With the Claude Code skill gate installed, the first edit of each language in each project root adds a `CODE STYLE (auto-detected…)` note naming the files to read and the repository's style tools. Read them before writing that file.
- Otherwise run `DS style` once per task (every project root of a monorepo: languages, frameworks, style tools, references) or `DS style --path <file>` for one file. `DS inspect` shows the same per root.

Detection reads manifests and file extensions only (Django/FastAPI from Python dependencies, React/Next/Vue/Angular/NestJS from `package.json`, Spring from Gradle/Maven, ASP.NET Core from `.csproj`, Laravel from `composer.json`, Flutter from `pubspec.yaml`, Android/Compose from Gradle, SwiftUI from `import SwiftUI`); it never runs project code.

## Which rule wins (STYLE-001)

1. The repository: its formatter/linter config (`.editorconfig`, `pyproject.toml [tool.ruff]`, `.eslintrc`, `.prettierrc`, `phpcs.xml`, `detekt.yml`, `analysis_options.yaml`, `.swiftlint.yml`…) and the style of the surrounding code (CTX-009 in write-maintainable-code).
2. The framework reference below, then the language reference.
3. The defaults in this skill.

Never reformat code you did not otherwise change; style-only diffs hide behavior changes (CODE-009). When the repository's tooling enforces a style that differs from a default here (for example a formatter that keeps one-line `if`), the tooling wins.

## Rules

- **STYLE-002 Names say what, in the language's casing.** Full words (`customer_count`, not `cc`/`custCnt`); booleans read as statements (`is_active`, `has_access`, `can_retry`); units in names (`timeout_seconds`, `price_minor`); functions are verb + object (`calculate_invoice_total`); length grows with scope (a 3-line loop may use `index`, a module-level value may not use `x`). Casing per language: the language reference.
- **STYLE-003 One statement per line; control-flow bodies on their own line.** In languages with braces, every `if/else/for/while` body uses braces on its own line, even for one statement; in Python the body goes on the next line. Guard clauses at the top of a function for early exits. No nested ternaries; a ternary only for a simple value choice.
- **STYLE-004 Lambdas, comprehensions and chains stay trivial.** A lambda is fine for a one-expression key/predicate passed inline (`sorted(users, key=lambda user: user.last_name)`). More than one expression, a reused lambda, or a lambda assigned to a variable becomes a named function. One `for` and at most one condition per comprehension; otherwise write the loop. Long call chains: one call per line, and a named intermediate variable where a step's meaning is not obvious.
- **STYLE-005 `static` only for what has no state and needs no replacement.** Use it for constants, pure helpers and named factory methods. Not for anything holding state, doing I/O, or that tests must replace (clocks, HTTP, DB, file system) — inject those instead. Language rules differ (Python prefers module functions over `@staticmethod`, Kotlin has no `static`): see the language reference.
- **STYLE-006 Patterns by signal, not by fashion.** Repository, builder, interface, abstract class, strategy and factory are applied when their signal is present in this change, and in the form the repository already uses: [patterns.md](references/patterns.md). The repository's existing pattern always comes first (DES-007).
- **STYLE-007 Explicit types and contracts at boundaries.** Public functions, exported members and API/DB boundaries declare parameter and return types where the language supports them; no `any`/`dynamic`/unchecked casts without validation (CODE-002).

```python
# Short but hard to scan
def active_emails(users): return [u.email for u in users if u.active and not u.deleted and u.email]

# Explicit
def collect_active_user_emails(users: list[User]) -> list[str]:
    """Emails of users who can receive messages: active, not deleted, with an address."""
    active_emails = []
    for user in users:
        if not user.is_active or user.is_deleted:
            continue
        if user.email:
            active_emails.append(user.email)
    return active_emails
```

## Language and framework references

Read the reference for the language you are editing, plus the framework reference when the file belongs to one. Each framework reference builds on its language reference.

| Language | Reference | Frameworks |
| --- | --- | --- |
| Python | [language-python.md](references/language-python.md) | [Django](references/framework-django.md), [FastAPI](references/framework-fastapi.md) |
| TypeScript / JavaScript | [language-typescript.md](references/language-typescript.md) | [React / Next.js](references/framework-react.md), [Vue / Nuxt](references/framework-vue.md), [Angular](references/framework-angular.md), [NestJS](references/framework-nestjs.md) |
| Java | [language-java.md](references/language-java.md) | [Spring / Spring Boot](references/framework-spring.md) |
| Kotlin | [language-kotlin.md](references/language-kotlin.md) | [Android / Jetpack Compose](references/framework-android-compose.md) |
| C# | [language-csharp.md](references/language-csharp.md) | [ASP.NET Core](references/framework-aspnet-core.md) |
| PHP | [language-php.md](references/language-php.md) | [Laravel](references/framework-laravel.md) |
| Go | [language-go.md](references/language-go.md) | — |
| Swift | [language-swift.md](references/language-swift.md) | [SwiftUI](references/framework-swiftui.md) |
| Dart | [language-dart.md](references/language-dart.md) | [Flutter](references/framework-flutter.md) |
| SQL | [language-sql.md](references/language-sql.md) | — |

A language or framework not listed: follow its official style guide and the repository, with the rules above as defaults.

## Hand-offs

- Comments, docstrings, error handling, no hard-coded domain values, changing existing code safely → **REQUIRED:** write-maintainable-code (load both for every code change, new or existing).
- Layers, modules and folders of a backend or frontend feature → implement-backend, implement-frontend.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `if (!user) return null;` on one line | Braces and the return on its own line (STYLE-003) |
| `const fn = (a) => a.items.filter(i => i.on).map(i => i.v * r)` | Named function, named intermediate (`activeItems`), descriptive parameter names (STYLE-004) |
| `x`, `tmp`, `data2`, `handleStuff`, `mgr` | Name the domain meaning (STYLE-002) |
| `static` cache or clock inside a service | Inject it; static only for pure helpers/constants (STYLE-005) |
| `IUserService` + one `UserService`, nothing replaces it | Concrete class until a second implementation or a test seam exists (STYLE-006) |
| Builder for a 3-field object in a language with named arguments | Named/keyword arguments or a data class (STYLE-006) |
| Reformatting a whole file while fixing one line | Format only what you changed (STYLE-001) |
