# SwiftUI style

Builds on [Swift style](language-swift.md); the project's architecture (MVVM, TCA or plain views) and SwiftLint rules win.

## Names

| Element | Style | Example |
| --- | --- | --- |
| View | noun + `View` when it would clash with a model name, otherwise the noun | `InvoiceListView` |
| Observable model / view model | feature + `Model` or `ViewModel` per repo | `InvoiceListModel` |
| Action method | verb phrase | `markAsPaid()` |
| Binding / state property | describes the value | `isShowingFilters`, `selectedInvoiceID` |

## Data flow

- `@State` for view-local values, `@Binding` to share a value with a child, `@Observable` (or `ObservableObject` on older targets) for model data shared across views, environment for app-wide dependencies — the model-data tools Apple documents.
- Services (network, storage) are passed into models through initializers or the environment, not reached as singletons from views.

## Explicit over clever

- `body` stays short: extract subviews with descriptive names instead of deep nesting or long `if` chains.
- Long modifier chains: one modifier per line; a custom `ViewModifier` when the same chain repeats.
- Side effects in `.task`/`.onChange` with explicit dependencies, not in `body`.

## Patterns by signal

Data access reused by several screens → a repository/service type injected into models; a protocol in front of it only when tests or previews need a replacement.

## Sources

- [SwiftUI — Model data](https://developer.apple.com/documentation/swiftui/model-data)
- [Swift API Design Guidelines](https://www.swift.org/documentation/api-design-guidelines/)
