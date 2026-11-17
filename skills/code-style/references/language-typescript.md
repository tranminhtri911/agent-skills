# TypeScript / JavaScript style

Frameworks: [React / Next.js](framework-react.md), [Vue / Nuxt](framework-vue.md), [Angular](framework-angular.md), [NestJS](framework-nestjs.md). Repository tooling (ESLint, Prettier, Biome, `tsconfig` strictness) wins over this page.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Variable, function, method, parameter, property | `lowerCamelCase` | `invoiceTotal`, `calculateInvoiceTotal` |
| Class, interface, type, enum, decorator | `UpperCamelCase` | `InvoiceService`, `PaymentStatus` |
| Enum member, global/module constant | `CONSTANT_CASE` | `MAX_RETRY_ATTEMPTS` |
| File | the repo's convention; otherwise `kebab-case.ts` | `invoice-service.ts` |
| Boolean | `is`/`has`/`can`/`should` | `isExpired` |

Interfaces are not prefixed with `I` and types are not suffixed with `Type` (Google TypeScript Style Guide). No `_` prefix for private members; use `private` or `#field`.

## Layout

- Braces on every `if/else/for/while`, the body on its own line — including one-statement bodies (this suite's default; the Google guides require blocks for multi-line control flow).
- `const` by default, `let` when reassigned, never `var`.
- Guard clauses first. Ternary only for a simple value; never nested.
- `===`/`!==` only.

```typescript
// Not this
if (!order) return null;
const total = items.filter(i => i.on).reduce((s, i) => s + i.p * i.q, 0);

// This
if (!order) {
  return null;
}
const billableItems = items.filter((item) => item.isBillable);
const totalMinor = billableItems.reduce((sum, item) => sum + item.priceMinor * item.quantity, 0);
```

## Arrow functions and chains

- Inline arrow functions for a one-expression callback (`map`, `filter`, `sort`). Longer logic, reuse or a name in a stack trace → a named function.
- Chains of more than two or three calls: one call per line, named intermediate values where meaning is not obvious.
- No `reduce` that builds complex objects; a loop is clearer.

## Static members and modules

- Constants and pure helpers are module exports, not classes full of `static` methods.
- `static` methods for named factories (`Money.fromMinor(...)`).
- Nothing that holds state, calls the network or reads the clock is static or module-global; inject it.

## Types

`strict` mode; explicit parameter and return types on exported functions; `unknown` + validation at boundaries instead of `any`; discriminated unions for states; `readonly` where data must not change.

## Sources

- [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html)
- [Google JavaScript Style Guide](https://google.github.io/styleguide/jsguide.html)
- [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript)
