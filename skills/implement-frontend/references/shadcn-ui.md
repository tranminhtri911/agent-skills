# shadcn/ui as the default component style

[shadcn/ui](https://ui.shadcn.com/) is not a dependency: its CLI copies accessible components (Radix primitives + Tailwind CSS) into the project, which then owns and edits them. Use it for new UI unless the project already has another component kit (CTX-009).

## Which case applies

| Project | Do |
| --- | --- |
| Already uses shadcn/ui (`components.json`, `components/ui/`) | Reuse `components/ui`; add missing components with the CLI; compose feature components from them |
| New React/Next.js app, or a project without a component kit | `npx shadcn@latest init`, then add components as screens need them |
| Uses MUI, Ant Design, Chakra, Vuetify, PrimeVue, Angular Material... | Keep that kit; follow ui-ux-pro-max for layout and spacing; propose shadcn/ui only as a separate decision |
| Vue/Nuxt, Svelte, Angular, React Native, Flutter without a kit | The port: `shadcn-vue`, `shadcn-svelte`, `spartan/ui`, `react-native-reusables` (NativeWind), Flutter `shadcn_ui` |

## Setup (React / Next.js)

```bash
npx shadcn@latest init                       # components.json, Tailwind theme variables, lib/utils.ts (cn)
npx shadcn@latest add button card input form dialog dropdown-menu sheet table sonner
```

- Components land in `components/ui/` (path from `components.json`). Edit them there; do not wrap them in a second layer of look-alike components.
- Forms: shadcn `Form` with react-hook-form + zod when the project has no form library yet; otherwise the project's library (CTX-009).
- Icons: `lucide-react`, the shadcn default, unless the project already has an icon set.
- Run the CLI only with the user's or project's package manager (`pnpm dlx`, `bunx`, `npx`); it changes files, so show the diff.

## Building screens

- Compose from `components/ui`: `Card` for grouped content, `Table` (or the data-table recipe with TanStack Table) for lists, `Dialog` on laptop and `Sheet`/`Drawer` on mobile for the same flow, `DropdownMenu` for row actions, `Sonner` toasts for async results, `Skeleton` for loading.
- Variants through `cva` and `cn()`; no inline styles, no new hard-coded colors.
- Keep Radix accessibility: do not remove focus rings, `aria-*` or keyboard handling the components ship with.
- Blocks and examples on ui.shadcn.com (dashboard, login, sidebar) are starting points; adapt them to the project's data flow and states (loading/empty/error).

## Theming and dark mode

shadcn/ui themes are CSS variables (`--background`, `--foreground`, `--card`, `--primary`, `--muted`, `--border`, `--ring`...) for `:root` and `.dark`. Change the palette there (pick it with ui-ux-pro-max), never per component.

- Light/Dark/System in Next.js: `next-themes` with `attribute="class"`, `defaultTheme="system"`, `enableSystem`, `disableTransitionOnChange`, and `suppressHydrationWarning` on `<html>`; the theme switcher is a `DropdownMenu` with Light, Dark, System.
- Vite/other React: the shadcn `ThemeProvider` recipe (localStorage + `prefers-color-scheme`), plus the inline head script from [frontend-patterns.md → Themes](frontend-patterns.md#themes-light-dark-system) to avoid a flash.
- Charts use the `--chart-1`...`--chart-5` variables so they follow the theme.

## Responsive with shadcn/ui

- Tailwind breakpoints (`sm` 640, `md` 768, `lg` 1024, `xl` 1280), mobile-first: base classes for the phone, `md:`/`lg:` for wider screens.
- Navigation: `Sidebar` (collapsible) on laptop, `Sheet` menu on mobile.
- Tables on mobile: hide secondary columns (`hidden md:table-cell`) or switch to a card list; never a page-wide horizontal scroll.
