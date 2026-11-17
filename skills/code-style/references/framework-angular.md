# Angular style

Builds on [TypeScript / JavaScript style](language-typescript.md). Angular's style guide changed across versions; the repository's existing naming (for example `.component.ts` suffixes) and lint rules win over the current guide.

## Names and files

| Element | Style | Example |
| --- | --- | --- |
| File | words separated by hyphens; the repo's suffix convention | `invoice-table.ts` or `invoice-table.component.ts` |
| Test file | same name + `.spec.ts` | `invoice-table.spec.ts` |
| Component / directive / service class | `UpperCamelCase` | `InvoiceTable`, `InvoiceApi` |
| Selector | project prefix + kebab-case | `app-invoice-table` |
| Event handler | named for what it does | `saveInvoice()`, not `handleClick()` |
| Observable | trailing `$` if the repo uses it | `invoices$` |

## Explicit over clever

- Prefer the `inject()` function over constructor parameter injection in new code when the project's Angular version and style use it; otherwise follow the existing constructor injection.
- Keep templates simple: logic in the component class or a pure pipe, not long expressions in the template.
- `protected` for members used only by the template; `readonly` for inputs, queries and injected services that must not change.
- Group code by feature area, one concept per file.

## Patterns by signal

- HTTP access reused by several components → a service in the feature (`InvoiceApi`), the Angular form of a repository/client.
- Shared state → signals or the project's store; component-local state stays in the component.

## Sources

- [Angular coding style guide](https://angular.dev/style-guide)
