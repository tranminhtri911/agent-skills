# Patterns by signal (STYLE-006)

A pattern is applied when its **signal** is present in the change you are making, in the form the repository already uses. Without the signal the plain version is clearer for every reader. Before adding one, look for the repository's existing version (`inspect` → "patterns in use"); a second, parallel version is never the answer (DES-007, write-maintainable-code [patterns-and-architecture.md](../../write-maintainable-code/references/patterns-and-architecture.md)).

| Pattern | Apply when (signal) | Keep it plain when | Form per stack |
| --- | --- | --- | --- |
| Repository | the same data access (query, filter, mapping) is needed by two or more callers; the repository already has a data layer; business rules must be tested without a database; the platform guide prescribes it (Android, Flutter) | one caller and the framework's data API is already readable (Django manager/QuerySet, Eloquent scope) | Django: custom `Manager`/`QuerySet` methods; Laravel: query scopes or a repository class if the repo has them; Spring Data: `interface OrderRepository extends JpaRepository`; EF Core: `DbContext` + a repository only if the repo uses one; Android/Flutter: `OrderRepository` in the data layer |
| Builder | many optional parts or a construction order that matters, and the language lacks named/default arguments (Java, Go); test data with many variants | the language has named/default arguments (Python, Kotlin, C#, Dart, Swift, TS object literals) and the object has few parts | Java: static nested `Builder` or Lombok `@Builder` if the repo uses Lombok; Go: functional options; tests: the repo's factory library (factory_boy, Laravel factories, fishery) |
| Interface / protocol | two or more real implementations; an external system (payment, mail, storage, clock) that tests must replace; a module boundary where callers must not depend on the implementation | one implementation and nothing replaces it | Go: small interface defined by the consumer; Java/C#/TS: interface named for the role (`PaymentGateway`), not `IThing` unless the language convention requires it (C#); Swift: protocol; Kotlin/Dart: interface/abstract class |
| Abstract base class | two or more subclasses share the same steps in the same order and differ in a few (template method) | one subclass, or the shared part is a helper function | Extract at the second or third real case (rule of three), never ahead of it |
| Strategy | a behavior is chosen at runtime from several variants (pricing rule, export format, provider) and the `if/switch` on the variant appears in more than one place | one `switch` in one place with simple branches | A map from enum to function/class, or one class per variant behind an interface, registered where the repo registers dependencies |
| Factory | creating an object needs a decision (which implementation, which config) or several steps that callers should not repeat | a constructor call says everything | A named static factory (`Money.ofMinor(...)`), a function, or the DI container's registration — not an abstract factory for one product |
| Static member | constant, pure helper, named factory method | holds state, does I/O, or must be replaced in tests | See STYLE-005 and the language reference |
| Dependency injection | the framework provides it (Spring, ASP.NET Core, NestJS, Angular, FastAPI `Depends`, Laravel container) | plain scripts and pure functions | Constructor injection of the dependency's interface or concrete class; no service locator in business code |

## Explaining the choice

When you add a pattern, say which signal justified it in one line of the change description ("Repository: the order query is now used by the API and the nightly export"). When you leave one out on purpose, that is not worth a comment.

## Sources

- [Refactoring.Guru — design patterns catalog](https://refactoring.guru/design-patterns), [Builder](https://refactoring.guru/design-patterns/builder), [Strategy](https://refactoring.guru/design-patterns/strategy), [Factory Method](https://refactoring.guru/design-patterns/factory-method)
- [Martin Fowler — Repository (Patterns of Enterprise Application Architecture)](https://martinfowler.com/eaaCatalog/repository.html)
- [Android — Guide to app architecture (data layer, repositories)](https://developer.android.com/topic/architecture)
- [Flutter — App architecture guide (views, view models, repositories, services)](https://docs.flutter.dev/app-architecture/guide)
- [Go Code Review Comments — Interfaces](https://go.dev/wiki/CodeReviewComments)
