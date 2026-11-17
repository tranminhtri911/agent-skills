# Changelog

## Unreleased

- Select skills by actual scope; add workflow modes and move Strict instructions to a reference.
- Make UI reference and Claude skill-gate installs opt-in; add project gate support and require an explicit UI CLI release.
- Follow project FK/comment conventions with explicit overrides.
- Fail closed for risky test profiles without OS network isolation.
- Fix duplicate evaluation IDs; add definition validation, release-source packaging and CI matrix.
- Skill gate routes only the user's own words; pasted checklists, logs and documents no longer require every skill they mention.
- Comment templates no longer mandate block comments over the repository's style.
- Release ZIP excludes `*.egg-info/`; INSTALL documents building it with `tools/package-release.py`.
- New `code-style` skill (17th): explicit-over-short rules STYLE-001..007, per-language references (Python, TS/JS, Java, Kotlin, C#, PHP, Go, Swift, Dart, SQL) and per-framework references (Django, FastAPI, React/Next, Vue, Angular, NestJS, Spring, Android/Compose, ASP.NET Core, Laravel, SwiftUI, Flutter) with cited official sources; patterns applied by signal. Linked both ways with write-maintainable-code, routed by dev-orchestrate, review-code and the skill gate (scenario EV52).
- Automatic style routing: `ds.py style` (and a section in `inspect`) detects languages, frameworks and style tools per project root of a monorepo from manifests and file extensions (adds Flutter, Android/Compose, SwiftUI and the ASP.NET Core web SDK); the skill gate adds the matching code-style references as context, without blocking, on the first edit of each language in each root.
- OPS-014: classify command targets as proven local, non-local or unknown; tunnels, network mounts and indirect commands are not proof of local, and a timeout never approves a non-local target (scenarios EV50, EV51).

See `docs/checklist-audit.md` for verification limits and proposed work not delivered.
