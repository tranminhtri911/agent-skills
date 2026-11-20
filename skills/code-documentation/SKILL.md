---
name: code-documentation
description: "Use when documenting new code that needs explanation or explicitly adding code comments or docstrings. Triggers (vi): thêm comment, viết docstring, bổ sung chú thích, ghi chú cho hàm, tài liệu code."
metadata:
  version: "1.0.6"
  suite: devskills
---

# Code Documentation

Comments make code easier to understand, review, debug and maintain. They explain **why** something exists, **what** purpose it serves, **what** behavior or result matters and **what** limits or side effects exist. The goal is not the most comments; it is accurate, concise and consistent ones.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs

- Base comment rules and per-language templates → write-maintainable-code (DOC-001…006). It also covers maintenance of existing comments.
- Naming and layout → code-style. Endpoint contracts → design-api; model constraints → change-database; jobs → implement-backend and design-reliability. A comment never replaces the check those skills require.

## General rules (DOC-007)

- Write comments in simple, clear English, unless the repository writes them in another language (DOC-006).
- Keep comments short, accurate and meaningful; explain purpose, behavior and reasoning.
- Do not repeat what the code already says.
- **Document only behavior verified from the implementation.** Never invent behavior, constraints, exceptions, status codes, schedules, retry counts, delivery guarantees, or security/performance guarantees. Unknown → leave it out or ask.
- Include an example only when it improves understanding.
- Prefer maintainability over comment quantity.

## When to apply (DOC-008)

- Apply DOC-010 to new declarations and non-obvious new logic, including additions within an existing file. Skip trivial methods and obvious logic.
- When the user explicitly asks to add comments or docstrings, apply this skill to the requested code, including existing code. Keep the comments within the requested scope.
- In mixed tasks, limit this skill to the additions that need documentation and comments the user requested. Use write-maintainable-code for routine changes to existing code (DOC-003).
- Never change business logic, formatting or architecture for documentation purposes (CODE-009).

## Which convention wins (DOC-009)

1. Explicit user instructions.
2. The repository's existing documentation conventions.
3. Language and framework standards.
4. This skill.

Use the `Target:` block format only when it fits the project's conventions; never introduce a conflicting documentation style into an existing codebase.

## What to document per kind of code (DOC-010)

| Kind | Document | Skip |
| --- | --- | --- |
| Class / interface | Primary purpose; responsibilities when not obvious | Repeating the name; simple DTOs whose fields say it all |
| Method / function | Purpose, parameters needing explanation, meaningful return (null/false/empty cases), important exceptions, side effects | Trivial getters/setters and obvious helpers |
| Complex logic | **Why**: business rule, unusual algorithm, workaround, technical decision — next to the logic | Translating code into English |
| Constant / config | Meaning, **unit**, limits, non-obvious defaults | Self-explanatory constants |
| Database / model | Purpose, important fields, relationships, constraints verified from schema/code, business meaning of null, soft vs hard delete | Repeating column names |
| API endpoint | Purpose, method + path, important request parts, response, status codes verified against code/framework, auth requirements | Duplicating existing OpenAPI docs |
| Background job / event | Trigger, result, retry policy, side effects, idempotency, failure handling — all as configured in code | Invented schedules or retry counts |
| Security / performance | The decision and the reason (parameterized query, batching, resource limits, trade-offs) | Standard framework behavior; unproven guarantees |

Examples and the full rules for each kind: [categories.md](references/categories.md).

## Language-native syntax (DOC-011)

| Language | Doc format |
| --- | --- |
| TypeScript / JavaScript | JSDoc / TSDoc |
| PHP | PHPDoc |
| C# | XML documentation (`///`) |
| Python | Docstrings (`#` for inline comments) |
| Java / Kotlin | Javadoc / KDoc |
| Go | GoDoc (`//`, starts with the name) |
| Other | The language's native convention |

Use the language's own syntax and tags; never force JSDoc into another language. Adapt the `Target:` / `@param` / `@returns` / `@throws` parts to the native equivalents (`Args:`/`Returns:`/`Raises:`, `<param>`/`<returns>`/`<exception>`). Prefer framework-supported conventions (OpenAPI decorators, Django model `help_text`) where the project uses them. Per-language templates: write-maintainable-code, its `references/comment-templates.md`.

## Workflow

1. Identify new code that may need documentation and any code the user explicitly asked to document (DOC-008).
2. Read the implementation and its existing comments; for APIs, models and jobs also the route/framework config, schema/migrations and scheduler/queue config they depend on.
3. Decide whether documentation is needed (DOC-008) and which kind applies (DOC-010).
4. Follow the project's and language's conventions (DOC-009, DOC-011).
5. Write concise, accurate comments.
6. Verify every statement against the final implementation (DOC-007).
7. Keep documentation changes within the task scope.

`DS check-code` flags public functions without docs, invalid comment syntax and TODOs without an owner; treat its findings as signals, not as a demand to document trivial code.

## Quality checklist before handover (DOC-012)

- [ ] New important classes and methods have meaningful documentation where needed.
- [ ] Parameters and return values are accurately described.
- [ ] Important errors and edge cases are documented.
- [ ] Complex logic explains WHY, not just WHAT.
- [ ] Database constraints match the schema.
- [ ] API documentation matches actual behavior and status codes.
- [ ] Job triggers and retry behavior match the configuration.
- [ ] Security and performance comments are meaningful and backed by evidence.
- [ ] No redundant or obvious comments were introduced.
- [ ] New documentation covers only in-scope additions and code the user explicitly asked to document.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `@throws ConflictError` the code never throws | Document only what the implementation does (DOC-007) |
| `// Retries 3 times` while the queue config says 5, or no retry exists | Read the job/queue config; state what it does or leave it out |
| `Errors: 404` on an endpoint whose framework returns 422 for that case | Verify status codes against the handler and framework |
| `Target:` blocks added to a codebase that uses one-line JSDoc summaries | Follow the repository's style (DOC-009) |
| `// increment i` / `// loop over users` | Delete; explain a business reason or nothing |
| JSDoc `@param` tags in a Python docstring | Native `Args:` / `Returns:` / `Raises:` (DOC-011) |
| Unrequested doc comments added to an existing method during a bugfix | Follow DOC-003 for existing comments. |
| Unit missing on `TIMEOUT = 30000` | `Unit: milliseconds.` or a unit in the name (`timeout_ms`) |
