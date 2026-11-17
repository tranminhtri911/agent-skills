# NestJS style

Builds on [TypeScript / JavaScript style](language-typescript.md); the project's module layout and lint rules win.

## Names and files

| Element | Style | Example |
| --- | --- | --- |
| Feature folder | kebab-case domain noun | `invoices/` |
| Module / controller / service | `<Domain>Module`, `<Domain>Controller`, `<Domain>Service` in `<domain>.module.ts` etc. | `InvoicesController` in `invoices.controller.ts` |
| DTO | role + `Dto` | `CreateInvoiceDto`, `InvoiceResponseDto` |
| Provider token | `UPPER_SNAKE_CASE` constant | `PAYMENT_GATEWAY` |

## Structure

- One feature module per domain area; it exports only the providers other modules need.
- Controllers stay thin: validate the DTO (class-validator/pipes) → call the service → map the response.
- Dependencies come in through constructor injection of providers; external systems (payment, mail, storage) behind an injection token so tests can replace them.

## Patterns by signal

- Data access reused by several services → a repository provider (TypeORM/MikroORM repository or the project's own), not queries in controllers.
- Several interchangeable providers (payment gateways, exporters) → an interface + injection token, chosen in the module's provider configuration.

## Explicit over clever

- No business logic in decorators, guards or interceptors beyond their concern (auth, logging, mapping).
- Async methods return typed `Promise<T>`; errors use the project's exception filters and error format.

## Sources

- [NestJS — Modules](https://docs.nestjs.com/modules)
