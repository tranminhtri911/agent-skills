# Dart style

Framework: [Flutter](framework-flutter.md). Repository tooling (`analysis_options.yaml`, `flutter_lints`/`lints`, `dart format`) wins over this page.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Class, enum, typedef, extension, mixin | `UpperCamelCase` | `InvoiceRepository` |
| File, package, directory, import prefix | `lowercase_with_underscores` | `invoice_repository.dart` |
| Variable, function, method, parameter, **constant** | `lowerCamelCase` | `calculateTotal`, `maxRetryAttempts` |
| Private | leading `_` | `_parseRow` |
| Boolean | `is`/`has`/`can` | `isExpired` |

Dart uses `lowerCamelCase` for constants, not `SCREAMING_CAPS` (Effective Dart). Acronyms longer than two letters are capitalised like words (`HttpClient`).

## Layout

- `dart format` decides formatting.
- Curly braces for all flow-control statements, body on its own line. Effective Dart allows a braceless one-line `if` without `else`; this suite's default is braces anyway unless the repository's lints say otherwise.
- Guard clauses first.

```dart
// Not this
if (invoice == null) return;

// This
if (invoice == null) {
  return;
}
```

## Closures and collections

- Arrow syntax (`=>`) for one-expression functions only.
- Collection `if`/`for` inside literals for simple cases; a loop for anything with more than one condition.
- Long `where/map/fold` chains: one call per line.

## Static members

`static const` for constants tied to a class, top-level functions for pure helpers, named/factory constructors (`Invoice.fromJson(...)`) for creation. Services, clients and clocks are injected (constructor, provider), not static singletons.

## Types

Sound null safety; `final` by default; explicit types on public APIs; immutable models (`final` fields, `copyWith`).

## Sources

- [Effective Dart: Style](https://dart.dev/effective-dart/style)
- [Effective Dart: Design](https://dart.dev/effective-dart/design)
