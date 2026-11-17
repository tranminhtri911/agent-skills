# Java style

Framework: [Spring / Spring Boot](framework-spring.md). Repository tooling (Checkstyle, Spotless, google-java-format, PMD, `.editorconfig`) wins over this page.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Package | all lowercase, no underscores | `com.acme.billing.invoice` |
| Class, interface, enum, record, annotation | `UpperCamelCase` | `InvoiceService`, `PaymentStatus` |
| Method, field, local, parameter | `lowerCamelCase` | `calculateInvoiceTotal` |
| Constant (`static final`, deeply immutable) | `CONSTANT_CASE` | `MAX_RETRY_ATTEMPTS` |
| Test class | class under test + `Test` | `InvoiceServiceTest` |
| Boolean method | `is`/`has`/`can` | `isExpired()` |

## Layout

- Braces are always used with `if`, `else`, `for`, `do` and `while`, even when the body is empty or a single statement (Google Java Style Guide 4.1.1). Body on its own line.
- One variable per declaration; one statement per line.
- Guard clauses first; no nested ternaries.

```java
// Not this
if (invoice == null) return BigDecimal.ZERO;

// This
if (invoice == null) {
    return BigDecimal.ZERO;
}
```

## Lambdas and streams

- A lambda for a one-expression function argument; anything longer becomes a private method used through a method reference (`this::isBillable`).
- Streams: one operation per line; a plain loop when the stream needs side effects, checked exceptions or several collectors.

## Static members

- `static final` constants and pure utility methods in a `final` class with a private constructor.
- Static factory methods with intention-revealing names (`Money.ofMinor(...)`, `List.of(...)`).
- No static mutable state, no static access to clocks, HTTP or repositories in business code — inject them (Spring beans, constructor parameters).

## Types and contracts

Records for immutable data; `Optional` as a return type for "may be absent", not for fields or parameters; `BigDecimal` or minor units for money; checked vs unchecked exceptions per the repository's convention.

## Sources

- [Google Java Style Guide](https://google.github.io/styleguide/javaguide.html)
