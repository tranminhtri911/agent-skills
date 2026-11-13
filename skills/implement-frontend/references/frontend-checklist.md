# Frontend checklist and framework notes

## Before handing over a screen

- [ ] All states designed and reachable in dev (loading, empty, error, timeout, permission denied).
- [ ] Keyboard-only flow works; focus order and visible focus; form errors announced.
- [ ] No console errors/warnings on load and main interactions.
- [ ] Every target device checked (default web: mobile 390×844 + laptop 1280×800; tablet/desktop when targeted); no horizontal scroll at 360 px; touch targets ≥ 44 px; long text wraps.
- [ ] Mobile app: iOS and Android phones (tablets when targeted); safe areas, keyboard open, Android back, font scaling.
- [ ] Components from shadcn/ui `components/ui` (or the project's existing kit); no look-alike duplicates, no hard-coded colors.
- [ ] Network failures and slow responses handled (throttle in devtools).
- [ ] No secrets or internal URLs in the bundle; no tokens in localStorage unless the architecture requires it.
- [ ] Layout, palette, typography and UX checked against ui-ux-pro-max (or this checklist when it is not installed); the project's design system still wins.
- [ ] Themes (when the project has them): every state works in Light and Dark; System follows the OS live; no flash of the wrong theme on reload; no hard-coded colors.
- [ ] Screenshots captured for changed states (verify-ui), in each theme the project supports.

## React / Next.js

```tsx
/* Abort the request when the order id changes or the component unmounts,
 * so a slow response cannot overwrite the newer screen. */
useEffect(() => {
  const controller = new AbortController();
  loadOrder(orderId, { signal: controller.signal }).then(setOrder).catch(handleAbortOrError);
  return () => controller.abort();
}, [orderId]);
```

- Server Components fetch on the server; Client Components only where interaction is needed (`"use client"`).
- Server actions/route handlers still validate and authorize.
- Prefer TanStack Query/SWR (if already used) for server state instead of global stores.

## Vue / Nuxt

```ts
onMounted(() => window.addEventListener("resize", onResize));
onBeforeUnmount(() => window.removeEventListener("resize", onResize));
```

- Mutating `reactive`/`ref` values is the intended model; do not force React-style immutability.
- `v-html` only with sanitized content.

## Angular

- Feature folders per the Angular style guide; standalone components where the project uses them.
- Unsubscribe with `takeUntilDestroyed()` / `async` pipe; avoid manual subscriptions in components.
- Use the built-in sanitizer; `bypassSecurityTrust*` needs a security review.

## Svelte / SvelteKit

- `onDestroy` for cleanup; `{@html}` only with sanitized content; load functions validate params.
