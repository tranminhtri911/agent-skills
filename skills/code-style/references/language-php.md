# PHP style

Framework: [Laravel](framework-laravel.md). Repository tooling (PHP-CS-Fixer, Laravel Pint, PHP_CodeSniffer, PHPStan/Larastan config) wins over this page.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Class, interface, trait, enum | `StudlyCaps` (PSR-1) | `InvoiceService`, `PaymentStatus` |
| Method | `camelCase` (PSR-1) | `calculateInvoiceTotal()` |
| Class constant | `UPPER_SNAKE_CASE` (PSR-1) | `MAX_RETRY_ATTEMPTS` |
| Property, variable | `camelCase`, consistently within the project | `$invoiceTotal` |
| Interface / abstract | the repository's convention; otherwise a role name (`PaymentGateway`) | |
| Boolean | `is`/`has`/`can` | `isExpired()` |

One class per file, namespace following PSR-4 paths.

## Layout

- `declare(strict_types=1);` in new files when the project uses it.
- The body of each control structure is enclosed by braces (PSR-12), on its own line — also for a single `return`.
- Guard clauses first; no nested ternaries (PHP 8 forbids unparenthesised nesting anyway); `match` over long `switch` for value mapping.

```php
// Not this
if (!$invoice) return null;

// This
if ($invoice === null) {
    return null;
}
```

## Closures and collections

- Arrow functions (`fn`) only for one-expression callbacks.
- Multi-step collection pipelines (Laravel `Collection`): one method per line, named intermediate variables when a step's meaning is not obvious.

## Static members

- Class constants and pure helpers may be static; named constructors (`Money::fromMinor(...)`) are static factories.
- Business logic in static methods cannot be replaced in tests; inject services through the constructor. Framework facades follow the framework reference.

## Types

Parameter, return and property types everywhere the PHP version supports them; enums (8.1+) instead of string constants for statuses; `readonly` properties for value objects.

## Sources

- [PSR-1: Basic Coding Standard](https://www.php-fig.org/psr/psr-1/)
- [PSR-12: Extended Coding Style](https://www.php-fig.org/psr/psr-12/)
