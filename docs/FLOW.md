# devskills workflow

These diagrams show how skills and `ds.py` commands work together from request to delivery, including safe testing, screenshots, dangerous operations, knowledge indexing, evidence aggregation, installation, and updates. Here, `ds.py` abbreviates `python3 <skill-directory>/scripts/ds.py`.

## 1. Task overview

```mermaid
flowchart TD
    A["Request: feature / bugfix / refactor"] --> B["dev-orchestrate<br/>ds.py run start + acceptance.json"]
    B --> C{"Classify risk<br/>ds.py risk → R0..R3"}
    C --> D["G1 Context<br/>discover-codebase<br/>(.knowledge → ds.py inspect [+ CodeGraph if available]<br/>→ learn bases/conventions + reference module → read call chain)"]
    D --> E{"R2/R3 or multiple approaches?"}
    E -->|Yes| F["G2 Design<br/>design-change → memo in docs/"]
    E -->|No| G
    F --> G["Declare required-check roster<br/>ds.py roster init"]
    G --> H["G3 Implement by module<br/>write-maintainable-code + backend / api / frontend / database / performance / reliability"]
    H --> I["G4 Verify<br/>native-checks (lint/typecheck/build/framework) · run-tests<br/>api-diff · api-examples (API-011) · screenshot · rate-limit-probe<br/>supporting: check-code · check-sql · scan-secrets<br/>→ trace: criterion ↔ test/check/artifact"]
    I --> J{"Gates satisfied?<br/>ds.py report"}
    J -->|fail / blocked| K["Classify failures; bounded fixes<br/>(understand failures before editing)"]
    K --> H
    J -->|pass / explained warn| L["G5 Final report<br/>final-report.md + summary"]
    L --> M{"User requested release?"}
    M -->|Yes| N["G6: only when authorized<br/>deploy / publish within authorization"]
    M -->|No| O["Done"]
```

Risk follows side effects, not diff size:

| Level | Example | Minimum checks |
| --- | --- | --- |
| R0 | Text/comments | check-code, scan-secrets (+ native lint for code edits) |
| R1 | Local logic | + context map, units, native typecheck/framework, acceptance trace |
| R2 | API, DB, auth, cache, queue | + preflight, isolated DB integrations, native build (+ api-diff for spec changes, migration checks for model changes) |
| R3 | Money, batches, deletion, permissions | + decision memo, failure-path/simulator tests |

## 2. Skill activation

```mermaid
flowchart LR
    subgraph understand["Understand and design"]
        DC["discover-codebase"]
        IK["index-project-knowledge"]
        DS["design-change"]
    end
    subgraph build["Implement"]
        WM["write-maintainable-code"]
        BE["implement-backend"]
        API["design-api"]
        FE["implement-frontend"]
        DB["change-database"]
        PF["review-performance"]
        RL["design-reliability"]
    end
    subgraph verify["Verify"]
        TS["test-safely"]
        UI["verify-ui"]
        SEC["review-security"]
        RC["review-code"]
    end
    ORC["dev-orchestrate<br/>(orchestration + dangerous-operation rules + report)"] --> understand
    ORC --> build
    ORC --> verify
    DC -.->|"no .knowledge yet"| IK
    BE -.-> API
    BE -.-> DB
    RL -.->|"simulate payment"| TS
    FE -.-> UI
    RC -.->|"each diff area"| SEC
    RC -.->|"queries, plans"| DB
```

## 3. Safe testing (test-safely)

```mermaid
flowchart TD
    A["ds.py run-tests --profile P -- TEST_COMMAND"] --> B["Build allowlisted environment<br/>(strip agent secrets, TZ=UTC)"]
    B --> C["Preflight: supplied env + .env/.env.test/.env.testing"]
    C -->|"live keys / APP_ENV=production / remote DB"| X["BLOCKED<br/>nothing executes"]
    C -->|safe| D["Network isolation<br/>macOS: sandbox-exec (loopback only)<br/>+ Python socket guard"]
    D --> E["Separate process group<br/>timeout → terminate whole tree"]
    E --> F["Capped logs + secret redaction"]
    F --> G{"Fresh JUnit report?"}
    G -->|"0 tests"| H1["blocked: no_tests"]
    G -->|"any unparseable report"| H6["blocked: report_unparseable"]
    G -->|"failures"| H2["fail"]
    G -->|"valid report, passing tests, exit 0"| H3["pass"]
    G -->|"no report, exit 0"| H4["warn: test count unverified"]
    E -->|"pass after retry"| H5["flaky → blocked"]
```

Dangerous effects always use simulators:

```mermaid
flowchart LR
    APP["App under test"] -->|"PAYMENT_API_BASE_URL=http://127.0.0.1:8787"| SIM["ds.py simulate payment"]
    SIM -->|"scenario: success_then_timeout / decline / rate_limited / slow_processing ..."| APP
    SIM -->|"HMAC-signed webhook: normal / duplicate / out_of_order"| APP
    SIM --> OUT["Email/SMS outbox<br/>(never real delivery)"]
```

## 4. Screenshots and baselines (verify-ui)

```mermaid
flowchart TD
    A["ds.py screenshot --url http://127.0.0.1:... --viewport mobile --viewport desktop"] --> B{"Local URL?"}
    B -->|No| X["Reject (exit 2)"]
    B -->|Yes| C["Fresh browser context<br/>viewport, locale, timezone, reduced motion"]
    C --> D["Block external-host requests<br/>(record in manifest)"]
    D --> E["Wait for selector/text + fonts<br/>disable animations/caret"]
    E --> F["Capture PNG + manifest<br/>(hash, browser, profile, console errors, page-text secret scan)"]
    F --> G{"--baseline-dir supplied?"}
    G -->|No| H["CAPTURE_ONLY<br/>(not a visual pass)"]
    G -->|Yes| I{"Baseline exists?"}
    I -->|No| J["NEEDS_BASELINE → human review"]
    J --> K["ds.py accept-baseline --approved-by NAME --reason ..."]
    K --> I
    I -->|Yes| L{"Same profile?"}
    L -->|No| M["PROFILE_MISMATCH"]
    L -->|Yes| N{"Difference ≤ threshold?"}
    N -->|Yes| P["PASS"]
    N -->|No| Q["FAIL + diff image"]
```

## 5. Confirm dangerous commands only on non-local servers

```mermaid
flowchart TD
    A["Identify the affected resource and command effect"] --> B{"Dangerous command on a known or suspected non-local server?"}
    B -->|"No: in-scope local work or read-only remote inspection"| C["Proceed without dangerous-command confirmation"]
    B -->|"Yes: dev, STG, prod or other remote/shared server"| D{"Same target and effect already authorized?"}
    D -->|"Yes"| E["Execute within existing authorization"]
    D -->|"No"| F["Show server and effect; await confirmation"]
    F -->|"User confirms"| E
```

Judge the affected resource, including remote targets reached through SSH, Docker/Kubernetes contexts, cloud CLIs or localhost tunnels. Clarify the server before a dangerous step if concrete signs suggest a remote target. Existing user restrictions and task scope still apply. The automatic Bash guard hook and blanket permission `ask` rules remain retired. Remove old settings with `python3 agent-skills.py guard --remove`; unrelated settings remain intact. Authorization persists across commands and turns.

## 6. Knowledge index (index-project-knowledge)

```mermaid
flowchart TD
    A["Need project documents"] --> B{".knowledge/INDEX.md exists?"}
    B -->|No| C{"docs/, specs/, tickets, Office/PDF?"}
    C -->|Yes| D["ds.py knowledge init --language en"]
    C -->|No| Z["Read originals directly"]
    D --> E["Create config.json + self-contained build.py<br/>mirror md/html/csv/docx/xlsx/pptx/pdf"]
    E --> F["Fill knowledge:manual block<br/>(reading order, synchronized documents)"]
    B -->|Yes| G["python3 .knowledge/build.py --check"]
    F --> G
    G -->|STALE| H["python3 .knowledge/build.py"]
    H --> G
    G -->|CURRENT| I["rg in .knowledge/mirrors"]
    I --> J["Verify wording, PDF pages, Excel cells in originals"]
    K["Add plans/specs/ADRs under docs/ or specs/"] --> H
```

## 7. Evidence and reporting

```mermaid
sequenceDiagram
    participant Agent
    participant DS as ds.py
    participant Run as .devskills/runs/ID
    Agent->>DS: run start --risk R2
    DS->>Run: run.json (revision, digest, python)
    Agent->>DS: roster init --run ID --risk R2
    DS->>Run: roster.json (required checks declared before execution)
    Agent->>DS: check-code / check-sql / preflight / run-tests ... --run ID
    DS->>Run: checks/CHECK_ID.json (gate + code digest at execution)
    Agent->>DS: report --run ID --summary-file summary.md
    DS->>Run: compare roster/results: missing → blocked, duplicate → blocked, changed code → stale, critical → fail
    DS-->>Agent: final-report.md + exit code (0 pass/warn, 3 fail, 4 blocked)
```

## 8. Installation, manual updates, rollback

```mermaid
flowchart TD
    A["Obtain new sources (git pull / copy)"] --> B["python3 agent-skills.py status"]
    B -->|"outdated"| C["python3 agent-skills.py update"]
    B -->|"up-to-date"| Z["No action needed"]
    C --> D{"Manually edited installed files?"}
    D -->|Yes| E["Stop and list files<br/>(move edits to source or use --force)"]
    D -->|No / --force| F["Back up under ~/.devskills/backups/TIMESTAMP"]
    F --> G["Install new version (vendored runtime + MANIFEST)"]
    G --> H["Self-check: ds.py --version + validate-skills"]
    H -->|error| I["python3 agent-skills.py rollback"]
    I --> J["Restore latest backup<br/>(current version also backed up)"]
```

## 9. Project conventions and native evidence

```mermaid
flowchart TD
    A["ds.py inspect --feature X"] --> B["Project conventions to reuse<br/>project bases/mixins · shared modules<br/>custom hooks · decorators · same-kind references<br/>existing enums/constants · patterns in use"]
    B --> C["Read bases + reference modules<br/>record conventions_to_follow"]
    C --> D["Extend/reuse existing bases<br/>(justify new bases/libraries — CTX-009)<br/>domain enums/constants, no bare literals — CODE-011<br/>follow source patterns; name unsolved problems for new patterns/libraries — DES-007/008<br/>add beside running logic, connect once — CHG; measure with ds.py footprint"]
    D --> E["ds.py native-checks (preview)"]
    E -->|"deploy/publish/curl in script"| X["Do not execute; report to user"]
    E -->|"missing node_modules/vendor/venv, classic .NET"| Y["blocked + reason"]
    E --> F["--execute --run ID<br/>safe runner (env allowlist, network blocking, timeout)"]
    F --> G["checks/native.*.json"]
    G --> H["ds.py trace --file acceptance.json"]
    H --> I["verified / weak / failed / unverified<br/>+ tag coverage warnings"]
    I --> J["ds.py report → Acceptance traceability"]
```

Debugging and refactoring:

```mermaid
flowchart LR
    subgraph bug["Debugging (dev-orchestrate)"]
        B1["Reproduce with a failing test"] --> B2["Trace the flow"] --> B3["Test hypotheses<br/>one change at a time"] --> B4["Fix the root cause"] --> B5["Regression test + native-checks"]
    end
    subgraph refactor["Refactor (write-maintainable-code)"]
        R1["Pin old code/snapshot<br/>Preserved cases vs authorized differences"] --> R2["Separate baseline run<br/>Characterization tests + source hashes"] --> R3["Map callers; small steps<br/>Same assertions on current code"] --> R4["trace: preservation/refactor<br/>Exact passes on both snapshots<br/>Unchanged test sources"]
    end
```

Maintenance and updates use the same preservation contract for behavior outside the requested change. Actual old code is the baseline; report spec/code discrepancies without silently changing behavior. `preservation`/`refactor` criteria link a separate baseline run, check and pinned source state; current-only passes cannot verify them. Bugfix `regression` criteria may intentionally fail on old code and remain separate. See [the baseline schema and limits](../skills/write-maintainable-code/references/refactoring-workflow.md#5-prove-it).
