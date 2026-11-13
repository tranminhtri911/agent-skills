---
name: implement-frontend
description: "Use when building, specifying, reviewing or changing UI screens, pages, components, forms, client-side state, routing, data fetching, responsive layouts or themes in React, Next.js, Vue, Nuxt, Angular, Svelte, or mobile apps in React Native, Expo, Flutter, Jetpack Compose or SwiftUI. Triggers (vi): màn hình, giao diện, trang, component, form, nút, hiển thị, widget, màn hình khóa, responsive, app Android/iOS, dark mode, theme. Applies even when the request is phrased as a question (\"làm sao…\", \"có thể … không?\"); load it together with dev-orchestrate, not after it."
metadata:
  version: "1.0.0"
  suite: devskills
---

# Implement Frontend

One folder per feature/screen, components split by responsibility, every UI state designed, framework rules respected, and security decisions left to the server.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

**Start from the project's base (CTX-009).** Reuse the project's API client/repository layer, custom hooks (`useAppContext`, query hooks), shared components and design tokens, form and validation library, routing and state conventions; copy the reference screen of the same kind. Never add a second HTTP client, state library or component kit. Statuses, roles and option lists come from the project's constants module or generated API types, labels from i18n (CODE-011). Follow the source's data flow (page → hook → repository/API layer, as `patterns in use` shows); a custom hook only for logic shared or isolated for testing, no new store or wrapper layer without a named problem (DES-007). Which actions a status allows comes from the API, not re-implemented rules (BE-011).

**UI design reference: ui-ux-pro-max (default).** Before creating any screen, page or component, and before changing a layout, consult the `ui-ux-pro-max` skill (installed with the suite by default) for the stack's layout, style, palette, typography, spacing, theming, UX and accessibility guidelines; also use it to review states, forms and responsive behavior of screens you change. It is a reference, not an authority: the project's existing design system, tokens and components win (CTX-009), its suggestions are built with the project's component kit, and it never restyles existing screens unasked. When it is not installed, say so in one line (`python3 agent-skills.py update` installs it) and use [frontend-checklist.md](references/frontend-checklist.md).

**Component style: shadcn/ui (default).** New UI is built from [shadcn/ui](https://ui.shadcn.com/) components (Radix primitives + Tailwind, added with `npx shadcn@latest add <component>` into `components/ui`, then owned by the project) and its CSS-variable theme. Projects that already use shadcn/ui extend it: reuse `components/ui`, compose new components from it, add missing ones with the CLI rather than writing look-alikes. Projects with another component kit keep it (CTX-009: never a second kit, no migration unasked). Other stacks use the shadcn port when the project has no kit: Vue `shadcn-vue`, Svelte `shadcn-svelte`, Angular `spartan/ui`, React Native `react-native-reusables`, Flutter `shadcn_ui`. Setup, theming and rules: [shadcn-ui.md](references/shadcn-ui.md).

**Target devices (from the prompt).** Build for the devices the task names. Unspecified: a web screen supports **mobile and laptop**; tablet and large desktop are added when the prompt or the product asks (POS, dashboards, iPad use). Mobile-first layout with the project's (or Tailwind's) breakpoints, nothing overflowing horizontally at 360 px, touch targets ≥ 44 px, no hover-only actions. A **mobile app** (React Native/Expo, Flutter, native) supports **iOS and Android** phones by default, tablets when asked: safe areas and notches, platform conventions (Android back, iOS swipe-back), keyboard avoidance, font scaling, both orientations if enabled. Details: [responsive-and-devices.md](references/responsive-and-devices.md).

**Themes: light, dark, system (when needed).** If the project already has themes, every new or changed screen works in all of them. A new app, or a user asking for dark mode, gets three choices: Light, Dark and System (default; follows `prefers-color-scheme`, live). An existing project without themes does not get them unasked; propose it instead. How: [frontend-patterns.md → Themes](references/frontend-patterns.md#themes-light-dark-system).

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- Any visible change → **REQUIRED:** verify-ui before handing over.
- The screen needs a new or changed endpoint or field → **REQUIRED:** design-api.
- Rendering user content, tokens, redirects, file uploads → **REQUIRED:** review-security.

## Feature layout (follow the repo's router conventions)

```
frontend/features/orders/
  pages/        # route entry (Next.js app/ or pages/ routes import from here)
  components/   # UI used only by orders
  api/          # typed client + mapping from API DTOs to view models
  hooks/        # state/effects (React) or composables (Vue)
  tests/
```

## States every screen must handle

`initial`, `loading`, `empty`, `success`, `validation_error`, `server_error`, `timeout`, `permission_denied`, `offline/degraded` where relevant. Submits move idle → submitting → succeeded/failed/**pending_unknown**: a payment timeout is "verifying", never "failed".

## Rules

- FE-001 no all-in-one components: separate data fetching, state and presentation.
- FE-002 clean up subscriptions, listeners, timers and in-flight requests (AbortController) when the component unmounts or the route changes; ignore stale responses.
- FE-003 follow the framework's update model: React immutable updates and Rules of Hooks; Vue reactive mutation through refs/reactive; Angular change detection and RxJS unsubscribe.
- FE-004 keep local UI state, server state (query cache), URL state and global state separate; global store only for truly shared state.
- FE-005 prevent double submit in the UI and rely on server idempotency for the real guarantee.
- FE-006 forms: labels, clear validation messages, focus the first error, keep user input after recoverable failures.
- FE-007 accessibility: semantic HTML, keyboard navigation, visible focus, contrast (WCAG 2.2 AA as a starting target), announcements for async results.
- FE-008 no secrets in the bundle; hiding a button is not authorization.
- FE-009 render text by default; raw HTML (`dangerouslySetInnerHTML`, `v-html`, `innerHTML`) only after sanitizing; validate URLs before using them in `href`/`src`.
- FE-010 every screen works on each target device (default web: mobile + laptop; app: iOS + Android); long text, i18n, time zones, currency formatting, font fallbacks.
- FE-011 optimize after profiling: pagination/virtualization for large lists, memoization only where measured.
- FE-012 optimistic updates need rollback/reconcile; never show payment success before the server confirms.
- FE-013 themes come from semantic color tokens, never hard-coded colors; the saved choice is applied before first paint (no flash of the wrong theme), and contrast meets AA in every theme.
- Cache keys include tenant/user/locale when data depends on them; clear state on logout/tenant switch.

Framework notes and examples: [frontend-checklist.md](references/frontend-checklist.md).

## Verify

`DS native-checks --execute --run <id>` runs the project's own linter, type checker, build and framework checks (primary evidence; `check-code` is a supporting layer). `DS check-code` flags effects without cleanup, raw HTML sinks, `any`, tokens in localStorage, missing docs on exported functions. Visual evidence for changed screens on each target device: verify-ui (`DS screenshot …`, default mobile + laptop; mobile apps from the iOS simulator and Android emulator). Behavior tests with the repo's runner via test-safely. Browser tests never replace server-side authorization tests.

Request races, tenant switch/logout during fetch, optimistic rollback, keyboard/focus and axe-core: [verification-frontend.md](references/verification-frontend.md). Components, forms, state, data fetching and cache with React/TS examples: [frontend-patterns.md](references/frontend-patterns.md).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `useEffect` adds a listener without returning cleanup | Return a function that removes it |
| Fetch result from the previous route overwrites the new one | AbortController or request id check |
| Price computed in the browser and sent to the server | Server computes; UI only displays |
| Spinner forever on timeout | Timeout state with retry and support info |
