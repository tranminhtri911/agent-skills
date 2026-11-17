# React / Next.js style

Builds on [TypeScript / JavaScript style](language-typescript.md); the project's folder layout, component kit and lint rules (eslint-plugin-react-hooks) win. UI states and accessibility live in implement-frontend.

## Names and files

| Element | Style | Example |
| --- | --- | --- |
| Component | `PascalCase` function, file named after it | `InvoiceTable` in `InvoiceTable.tsx` (or the repo's `invoice-table.tsx`) |
| Hook | starts with `use` | `useInvoiceFilters` |
| Props type | component name + `Props` | `InvoiceTableProps` |
| Event handler prop / handler | `on<Event>` / `handle<Event>` | `onSelect` / `handleSelect` |
| Boolean prop | `is`/`has`/`can` | `isLoading` |
| Next.js route files | framework names | `page.tsx`, `layout.tsx`, `route.ts` |

## Rules of React

- Components and hooks are pure during render; side effects go in event handlers or `useEffect` with cleanup.
- Hooks only at the top level of components and custom hooks, never inside conditions or loops.
- Never call component functions directly; render them as JSX.

## Explicit over clever

- One component per file for exported components; split when a component fetches data, holds state and renders a large tree (container + presentational).
- Conditional rendering: early `return` for loading/error/empty states; `&&` only with booleans (`items.length > 0 &&`, not `items.length &&`); no nested ternaries in JSX — extract a component or a variable.
- Inline arrow handlers only for one call (`onClick={() => onSelect(invoice.id)}`); anything longer becomes `handleSelect`.

## Patterns by signal

- Logic shared by two or more components, or isolated for testing → a custom hook.
- Server data → the project's data layer (React Query/SWR/server components/`api/` client), not `fetch` scattered in components.
- Global state only for state that is truly shared; local state stays local.

## Sources

- [Rules of React](https://react.dev/reference/rules)
- [Reusing logic with custom hooks](https://react.dev/learn/reusing-logic-with-custom-hooks)
- [Next.js project structure](https://nextjs.org/docs/app/getting-started/project-structure)
