# Frontend verification

| Need | Pass criterion |
| --- | --- |
| Out-of-order responses | request A answering after B never overwrites B's result |
| Tenant switch / logout during fetch | a response for the old tenant/user never renders for the new one |
| Optimistic update fails | UI rolls back to server truth and shows the error |
| Keyboard and focus | every action works with keyboard; focus visible and moved predictably (dialogs, errors) |
| Accessibility | axe-core has no serious/critical violations on the changed screens |
| Visual | screenshots per viewport via `DS screenshot` (verify-ui) |

Primary evidence: `DS native-checks --execute` (tsc, eslint, build), then component/E2E tests through `DS run-tests` with a JUnit reporter (`vitest --reporter=junit --outputFile=…`, `jest --reporters=jest-junit`, `playwright test --reporter=junit`).

## Request race test (Vitest/Jest + Testing Library + MSW)

```tsx
it("keeps the latest filter's result when an older response arrives late", async () => {
  server.use(http.get("/api/orders", async ({ request }) => {
    const status = new URL(request.url).searchParams.get("status");
    if (status === "new") await delay(200);          // A: slow
    return HttpResponse.json([{ id: status, name: `orders-${status}` }]);
  }));
  render(<OrderListPage />);
  await user.selectOptions(screen.getByLabelText("Status"), "new");  // A
  await user.selectOptions(screen.getByLabelText("Status"), "paid"); // B
  expect(await screen.findByText("orders-paid")).toBeInTheDocument();
  await act(() => delay(250));
  expect(screen.queryByText("orders-new")).not.toBeInTheDocument();
});
```

## Tenant switch / logout

```tsx
it("drops the old tenant's response after switching tenant", async () => {
  server.use(http.get("/api/orders", async () => { await delay(200); return HttpResponse.json([{ id: 1, name: "tenant-A-order" }]); }));
  const { switchTenant } = renderWithAuth(<OrderListPage />, { tenantId: "A" });
  await switchTenant("B");
  await act(() => delay(250));
  expect(screen.queryByText("tenant-A-order")).not.toBeInTheDocument();
});
```

Also assert the query cache/store is empty after logout.

## Optimistic rollback

Make the mutation endpoint return 500 (or 409), perform the action, assert the old value is back and an error message is announced (`role="alert"`).

## Keyboard and focus

- Tab order follows the visual order; no keyboard trap; `Esc` closes dialogs and returns focus to the trigger.
- After a failed submit, focus moves to the first invalid field or the error summary.
- Test with `user.tab()` / `user.keyboard("{Enter}")` and `expect(element).toHaveFocus()`.

## axe-core

```tsx
import { axe } from "jest-axe"; // or vitest-axe
it("has no serious accessibility violations", async () => {
  const { container } = render(<OrderForm />);
  const results = await axe(container);
  expect(results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});
```

E2E on the local dev server (`@axe-core/playwright`):

```ts
const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
```

axe finds roughly a third to half of issues; keyboard, focus and screen-reader names still need the checks above.

## Vue (Laravel + Vue projects)

Same criteria with Vue Test Utils/Testing Library for Vue; cancel requests in `onBeforeUnmount`/`watch` cleanup (`onCleanup(() => controller.abort())`).
