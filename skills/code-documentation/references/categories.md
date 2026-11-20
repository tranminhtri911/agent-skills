# What to document, per kind of code (DOC-010)

Examples use TypeScript with the `Target:` block format. Use that format only when it fits the project's conventions (DOC-009), and translate the parts into the language's native syntax (DOC-011): Python `Args:`/`Returns:`/`Raises:`, C# `<summary>`/`<param>`/`<returns>`/`<exception>`, Go a `//` sentence starting with the name. Every value in a comment (status code, unit, retry count, schedule, constraint) must come from the implementation or its configuration (DOC-007).

## 1. Class / interface

Document the purpose and main responsibilities.

```typescript
/**
 * Target:
 *   Manage user accounts and their lifecycle.
 *
 * Responsibilities:
 *   Create, retrieve, update, and delete users.
 */
class UserService {
  // Implementation
}

/**
 * Target:
 *   Define the data required to create a user.
 */
interface CreateUserDto {
  name: string;
  email: string;
}
```

- Describe the primary purpose.
- Include responsibilities when they are not obvious.
- Avoid repeating class or interface names.
- Do not document every simple interface.

## 2. Method / function

Document the purpose, parameters, return value and important exceptions.

```typescript
/**
 * Target:
 *   Create a new user in the database.
 *
 * @param data - User information to create.
 *
 * @returns The created user.
 *   Example: { id: 1, name: "John" }
 *
 * @throws ConflictError - If the email already exists.
 */
async function createUser(
  data: CreateUserDto
): Promise<User> {
  // Implementation
}
```

- `Target`: required for methods that need documentation.
- `@param`: when parameters need explanation.
- `@returns`: meaningful return values; explain special cases such as null, false or empty results.
- `Example`: optional; only when useful.
- `@throws`: important exceptions the code actually raises.
- Explain important side effects.
- Do not document trivial methods.

## 3. Complex logic

Explain WHY the logic exists, not WHAT each line does.

```typescript
// Use soft delete to preserve audit history
// and allow deleted accounts to be restored.
await user.update({
  deletedAt: new Date()
});
```

- Explain non-obvious business rules, unusual algorithms, workarounds and important technical decisions.
- Never translate code into English.
- Keep the comment next to the logic it explains.

## 4. Constants / config

Document meaning, units and important limits.

```typescript
/**
 * Target:
 *   Limit failed login attempts to reduce
 *   brute-force attacks.
 *
 * Unit: attempts per account.
 */
const MAX_LOGIN_ATTEMPTS = 5;

/**
 * Target:
 *   Define the timeout for external API requests.
 *
 * Unit: milliseconds.
 */
const API_TIMEOUT = 30000;
```

- Describe the purpose when it is unclear.
- Specify units when relevant (or put the unit in the name: `apiTimeoutMs`).
- Explain important limits, restrictions and non-obvious defaults.
- No comment for self-explanatory constants.

## 5. Database / model

Document the model's purpose, important fields, relationships and constraints.

```typescript
/**
 * Target:
 *   Store user account information.
 *
 * Constraints:
 *   Email must be unique.
 *   Deleted users are retained for audit history.
 */
interface User {
  id: number;
  name: string;
  email: string;

  /**
   * Soft-delete timestamp.
   * Null indicates an active account.
   */
  deletedAt: Date | null;
}
```

- Explain important constraints and non-obvious relationships.
- Explain special field behavior and nullability with business meaning.
- Distinguish soft delete from hard delete.
- Do not repeat column names.
- Document only constraints verified in the schema, migrations or implementation (the migration wins over the ORM model; change-database).

## 6. API endpoint

Document purpose, request, response and important errors.

```typescript
/**
 * Target:
 *   Register a new user.
 *
 * Endpoint:
 *   POST /api/users
 *
 * @param body - User registration information.
 *
 * @returns HTTP 201 with the created user.
 *   Example: { id: 1, name: "John" }
 *
 * Errors:
 *   400 - Invalid request data.
 *   409 - Email already exists.
 */
@Post("/users")
async createUser(
  @Body() body: CreateUserDto
) {
  return this.userService.createUser(body);
}
```

- Document the endpoint purpose, important request parameters and response behavior.
- List important HTTP status codes, verified against the handler, exception filters and framework defaults.
- Document authentication or authorization requirements when relevant.
- Do not duplicate existing API documentation (OpenAPI decorators, `docs/openapi.json`); the contract itself belongs to design-api.

## 7. Background job / event

Document trigger, behavior, result, retry policy and side effects.

```typescript
/**
 * Target:
 *   Send notification emails for pending orders.
 *
 * Trigger:
 *   Scheduled every 5 minutes.
 *
 * Result:
 *   Sends emails to eligible customers.
 *
 * Retry:
 *   Failed deliveries are retried up to 3 times.
 *
 * Side Effects:
 *   Updates notification status in the database.
 */
async function sendOrderNotifications(): Promise<void> {
  // Implementation
}
```

- Explain when and how the job is triggered, and its expected result.
- Document retry behavior, idempotency requirements and failure handling when they apply.
- Explain important side effects.
- Take the schedule and retry count from the scheduler/queue configuration; never invent schedules, retry counts or delivery guarantees.

## 8. Security / performance

Explain important technical decisions and the reasons behind them.

```typescript
// Use parameterized queries to prevent SQL injection.
// Never concatenate user input into SQL statements.
const user = await db.query(
  "SELECT * FROM users WHERE email = ?",
  [email]
);
```

```typescript
// Process records in batches to avoid loading
// the entire dataset into memory.
const BATCH_SIZE = 500;

for (let offset = 0; offset < total; offset += BATCH_SIZE) {
  await processBatch(offset, BATCH_SIZE);
}
```

- Explain non-obvious security decisions and important restrictions.
- Explain performance trade-offs and resource limits.
- No comments about standard framework behavior.
- Do not claim security or performance guarantees without evidence (review-security, review-performance).
