# Spring / Spring Boot style

Builds on [Java style](language-java.md); the project's package layout, Lombok usage and formatter win.

## Names and structure

| Element | Style | Example |
| --- | --- | --- |
| Package | by feature under the application's root package | `com.acme.billing.invoice` |
| Controller | `<Domain>Controller` | `InvoiceController` |
| Service | `<Domain>Service` (interface + `Impl` only if the project already does that) | `InvoiceService` |
| Repository | `<Entity>Repository` | `InvoiceRepository extends JpaRepository<Invoice, Long>` |
| Request / response DTO | role suffix | `CreateInvoiceRequest`, `InvoiceResponse` |
| Configuration | `<Topic>Config` / `@ConfigurationProperties` class | `PaymentProperties` |

Place the main application class in the root package so component scanning covers the feature packages (Spring Boot "Structuring Your Code").

## Dependency injection

- Constructor injection with `final` fields; no `@Autowired` on fields. A single constructor needs no `@Autowired`.
- Configuration values through typed `@ConfigurationProperties`, not scattered `@Value` strings.

## Patterns by signal

- Data access → Spring Data repository interfaces; derived-query method names stay readable (`findByCustomerIdAndStatus`); anything longer gets `@Query` with a descriptive method name.
- Several interchangeable implementations (payment providers) → an interface with one bean per implementation, selected by a qualifier or a map of beans — a strategy without `if/else` on provider names.
- Transactions on service methods (`@Transactional`), not controllers.

## Explicit over clever

- Controllers: validate (`@Valid`) → call the service → map the response; no repository calls in controllers.
- No static access to beans or the application context in business code.

## Sources

- [Spring Boot — Structuring your code](https://docs.spring.io/spring-boot/reference/using/structuring-your-code.html)
- [Spring Boot — Spring beans and dependency injection](https://docs.spring.io/spring-boot/reference/using/spring-beans-and-dependency-injection.html)
- [Spring Framework — Dependency injection](https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html)
