# Responsive web and mobile devices

## Choose the target devices

Read them from the prompt and the product; when nothing is said, use the defaults.

| Product | Default targets | Add when asked or needed |
| --- | --- | --- |
| Web app / website | **mobile** (390×844) and **laptop** (1280×800) | tablet (768×1024), large desktop (1440×900 and up), print |
| Admin / dashboard | laptop and mobile (read-only flows at least) | large desktop, tablet |
| Mobile app (React Native/Expo, Flutter, native) | **iOS and Android phones** | tablets (iPad, Android tablets), landscape, foldables |

Say in the hand-over which devices were built and checked; a device that was not checked is not claimed.

## Responsive web

- Mobile-first: base styles for the phone, widen at the project's breakpoints (Tailwind: `sm` 640, `md` 768, `lg` 1024, `xl` 1280). Do not invent new breakpoints per screen.
- Layout: one column on mobile, grid/sidebar from `md`/`lg`; navigation collapses into a menu (`Sheet`) on mobile.
- No horizontal page scroll at 360 px. Wide tables: hide secondary columns or switch to cards on mobile; scroll only inside the table container.
- Touch: targets ≥ 44×44 px, spacing between them, no hover-only actions or tooltips holding essential information; inputs use the right `type`/`inputmode` (email, tel, numeric) for the mobile keyboard.
- Text: relative sizes, long Vietnamese/German strings wrap, numbers and currency do not break mid-value.
- Media: `srcset`/`sizes` or the framework image component; set width/height (or aspect ratio) so layout does not jump.
- Viewport: `<meta name="viewport" content="width=device-width, initial-scale=1">`; use `dvh` instead of `100vh` for full-height mobile layouts; `env(safe-area-inset-*)` for notched phones in PWAs.
- Dialogs: full-screen sheet or drawer on mobile, centered dialog on laptop.

## Mobile apps: iOS and Android

### React Native / Expo

- Layout with Flexbox and `useWindowDimensions()`; no fixed pixel widths for screens. Tablets: breakpoints on width (e.g. ≥ 768 → two panes).
- `SafeAreaView`/`react-native-safe-area-context` for notches, the home indicator and Android status/navigation bars.
- `KeyboardAvoidingView` (`behavior="padding"` on iOS, `"height"` on Android) or `react-native-keyboard-controller`; forms stay reachable with the keyboard open.
- `Platform.select` / `.ios.tsx` / `.android.tsx` only for real platform differences: Android hardware back (`BackHandler` or the navigator), iOS swipe-back, date pickers, permissions text, haptics.
- Text respects system font scaling (`allowFontScaling`, `maxFontSizeMultiplier` only where layout truly breaks).
- Touch targets ≥ 44 pt (iOS) / 48 dp (Android); `hitSlop` for small icons; `Pressable` with visible pressed state.
- Theme: `useColorScheme()` for System, plus the user's Light/Dark choice; shadcn-style components through `react-native-reusables` (NativeWind) when the app has no kit.
- Orientation: lock it in `app.json` unless the product needs landscape; if enabled, check both.

### Flutter

- `LayoutBuilder` / `MediaQuery.sizeOf(context)` for breakpoints; `SafeArea`; `Scaffold(resizeToAvoidBottomInset: true)`.
- Material 3 on Android and Cupertino-adaptive widgets (`Switch.adaptive`, `showAdaptiveDialog`) where platform feel matters; `shadcn_ui` when the app has no design system.
- `MediaQuery.textScalerOf` respected; `ThemeMode.system` plus Light/Dark.

### Native (SwiftUI / Jetpack Compose)

- SwiftUI size classes (`horizontalSizeClass`), Dynamic Type, safe areas by default. Compose `WindowSizeClass`, edge-to-edge with `WindowInsets`, font scale.

## Check

| Target | How |
| --- | --- |
| Web | Select widths using the `verify-ui` viewport plan. Capture target sizes and the edges of affected breakpoints, including both color schemes when the app has themes. |
| iOS | Simulator (small phone such as iPhone SE and a large one); `xcrun simctl io booted screenshot ios.png` |
| Android | Emulator (small ~360 dp and large phone); `adb exec-out screencap -p > android.png` |
| Tablets | iPad / Android tablet simulator, only when tablets are targets |

When a simulator or emulator is not available, the platform check is `blocked`, not `pass`.
