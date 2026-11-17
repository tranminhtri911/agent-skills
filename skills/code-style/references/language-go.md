# Go style

No framework reference: Go services usually follow the standard library and the repository's own layout. `gofmt`/`goimports` and the repository's `golangci-lint` config always win.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Package | short, lowercase, single word, no underscores | `invoice` |
| Exported identifier | `MixedCaps` | `CalculateTotal`, `Invoice` |
| Unexported identifier | `mixedCaps` | `parseRow` |
| Acronyms | consistent case | `userID`, `HTTPClient` (not `userId`, `HttpClient`) |
| Getter | no `Get` prefix | `invoice.Owner()`, setter `SetOwner` |
| One-method interface | method name + `-er` | `Reader`, `Notifier` |
| Receiver | short, consistent abbreviation of the type | `func (s *InvoiceService)` |

Short names are idiomatic for short scopes (`i`, `r` for a reader in a few lines); exported and long-lived names are descriptive. Do not repeat the package name (`invoice.Service`, not `invoice.InvoiceService`).

## Layout

- `gofmt` decides formatting; braces are mandatory in Go.
- Handle the error first and return early; keep the normal path unindented (Effective Go). No `else` after a `return`.

```go
invoice, err := repository.FindInvoice(ctx, invoiceID)
if err != nil {
    return fmt.Errorf("find invoice %s: %w", invoiceID, err)
}
```

## Function literals

Closures for short callbacks and goroutine bodies; a named function when the body grows beyond a few lines or is reused. Every goroutine has an owner and a way to stop (`context.Context`).

## Package-level state

Package-level variables only for constants, sentinel errors (`var ErrNotFound = errors.New(...)`) and immutable tables. Clients, clocks and configuration are passed in (struct fields, constructor parameters), not package globals.

## Interfaces

Interfaces belong in the package that uses them, not the one that implements them; return concrete types, accept small interfaces. No interface before there is a consumer that needs it.

## Sources

- [Effective Go](https://go.dev/doc/effective_go)
- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [Google Go Style Guide](https://google.github.io/styleguide/go/)
