"""PreToolUse hook for Claude Code: ask (or deny) before dangerous shell commands.

Rules in a skill are guidance; this hook is enforcement that runs on every Bash
call (plan §4.2, AGENT-002, OPS-001..OPS-010).

Default mode `standard`:
- ASK before dangerous work the user may legitimately want: deleting, renaming
  or rewriting branches/tags/history, discarding uncommitted work, dropping,
  resetting or mass-editing databases, deleting data volumes, recursive deletes,
  infrastructure changes, deploys/publishing, sudo.
- DENY the few things an agent must never do even with a click: production
  data/infra changes, live payments, sending secrets out, remote load tests,
  wiping the disk or home directory. The user can still run those manually.
Mode `strict` turns every ASK into DENY; mode `ask` turns every DENY into ASK.

Rules match the command's *active* text only: quoted text given to search/print
tools (`grep "DROP TABLE"`, `git commit -m "..."`) and heredoc bodies written to
files (`cat > f <<EOF`) are data, not commands, and are blanked first. Routine
local work is not asked about: recursive deletes of rebuildable or temp
directories (`node_modules`, `dist`, `/tmp/x`) and scoped row changes through a
local database client.

Hook contract: JSON on stdin with tool_name/tool_input; JSON on stdout with
hookSpecificOutput.permissionDecision = deny | ask. Silence means "no opinion".
For "ask", the reason (severity icon, title and what to check, in English or
Vietnamese following the user's latest prompt in the transcript) is shown to the
user in the permission prompt, and the Bash description is prefixed with the
title so prompts raised by settings `ask` rules explain themselves too. For
"deny", the reason goes to the agent, which must present the command to the user.
Internal errors fail open with a message on stderr, so a guard bug cannot block
all work. Pair the hook with permission `ask` rules (installer --with-guard):
in bypassPermissions mode a hook "ask" does not prompt, the rules do.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass

DENY = "deny"
ASK = "ask"
MODES = ("standard", "strict", "ask")

# Letters may not touch the word: "prod-db" and "eks_prod" count, "products" and "deliverables" do not.
_PROD_WORD = r"(?<![A-Za-z])(?:prod|production|live|prd)(?![A-Za-z])"
_LOCAL_HOST = (r"(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0|host\.docker\.internal|[A-Za-z0-9\-]+\.localhost|"
               r"db|postgres|mysql|mariadb|redis|mongo|database)")
_DB_CLIENTS = r"(?:psql|mysql|mariadb|mongosh|mongo|redis-cli|sqlcmd|sqlplus|cqlsh|clickhouse-client|pg_restore)"
# A local name only counts when the host ends there: "db" is local, "db.staging.example.com" is not.
_REMOTE_HOST_FLAG = r"(?:-h\s*|--host[= ]|@|//)(?!" + _LOCAL_HOST + r"(?![A-Za-z0-9.\-]))[A-Za-z0-9\-]+\.[A-Za-z0-9.\-]+"
_SQL_WRITE = r"\b(?:INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|TRUNCATE|GRANT|REVOKE|MERGE|REPLACE)\b"
_DATA_TOOLS = (r"(?:migrate|seed|db:|artisan|manage\.py|rake|knex|prisma\s+(?:migrate|db)|sequelize|typeorm|alembic|flyway|"
               r"liquibase|psql|mysql|mongosh|mongo|redis-cli|sqlcmd|pg_restore)")
# Start of a command: line start or after an operator, then env assignments and wrappers such as sudo/npx.
_COMMAND_START = r"(?:^|[;&|(]\s*)(?:[A-Za-z_]\w*=\S*\s+)*(?:(?:sudo|time|nohup|exec|command|npx|bunx)\s+(?:-\S+\s+)*)*"
_RM_RECURSIVE = re.compile(r"\brm\s+(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive)\b")
_ROW_CHANGE = re.compile(r"\bDELETE\s+FROM\b|\bUPDATE\s+[\w.\"`]+\s+SET\b|\bINSERT\s+INTO\b", re.IGNORECASE)


@dataclass(frozen=True)
class GuardRule:
    rule_id: str
    decision: str
    pattern: re.Pattern[str]
    reason: str  # English, for the agent and logs.
    title_en: str  # Short title shown to the user, in the language of the user's prompt.
    title_vi: str
    advice_vi: str  # What happens and what to check before confirming.
    advice_en: str
    exempt: Callable[[list[str]], bool] | None = None  # True when every match is routine local work.

    def title(self, language: str) -> str:
        return self.title_vi if language == "vi" else self.title_en

    def advice(self, language: str) -> str:
        return self.advice_vi if language == "vi" else self.advice_en

    @property
    def level(self) -> int:
        """Index into LEVELS: deny rules block, notice rules are easy to undo, the rest can lose work or data."""
        if self.decision == DENY:
            return 0
        return 2 if self.rule_id in _NOTICE_RULES else 1


LANGUAGES = ("en", "vi")
# Severity shown in front of every prompt, most severe first: icon and label per language.
LEVELS = (("⛔", {"en": "Blocked", "vi": "Bị chặn"}), ("🔴", {"en": "Danger", "vi": "Nguy hiểm"}),
          ("🟡", {"en": "Warning", "vi": "Cảnh báo"}))
# Asked about, but usually reversible or local: rewritten local commits, skipped hooks, config, reads.
_NOTICE_RULES = frozenset({"G-GIT-RENAME-BRANCH", "G-GIT-AMEND-REBASE", "G-GIT-SKIP-HOOKS", "G-GIT-GLOBAL-CONFIG",
                           "G-DB-REMOTE-CLIENT", "G-DOCKER-PRUNE", "G-FS-MASS-KILL"})
_MESSAGES = {
    "confirm": {"en": "Approve only if this is the exact command and target you intended.",
                "vi": "Chỉ đồng ý nếu đúng lệnh và đúng đích bạn muốn."},
    "columns": {"en": "Purpose | Command | Risk / what to check", "vi": "Mục đích | Lệnh | Rủi ro / cần kiểm tra"},
}


def _heading(decision: str, rules: list[GuardRule], language: str) -> str:
    """"🔴 Danger — <titles>": blocked for any deny (also strict mode), else the most severe rule level."""
    icon, labels = LEVELS[0 if decision == DENY else min(rule.level for rule in rules)]
    return f"{icon} {labels[language]} — " + " + ".join(rule.title(language) for rule in rules)


def _rule(rule_id: str, decision: str, pattern: str, reason: str, title_en: str, title_vi: str, advice_vi: str,
          advice_en: str, flags: int = 0, exempt: Callable[[list[str]], bool] | None = None) -> GuardRule:
    return GuardRule(rule_id, decision, re.compile(pattern, flags), reason, title_en, title_vi, advice_vi, advice_en, exempt)


# --------------------------------------------------------------------------- prompt language

_VIETNAMESE_LETTERS = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.IGNORECASE)
_INJECTED_BLOCK = re.compile(r"<([a-z][\w-]*)\b[^>]*>.*?</\1>", re.DOTALL)  # system-reminder, command wrappers...
_TRANSCRIPT_TAIL_BYTES = 512 * 1024


def language_of(text: str) -> str:
    """"vi" when the text has Vietnamese letters (ă, ơ, ệ...), else "en"."""
    return "vi" if len(_VIETNAMESE_LETTERS.findall(_INJECTED_BLOCK.sub("", text))) >= 2 else "en"


def _text_of(content: object) -> str:
    """Plain text of a message content (a string or a list of blocks); tool results and images are skipped."""
    if isinstance(content, list):
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    return content if isinstance(content, str) and _INJECTED_BLOCK.sub("", content).strip() else ""


def _last_user_text(transcript_path: str) -> str:
    """Newest thing the human typed, from the tail of a Claude Code JSONL transcript.

    Newest first: a message sent mid-turn (attachment `queued_command`) or a human `user` entry. Tool results are
    `user` entries too and are skipped. `last-prompt` entries repeat the turn's prompt but miss mid-turn messages,
    so they are only the fallback when the prompt itself is older than the tail.
    """
    with open(transcript_path, "rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - _TRANSCRIPT_TAIL_BYTES))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    fallback = ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # The first line of the tail is usually cut in half.
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        attachment = entry.get("attachment") if kind == "attachment" else None
        if isinstance(attachment, dict) and attachment.get("type") == "queued_command":
            text = _text_of(attachment.get("prompt"))
        elif kind == "user" and (entry.get("origin") or {}).get("kind", "human") == "human":
            text = _text_of((entry.get("message") or {}).get("content"))
        else:
            if kind == "last-prompt" and not fallback:
                fallback = _text_of(entry.get("lastPrompt"))
            continue
        if text:
            return text
    return fallback


def resolve_language(requested: str, payload: dict) -> str:
    """--lang / DEVSKILLS_GUARD_LANG win; "auto" follows the user's latest prompt, then the locale, then English."""
    requested = (os.environ.get("DEVSKILLS_GUARD_LANG") if requested == "auto" else requested) or "auto"
    if requested in LANGUAGES:
        return requested
    transcript_path = payload.get("transcript_path")
    if transcript_path:
        try:
            prompt = _last_user_text(str(transcript_path))
            if prompt:
                return language_of(prompt)
        except OSError:
            pass
    locale = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return "vi" if locale.lower().startswith("vi") else "en"


# --------------------------------------------------------------------------- command parsing

# Programs whose quoted arguments are only text to search, print or store (not executed).
_TEXT_ONLY_PROGRAMS = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack", "echo", "printf", "gh"})
_TEXT_ONLY_GIT = frozenset({"grep", "log", "show", "diff", "blame", "commit", "tag", "notes", "stash"})
_DATA_SINKS = frozenset({"cat", "tee"})
_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][\w.\-]*)\2")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")


def _program(segment: str) -> tuple[str, str]:
    """(program, first argument) of a segment, skipping env assignments and sudo/time wrappers."""
    words = segment.split()
    while words and (_ENV_ASSIGNMENT.match(words[0]) or words[0] in ("sudo", "time", "nohup", "command", "exec")):
        words.pop(0)
    if not words:
        return "", ""
    return words[0].rsplit("/", 1)[-1], words[1] if len(words) > 1 else ""


def _strip_data_heredocs(command: str) -> str:
    """Drop heredoc bodies that `cat`/`tee` only write to a file; bodies fed to psql/python/sh are kept."""
    lines = command.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        match = _HEREDOC.search(line)
        if not match:
            continue
        head = re.split(r"&&|\|\||[;&|]", line[:match.start()])[-1]
        if _program(head)[0] not in _DATA_SINKS or "|" in line[match.end():]:
            continue
        terminator, strip_tabs = match.group(3), match.group(1) == "-"
        while index < len(lines) and (lines[index].lstrip("\t") if strip_tabs else lines[index]).strip() != terminator:
            index += 1
        index += 1  # Skip the terminator line too.
    return "\n".join(kept)


def _split_segments(command: str) -> list[tuple[str, str]]:
    """Split on unquoted ; && || | & and newlines: [(segment, operator that follows it)]."""
    segments: list[tuple[str, str]] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(command):
                current.append(command[index + 1])
                index += 1
            elif char == quote:
                quote = ""
        elif char == "\\" and index + 1 < len(command):
            current.extend(command[index:index + 2])
            index += 1
        elif char in ("'", '"'):
            quote = char
            current.append(char)
        elif command.startswith(("&&", "||"), index):
            segments.append(("".join(current), command[index:index + 2]))
            current = []
            index += 1
        elif char in ";|\n" or (char == "&" and not (current and current[-1] in "<>") and command[index + 1:index + 2] != ">"):
            segments.append(("".join(current), char))
            current = []
        else:
            current.append(char)
        index += 1
    segments.append(("".join(current), ""))
    return [(segment, operator) for segment, operator in segments if segment.strip() or operator]


def _is_text_only(segment: str, operator: str, next_segment: str) -> bool:
    if "$(" in segment or "`" in segment:
        return False
    program, first_argument = _program(segment)
    if program == "git":
        text_only = first_argument in _TEXT_ONLY_GIT
    else:
        text_only = program in _TEXT_ONLY_PROGRAMS
    if not text_only:
        return False
    # Text piped into another program (echo "DROP TABLE x" | psql) is input to that program.
    return operator != "|" or _program(next_segment)[0] in _TEXT_ONLY_PROGRAMS


def _blank_data(segment: str) -> str:
    """Search/print tools keep only their name; git and gh keep flags (--amend, release create) but lose quoted text."""
    program = _program(segment)[0]
    if program not in ("git", "gh"):
        return program
    return re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", '""', segment)


def active_segments(command: str) -> list[tuple[str, str]]:
    """Segments with data-only text removed: args of grep/echo, quoted text of git log/commit/gh, file-only heredoc bodies."""
    segments = _split_segments(_strip_data_heredocs(command))
    result = []
    for position, (segment, operator) in enumerate(segments):
        next_segment = segments[position + 1][0] if position + 1 < len(segments) else ""
        if _is_text_only(segment, operator, next_segment):
            segment = _blank_data(segment)
        result.append((" ".join(segment.split()), operator if operator != "\n" else ";"))
    return result


# --------------------------------------------------------------------------- local-work exemptions

# Directories a build or install recreates; deleting them loses nothing that is not regenerated.
_REBUILDABLE_DIRS = frozenset({
    "node_modules", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache", ".cache",
    ".angular", ".expo", ".dart_tool", "storybook-static", "coverage", ".nyc_output", "htmlcov", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".eggs", "target", ".gradle", "tmp", ".tmp",
})
_TEMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "$TMPDIR/", "${TMPDIR}/")


def _is_rebuildable_or_temp(target: str) -> bool:
    for prefix in _TEMP_PREFIXES:
        if target.startswith(prefix):
            rest = target[len(prefix):]
            return bool(rest.strip("/*")) and ".." not in rest.split("/") and "$" not in rest
    if target.startswith(("/", "~", "-")) or any(char in target for char in "$`"):
        return False
    for suffix in ("/*", "/"):
        target = target.removesuffix(suffix)
    parts = [part for part in target.split("/") if part not in ("", ".")]
    if not parts or ".." in parts or any(char in part for part in parts if part != "*" for char in "*?[{"):
        return False
    return any(part in _REBUILDABLE_DIRS or part.endswith(".egg-info") for part in parts)


def _rm_only_rebuildable(segments: list[str]) -> bool:
    """True when every recursive rm deletes only rebuildable dirs (node_modules, dist...) or temp paths."""
    for segment in segments:
        if not _RM_RECURSIVE.search(segment):
            continue
        if _program(segment)[0] != "rm":  # find -exec rm, xargs rm: targets are unknown.
            return False
        try:
            words = shlex.split(segment)
        except ValueError:
            return False
        words = words[words.index("rm") + 1:]
        targets = [word for word in words if not word.startswith("-")] if "--" not in words else words[words.index("--") + 1:]
        if not targets or not all(_is_rebuildable_or_temp(target) for target in targets):
            return False
    return True


_LOCAL_CLIENT = re.compile(
    r"^(?:[A-Za-z_]\w*=\S*\s+)*(?:docker(?:-compose|\s+compose)?\s+exec\b[^;&|]*?\s)?"
    r"(?P<client>psql|mysql|mariadb|sqlite3|duckdb|mongosh|mongo|redis-cli|sqlcmd|clickhouse-client)\b")
_REMOTE_DB_ENV = re.compile(r"\b(?:PGHOST|PGSERVICE|MYSQL_HOST|DATABASE_URL|DB_HOST)=")


def _row_change_is_local(segments: list[str]) -> bool:
    """True when every row change goes through a database client aimed at this machine or a local container."""
    for segment in segments:
        if not _ROW_CHANGE.search(segment):
            continue
        match = _LOCAL_CLIENT.match(segment)
        if not match:
            return False
        if match.group("client") in ("sqlite3", "duckdb"):
            continue
        if "$" in segment or _REMOTE_DB_ENV.search(segment) or re.search(_REMOTE_HOST_FLAG, segment):
            return False
    return True


# --------------------------------------------------------------------------- rules

GUARD_RULES: tuple[GuardRule, ...] = (
    # Never, even with approval: production, real money, secrets leaving the machine, disk/home wipes.
    _rule("G-PROD-ENV-DATA", DENY,
          r"\b(?:APP_ENV|NODE_ENV|RAILS_ENV|RACK_ENV|ASPNETCORE_ENVIRONMENT|SPRING_PROFILES_ACTIVE|ENVIRONMENT|ENV)=" + _PROD_WORD + r"\b[^\n]*\b" + _DATA_TOOLS,
          "data/migration tooling with a production environment marker (SAFE-001)",
          "Migration/data command on production", "Chạy migration/dữ liệu trên môi trường production",
          "Biến môi trường trỏ tới production, lệnh có thể sửa dữ liệu thật của khách hàng.",
          "The environment variable points at production; this can change real customer data.", re.IGNORECASE),
    _rule("G-PROD-HOST-WRITE", DENY,
          r"(?:-h\s*|--host[= ]|@|//)[A-Za-z0-9.\-]*?" + _PROD_WORD + r"[A-Za-z0-9.\-]*[^\n]*" + _SQL_WRITE,
          "write/DDL statement against a production-looking host (SAFE-002)",
          "Write to a production database", "Ghi/sửa cấu trúc database production",
          "Host có tên giống production; câu SQL ghi hoặc đổi schema trên dữ liệu thật.",
          "The host looks like production; the SQL writes data or changes the schema on real data.", re.IGNORECASE),
    _rule("G-INFRA-PROD", DENY,
          r"\b(?:kubectl|helm|terraform|tofu|pulumi)\b[^\n;&|]*" + _PROD_WORD +
          r"[^\n;&|]*\b(?:delete|destroy|apply|up|scale|uninstall|rollout)\b|"
          r"\b(?:kubectl|helm|terraform|tofu|pulumi)\b[^\n;&|]*\b(?:delete|destroy|apply|up|scale|uninstall|rollout)\b[^\n;&|]*" +
          _PROD_WORD,
          "infrastructure change on a production-looking target",
          "Change production infrastructure", "Thay đổi hạ tầng production",
          "Lệnh kubectl/helm/terraform áp dụng hoặc xóa tài nguyên có tên production/live; có thể gây sự cố thật.",
          "kubectl/helm/terraform applies or deletes resources named production/live; this can cause a real outage.",
          re.IGNORECASE),
    _rule("G-LIVE-PAYMENT-KEY", DENY, r"\b(?:sk|rk)_live_[A-Za-z0-9]{8,}",
          "a live payment key is in the command; use test keys or the simulator (SAFE-005)",
          "Live payment key", "Dùng khóa thanh toán thật (live key)",
          "Có thể trừ tiền thật. Dùng khóa test (sk_test_...) hoặc simulator.",
          "This can charge real money. Use a test key (sk_test_...) or the simulator."),
    _rule("G-STRIPE-LIVE", DENY, r"\bstripe\b[^\n|;&]*\s--live\b", "Stripe CLI in live mode can move real money (MONEY-007)",
          "Stripe CLI in live mode", "Stripe CLI ở chế độ live",
          "Giao dịch thật, tiền thật. Bỏ --live để dùng chế độ test.",
          "Real transactions, real money. Drop --live to use test mode."),
    _rule("G-SECRET-EXFILTRATION", DENY,
          r"\b(?:curl|wget|http|https|nc|ncat|scp|rsync)\b[^\n]*(?:@|<\s*|--upload-file\s+|-T\s+)\S*"
          r"(?:\.env\b|id_rsa|id_ed25519|\.pem\b|\.p12\b|credentials|\.aws/|\.ssh/|\.npmrc|\.pypirc|\.netrc|\.kube/config)",
          "sending a secret file to a network destination (AGENT-007)",
          "Send a secret file over the network", "Gửi file bí mật ra mạng",
          "Lệnh tải file chứa mật khẩu/khóa (.env, SSH key, credentials) lên một địa chỉ mạng.",
          "Uploads a file holding passwords or keys (.env, SSH key, credentials) to a network address."),
    _rule("G-ENV-EXFILTRATION", DENY, r"\b(?:printenv|env|set)\b\s*\|[^\n]*\b(?:curl|wget|nc|ncat|http)\b",
          "piping the environment (secrets) to a network tool",
          "Send environment variables over the network", "Gửi toàn bộ biến môi trường ra mạng",
          "Biến môi trường thường chứa token và mật khẩu; lệnh chuyển chúng tới một địa chỉ mạng.",
          "Environment variables usually hold tokens and passwords; this sends them to a network address."),
    _rule("G-REMOTE-LOAD-TEST", DENY,
          r"(?:" + _COMMAND_START + r"|(?<=/))(?:ab|wrk|wrk2|hey|vegeta|k6|locust|artillery|siege|bombardier|autocannon|oha|jmeter)\s"
          r"[^\n;&|]*https?://(?!(?:localhost|127\.0\.0\.1|\[::1\])(?::|/|\s|$))",
          "load test against a non-local target (PERF-008)",
          "Load test against a remote server", "Load test vào server không phải máy local",
          "Bắn tải lớn vào server thật/chung có thể làm sập dịch vụ hoặc phát sinh chi phí. Chỉ test tải với localhost.",
          "Heavy load on a real or shared server can take it down or cost money. Load test only localhost."),
    _rule("G-FS-WIPE", DENY,
          r"\brm\s+(?:-[A-Za-z]*[rR][A-Za-z]*\s+|--recursive\s+)+(?:-[A-Za-z]+\s+)*(?:/|~|\$HOME|/\*)(?:\s|$|;|&)|"
          r"\bmkfs(?:\.\w+)?\b|\bdd\b[^\n;&|]*\bof=/dev/|\bdiskutil\s+(?:erase\w*|partitionDisk)\b|:\(\)\s*\{\s*:\|:&\s*\};:",
          "wipes the disk, the home directory or the filesystem root",
          "Wipe the disk or home directory", "Xóa sạch ổ đĩa / thư mục home",
          "Lệnh xóa toàn bộ /, ~ hoặc format ổ đĩa; không khôi phục được.",
          "Deletes all of / or ~, or formats a disk; it cannot be recovered."),

    # Git: branches, tags, history and uncommitted work (OPS-001..OPS-003) — ask first.
    _rule("G-GIT-DELETE-BRANCH", ASK,
          r"\bgit\s+branch\b[^\n;&|]*\s(?:-d|-D|--delete)\b|\bgit\s+push\b[^\n;&|]*\s(?:--delete|-d)\b|\bgit\s+push\s+\S+\s+:\S+",
          "deletes a branch or a remote ref",
          "Delete a git branch", "Xóa nhánh git",
          "Nhánh chưa merge sẽ mất commit; nhánh trên remote thì người khác/CI cũng mất. Kiểm tra đúng tên nhánh và nhánh đã merge chưa.",
          "Unmerged commits are lost; a remote branch disappears for teammates and CI too. Check the name and that it is merged."),
    _rule("G-GIT-RENAME-BRANCH", ASK, r"\bgit\s+branch\b[^\n;&|]*\s(?:-m|-M|--move|-c|-C|--copy)\b",
          "renames/copies a branch (shared refs change)",
          "Rename or copy a git branch", "Đổi tên / sao chép nhánh git",
          "PR, CI và người khác đang dùng tên cũ sẽ bị lệch. -M ghi đè nhánh trùng tên.",
          "PRs, CI and teammates using the old name get out of sync. -M overwrites a branch with the same name."),
    _rule("G-GIT-FORCE-PUSH", ASK, r"\bgit\s+push\b[^\n;&|]*(?:--force\b|--force-with-lease\b|--force-if-includes\b|\s-f\b|\s\+[\w./-]+)",
          "force push rewrites remote history",
          "Force push", "Force push (ghi đè lịch sử trên remote)",
          "Commit của người khác trên nhánh remote có thể bị mất. Chỉ đồng ý nếu nhánh là của riêng bạn.",
          "Other people's commits on the remote branch can be lost. Approve only if the branch is yours alone."),
    _rule("G-GIT-REWRITE-HISTORY", ASK,
          r"\bgit\s+(?:filter-branch|filter-repo|replace)\b|\bgit\s+update-ref\s+-d\b|\bgit\s+reflog\s+(?:expire|delete)\b|"
          r"\bgit\s+gc\b[^\n;&|]*--prune=now\b|\bgit\s+tag\b[^\n;&|]*\s(?:-d|--delete|-f|--force)\b|\bgit\s+checkout\s+-B\b|\bgit\s+switch\s+-C\b",
          "rewrites or deletes git history, tags or refs",
          "Rewrite or delete git history/tags", "Viết lại / xóa lịch sử, tag git",
          "Commit, tag hoặc ref bị xóa/thay thế; clone của người khác sẽ lệch. Kiểm tra đúng tag/nhánh.",
          "Commits, tags or refs are deleted or replaced; other clones diverge. Check the tag or branch."),
    _rule("G-GIT-DISCARD-WORK", ASK,
          r"\bgit\s+(?:reset\b[^\n;&|]*--hard|clean\b[^\n;&|]*\s-[A-Za-z]*f|checkout\s+(?:-f\b|--\s|\.(?:\s|$))|"
          r"restore\b(?![^\n;&|]*(?:--staged|\s-S\b))[^\n;&|]*|restore\b[^\n;&|]*(?:--worktree|\s-W\b)[^\n;&|]*|stash\s+(?:drop|clear))",
          "discards uncommitted developer work (AGENT-008)",
          "Discard uncommitted changes", "Bỏ thay đổi chưa commit",
          "Code đang sửa dở (kể cả của bạn, ngoài task) sẽ mất vĩnh viễn. Chạy git status để xem file nào bị ảnh hưởng.",
          "Work in progress (including yours, outside the task) is lost for good. Run git status to see which files are affected."),
    _rule("G-GIT-AMEND-REBASE", ASK, r"\bgit\s+(?:commit\b[^\n;&|]*--amend|rebase\b|revert\b)",
          "changes existing commits or branch state",
          "Rewrite commits (amend/rebase/revert)", "Sửa commit cũ (amend / rebase / revert)",
          "Nếu commit đã push thì phải force push sau đó. Với commit local chưa push thì thường an toàn.",
          "If the commits were pushed, a force push is needed afterwards. Usually safe for local, unpushed commits."),
    _rule("G-GIT-SKIP-HOOKS", ASK, r"\bgit\s+(?:commit\b[^\n;&|]*\s(?:--no-verify|-n)\b|(?:push|merge)\b[^\n;&|]*\s--no-verify\b)",
          "bypasses repository hooks/checks",
          "Skip git hooks", "Bỏ qua git hook (lint/test trước commit/push)",
          "Code có thể lọt qua mà không chạy lint/test của repo.",
          "Code can get through without the repository's lint and tests."),
    _rule("G-GIT-PUSH-PROTECTED", ASK,
          r"\bgit\s+push\b[^\n;&|]*(?:\s|:)(?:main|master|develop|production|release[\w./-]*)(?=\s|$|;|&|\|)",
          "pushes to a protected/shared branch",
          "Push to a protected branch", "Push thẳng lên nhánh chính (main/master/develop/release)",
          "Code lên nhánh chung không qua review, có thể kích hoạt deploy.",
          "Code lands on a shared branch without review and may trigger a deploy."),
    _rule("G-GIT-GLOBAL-CONFIG", ASK,
          r"\bgit\s+config\s+(?:--global|--system)\b(?!(?:\s+--\S+)*\s+(?:--get(?:-all|-regexp)?|--list|-l|get|list)\b)",
          "changes the user's global git configuration",
          "Change global git config", "Sửa cấu hình git toàn máy",
          "Ảnh hưởng mọi repo trên máy (tên, email, hook, credential...).",
          "Affects every repository on this machine (name, email, hooks, credentials...)."),

    # Databases (OPS-004..OPS-006) — ask first.
    _rule("G-DB-DESTRUCTIVE-SQL", ASK,
          r"\bDROP\s+(?:DATABASE|SCHEMA|TABLE|VIEW|MATERIALIZED\s+VIEW|INDEX|USER|ROLE|OWNED)\b|\bTRUNCATE\b\s+(?:TABLE\s+)?[\w.\"`]|"
          r"\bALTER\s+TABLE\b[^;\"']*\bDROP\b|\bDELETE\s+FROM\s+[\w.\"`]+\s*(?:;|\"|'|$)|\bUPDATE\s+[\w.\"`]+\s+SET\b(?![^;\"']*\bWHERE\b)",
          "destructive SQL (drop/truncate/delete or update without WHERE)",
          "Destructive SQL", "SQL xóa/sửa hàng loạt (DROP, TRUNCATE, DELETE/UPDATE không có WHERE)",
          "Xóa bảng hoặc toàn bộ dữ liệu của bảng. Kiểm tra đúng database (local/test) và đã có backup.",
          "Drops a table or all of its rows. Check it is the right (local/test) database and that a backup exists.", re.IGNORECASE),
    _rule("G-DB-RESET-COMMAND", ASK,
          r"\b(?:migrate:fresh|migrate:reset|migrate:refresh|db:wipe|db:drop|db:reset|db:schema:load|db:purge|schema:drop|"
          r"database:drop|doctrine:database:drop|doctrine:schema:drop|dropdb|mysqladmin\b[^\n;&|]*\bdrop|"
          r"prisma\s+migrate\s+reset|prisma\s+db\s+push\b[^\n;&|]*--force-reset|manage\.py\s+(?:flush|reset_db)|"
          r"flyway\b[^\n;&|]*\bclean|liquibase\b[^\n;&|]*\bdrop-?all|alembic\s+downgrade\s+base|knex\s+migrate:rollback\b[^\n;&|]*--all|"
          r"sequelize\b[^\n;&|]*db:drop|typeorm\b[^\n;&|]*schema:drop|dropDatabase\s*\(|FLUSHALL|FLUSHDB|deleteMany\s*\(\s*\{\s*\}\s*\))",
          "drops or resets a database",
          "Drop or reset a database", "Xóa / reset toàn bộ database",
          "Mọi dữ liệu trong database bị xóa và tạo lại từ đầu. Kiểm tra lệnh đang trỏ tới database nào (xem .env).",
          "All data in the database is deleted and recreated. Check which database the command targets (see .env).",
          re.IGNORECASE),
    _rule("G-DB-VOLUME-DELETE", ASK,
          r"\bdocker(?:-compose|\s+compose)?\b[^\n;&|]*\bdown\b[^\n;&|]*(?:\s-v\b|--volumes)|\bdocker\s+volume\s+(?:rm|prune)\b|"
          r"\bdocker\s+system\s+prune\b[^\n;&|]*--volumes|\bdocker\s+compose\s+rm\b[^\n;&|]*\s-v\b",
          "deletes container volumes (database data)",
          "Delete Docker volumes", "Xóa volume Docker (mất dữ liệu database trong container)",
          "Dữ liệu DB/Redis local trong volume sẽ mất. Dùng `docker compose down` (không -v) nếu chỉ muốn tắt container.",
          "Local DB/Redis data in the volume is lost. Use `docker compose down` (without -v) to just stop the containers."),
    _rule("G-DB-REMOTE-WRITE", ASK, r"\b" + _DB_CLIENTS + r"\b[^\n]*" + _REMOTE_HOST_FLAG + r"[^\n]*" + _SQL_WRITE,
          "data/schema change against a non-local database",
          "Write to a non-local database", "Ghi dữ liệu vào database không phải local",
          "Host không phải máy này (staging/dev chung). Dữ liệu của người khác có thể bị ảnh hưởng.",
          "The host is not this machine (shared staging/dev). Other people's data may be affected.", re.IGNORECASE),
    _rule("G-DB-DATA-CHANGE", ASK, _ROW_CHANGE.pattern,
          "modifies database rows; confirm it is a disposable test database",
          "Change database rows", "Thêm/sửa/xóa dòng dữ liệu trong database",
          "Không xác định được database đích là local (lệnh qua biến môi trường, script hoặc host lạ). Kiểm tra đúng database test.",
          "The target database could not be confirmed as local (env variable, script or unknown host). Check it is a test database.",
          re.IGNORECASE, exempt=_row_change_is_local),
    _rule("G-DB-MIGRATION-ROLLBACK", ASK,
          r"\b(?:migrate:rollback|db:rollback|alembic\s+downgrade|knex\s+migrate:(?:rollback|down)|prisma\s+migrate\s+resolve)\b",
          "rolls back migrations; data in new columns/tables may be lost",
          "Roll back migrations", "Rollback migration",
          "Bảng/cột mới tạo sẽ bị xóa cùng dữ liệu trong đó.",
          "Newly created tables and columns are dropped together with their data."),
    _rule("G-DB-REMOTE-CLIENT", ASK, r"\b(?:" + _DB_CLIENTS + r"|pg_dump|mysqldump)\b[^\n]*" + _REMOTE_HOST_FLAG,
          "database client against a remote host; confirm it is an approved sandbox",
          "Connect to a remote database", "Kết nối database ở máy khác",
          "Host không phải local. Kiểm tra đây là sandbox được phép dùng, không phải production.",
          "The host is not local. Check it is an approved sandbox, not production."),

    # Files, system, infrastructure, publishing (OPS-007..OPS-010) — ask first.
    _rule("G-FS-RM-RECURSIVE", ASK, _RM_RECURSIVE.pattern,
          "recursive delete",
          "Recursive delete", "Xóa thư mục (rm -r)",
          "Xóa vĩnh viễn, không qua thùng rác. Kiểm tra đường dẫn (thư mục build/cache/tmp được tự cho qua).",
          "Permanent delete, no trash. Check the path (build, cache and tmp folders are allowed automatically).",
          exempt=_rm_only_rebuildable),
    _rule("G-FS-PERMISSIONS", ASK, r"\bchmod\s+(?:-R\s+)?0?777\b|\bchown\s+-R\b|\bcrontab\s+-r\b",
          "broad permission/ownership change",
          "Mass permission/ownership change", "Đổi quyền / chủ sở hữu file hàng loạt",
          "chmod 777 cho mọi người ghi; chown -R đổi chủ cả cây thư mục; crontab -r xóa hết lịch chạy.",
          "chmod 777 lets everyone write; chown -R changes the owner of a whole tree; crontab -r deletes every schedule."),
    _rule("G-FS-SYSTEM-POWER", ASK, _COMMAND_START + r"(?:shutdown|reboot|halt|poweroff)\b|\bsystemctl\s+(?:reboot|poweroff|halt)\b",
          "stops or restarts the machine",
          "Shut down or restart the machine", "Tắt / khởi động lại máy",
          "Mọi chương trình đang chạy và việc chưa lưu sẽ mất.",
          "Every running program and all unsaved work is lost."),
    _rule("G-FS-SUDO", ASK, r"(?:^|[;&|]\s*)sudo\b", "runs with elevated privileges",
          "Run as admin (sudo)", "Chạy với quyền admin (sudo)",
          "Lệnh có toàn quyền trên máy. Kiểm tra kỹ lệnh phía sau sudo.",
          "The command gets full control of the machine. Read what follows sudo carefully."),
    _rule("G-FS-MASS-KILL", ASK, r"\bkill\s+-9\s+-1\b|\bkillall\b|\bpkill\s+-9\b", "kills many processes",
          "Kill many processes", "Tắt hàng loạt tiến trình",
          "Có thể tắt cả chương trình khác cùng tên (IDE, server của dự án khác).",
          "May also kill other programs with the same name (IDE, other projects' servers)."),
    _rule("G-INFRA-DESTROY", ASK,
          r"\b(?:terraform|tofu|pulumi)\s+destroy\b|\bkubectl\s+delete\b|\bhelm\s+uninstall\b|"
          r"\baws\s+(?:s3\s+(?:rb|rm)|rds\s+delete-db-\w+|dynamodb\s+delete-table|ec2\s+terminate-instances)\b|"
          r"\b(?:gcloud|az|doctl)\b[^\n;&|]*\bdelete\b|\bnpm\s+unpublish\b",
          "destroys infrastructure, cloud data or published packages",
          "Destroy infrastructure or cloud data", "Xóa hạ tầng / dữ liệu cloud / package đã publish",
          "Tài nguyên cloud (server, DB, bucket) hoặc package bị xóa thật. Kiểm tra đúng account/project/môi trường.",
          "Cloud resources (servers, databases, buckets) or packages are really deleted. Check the account, project and environment."),
    _rule("G-INFRA-APPLY", ASK, r"\b(?:terraform|tofu)\s+apply\b|\bpulumi\s+up\b|\bkubectl\s+(?:apply|scale|rollout\s+restart)\b",
          "changes shared infrastructure",
          "Apply infrastructure changes", "Áp dụng thay đổi hạ tầng",
          "Tạo/sửa/xóa tài nguyên thật. Xem kết quả `terraform plan` / `kubectl diff` trước.",
          "Creates, changes or deletes real resources. Review `terraform plan` / `kubectl diff` first."),
    _rule("G-INFRA-ACCESS", ASK,
          r"\baws\s+iam\s+(?:create|attach|put|update|add|delete|detach|remove|upload)-[\w-]+|"
          r"\baws\s+ec2\s+(?:authorize|revoke)-security-group-\w+|\baws\s+\S+\s+(?:put-[\w-]*policy|add-permission)\b|"
          r"\bgcloud\b[^\n;&|]*\b(?:add-iam-policy-binding|remove-iam-policy-binding|set-iam-policy)\b|"
          r"\bgcloud\s+iam\s+service-accounts\s+keys\s+create\b|\bgcloud\s+compute\s+firewall-rules\s+(?:create|update)\b|"
          r"\b(?:terraform|tofu)\s+(?:import|taint|untaint|force-unlock|state\s+(?:rm|mv|push|replace-provider))\b",
          "changes cloud permissions, network exposure or Terraform state",
          "Change cloud access, firewall or Terraform state", "Đổi quyền truy cập cloud / firewall / Terraform state",
          "Có thể mở quyền hoặc cổng mạng ra ngoài, hoặc làm Terraform state lệch với thực tế.",
          "May open permissions or network ports to the outside, or make Terraform state drift from reality."),
    _rule("G-PUBLISH-DEPLOY", ASK,
          r"\b(?:npm|pnpm|yarn)\s+publish\b|\bdocker\s+push\b|\b(?:vercel|netlify|fly|flyctl|firebase)\b[^\n;&|]*\b(?:deploy|--prod)\b|"
          r"\btwine\s+upload\b|\bgh\s+release\s+create\b",
          "publishes or deploys outside the local machine",
          "Publish or deploy", "Publish / deploy ra ngoài",
          "Package, image hoặc website lên môi trường công khai; thường không gỡ lại hoàn toàn được.",
          "The package, image or website goes public; it usually cannot be fully taken back."),
    _rule("G-DOCKER-PRUNE", ASK, r"\bdocker\s+(?:system|image|container|builder)\s+prune\b",
          "removes local docker data",
          "Prune local Docker data", "Dọn dữ liệu Docker local",
          "Xóa image/container/cache đã dừng; lần build sau sẽ chậm, container dừng sẽ mất.",
          "Removes stopped images, containers and build cache; the next build is slower."),
    _rule("G-SECRET-READ", ASK,
          r"\b(?:cat|less|more|head|tail|bat|type|strings|xxd)\s+[^\n|;&]*(?:(?<![\w.])\.env(?!\.(?:example|sample|template|dist))\b|"
          r"id_rsa|id_ed25519|\.pem\b|\.p12\b|\.aws/credentials|\.npmrc|\.pypirc|\.netrc|\.kube/config)",
          "prints credentials into the transcript (AGENT-003)",
          "Print a secrets file", "Hiển thị file chứa mật khẩu/khóa",
          "Nội dung bí mật (.env, SSH key, token) sẽ nằm trong lịch sử hội thoại.",
          "Secret content (.env, SSH key, token) ends up in the conversation history."),
    _rule("G-PIPE-TO-SHELL", ASK, r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python3?|node)\b",
          "executes a downloaded script without review (supply chain)",
          "Run a downloaded script", "Tải script từ mạng và chạy ngay",
          "Script chưa được xem nội dung sẽ chạy trên máy. Nên tải về, đọc rồi mới chạy.",
          "An unreviewed script runs on this machine. Download it, read it, then run it."),
)


# --------------------------------------------------------------------------- evaluation and hook output


def _effective(decision: str, mode: str) -> str:
    if mode == "strict":
        return DENY
    if mode == "ask":
        return ASK
    return decision


def evaluate_command(command: str, mode: str = "standard") -> tuple[str | None, list[GuardRule]]:
    """Return (decision, matched rules) for one shell command; deny wins over ask; None = no opinion."""
    segments = active_segments(command)
    texts = [segment for segment, _operator in segments]
    active = " ".join(f"{segment} {operator}" for segment, operator in segments).strip()
    matched = [rule for rule in GUARD_RULES
               if rule.pattern.search(active) and not (rule.exempt and rule.exempt(texts))]
    if not matched:
        return None, []
    decisions = {_effective(rule.decision, mode) for rule in matched}
    decision = DENY if DENY in decisions else ASK
    return decision, [rule for rule in matched if _effective(rule.decision, mode) == decision]


def hook_output(decision: str, rules: list[GuardRule], tool_input: dict | None = None, language: str = "en") -> dict:
    """PreToolUse JSON telling Claude Code to deny or ask, with plain-language reasons in the user's language."""
    heading = _heading(decision, rules, language)
    advice = " ".join(rule.advice(language) for rule in rules)
    if decision == DENY:
        # The agent reads this one; it relays the command to the user in the user's language.
        reason = (f"{heading}. " + "; ".join(f"{rule.rule_id}: {rule.reason}" for rule in rules) +
                  ". The agent must not run this. Show it to the user, in the language of their prompt, as a table "
                  f"with columns {_MESSAGES['columns'][language]}: ⛔ + what it does in plain words, the exact command, "
                  f"and the risk ({advice}), so they can decide and run it themselves.")
        output = {"hookEventName": "PreToolUse", "permissionDecision": decision,
                  "permissionDecisionReason": f"devskills guard — {reason}"}
        return {"hookSpecificOutput": output}
    rule_ids = ", ".join(rule.rule_id for rule in rules)
    output = {"hookEventName": "PreToolUse", "permissionDecision": decision,
              "permissionDecisionReason": f"{heading}. {advice} {_MESSAGES['confirm'][language]} [{rule_ids}]"}
    if tool_input and tool_input.get("command"):
        # The Bash prompt shows the description; prefixing it explains prompts raised by settings ask rules too.
        description = str(tool_input.get("description") or "").strip()
        output["updatedInput"] = {**tool_input, "description": heading + (f" | {description}" if description else "")}
    return {"hookSpecificOutput": output}


def run(args: argparse.Namespace) -> int:
    """Hook entry point: read PreToolUse JSON from stdin (or --check COMMAND) and print a deny/ask decision."""
    try:
        if args.check is not None:
            decision, rules = evaluate_command(args.check, args.mode)
            if decision is None:
                print("no opinion (normal permission flow applies)")
            else:
                language = resolve_language(args.lang, {})
                print(f"{decision}: {_heading(decision, rules, language)}\n" +
                      "\n".join(f"  [{rule.rule_id}] {rule.advice(language)}" for rule in rules))
            return 0
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input) if raw_input.strip() else {}
        if payload.get("tool_name") != "Bash":
            return 0
        tool_input = payload.get("tool_input") or {}
        decision, rules = evaluate_command(str(tool_input.get("command") or ""), args.mode)
        if decision is not None:  # The transcript is read only when there is something to say.
            language = resolve_language(args.lang, payload)
            print(json.dumps(hook_output(decision, rules, tool_input, language), ensure_ascii=False))
        return 0
    except Exception as error:  # noqa: BLE001 — fail open: a guard bug must not block every shell command.
        print(f"devskills guard error (allowing normal permission flow): {type(error).__name__}: {error}", file=sys.stderr)
        return 0
