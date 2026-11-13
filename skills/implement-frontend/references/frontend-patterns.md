# Frontend patterns (React + TypeScript first)

Reuse the project's API layer, hooks, components and form library first (CTX-009). The examples show responsibilities; adapt them to the repo's data layer (TanStack Query, SWR, RTK Query, a custom `BaseRepository`, Inertia).

## Feature folder

```
features/orders/
  api.ts            typed calls through the project's API client (no fetch() scattered in components)
  queries.ts        query keys + hooks (useOrders, useCreateOrder)
  OrderListPage.tsx route-level: reads params, composes, handles page states
  components/       presentational parts (OrderTable, OrderFilters)
  schema.ts         form schema (zod/yup) shared with type inference
  __tests__/
```

## Data fetching and request races

```tsx
// queries.ts — the key carries every input that changes the answer, including tenant.
export const orderKeys = {
  list: (tenantId: string, filters: OrderFilters) => ["orders", tenantId, filters] as const,
};

export function useOrders(filters: OrderFilters) {
  const { tenantId } = useAuthContext(); // project hook
  return useQuery({
    queryKey: orderKeys.list(tenantId, filters),
    queryFn: ({ signal }) => api.listOrders(filters, { signal }), // aborted when the key changes
    placeholderData: keepPreviousData,
  });
}
```

Without a query library, guard by request identity:

```tsx
useEffect(() => {
  const controller = new AbortController();
  api.listOrders(filters, { signal: controller.signal })
    .then(setOrders)
    .catch((error) => { if (!controller.signal.aborted) setError(error); });
  return () => controller.abort(); // A late response for old filters is dropped, never rendered.
}, [tenantId, filters]);
```

On logout or tenant switch: `queryClient.clear()` (or reset the store) **before** rendering the new tenant, and cancel in-flight queries.

## Mutations and optimistic updates

```tsx
export function useRenameOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.renameOrder,
    onMutate: async ({ id, name }) => {
      await queryClient.cancelQueries({ queryKey: ["orders"] });
      const previous = queryClient.getQueriesData<Order[]>({ queryKey: ["orders"] });
      queryClient.setQueriesData<Order[]>({ queryKey: ["orders"] }, (rows) =>
        rows?.map((row) => (row.id === id ? { ...row, name } : row)));
      return { previous };
    },
    onError: (_error, _vars, context) => context?.previous.forEach(([key, data]) => queryClient.setQueryData(key, data)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["orders"] }),
  });
}
```

Money, stock and permissions are never optimistic: wait for the server.

## Forms

- One schema for client validation; server errors (422 field errors) are mapped back onto the same fields (`setError`). The server stays the authority.
- Disable submit while pending and send an idempotency key for create/pay actions; double-click must not create two records.
- Preserve user input on error; focus the first invalid field and announce the error (`aria-describedby`, `role="alert"`).

## Page states and responsive layout

Every screen designs: loading (skeleton, no layout jump), empty, error with retry, partial data, forbidden (403) and not found, long text and many rows. Layout from the project's breakpoints/tokens, mobile-first, for the target devices (default mobile + laptop; tablet when asked): [responsive-and-devices.md](responsive-and-devices.md). Check with verify-ui.

## Themes: light, dark, system

When: the project already has themes (every screen supports all of them), a new app, or the user asks for dark mode. An existing project without themes gets a proposal, not a surprise restyle.

- Offer three choices: **Light**, **Dark**, **System** (default). System follows `prefers-color-scheme` and updates live when the OS switches.
- Colors come from semantic tokens (`--color-bg`, `--color-text`, `--color-surface`, `--color-border`, `--color-accent`), defined once per theme; components never use raw hex values. Use the project's token system when it has one: shadcn/ui variables (`--background`, `--foreground`... on `:root` and `.dark`, see [shadcn-ui.md](shadcn-ui.md)), Tailwind `dark:` with class-based dark mode, MUI/Chakra/Vuetify color modes. Take palettes and contrast pairs from ui-ux-pro-max. With shadcn/ui the class is `dark` on `<html>`, not `data-theme`.
- Apply the saved choice before first paint (blocking inline script in `<head>`, or the framework's helper: `next-themes`, `@nuxtjs/color-mode`), otherwise the page flashes in the wrong theme.
- Persist the choice per device (localStorage `theme`: `light` | `dark` | `system`), or in the user profile when the product syncs settings.
- Set `color-scheme` so native controls, scrollbars and form fields follow; check images, logos, charts, shadows and focus rings in each theme; contrast AA in every theme.

```html
<!-- In <head>, before stylesheets render: apply the saved theme (default system) without a flash. -->
<script>
  (function () {
    var choice = "system";
    try { choice = localStorage.getItem("theme") || "system"; } catch (error) { /* storage blocked */ }
    var dark = choice === "dark" || (choice === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  })();
</script>
```

```css
:root, [data-theme="light"] { --color-bg: #ffffff; --color-text: #111827; --color-surface: #f3f4f6; }
[data-theme="dark"] { --color-bg: #0b1120; --color-text: #e5e7eb; --color-surface: #1f2937; }
body { background: var(--color-bg); color: var(--color-text); }
```

```ts
/* Theme switcher: store the choice; while on "system", follow OS changes live. */
const media = matchMedia("(prefers-color-scheme: dark)");

export function applyTheme(choice: "light" | "dark" | "system"): void {
  try { localStorage.setItem("theme", choice); } catch { /* storage blocked: keep it for this page only */ }
  const dark = choice === "dark" || (choice === "system" && media.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

media.addEventListener("change", () => {
  if ((localStorage.getItem("theme") ?? "system") === "system") applyTheme("system");
});
```

## State placement

Server state in the query cache, URL state (filters, page, tab) in the URL, form state in the form, global UI state (theme, auth) in the project's context/store. Do not copy server data into a global store "for convenience" — it goes stale and leaks across tenants.
