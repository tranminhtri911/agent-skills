# C# style

Framework: [ASP.NET Core](framework-aspnet-core.md). Repository tooling (`.editorconfig`, Roslyn analyzers, StyleCop, `dotnet format`) wins over this page.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Namespace, class, record, struct, enum, method, property, event, public field | `PascalCase` | `InvoiceService.CalculateTotal` |
| Interface | `I` + `PascalCase` | `IPaymentGateway` |
| Local, parameter | `camelCase` | `invoiceTotal` |
| Private instance field | `_camelCase` | `_paymentGateway` |
| Constant | `PascalCase` | `MaxRetryAttempts` |
| Async method | ends in `Async` | `GetInvoiceAsync` |
| Boolean | `Is`/`Has`/`Can` | `IsExpired` |

## Layout

- Allman braces (each brace on its own line); braces on every `if/else/for/foreach/while`, body on its own line.
- `var` only when the type is obvious from the right-hand side (`var invoice = new Invoice()`); otherwise write the type.
- Guard clauses first (`ArgumentNullException.ThrowIfNull(order)`); no nested `?:`.

```csharp
// Not this
if (order is null) return Result.NotFound();

// This
if (order is null)
{
    return Result.NotFound();
}
```

## Lambdas and LINQ

- LINQ improves readability for filtering and projection; one clause or method call per line.
- A lambda with more than one expression or reused in several places becomes a private method.
- No query that mixes side effects into `Select`.

## Static members

Static classes sparingly, as supporting helpers (extension methods, pure functions, constants), not for business services. Anything with state, I/O or time (`DateTime.Now` → `TimeProvider`) is injected through the DI container.

## Types and contracts

Nullable reference types enabled; `record` for immutable data; `decimal` for money; `async`/`await` all the way (no `.Result`/`.Wait()`); `CancellationToken` passed through I/O methods.

## Sources

- [.NET identifier naming rules and conventions](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/coding-style/identifier-names)
- [Common C# code conventions](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/coding-style/coding-conventions)
- [.NET Framework design guidelines — naming](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/naming-guidelines), [static class design](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/static-class)
- [Asynchronous programming with async and await](https://learn.microsoft.com/en-us/dotnet/csharp/asynchronous-programming/)
