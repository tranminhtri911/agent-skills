# Swift style

Framework: [SwiftUI](framework-swiftui.md). Repository tooling (SwiftLint, swift-format) wins over this page.

## Names

Clarity at the point of use is the most important goal; clarity is more important than brevity (Swift API Design Guidelines).

| Element | Style | Example |
| --- | --- | --- |
| Type, protocol, enum | `UpperCamelCase` | `InvoiceRepository` |
| Function, property, variable, enum case | `lowerCamelCase` | `calculateTotal(for:)`, `.paid` |
| Boolean | reads as an assertion | `isEmpty`, `hasAccess`, `canRetry` |
| Protocol describing what something is | noun | `Collection` |
| Protocol describing a capability | `-able`, `-ible`, `-ing` | `Equatable`, `ProgressReporting` |
| Mutating / non-mutating pair | verb / past participle | `sort()` / `sorted()` |

Argument labels make call sites read as phrases (`move(from: start, to: end)`); omit needless words.

## Layout

- Braces are mandatory; put the body on its own line.
- `guard` for early exits at the top of a function; the main path stays unindented.

```swift
guard let invoice = invoices.first(where: { $0.id == invoiceID }) else {
    return nil
}
```

## Closures

- `$0` only in one-line closures; name the parameters otherwise.
- Trailing closure syntax for the last closure argument; not when a call takes several closures.
- `[weak self]` in escaping closures that capture `self` and may outlive it.

## Static members

`static let` for constants and `static func` for named factories; no `static var` holding mutable state that tests must reset. Services are passed in (initializer injection, environment), not reached through singletons.

## Types

Value types (`struct`, `enum`) by default; `final class` when reference semantics are needed; `Decimal` for money; `async`/`await` with structured concurrency.

## Sources

- [Swift API Design Guidelines](https://www.swift.org/documentation/api-design-guidelines/)
- [Google Swift Style Guide](https://google.github.io/swift/)
