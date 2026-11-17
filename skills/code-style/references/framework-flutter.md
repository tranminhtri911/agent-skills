# Flutter style

Builds on [Dart style](language-dart.md); the project's state-management library and `analysis_options.yaml` win.

## Names and files

| Element | Style | Example |
| --- | --- | --- |
| Widget | `UpperCamelCase` noun | `InvoiceList` in `invoice_list.dart` |
| Screen / page | feature + `Screen`/`Page` per repo | `InvoiceListScreen` |
| View model / controller / notifier | feature + role per repo | `InvoiceListViewModel` |
| Repository / service | `<Domain>Repository` / `<External>Service` | `InvoiceRepository`, `PaymentApiService` |
| Callback parameter | `on<Event>` | `onInvoiceTap` |

## Architecture by the platform guide

Flutter's app architecture guide separates a UI layer (views + view models) from a data layer (repositories as the source of truth, services wrapping external APIs). Follow that split when the project has no other one; keep the project's existing structure (Bloc, Riverpod, Provider) when it does.

## Explicit over clever

- `build` stays short and free of side effects: extract widgets (classes, not helper methods returning widgets) with descriptive names.
- `const` constructors wherever possible.
- No business logic or network calls in widgets; they call the view model.
- Avoid abbreviations in names, including in private members (Flutter repository style guide).

## Patterns by signal

- Data reused across screens → a repository; an abstract class in front of it when tests or fakes need to replace it.
- Platform or third-party APIs → a service class injected into repositories.

## Sources

- [Flutter — App architecture guide](https://docs.flutter.dev/app-architecture/guide)
- [Flutter repository style guide](https://github.com/flutter/flutter/blob/main/docs/contributing/Style-guide-for-Flutter-repo.md)
- [Effective Dart: Style](https://dart.dev/effective-dart/style)
