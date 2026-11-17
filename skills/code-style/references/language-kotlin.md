# Kotlin style

Framework: [Android / Jetpack Compose](framework-android-compose.md). Repository tooling (ktlint, detekt, `.editorconfig`, Android Studio code style) wins over this page.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Package | lowercase, no underscores | `com.acme.billing` |
| Class, interface, object, enum, typealias | `UpperCamelCase` | `InvoiceRepository` |
| Function, property, local, parameter | `lowerCamelCase` | `calculateInvoiceTotal` |
| `const val`, top-level/object immutable values | `SCREAMING_SNAKE_CASE` | `MAX_RETRY_ATTEMPTS` |
| Backing property | `_` + name | `private val _uiState` / `val uiState` |
| Boolean | `is`/`has`/`can` | `isExpired` |

## Layout

- Braces and a body on its own line for multi-statement and side-effect branches. `if` used as an expression for a simple value (`val label = if (isPaid) "Paid" else "Due"`) is idiomatic.
- `when` instead of `if/else if` chains with three or more branches.
- An expression body (`fun total() = items.sumOf { it.priceMinor }`) only when the expression is short and obvious (Kotlin coding conventions); otherwise a block body with `return`.

## Lambdas and scope functions

- `it` only in a one-line lambda; name the parameter otherwise (`orders.filter { order -> order.isPaid }`).
- Scope functions (`let`, `run`, `apply`, `also`, `with`) at most one level deep; nested scope functions become local variables.
- Long collection chains: one call per line.

## Static members

Kotlin has no `static`: use top-level functions and constants for pure helpers, `companion object` for factories (`Invoice.fromRow(row)`) and constants tied to a class, `object` only for true stateless singletons. Anything holding state or doing I/O is injected (Hilt/Koin/constructor), not an `object`.

## Types and contracts

Non-null by default; `!!` only with a comment stating why it cannot be null; `data class` for values; `sealed interface` for states and results; explicit return types on public functions.

## Sources

- [Kotlin coding conventions](https://kotlinlang.org/docs/coding-conventions.html)
- [Android Kotlin style guide](https://developer.android.com/kotlin/style-guide)
