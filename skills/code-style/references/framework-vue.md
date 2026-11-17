# Vue / Nuxt style

Builds on [TypeScript / JavaScript style](language-typescript.md); the project's eslint-plugin-vue level and folder layout win.

## Names and files (Vue style guide)

| Element | Style | Example |
| --- | --- | --- |
| Component name | multi-word, `PascalCase` | `InvoiceTable` (never a single word like `Table`) |
| Single-file component file | `PascalCase.vue` (or the repo's kebab-case) | `InvoiceTable.vue` |
| Base / app-wide single-instance components | prefix `Base` / `The` | `BaseButton`, `TheHeader` |
| Prop in script / in template | `camelCase` / `kebab-case` | `invoiceId` / `:invoice-id` |
| Composable | starts with `use` | `useInvoiceFilters` |
| Emitted event | `kebab-case` or `camelCase` per repo | `update:modelValue`, `invoice-selected` |

## Explicit over clever

- Prop definitions are detailed: types, `required`, defaults (Vue essential rules).
- `v-for` always with a stable `:key`; never `v-if` on the same element as `v-for` — filter in a computed property.
- Template expressions stay simple; anything with logic becomes a computed property or method with a descriptive name.
- `<script setup lang="ts">` with typed `defineProps`/`defineEmits` when the project uses the Composition API.

## Patterns by signal

- Logic shared by two or more components → a composable.
- Server data and shared state → the project's store (Pinia) or data layer; component-local state stays in the component.

## Sources

- [Vue style guide](https://vuejs.org/style-guide/)
