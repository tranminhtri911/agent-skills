# Laravel style

Builds on [PHP style](language-php.md); the project's folder layout and Pint/PHP-CS-Fixer rules win.

## Names

| Element | Style | Example |
| --- | --- | --- |
| Model | singular `StudlyCaps` | `Invoice` |
| Table | plural `snake_case` (Eloquent default) | `invoices` |
| Controller | the repo's choice; Laravel docs examples use singular + `Controller` | `InvoiceController` |
| Form request | action + model + `Request` | `StoreInvoiceRequest` |
| Job / event / listener | action phrase / past tense / reaction | `SendInvoiceReminder`, `InvoicePaid`, `NotifyCustomerOfPayment` |
| Route name | dotted, plural resource | `invoices.show` |
| Config / translation key | `snake_case` | `config('billing.retry_attempts')` |

## Structure and patterns by signal

- Controllers stay thin: `FormRequest` validates and authorizes → a service or action class does the work → a resource/response is returned.
- Query logic used by several callers → Eloquent query scopes or a repository class if the project already has a repository layer.
- Several steps that must succeed together → a service/action wrapped in `DB::transaction`.
- Interchangeable implementations → bind an interface to an implementation in a service provider.

## Explicit over clever

- Constructor injection in services; facades and helpers in the style the project already uses, not mixed within one class.
- No queries in Blade views; eager load (`with`) in the controller or query.
- Values from `config()`/enums, never `env()` outside config files.

## Sources

- [Spatie — Laravel & PHP guidelines](https://spatie.be/guidelines/laravel)
- [Laravel — contribution guide (framework coding style follows PSR-2 and PSR-4)](https://laravel.com/docs/12.x/contributions)
- [Laravel best practices (community)](https://github.com/alexeymezenin/laravel-best-practices)
