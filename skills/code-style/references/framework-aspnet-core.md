# ASP.NET Core style

Builds on [C# style](language-csharp.md); the project's solution layout (controllers vs minimal APIs, Clean Architecture or not) and analyzers win.

## Names and structure

| Element | Style | Example |
| --- | --- | --- |
| Controller | plural or domain noun + `Controller` per repo | `InvoicesController` |
| Minimal API endpoint group | `Map<Domain>Endpoints` extension | `app.MapInvoiceEndpoints()` |
| Service interface / class | `I<Domain>Service` / `<Domain>Service` | `IInvoiceService` |
| Request / response | role suffix | `CreateInvoiceRequest`, `InvoiceResponse` |
| Options class | `<Topic>Options` bound from configuration | `PaymentOptions` |

## Dependency injection

- Register services in the container with the right lifetime (`AddScoped` for per-request work using `DbContext`, `AddSingleton` only for thread-safe stateless services, `AddTransient` for lightweight stateless ones).
- Constructor injection; no `IServiceProvider` service locator in business code; configuration through `IOptions<T>`.

## Patterns by signal

- EF Core `DbContext` is already a unit of work with `DbSet` repositories: add a repository layer only if the project has one or the same query is reused across services.
- Interchangeable providers → an interface with several registrations (keyed services or a factory) instead of `if` on provider names.

## Explicit over clever

- Controllers / endpoints: validate → call the service → map the result to `IActionResult`/`Results.*` with explicit status codes.
- `async` end to end with `CancellationToken` from the request.

## Sources

- [Dependency injection in ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/dependency-injection)
- [.NET identifier naming rules and conventions](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/coding-style/identifier-names)
