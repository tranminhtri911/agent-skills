# Changelog

Every committed change bumps the suite version by one patch step (1.0.0 → 1.0.1 → 1.0.2) in `pyproject.toml`, `src/devskills/__init__.py`, every `skills/*/SKILL.md` `metadata.version` and a section below; `SuiteVersionTest` fails when they disagree.

## 1.0.3 (2026-11-19)

- Include responsive layout inspection in every UI E2E run.
- Reuse established UI patterns for development and maintenance. Consult the UI/UX skill for design gaps and during rendered review.

## 1.0.2 (2026-11-19)

- Route new UI design and rendered UI review to the available UI/UX skill, with responsive checks around affected breakpoints.
- Remove the GitHub Actions regression workflow.

## 1.0.1 (2026-11-17)

- Select skills by actual scope; add workflow modes and move Strict instructions to a reference.
- Make the UI reference install opt-in; add project gate support and require an explicit UI CLI release.
- Follow project FK/comment conventions with explicit overrides.
- Fail closed for risky test profiles without OS network isolation.
- Fix duplicate evaluation IDs; add definition validation, release-source packaging and CI matrix.
- Skill gate routes only the user's own words; pasted checklists, logs and documents no longer require every skill they mention.
- Comment templates no longer mandate block comments over the repository's style.
- Release ZIP excludes `*.egg-info/`; INSTALL documents building it with `tools/package-release.py`.
- New `code-style` skill (17th): explicit-over-short rules STYLE-001..007, per-language references (Python, TS/JS, Java, Kotlin, C#, PHP, Go, Swift, Dart, SQL) and per-framework references (Django, FastAPI, React/Next, Vue, Angular, NestJS, Spring, Android/Compose, ASP.NET Core, Laravel, SwiftUI, Flutter) with cited official sources; patterns applied by signal. Linked both ways with write-maintainable-code, routed by dev-orchestrate, review-code and the skill gate (scenario EV52).
- Automatic style routing: `ds.py style` (and a section in `inspect`) detects languages, frameworks and style tools per project root of a monorepo from manifests and file extensions (adds Flutter, Android/Compose, SwiftUI and the ASP.NET Core web SDK); the skill gate adds the matching code-style references as context, without blocking, on the first edit of each language in each root.
- OPS-014: classify command targets as proven local, non-local or unknown; tunnels, network mounts and indirect commands are not proof of local, and a timeout never approves a non-local target (scenarios EV50, EV51).
- The skill gate is installed by default by `install` and `update` (`--without-skill-gate` opts out; `--with-skill-gate` is kept and does nothing extra).
- Codex: `install --target codex` adds a non-blocking `apply_patch` hook to `~/.codex/hooks.json` that supplies the code-style references (`skill-gate.py codex-style`); it merges with existing hooks and needs one trust step in Codex `/hooks`.

See `docs/checklist-audit.md` for verification limits and proposed work not delivered.
