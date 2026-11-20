#!/usr/bin/env python3
"""Skill gate: make Claude load the right skills with the Skill tool, at the right time.

Skills are routed by WHAT THE DEVELOPER ASKS FOR, never by class names or file contents:
  - the request  - the user's prompt (accent-insensitive Vietnamese + English) decides the domain and
                   superpowers skills; a code edit additionally needs the base edit skills (BASE_EDIT)
  - the command  - running tests, a database CLI or a commit needs test-safely / change-database / review-code
The skills' own descriptions carry Vietnamese triggers too, so Claude matches them natively; the
hooks are the safety net. They set a floor: Claude still loads whatever else the task touches.

Subcommands (hook payload JSON on stdin):
  prompt    UserPromptSubmit  -> route the request; tell Claude which skills it touches
  gate      PreToolUse        -> deny code edits / test, DB, commit commands until routed skills are loaded
  subagent  SubagentStart     -> tell a subagent to load its own skills
  compact   SessionStart      -> after compaction: soft reminder (loaded skills stay valid)
  stop      Stop              -> block finishing a request whose skills were never loaded, or a
                                 "Skills applied" list naming skills that were never loaded (once per stop)

Escape hatch: env SKILL_GATE=off, or `touch ~/.claude/state/skill-gate/disabled`.
Every error path fails open (never blocks the user because the hook itself broke).
"""
import json
import os
import re
import subprocess
import sys
import unicodedata

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude", "state", "skill-gate")

ALL_SKILLS = [
    "dev-orchestrate", "discover-codebase", "design-change", "change-database",
    "design-api", "implement-backend", "implement-frontend", "verify-ui",
    "design-reliability", "review-performance", "review-security", "test-safely",
    "design-infrastructure", "write-maintainable-code", "code-style", "index-project-knowledge",
    "review-code", "e2e-evidence", "task-spec", "code-documentation",
]
BASE_EDIT = ["dev-orchestrate", "discover-codebase", "write-maintainable-code", "code-style"]

# superpowers process skills, combined with devskills: dev-orchestrate routes first, then the process
# skill (how to work), then the domain skills (what rules apply), then verification before handover.
SP_DEBUG = "superpowers:systematic-debugging"
SP_BRAINSTORM = "superpowers:brainstorming"
SP_TDD = "superpowers:test-driven-development"
SP_PLAN = "superpowers:writing-plans"
SP_VERIFY = "superpowers:verification-before-completion"
SP_RECEIVE_REVIEW = "superpowers:receiving-code-review"
SUPERPOWERS = [SP_DEBUG, SP_BRAINSTORM, SP_TDD, SP_PLAN, SP_VERIFY, SP_RECEIVE_REVIEW]

# These skills have their own verification or evidence phase.
AFTER_WORK = {"verify-ui", "review-code", "e2e-evidence", SP_VERIFY}


def superpowers_enabled():
    """True when the superpowers plugin is enabled in the user's Claude Code settings.

    Its skills are required only then: requiring a skill that cannot be loaded would block every edit.
    """
    try:
        with open(os.path.join(HOME, ".claude", "settings.json"), encoding="utf-8") as fh:
            plugins = json.load(fh).get("enabledPlugins") or {}
    except Exception:
        return False
    return any(name.split("@")[0] == "superpowers" and on is True for name, on in plugins.items())

CODE_EXT = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".py", ".kt",
    ".kts", ".java", ".swift", ".dart", ".go", ".rs", ".php", ".rb", ".cs", ".sql",
    ".css", ".scss", ".html", ".gradle", ".tf",
}
SKIP_PARTS = (
    "/.claude/", "/.devskills/", "/.knowledge/", "/node_modules/", "/.git/",
    "/.playwright-mcp/", "/private/tmp/", "/tmp/", "/scratchpad/", "/build/", "/dist/",
    "/.next/", "/graphify-out/", "/.codegraph/",
    "/tools/skill-gate/",  # the gate's own source holds the patterns below and would match itself
)

# --------------------------------------------------------------------------- 1. the request
# Keywords are matched on accent-folded lowercase text ("Xóa dữ liệu" -> "xoa du lieu"), so they are
# written without accents. Multi-word keywords avoid folded collisions ("bang" = table/equal, "trang"
# = page/state), which is why several areas list phrases instead of single words.
PROMPT_AREAS = {
    "change-database": [
        # Deleting or listing records is a data change even when nobody says "database" (dev-orchestrate's
        # own example: "delete test surveys from the result list").
        "danh sach", "nhap du lieu", "xuat du lieu", "bao cao",
        "thong ke", "re:(them|xoa|doi|sua)\\s+cot",
        "database", "db", "csdl", "co so du lieu", "du lieu", "data", "sql", "query", "truy van", "migration",
        "migrate", "schema", "bang du lieu", "table", "cot du lieu", "column", "index", "khoa ngoai",
        "khoa chinh", "foreign key", "transaction", "lock", "deadlock", "ban ghi", "record",
        "xoa du lieu", "xoa ban ghi", "backup", "restore", "sao luu", "khoi phuc", "room db", "prisma", "orm",
        "crud", "sqlite", "postgres", "mysql", "mongodb", "redis",
        "khoa ban ghi", "toan ven du lieu", "chi muc", "phan trang du lieu", "connection pool",
        "rollback", "upsert", "soft delete", "nang cap schema",
    ],
    "design-api": [
        "api", "endpoint", "webhook", "rest", "graphql", "openapi", "swagger", "route", "status code", "idempotent", "idempotency", "phan trang", "pagination",
        "request body", "response body", "http header", "ma loi", "hop dong api",
    ],
    "implement-backend": [
        "api", "backend", "back end", "server", "may chu", "service", "job", "batch", "cron", "scheduler",
        "worker", "upload", "tai len", "xu ly nen", "background", "chay ngam", "dong bo", "sync",
        "nghiep vu", "business logic", "controller", "handler", "middleware", "hangfire", "celery",
    ],
    "implement-frontend": [
        "re:trang(?!\\s+thai)", "setting", "cai dat", "dieu khoan", "gioi thieu", "noi dung", "app", "ung dung",
        "apk", "ipa", "aab",
        "man hinh", "giao dien", "ui", "ux", "screen", "page", "trang web", "trang chu", "component", "form",
        "nut", "button", "layout", "responsive", "dark mode", "theme", "css", "mobile", "android", "ios",
        "compose", "swiftui", "react", "nextjs", "next js", "vue", "widget", "lockscreen", "man hinh khoa",
        "hien thi", "menu", "dialog", "popup", "tab", "icon", "font", "mau sac", "animation", "web",
        "vo layout", "vo giao dien", "xuong dong", "tran chu", "can le", "khoang cach", "co chu",
        "loading state", "empty state", "error state", "accessibility", "a11y", "tablet", "tailwind",
    ],
    "verify-ui": [
        "kiem tra ui", "kiem tra giao dien", "kiem tra responsive", "review ui", "review ux", "review giao dien",
        "review man hinh", "review layout", "ui review", "ux review", "visual review", "check ui", "inspect ui",
        "chup man hinh", "chup anh ui", "screenshot", "visual regression", "vo layout", "vo giao dien", "tran chu",
    ],
    "design-reliability": [
        "re:google\\s+driv\\w*", "drive", "backup", "sao luu", "khoi phuc", "restore", "upload", "tai len",
        "retry", "thu lai", "timeout", "het thoi gian", "queue", "hang doi", "outbox", "fallback",
        "thanh toan", "payment", "email", "sms", "push", "notification", "thong bao", "nhac nho", "reminder",
        "google drive", "firebase", "external", "ben thu ba", "third party", "goi api", "ket noi",
        # Duplicate effects only: "trùng lặp" / "duplicate" alone is usually duplicated code (write-maintainable-code).
        "mat ket noi", "offline", "dong bo", "sync", "chay hai lan", "tao trung", "ghi trung",
        "duplicate request", "duplicate payment", "duplicate charge", "duplicate message", "duplicate job",
        "gui trung", "chay trung", "mat mang", "dut ket noi", "thu lai tu dong", "circuit breaker",
        "partial failure", "compensation", "dead letter",
    ],
    "review-security": [
        "bao mat", "security", "dang nhap", "login", "logout", "dang ky", "signup", "auth", "token", "mat khau",
        "password", "phan quyen", "quyen", "permission", "role", "phien dang nhap", "session token", "cookie", "cors", "xss",
        "injection", "secret", "api key", "ma hoa", "encrypt", "du lieu ca nhan", "privacy", "oauth", "jwt",
        "xac thuc", "xac quyen", "kiem soat truy cap", "authorization", "authentication", "csrf",
        "ssrf", "rate limit", "multi tenant", "multi-tenant", "tenant isolation", "path traversal",
    ],
    "review-performance": [
        "cham", "slow", "hieu nang", "performance", "toi uu", "optimize", "memory", "bo nho", "leak",
        "cache", "n+1", "thread", "async", "lag", "giat", "treo", "hang", "cpu", "tai nhanh",
        "ro ri bo nho", "ton bo nho", "qua tai", "nghen", "thread pool", "connection pool",
        "latency", "throughput", "bottleneck", "profiling",
    ],
    "test-safely": [
        "test", "kiem thu", "e2e", "unit test", "playwright", "tdd", "mock", "seed", "chay test",
        "viet test", "regression", "fixture",
        "kiem chung", "tai hien", "reproduce", "repro", "smoke test", "integration test", "snapshot test",
    ],
    "task-spec": [
        # A ticket's written plan from its requirement, not code work itself.
        "require.md", "plan.html", "sub task", "sub_tasks", "subtask", "tao spec", "viet spec", "write spec",
        "chia task", "break task", "estimate task",
        r"re:(?:plan|ke hoach|spec|dac ta)\s+(?:(?:cho|for)\s+)?(?:ticket|task)",
    ],
    "write-maintainable-code": [
        "docstring", "jsdoc", "tsdoc", "phpdoc", "javadoc", "godoc", "kdoc", "xml doc", "doc comment",
        "viet comment", "them comment", "sua comment", "comment code", "chu thich", "tai lieu code",
        "document code", "code documentation", "refactor", "code sach", "de bao tri", "code trung lap",
    ],
    "code-style": [
        "dat ten", "doi ten bien", "doi ten ham", "naming", "coding style", "code style", "convention", "lambda",
    ],
    "e2e-evidence": [
        # Running or verifying a test checklist with screenshots per step. Writing an E2E suite is test-safely;
        # A screenshot to judge a layout is verify-ui.
        "chay e2e", "run e2e", "verify e2e", "teste2e", "test e2e", "chay playwright", "run playwright",
        "tao checklist", "create checklist",
        "test thu cong", "manual test", "chup anh tung step", "chup anh tung buoc",
        "chup man hinh tung step", "chup man hinh tung buoc", "screenshot tung step", "test theo checklist",
        "danh gia ok", "ok hay ng", "ok/ng",
    ],
    "design-change": [
        "thiet ke", "design", "de xuat", "proposal", "phuong an", "kha thi", "feasibility", "ke hoach", "plan",
        "spec", "dac ta", "estimate", "uoc luong", "kien truc", "architecture", "adr", "backlog",
        "danh gia anh huong", "impact", "tac dong", "anh huong",
        "chia task", "giai phap", "tradeoff", "trade-off", "decision memo", "technical proposal",
    ],
    "review-code": [
        "review", "ra soat", "pull request", "merge request", "diff", "commit", "truoc khi merge",
        "tu review", "kiem tra code", "code review", "truoc khi ban giao",
    ],
    "index-project-knowledge": [
        # Project documents, not product features ("tạo pdf" is a feature): only words that name the docs.
        "tai lieu", "docs", "specs", "requirement", "yeu cau du an", "dac ta yeu cau", "file thiet ke",
        "knowledge index", "index tai lieu", "tai lieu du an", "file excel", "file word", "file pdf",
    ],
    "discover-codebase": [
        "tim trong code", "tim code", "doc code", "doc source", "xem code", "code nay chay", "codebase",
        "luong hien tai", "trace flow", "trace code",
    ],
    "design-infrastructure": [
        "terraform", "aws", "gcp", "vpc", "subnet", "iam", "rds", "ec2", "kubernetes", "k8s", "cloudformation",
        "ha tang", "infrastructure", "cloud sql",
        "security group", "cloud run", "cloudformation", "pulumi", "bucket", "ecs", "gke",
    ],
}
# Verbs that make a prompt a piece of work (not a question about something). Without one the
# areas are only suggested; with one they are required by the end of the request.
WORK_WORDS = [
    "them", "sua", "fix", "trien khai", "implement", "viet", "tao", "xay dung", "build", "code",
    # Not "lam" alone: "làm sao" / "để làm gì" ask how/why. Only imperative uses count.
    "lam di", "lam luon", "lam tiep", "lam lai", "lam giup", "hay lam",
    "refactor", "xoa", "doi", "thay doi", "change", "update", "cap nhat", "nang cap", "chuyen", "tich hop",
    "integrate", "add", "remove", "review", "ra soat", "test", "kiem thu", "kiem tra", "thiet ke", "design",
    "de xuat", "phan tich", "analyze", "danh gia", "uoc luong", "estimate", "spec", "ke hoach", "plan",
    "toi uu", "optimize", "debug", "commit", "deploy", "port", "ho tro", "bo sung", "gop", "tach",
    # Requests phrased as wishes or needs ("nên có", "cần", "muốn", "giúp") are work too.
    # Not "can"/"nen" alone: "ko cần" (no need) and "nên không" are questions, not requests.
    "nen co", "nen them", "can them", "can sua", "muon", "giup", "yeu cau", "chinh sua", "hien thi", "rename",
    "kiem chung", "tai hien", "reproduce", "repro", "chay", "run", "chup", "screenshot", "check", "verify",
    "doc", "read", "tim", "find", "xem", "inspect", "trace", "len plan", "write", "create", "document",
]
# Phrases removed before matching because a keyword inside them means something else
# ("chính sách bảo mật" is a privacy-policy page, not security work).
IGNORED_PHRASES = re.compile(r"chinh\s+sach\s+bao\s+mat|privacy\s+policy|trang\s+thai")
# Phrases removed for one area only when they name work owned by another skill.
AREA_IGNORED_PHRASES = {
    "review-code": re.compile(r"\breview\s+(?:lai\s+)?(?:giao\s+dien|ui|ux|man\s+hinh|layout)\b|\b(?:ui|ux|visual)\s+review\b"),
    "change-database": re.compile(r"\bindex\s+(?:(?:cho|for)\s+)?(?:tai\s+lieu|docs)\b|\bknowledge\s+index\b"),
    "index-project-knowledge": re.compile(r"\btai\s+lieu\s+code\b"),
}
BUILD_WORDS = [
    "them", "sua", "fix", "trien khai", "implement", "viet", "tao", "xay dung", "build",
    "lam di", "lam luon", "lam tiep", "lam lai", "lam giup", "hay lam",
    "refactor", "xoa", "doi", "thay doi", "cap nhat", "nang cap", "tich hop", "add", "remove", "toi uu",
    "port", "bo sung", "gop", "tach", "write", "create", "rename", "document",
]
# Process signals for superpowers. A bug report is work even when phrased as a question ("vì sao ... ko được").
BUG_WORDS = [
    "bug", "sua loi", "bi loi", "gap loi", "bao loi", "loi khi", "fix", "crash", "khong chay", "ko chay",
    "khong duoc", "ko duoc", "ko dc", "khong hoat dong", "ko hoat dong", "sai", "fail", "failed", "failing",
    "error", "exception", "debug", "broken", "hong", "khong hien", "ko hien", "tra ve sai", "bi sai",
    # Not "vì sao" / "tại sao" alone: users ask why about designs and choices far more than about failures.
]
FEATURE_WORDS = [
    "chuc nang", "tinh nang", "feature", "y tuong", "xay dung", "tao moi", "app moi", "man hinh moi",
    "trang moi", "phien ban", "version", "co the them",
]
PLAN_WORDS = ["ke hoach", "plan", "lo trinh", "roadmap", "nhieu buoc", "spec", "dac ta", "backlog", "chia task"]
REVIEW_FEEDBACK_WORDS = [
    "review comment", "nhan xet", "gop y", "feedback", "reviewer", "codex review", "ket qua review",
    "comment tren pr", "sua theo review",
]


def fold(text):
    """Lowercase, đ -> d, strip accents: 'Xóa dữ liệu' -> 'xoa du lieu'."""
    text = (text or "").lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _words_re(words):
    """One regex for a keyword list; an entry starting with 're:' is a raw regex, the rest are literal."""
    def one(word):
        return word[3:] if word.startswith("re:") else re.escape(word).replace(r"\ ", r"\s+")
    alternatives = "|".join(one(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9])(" + alternatives + r")(?![a-z0-9])")


# A request phrased as a confirmation question ("chỉ sửa UI ... đúng ko", "đã sửa xong?") asks about work,
# it does not order it; an imperative marker ("... đi", "giúp", "hãy") turns it back into a request.
QUESTION_TAIL_RE = re.compile(
    r"(dung\s+(ko|khong)|phai\s+(ko|khong)|chua|xong|nghia\s+la\s+sao|la\s+sao|de\s+lam\s+gi|lam\s+gi|la\s+gi"
    r"|o\s+dau|the\s+nao|ra\s+sao|bao\s+nhieu|roi\s+chu|dung\s+chu)"
    r"(\s+(vay|a|nhi|ha|the|day|z|ha|chu))*\W*$")
IMPERATIVE_RE = re.compile(r"(?<![a-z0-9])(di|giup|hay|vui\s+long|nhe|luon|please)(?![a-z0-9])")
# Claude Code wraps pasted text as <pasted_content id="…">…</pasted_content id="…">. A pasted checklist, log or
# document names many areas and imperatives that are not the user's request, so only the user's own words are
# routed; the pasted text is routed only when the message contains nothing else.
PASTED_RE = re.compile(r'<pasted_content id="([^"]*)">(.*?)</pasted_content id="\1">', re.S)


def own_words(prompt):
    """The user's own text of a prompt, or the pasted text when the user wrote nothing besides it."""
    own = PASTED_RE.sub(" ", prompt or "")
    if own.strip():
        return own
    return " ".join(m.group(2) for m in PASTED_RE.finditer(prompt or ""))

PROMPT_AREA_RES = {skill: _words_re(words) for skill, words in PROMPT_AREAS.items()}
WORK_RE = _words_re(WORK_WORDS)
BUILD_RE = _words_re(BUILD_WORDS)
BUG_RE = _words_re(BUG_WORDS)
FEATURE_RE = _words_re(FEATURE_WORDS)
PLAN_RE = _words_re(PLAN_WORDS)
REVIEW_FEEDBACK_RE = _words_re(REVIEW_FEEDBACK_WORDS)
PLAN_REQUEST_RE = re.compile(
    r"^(?:(?:hay|please|giup|vui\s+long)\s+)?(?:"
    r"(?:(?:len|lap|viet|tao|write|create(?:\s+a)?)\s+)?(?:ke\s+hoach|plan|spec|dac\s+ta|roadmap|backlog)|"
    r"chia\s+task|phan\s+tich\s+yeu\s+cau|(?:estimate|uoc\s+luong)\s+task)\b"
)
DOC_READ_RE = re.compile(r"^(?:doc|read|xem|open|tim|find)\s+(?:(?:the|file)\s+)*(?:spec|plan\.html|require\.md)\b")
FOLLOW_UP_RE = _words_re(["lam di", "lam luon", "lam tiep", "sua luon di", "tiep tuc", "go ahead", "continue"])
ARTIFACT_ONLY_RE = re.compile(r"\b(?:tao|create|build|cap\s+nhat|update)\s+(?:(?:a|the)\s+)?(?:checklist|(?:knowledge\s+)?index)\b")
TEST_AUTHORING_RE = re.compile(r"\b(?:viet|write|them|add)\s+(?:(?:them|cac|an?|some)\s+)*(?:test|e2e|unit\s+test)\b")
TEST_EXECUTION_RE = re.compile(r"\b(?:chay|run|verify)\s+(?:(?:lai|the)\s+)*(?:test|e2e|playwright)\b")
DATA_DELETE_RE = _words_re([
    r"re:(?:xoa|delete)\s+(?:(?:cac|all|the)\s+)*(?:khao\s+sat|surveys?|du\s+lieu|records?|"
    r"nguoi\s+dung|users?|khach\s+hang|customers?|don\s+hang|orders?)",
])
DOC_REQUEST_RE = re.compile(
    r"\b(?:them|viet|bo\s+sung|add|write)\s+(?:(?:them|cac|an?|more)\s+)*"
    r"(?:comment[s]?|docstring[s]?|chu\s+thich|ghi\s+chu|jsdoc|tsdoc|phpdoc|javadoc|kdoc)\b"
)


def area_text(skill, text):
    """The request text one area is matched against, without the phrases another skill owns."""
    ignored = AREA_IGNORED_PHRASES.get(skill)
    if ignored is None:
        return text
    return ignored.sub(" ", text)


def route_prompt(prompt):
    """Read a user request into routing signals.

    areas: domain skills whose keywords occur; work: it asks for work, not only a question;
    build: the work changes code; bug / feature / plan / review_feedback: which process applies.
    """
    text = fold(own_words(prompt)).strip()
    if text.startswith("[request interrupted"):
        text = ""  # Claude Code's own marker, not a request
    matched = IGNORED_PHRASES.sub(" ", text)
    bug = bool(BUG_RE.search(text))
    asks_only = bool(QUESTION_TAIL_RE.search(text)) and not IMPERATIVE_RE.search(text)
    areas = [skill for skill, pattern in PROMPT_AREA_RES.items() if pattern.search(area_text(skill, matched))]
    plan_only = bool(PLAN_REQUEST_RE.search(text))
    writes_tests = bool(TEST_AUTHORING_RE.search(text))
    runs_tests = bool(TEST_EXECUTION_RE.search(text))
    artifact_only = bool(ARTIFACT_ONLY_RE.search(text)) and set(areas) <= {"e2e-evidence", "index-project-knowledge"}
    build = bool(BUILD_RE.search(text)) and not (plan_only or artifact_only)

    if DATA_DELETE_RE.search(text) and "change-database" not in areas:
        areas.append("change-database")
    if DOC_READ_RE.search(text):
        areas = [skill for skill in areas if skill not in {"task-spec", "design-change"}]
        areas.append("index-project-knowledge")
    if plan_only:
        areas = [skill for skill in areas if skill not in {"e2e-evidence", "verify-ui"}]
    if writes_tests and not runs_tests and "e2e-evidence" in areas:
        areas.remove("e2e-evidence")
    if "implement-frontend" in areas:
        visual_review = "verify-ui" in areas
        ui_e2e = "e2e-evidence" in areas and not plan_only
        asks_how_to_change = "lam sao" in text or "how to" in text
        if visual_review or ui_e2e or (not writes_tests and (build or asks_how_to_change)):
            areas.append("verify-ui")
        if (visual_review or ui_e2e or writes_tests) and (not build or writes_tests):
            areas.remove("implement-frontend")

    # A plan may describe future edits, tests and UI. Its output is the plan itself.
    if plan_only and "design-change" not in areas:
        areas.append("design-change")
    if (writes_tests or runs_tests or "e2e-evidence" in areas) and "test-safely" not in areas:
        areas.append("test-safely")
    documentation_only = bool(DOC_REQUEST_RE.search(text)) and areas == ["write-maintainable-code"]
    return {
        "areas": dedupe(areas),
        "work": (bool(WORK_RE.search(text)) or bug or plan_only or bool(FOLLOW_UP_RE.search(text))) and not asks_only,
        "build": build and not asks_only,
        "bug": bug,
        "feature": bool(FEATURE_RE.search(text)),
        "plan": plan_only or (bool(PLAN_RE.search(text)) and "design-change" in areas and "task-spec" in areas),
        "documentation": bool(DOC_REQUEST_RE.search(text)),
        "documentation_only": documentation_only,
        "follow_up": bool(FOLLOW_UP_RE.fullmatch(text.rstrip(".!? ").removeprefix("ok "))),
        "review_feedback": bool(REVIEW_FEEDBACK_RE.search(text)),
    }


def skills_for_request(route, with_superpowers=False):
    """The full set a request needs by its end: dev-orchestrate's routing, plus superpowers' process skills."""
    areas = route["areas"]
    # Topic-free follow-ups inherit only when cmd_prompt recognizes a continuation.
    if route["follow_up"] or (not areas and not (route["work"] and route["build"])):
        return []
    req = ["dev-orchestrate"]
    if route["build"] or route["plan"] or route["bug"]:
        req.append("discover-codebase")
    req += areas
    if route["feature"] or route["plan"]:
        req.append("design-change")
    if route["build"]:
        req += ["write-maintainable-code", "code-style", "test-safely", "review-code"]
    process = []
    if with_superpowers:
        # A ticket's plan is task-spec's plan.html (ROUTE-002); brainstorming and writing-plans would write a
        # second design/plan file under docs/superpowers/.
        plan_owned_by_task_spec = "task-spec" in areas
        if route["bug"] and not route["plan"]:
            process.append(SP_DEBUG)
        elif route["feature"] and not plan_owned_by_task_spec:
            process.append(SP_BRAINSTORM)
        if route["plan"] and not plan_owned_by_task_spec:
            process.append(SP_PLAN)
        if route["review_feedback"]:
            process.append(SP_RECEIVE_REVIEW)
        if route["build"] and not route["documentation_only"]:
            req.append(SP_TDD)
        if route["build"]:
            req.append(SP_VERIFY)
    return dedupe(req[:1] + process + [s for s in req[1:] if s not in AFTER_WORK]
                  + [s for s in req[1:] if s in AFTER_WORK])


# --------------------------------------------------------------------------- 2. the command
TEST_CMD_RE = re.compile(
    r"\b(pytest|unittest|vitest|jest|mocha|playwright\s+test|(npm|pnpm|yarn|bun)\s+(run\s+)?test\w*|go\s+test"
    r"|cargo\s+test|gradlew?\s+[^|;&]*\b(test|connected\w*Test|check)\w*|xcodebuild\s+[^|;&]*\btest|phpunit"
    r"|rspec|dotnet\s+test|mvn\s+[^|;&]*\btest|ds\.py\s+run-tests)", re.I)
E2E_CMD_RE = re.compile(r"\b(?:playwright\s+test|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:e2e|test:e2e))\b", re.I)
DB_CMD_RE = re.compile(
    r"\b(psql|mysql|sqlite3|mongosh|redis-cli|prisma\s+(migrate|db)|manage\.py\s+(migrate|makemigrations|flush|dbshell)"
    r"|alembic|flyway|liquibase|knex\s+migrate|sequelize\s+db|artisan\s+(migrate|db))\b", re.I)
COMMIT_RE = re.compile(r"\bgit\s+commit\b")
_EXT_ALT = "|".join(sorted(e[1:] for e in CODE_EXT))
BASH_WRITE_RE = re.compile(r"(?:>>?|\btee\s+(?:-a\s+)?)\s*['\"]?([^\s'\";|&<>]+\.(?:%s))\b" % _EXT_ALT)
INPLACE_RE = re.compile(r"\b(sed\s+-i|perl\s+-[a-z]*i)")
CODE_TOKEN_RE = re.compile(r"['\"]?([^\s'\";|&<>]+\.(?:%s))\b" % _EXT_ALT)


# --------------------------------------------------------------------------- state + transcript
def read_payload():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def disabled():
    return os.environ.get("SKILL_GATE") == "off" or os.path.exists(os.path.join(STATE_DIR, "disabled"))


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.exit(0)


def norm(name):
    return (name or "").split(":")[-1].strip()


def dedupe(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def state_path(session_id):
    return os.path.join(STATE_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown") + ".json")


def load_state(session_id):
    try:
        with open(state_path(session_id)) as fh:
            state = json.load(fh)
        # Older hook copies could persist code-documentation as a blocking requirement.
        for key in ("last_request", "request_required"):
            if key in state:
                state[key] = [skill for skill in state[key] if skill != "code-documentation"]
        return state
    except Exception:
        return {}


def save_state(session_id, st):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(state_path(session_id), "w") as fh:
            json.dump(st, fh)
    except Exception:
        pass


def scan_file(path, offsets, loaded):
    """Incrementally scan a transcript; add skill names loaded via Skill tool or SKILL.md reads."""
    if not path or not os.path.exists(path):
        return
    start = offsets.get(path, 0)
    if start > os.path.getsize(path):
        start = 0
    with open(path, "rb") as fh:
        fh.seek(start)
        for raw in fh:
            if b'"Skill"' not in raw and b"SKILL.md" not in raw:
                continue
            try:
                d = json.loads(raw)
            except Exception:
                continue
            if d.get("type") != "assistant":
                continue
            content = d.get("message", {}).get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if part.get("type") != "tool_use":
                    continue
                inp = part.get("input") or {}
                if part.get("name") == "Skill":
                    loaded.add(norm(inp.get("skill")))
                elif part.get("name") in ("Read", "Bash"):
                    for m in re.finditer(r"skills/([a-z-]+)/SKILL\.md", json.dumps(inp)):
                        loaded.add(m.group(1))
        offsets[path] = fh.tell()


def loaded_skills(p, st=None):
    sid = p.get("session_id") or ""
    st = st if st is not None else load_state(sid)
    offsets = st.get("offsets", {})
    loaded = set(st.get("loaded", []))
    tp = p.get("transcript_path")
    try:
        scan_file(tp, offsets, loaded)
        agent_id = p.get("agent_id")
        if agent_id and tp:
            scan_file(os.path.join(os.path.dirname(tp), sid, "subagents", "agent-%s.jsonl" % agent_id), offsets, loaded)
    except Exception:
        pass
    st["offsets"], st["loaded"] = offsets, sorted(loaded)
    save_state(sid, st)
    return loaded


# --------------------------------------------------------------------------- routing of an edit
def required_for(path, task=()):
    """Skills a code edit needs for the current request.

    Routing comes from the request (the prompt), never from class names or file contents; skills that
    belong after the work (verify-ui, review-code, verification) are left for the end of the request.
    """
    return dedupe(["dev-orchestrate"] + [s for s in task if s not in AFTER_WORK] + BASE_EDIT[1:])


def required_for_command(command, task=()):
    """Skills a Bash command needs by what it does; [] when it does nothing the gate cares about."""
    req = []
    e2e = E2E_CMD_RE.search(command)
    if e2e or TEST_CMD_RE.search(command):
        req += ["dev-orchestrate", "test-safely"]
        if e2e:
            req.extend(skill for skill in task if skill in {"e2e-evidence", "verify-ui"})
    if DB_CMD_RE.search(command):
        req += ["dev-orchestrate", "change-database"]
    if COMMIT_RE.search(command):
        req += ["dev-orchestrate", "review-code"]
    targets = [m.group(1) for m in BASH_WRITE_RE.finditer(command)]
    if INPLACE_RE.search(command):
        targets += [m.group(1) for m in CODE_TOKEN_RE.finditer(command)]
    for target in targets:
        if not any(part in target.lower() for part in SKIP_PARTS):
            req += required_for(target, task)
    return dedupe(req)


# --------------------------------------------------------------------------- hook commands
RULE = (
    "SKILL GATE: load dev-orchestrate first with the Skill tool. Follow ROUTE-001/002 for process, domain, "
    "implementation and verification phases. Route from the current request and confirmed effects. "
    "Print `Skills: ...` before the first edit and list only loaded skills under `Skills applied`. "
    "Load code-documentation for new code that needs documentation or when the user explicitly asks to add comments or docstrings, "
    "if the skill is available. Keep the comments in scope. For routine maintenance, follow write-maintainable-code. Code edits and "
    "test/DB/commit commands are blocked until their skills are loaded."
)


def cmd_prompt(p):
    sid = p.get("session_id") or ""
    route = route_prompt(p.get("prompt") or "")
    areas, is_work = route["areas"], route["work"]
    needed = skills_for_request(route, superpowers_enabled())
    st = load_state(sid)
    if is_work and route["follow_up"]:
        # A follow-up such as "ok làm đi" / "sửa luôn đi" names no area: it continues the previous request.
        needed = st.get("last_request", [])
        areas = [s for s in needed if s in PROMPT_AREAS]
    if is_work and needed:
        st["last_request"] = needed
    # Required by the end of THIS request only when it asks for work; a question gets a suggestion.
    st["request_required"] = needed if is_work else []
    save_state(sid, st)
    text = RULE
    if needed:
        loaded = loaded_skills(p, st)
        todo = [s for s in needed if norm(s) not in loaded]
        if areas:
            text += "\nThis request touches: %s." % ", ".join(areas)
        if todo:
            text += (" %s each with the Skill tool before its phase: %s (plus any skill actual scope requires). "
                     "If one clearly does not apply, say why in one line." % ("Load" if is_work else "Likely load",
                                                                                ", ".join(todo)))
    if is_work and route["documentation"]:
        text += "\nThis request explicitly adds code comments or docstrings. Load code-documentation if available."
    emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}})


# --------------------------------------------------------------------------- automatic style routing
# The code-style skill's runtime detects the file's language, its project root's frameworks and the
# repository's style tools; the gate passes that to Claude the first time a (root, language) is edited.
CODE_STYLE_DS_ENV = "DEVSKILLS_CODE_STYLE_DS"
STYLE_HINT_TIMEOUT_SECONDS = 8
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


AGENT_HOME_DIRS = (".claude", ".codex", ".agents")  # where an installed code-style skill is looked up, in order


def code_style_ds(cwd):
    """The code-style skill's ds.py: explicit override, project install, then user installs; None when absent."""
    candidates = [
        os.environ.get(CODE_STYLE_DS_ENV) or "",
        os.path.join(cwd or "", ".claude", "skills", "code-style", "scripts", "ds.py") if cwd else "",
    ]
    for agent_dir in AGENT_HOME_DIRS:
        candidates.append(os.path.join(HOME, agent_dir, "skills", "code-style", "scripts", "ds.py"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def style_lookup_directory(path, cwd):
    """Where to run the lookup: the session directory when it contains the file, else the file's nearest folder."""
    if cwd and os.path.abspath(path).startswith(os.path.abspath(cwd) + os.sep):
        return cwd
    directory = os.path.dirname(os.path.abspath(path))
    while directory and not os.path.isdir(directory):
        directory = os.path.dirname(directory)
    return directory or None


def style_hint(p, path, st):
    """Context naming the style references for this file; None when already given for its root and language."""
    ds = code_style_ds(p.get("cwd"))
    lookup_directory = style_lookup_directory(path, p.get("cwd"))
    if not ds or not lookup_directory:
        return None
    completed = subprocess.run([sys.executable, ds, "style", "--path", os.path.abspath(path), "--json"],
                               cwd=lookup_directory, capture_output=True, text=True,
                               timeout=STYLE_HINT_TIMEOUT_SECONDS, check=False)
    if completed.returncode != 0:
        return None
    result = json.loads(completed.stdout)
    if not result.get("language"):
        return None
    hint_key = "%s|%s|%s" % (result.get("repository"), result["root"], result["language"])
    hinted = st.setdefault("style_hinted", [])
    if hint_key in hinted:
        return None
    hinted.append(hint_key)
    save_state(p.get("session_id") or "", st)
    references_dir = os.path.join(os.path.dirname(os.path.dirname(ds)), "references")
    frameworks = ", ".join(result["frameworks"]) or "none detected"
    text = ("CODE STYLE (auto-detected from the source): %s is %s in project root `%s` (frameworks: %s). "
            "Before writing it, read %s in %s and apply them." % (
                result["path"], result["language"], result["root"], frameworks,
                ", ".join(result["references"]), references_dir))
    if result.get("style_tools"):
        text += " The repository's own style tools win where they differ: %s." % ", ".join(result["style_tools"])
    return text


# --------------------------------------------------------------------------- Codex
# Codex edits files with apply_patch, whose tool_input.command is the patch text. Codex has no Skill tool and
# its transcript format is not a stable interface, so nothing is enforced there: the hook only adds the style
# references, as non-blocking context, the first time a (root, language) is patched in a session.
CODEX_STATE_DIR = os.path.join(HOME, ".codex", "state", "skill-gate")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+?)\s*$", re.M)


def patch_paths(command):
    """Files an apply_patch command writes: added, updated and the destination of a move; deletions are ignored."""
    return dedupe(PATCH_FILE_RE.findall(command or ""))


def cmd_codex_style(p):
    global STATE_DIR, AGENT_HOME_DIRS
    STATE_DIR = CODEX_STATE_DIR  # Codex sessions keep their own state, apart from Claude Code's.
    AGENT_HOME_DIRS = (".codex", ".agents", ".claude")  # and prefer the skill installed for Codex.
    if p.get("tool_name") != "apply_patch":
        return
    working_directory = p.get("cwd") or os.getcwd()
    st = load_state(p.get("session_id") or "")
    hints = []
    for patched_path in patch_paths((p.get("tool_input") or {}).get("command")):
        path = patched_path if os.path.isabs(patched_path) else os.path.join(working_directory, patched_path)
        lowered_path = path.lower()
        if any(part in lowered_path for part in SKIP_PARTS) or os.path.splitext(lowered_path)[1] not in CODE_EXT:
            continue
        hint = style_hint(p, path, st)
        if hint:
            hints.append(hint)
    if hints:
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "\n".join(hints)}})


def deny(reason):
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                 "permissionDecisionReason": reason}})


def cmd_gate(p):
    ti = p.get("tool_input") or {}
    st = load_state(p.get("session_id") or "")
    task = st.get("request_required", [])
    if p.get("tool_name") == "Bash":
        command = ti.get("command") or ""
        req = required_for_command(command, task)
        what = "running this command"
    else:
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        lp = path.lower()
        if not path or any(s in lp for s in SKIP_PARTS) or os.path.splitext(lp)[1] not in CODE_EXT:
            return
        req = required_for(path, task)
        what = "editing " + os.path.basename(path)
    if not req:
        return
    loaded = loaded_skills(p, st)
    missing = [s for s in req if norm(s) not in loaded]
    if missing:
        deny("SKILL GATE: your request touches %s. Before %s, load with the Skill tool in this order: "
             "%s. Then state `Skills: ...` and retry." % (
                 ", ".join(s for s in req if s not in BASE_EDIT) or "code", what, ", ".join(missing)))
    if p.get("tool_name") not in EDIT_TOOLS:
        return
    hint = style_hint(p, path, st)
    if hint:
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": hint}})


def cmd_subagent(p):
    emit({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": (
        "SKILL GATE: subagents do not inherit loaded skills. Read your task, decide what it touches (data, "
        "screens, endpoints, external calls, auth, tests...) and load dev-orchestrate plus those domain skills "
        "with the Skill tool before working. Code edits and test/DB/commit commands are blocked until they are "
        "loaded. Report only skills you actually loaded.")}})


def cmd_compact(p):
    # Soft reminder only: loaded skills stay "loaded" for the gate after compaction.
    if (p.get("source") or "") != "compact":
        return
    emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": (
        "SKILL GATE: context was compacted. Skills already loaded stay valid for the gate; if you no longer "
        "remember a skill's rules for the area you are working on, re-invoke it with the Skill tool.")}})


def last_assistant_text(tp):
    with open(tp, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        fh.seek(max(0, fh.tell() - 400000))
        lines = fh.read().splitlines()
    for raw in reversed(lines):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if d.get("type") == "assistant":
            c = d.get("message", {}).get("content")
            if isinstance(c, list):
                text = "\n".join(x.get("text", "") for x in c if x.get("type") == "text")
                if text:
                    return text
    return ""


def cmd_stop(p):
    if p.get("stop_hook_active"):
        return  # second stop in a row: Claude has answered the block once; never loop
    tp = p.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return
    sid = p.get("session_id") or ""
    st = load_state(sid)
    loaded = loaded_skills(p, st)
    problems = []
    unrouted = [s for s in st.get("request_required", []) if norm(s) not in loaded]
    if unrouted:
        problems.append(
            "this request touches skills you never loaded: %s. Load them, re-check your work and answer "
            "against their rules, or say in one line per skill why it does not apply" % ", ".join(unrouted))
    text = p.get("last_assistant_message") or last_assistant_text(tp)
    m = re.search(r"skills applied", text, re.I)
    if m:
        tail = text[m.end():]
        claimed = [s for s in ALL_SKILLS if re.search(r"(?<![\w:-])%s(?![\w-])" % re.escape(s), tail)]
        claimed += ["superpowers:" + s for s in re.findall(r"superpowers:([a-z-]+)", tail)]
        ghost = dedupe(s for s in claimed if norm(s) not in loaded)
        if ghost:
            problems.append("'Skills applied' names skills never loaded with the Skill tool: %s; load them or "
                            "remove them from the list" % ", ".join(ghost))
    if problems:
        emit({"decision": "block", "reason": "SKILL GATE: " + "; ".join(problems) + "."})


def main():
    if len(sys.argv) < 2 or disabled():
        return
    p = read_payload()
    try:
        {"prompt": cmd_prompt, "gate": cmd_gate, "subagent": cmd_subagent,
         "compact": cmd_compact, "stop": cmd_stop, "codex-style": cmd_codex_style}.get(sys.argv[1], lambda _p: None)(p)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
