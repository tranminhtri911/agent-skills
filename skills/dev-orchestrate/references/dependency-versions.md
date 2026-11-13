# Dependency versions (DEP-001 … DEP-004)

First decide which case the task is. The two cases have opposite rules.

| Case | How to recognise it | Versions |
| --- | --- | --- |
| **New project** | empty repo, scaffolding (`create-next-app`, `npm create vite`, `django-admin startproject`, `laravel new`...), or the user says "new project" | latest **stable** release of every framework, library and tool, **pinned exactly** |
| **Existing project** (maintenance, feature, bugfix) | a manifest and lockfile already exist (`package.json` + lock, `pyproject.toml`/`requirements*.txt`, `composer.lock`, `Gemfile.lock`, `go.sum`, `pom.xml`...) | **do not touch**: no upgrade, downgrade, add or remove unless that is the task or the user asks |

## DEP-001 New project: latest stable, checked, not remembered

- Look the version up in the registry at the time of the task; model memory is out of date.

| Ecosystem | Latest stable version |
| --- | --- |
| npm | `npm view <pkg> version` (and `npm view <pkg> dist-tags`) |
| Python | `pip index versions <pkg>` or `uv pip compile` result |
| PHP | `composer show -a <vendor/pkg>` |
| Go | `go list -m -versions <module>` |
| Ruby | `gem list -r <gem> --exact` |
| Java/Kotlin | Maven Central search / `./gradlew dependencyUpdates` |

- Stable only: no `beta`, `rc`, `canary`, `next`, `alpha` tags unless the user asks.
- Runtimes: the current **LTS** (Node.js LTS, Java LTS, .NET LTS) or the newest stable minor the main framework supports (Python, PHP, Go).
- Check that the chosen majors work together (framework ↔ UI kit ↔ Tailwind ↔ TypeScript ↔ test runner) using each project's release notes; if two latest versions conflict, take the newest compatible pair and say why.
- Scaffold with the current generator (`npx create-next-app@latest`, `npm create vite@latest`) and then pin what it produced.

## DEP-002 Pin exactly

| Ecosystem | Pin |
| --- | --- |
| npm/pnpm/yarn/bun | exact versions in `package.json` (no `^`/`~`): `.npmrc` `save-exact=true`, or `--save-exact` / `pnpm add -E`; `packageManager` field (corepack); commit the lockfile |
| Node.js | `.nvmrc` or `.node-version`, `engines.node` |
| Python | `==` in requirements with a lock (`uv.lock`, `poetry.lock`, `pip-compile` output), `requires-python`, `.python-version` |
| PHP | exact constraints in `composer.json`, commit `composer.lock`, `config.platform.php` |
| Ruby / Go / Java | `Gemfile.lock` + `.ruby-version`; `go.mod`/`go.sum` + `toolchain`; exact versions, no `+`/ranges in Gradle/Maven |
| Docker / CI | versioned image tags (`node:22.12-alpine`, not `latest`; digest for production images), versioned CI actions (`actions/checkout@v4` or a SHA) |

Report the pinned versions in the hand-over (table: package, version, why).

## DEP-003 Existing project: do not touch versions

- Use what the lockfile has, and write code for **that** version's API (read the installed version, `node_modules/<pkg>/package.json`, `pip show`, `composer show`; follow that version's docs, not the newest).
- Install with lockfile-respecting commands only: `npm ci`, `pnpm install --frozen-lockfile`, `yarn install --immutable`, `bun install --frozen-lockfile`, `uv sync --frozen`, `poetry install` (no `lock`), `pip install -r requirements.txt`, `composer install`, `bundle install`, `go mod download`.
- Never on your own: `npm update`, `npm install <pkg>@latest`, `npm audit fix --force`, `npx npm-check-updates -u`, `yarn upgrade`, `pnpm update`, `composer update`, `bundle update`, `pip install -U`, `poetry update`, `go get -u`, changing `.nvmrc`/Docker base tags/CI versions.
- If the lockfile or a manifest changes during your work and the task did not ask for it, stop and report it; do not commit it.
- A new dependency in an existing project is a proposal first (DES-008 checklist: why, license, maintenance, weight, audit), added at an exact version compatible with the existing ones, only after the user agrees.

## DEP-004 Upgrades are their own task

When the user asks for an upgrade or a security fix: one package (or one framework family) per change, read its changelog/migration guide, keep it pinned, run the full checks, and keep the upgrade out of feature diffs (CODE-009). An authorized dependency change does not need another confirmation per command.
