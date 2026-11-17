# Android / Jetpack Compose style

Builds on [Kotlin style](language-kotlin.md); the project's module layout, DI library and lint/detekt rules win.

## Names

| Element | Style | Example |
| --- | --- | --- |
| `@Composable` that emits UI (returns `Unit`) | `PascalCase` noun | `InvoiceList` |
| `@Composable` that returns a value | `lowerCamelCase`, starts with `remember` when it remembers | `rememberInvoiceFilterState()` |
| ViewModel | screen/feature + `ViewModel` | `InvoiceListViewModel` |
| UI state | screen/feature + `UiState` | `InvoiceListUiState` |
| Repository / data source | `<Domain>Repository` / `<Domain>RemoteDataSource` | `InvoiceRepository` |

## Composable parameters

- The first optional parameter of a UI composable is `modifier: Modifier = Modifier`, applied to the root element (Compose API guidelines).
- State flows down as parameters, events flow up as lambdas named `on<Event>` (`onInvoiceClick`).

## Architecture by the platform guide

- UI layer (composables + ViewModel exposing an immutable `UiState`) → optional domain layer (use cases) → data layer (repositories, data sources). Repositories are the platform-recommended entry point to data.
- Use cases only when logic is reused by several ViewModels or is complex enough to test alone.
- Dependencies through constructor injection (Hilt/Koin/manual), never singletons reached from composables.

## Explicit over clever

- Composables stay side-effect free; side effects in `LaunchedEffect`/`DisposableEffect` with clear keys.
- Long modifier chains: one modifier per line.
- `collectAsStateWithLifecycle()` for flows in UI.

## Sources

- [Android — Guide to app architecture](https://developer.android.com/topic/architecture)
- [Jetpack Compose API guidelines](https://github.com/androidx/androidx/blob/androidx-main/compose/docs/compose-api-guidelines.md)
- [Android Kotlin style guide](https://developer.android.com/kotlin/style-guide)
