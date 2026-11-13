"""Security signals for check-code: XSS, SQL/NoSQL injection, path traversal, SSRF,
open redirect, template injection, JWT misuse, CORS/cookie/CSRF settings, mass
assignment, prototype pollution, ReDoS, XXE, weak password hashing and login
routes without rate limiting (plan §21, OWASP ASVS / API Top 10).

These are taint-free heuristics: they look for user input (`request.*`,
`req.body`, `$_GET`, ...) flowing directly into a dangerous sink on the same
statement. Data that travels through variables is not tracked, so a clean result
is not proof of safety; the review-security skill covers the semantic review.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from devskills.models import Finding

PY_REQUEST_ROOTS = frozenset({"request", "req"})
# Attributes through which Flask/Django/Starlette/DRF expose client-controlled data.
PY_REQUEST_INPUT_ATTRIBUTES = frozenset({
    "args", "form", "values", "json", "data", "files", "cookies", "headers", "GET", "POST", "FILES", "COOKIES",
    "query_params", "path_params", "body", "get_json", "query", "params", "META",
})
LOGIN_ROUTE = re.compile(r"""['"`][^'"`\n]*(login|signin|sign-in|token|password|otp|register|signup|forgot|reset)[^'"`\n]*['"`]""", re.IGNORECASE)
RATE_LIMIT_MARKERS = re.compile(r"(?i)(limiter|rate_?limit|ratelimit|throttl|slowapi|express-rate-limit|rate-limiter|bucket4j|RateLimiter|@Throttle)")
# A quantified group whose first atom is itself quantified and whose remaining atoms are all
# optional, e.g. (\w+)+, ([a-z]+)*, (.*)+, (\w+\s?)+ — the shapes behind catastrophic backtracking.
# Groups with a mandatory separator such as (-[a-z]+)* or (\w+\s+)* are not reported.
_REGEX_ATOM = r"(?:\[(?:\\.|[^\]\\])*\]|\\.|[^()\[\]\\|+*?{}])"
NESTED_QUANTIFIER = re.compile(r"\((?:\?:)?" + _REGEX_ATOM + r"[+*](?:" + _REGEX_ATOM + r"[*?])*\)[+*{]")
JS_REGEX_LITERAL = re.compile(r"(?<![\w$)\]])/((?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\n\\\[])+)/[dgimsuyv]*")


def _finding(rule_id: str, severity: str, message: str, path: str, line: int | None, hint: str) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message=message, path=path, line=line, hint=hint)


# --------------------------------------------------------------------------- Python (AST)


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        parts.append(_dotted(node.func) + "()")
    return ".".join(reversed(parts))


def _uses_request(node: ast.AST) -> bool:
    """True when the expression reads client data directly, e.g. request.args / request.GET / req.body.

    A bare variable named `request` (for example a urllib Request object) is not enough.
    """
    for child in ast.walk(node):
        if (isinstance(child, ast.Attribute) and child.attr in PY_REQUEST_INPUT_ATTRIBUTES
                and isinstance(child.value, ast.Name) and child.value.id in PY_REQUEST_ROOTS):
            return True
    return False


def _mentions(node: ast.AST, pattern: re.Pattern[str]) -> bool:
    return any(isinstance(child, ast.Name) and pattern.search(child.id) or
               isinstance(child, ast.Attribute) and pattern.search(child.attr)
               for child in ast.walk(node))


_PASSWORD_NAME = re.compile(r"(?i)pass(word|wd)?|pwd")


def python_security_findings(rel_path: str, tree: ast.AST, text: str) -> list[Finding]:
    """Security signals for one parsed Python file: sinks fed directly by request data, unsafe settings."""
    findings: list[Finding] = []

    def add(node: ast.AST, rule_id: str, severity: str, message: str, hint: str) -> None:
        findings.append(_finding(rule_id, severity, message, rel_path, getattr(node, "lineno", None), hint))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            short = name.rsplit(".", 1)[-1]
            keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
            arguments = [*node.args, *keywords.values()]
            request_input = any(_uses_request(argument) for argument in arguments)
            if short == "render_template_string" and node.args and not isinstance(node.args[0], ast.Constant):
                add(node, "PY-SSTI", "high", "template rendered from a dynamic string",
                    "Never render user input as a template; pass it as a variable to a fixed template (SEC-003).")
            if short in ("mark_safe", "Markup") and node.args and not isinstance(node.args[0], ast.Constant):
                add(node, "PY-XSS-MARK-SAFE", "medium", f"{short}() on dynamic content disables escaping",
                    "Escape user data; use format_html/escape or sanitize with a maintained library (FE-009).")
            if short == "Environment" and "jinja2" in text and (
                    "autoescape" not in keywords or (isinstance(keywords["autoescape"], ast.Constant) and keywords["autoescape"].value is False)):
                add(node, "PY-XSS-AUTOESCAPE-OFF", "medium", "Jinja2 Environment without autoescape",
                    "Use autoescape=select_autoescape() for HTML templates (FE-009).")
            if name in ("jwt.decode",):
                options = keywords.get("options")
                no_verify = isinstance(options, ast.Dict) and any(
                    isinstance(key, ast.Constant) and key.value == "verify_signature" and isinstance(value, ast.Constant) and value.value is False
                    for key, value in zip(options.keys, options.values))
                if no_verify or (isinstance(keywords.get("verify"), ast.Constant) and keywords["verify"].value is False):
                    add(node, "PY-JWT-NO-VERIFY", "high", "JWT decoded without signature verification",
                        "Verify signatures with an explicit algorithms=[...] list and check exp/aud/iss (SEC-007).")
                elif "algorithms" not in keywords:
                    add(node, "PY-JWT-NO-ALGORITHMS", "medium", "jwt.decode without an explicit algorithms list",
                        "Pin algorithms=['RS256'] (or the one you issue) to prevent algorithm confusion.")
            if name in ("hashlib.md5", "hashlib.sha1", "hashlib.sha256", "hashlib.sha512", "md5", "sha1") and any(
                    _mentions(argument, _PASSWORD_NAME) for argument in node.args):
                add(node, "PY-WEAK-PASSWORD-HASH", "high", f"password hashed with fast hash {name}",
                    "Use argon2/bcrypt/scrypt through a maintained library (passlib, argon2-cffi, Django hashers) (SEC-006).")
            if request_input and (short.endswith("redirect") or short in ("HttpResponseRedirect", "RedirectResponse")):
                add(node, "PY-OPEN-REDIRECT", "medium", "redirect target taken from the request",
                    "Allow only relative paths or an allowlist of hosts (url_has_allowed_host_and_scheme) (SEC-008).")
            if request_input and (name in ("requests.get", "requests.post", "requests.put", "requests.request", "httpx.get",
                                           "httpx.post", "urllib.request.urlopen", "urlopen", "aiohttp.request")
                                  or short in ("urlopen",)):
                add(node, "PY-SSRF", "high", "outbound request to a URL taken from the request",
                    "Allowlist schemes/hosts, resolve and block private/metadata IPs, disable redirects (SEC-008).")
            if request_input and (short in ("open", "send_file", "FileResponse", "safe_join") or name in ("os.path.join", "pathlib.Path", "Path")):
                add(node, "PY-PATH-TRAVERSAL", "high", "file path built from request input",
                    "Use server-generated names; resolve the path and verify it stays inside the base directory (SEC-008).")
            if short == "extractall" and not keywords.get("filter"):
                add(node, "PY-ARCHIVE-SLIP", "medium", "archive extracted without validating member paths",
                    "Check every member stays inside the target dir (tarfile filter='data' on 3.12+) and cap total size.")
            if short == "XMLParser" and isinstance(keywords.get("resolve_entities"), ast.Constant) and keywords["resolve_entities"].value is True:
                add(node, "PY-XXE", "high", "XML parser resolves external entities",
                    "Disable entity resolution or use defusedxml for untrusted XML.")
            if short in ("set_cookie",):
                for flag in ("httponly", "secure"):
                    if isinstance(keywords.get(flag), ast.Constant) and keywords[flag].value is False:
                        add(node, "PY-COOKIE-FLAGS", "medium", f"cookie set with {flag}=False",
                            "Session/auth cookies need HttpOnly, Secure and an explicit SameSite (SEC-007).")
            if short in ("compile", "match", "search", "fullmatch", "findall", "sub") and name.startswith("re.") and node.args:
                pattern = node.args[0]
                if isinstance(pattern, ast.Constant) and isinstance(pattern.value, str) and NESTED_QUANTIFIER.search(pattern.value):
                    add(node, "PY-REDOS", "medium", "regex with nested quantifiers can backtrack catastrophically",
                        "Rewrite without nested quantifiers, bound input length, or use a linear-time engine (SEC-009).")
                elif request_input:
                    add(node, "PY-USER-REGEX", "high", "regular expression built from request input",
                        "Escape input with re.escape and bound its length (ReDoS).")
            if short in ("add_middleware",) and node.args and _dotted(node.args[0]).endswith("CORSMiddleware"):
                origins = keywords.get("allow_origins")
                credentials = keywords.get("allow_credentials")
                wildcard = isinstance(origins, (ast.List, ast.Tuple)) and any(isinstance(item, ast.Constant) and item.value == "*" for item in origins.elts)
                if wildcard and isinstance(credentials, ast.Constant) and credentials.value is True:
                    add(node, "PY-CORS-WILDCARD-CREDENTIALS", "high", "CORS allows any origin with credentials",
                        "List trusted origins explicitly; CORS never replaces authorization (SEC-007).")
            if short in ("create", "update", "objects.create") and any(
                    isinstance(keyword, ast.keyword) and keyword.arg is None and _uses_request(keyword.value) for keyword in node.keywords):
                add(node, "PY-MASS-ASSIGNMENT", "medium", "model fields assigned from the whole request payload",
                    "Map an explicit DTO/serializer with allowed fields; never let clients set protected fields (API-003).")
            if short == "run" and isinstance(keywords.get("debug"), ast.Constant) and keywords["debug"].value is True:
                add(node, "PY-DEBUG-ENABLED", "medium", "application started with debug=True",
                    "Debug mode exposes stack traces and consoles; enable only in local development config.")
        elif isinstance(node, ast.ClassDef):
            for statement in node.body:
                if (isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "fields" for target in statement.targets)
                        and isinstance(statement.value, ast.Constant) and statement.value.value == "__all__"):
                    add(statement, "PY-MASS-ASSIGNMENT", "medium", "serializer/form exposes fields='__all__'",
                        "List fields explicitly and mark protected ones read-only (API-002/API-003).")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if _dotted(decorator if not isinstance(decorator, ast.Call) else decorator.func).endswith("csrf_exempt"):
                    add(decorator, "PY-CSRF-EXEMPT", "medium", f"CSRF protection disabled on `{node.name}`",
                        "Keep CSRF protection for cookie-authenticated endpoints; exempt only token-authenticated APIs.")
    if PurePosixPath(rel_path).name.startswith("settings") or rel_path.endswith(("config.py", "settings.py")):
        for match in re.finditer(r"^(DEBUG\s*=\s*True|ALLOWED_HOSTS\s*=\s*\[\s*['\"]\*['\"]\s*\]|CORS_(?:ORIGIN_)?ALLOW_ALL(?:_ORIGINS)?\s*=\s*True|"
                                 r"(?:SESSION|CSRF)_COOKIE_SECURE\s*=\s*False)", text, re.MULTILINE):
            findings.append(_finding("PY-INSECURE-SETTING", "medium", f"insecure setting `{match.group(1)}`", rel_path,
                                     text.count("\n", 0, match.start()) + 1,
                                     "Keep production-safe defaults; override only in local development settings."))
    findings.extend(_login_without_rate_limit(rel_path, text, re.compile(r"@\w+\.(post|put|route|api_view)\(|path\(|re_path\(")))
    return findings


# --------------------------------------------------------------------------- pattern rules for other languages


@dataclass(frozen=True)
class PatternRule:
    languages: frozenset[str]
    rule_id: str
    severity: str
    regex: re.Pattern[str]
    message: str
    hint: str
    # "masked" = strings and comments blanked; "code" = comments blanked, strings kept.
    source: str = "code"


_JS = frozenset({"js"})
_PHP = frozenset({"php"})
_JVM = frozenset({"java", "cs"})
_REQ_JS = r"req(?:uest)?\.(?:body|query|params|headers|cookies)"
_REQ_PHP = r"(?:\$_(?:GET|POST|REQUEST|COOKIE|FILES)|\$request->(?:input|get|query|post|all|file)\()"

PATTERN_RULES: tuple[PatternRule, ...] = (
    # XSS
    PatternRule(_JS, "JS-DOCUMENT-WRITE", "medium", re.compile(r"\bdocument\.write(ln)?\s*\("), "document.write injects raw HTML",
                "Create elements/text nodes instead (FE-009).", "masked"),
    PatternRule(_JS, "JS-REFLECTED-XSS", "high", re.compile(r"\bres\.(send|write|end)\s*\([^;\n]*" + _REQ_JS),
                "request data written straight into the response", "Render through an escaping template or return JSON (FE-009)."),
    PatternRule(_JS, "JS-STRING-TIMER", "medium", re.compile(r"\bset(Timeout|Interval)\s*\(\s*['\"`]"),
                "timer with a code string is eval", "Pass a function, never a string (SEC-004)."),
    PatternRule(_PHP, "PHP-REFLECTED-XSS", "high", re.compile(r"\b(echo|print)\b[^;\n]*" + _REQ_PHP),
                "request data echoed without escaping", "Escape with htmlspecialchars($v, ENT_QUOTES) or Blade {{ }} (FE-009)."),
    PatternRule(_PHP, "PHP-BLADE-RAW", "medium", re.compile(r"\{!!\s*\$"), "Blade {!! !!} prints unescaped HTML",
                "Use {{ }} unless the value is sanitized HTML (FE-009)."),
    PatternRule(frozenset({"cs"}), "CS-HTML-RAW", "medium", re.compile(r"\bHtml\.Raw\s*\("), "Html.Raw prints unescaped HTML",
                "Encode output; sanitize when HTML is required (FE-009)."),
    # Injection
    PatternRule(_JS, "JS-PRISMA-UNSAFE-RAW", "high", re.compile(r"\$(queryRawUnsafe|executeRawUnsafe)\s*\("),
                "Prisma *Unsafe raw query", "Use $queryRaw tagged templates (parameterized) (SEC-002).", "masked"),
    PatternRule(_JS, "JS-NOSQL-INJECTION", "medium", re.compile(r"\.(find|findOne|findOneAndUpdate|updateOne|updateMany|deleteOne|deleteMany|countDocuments)\s*\(\s*" + _REQ_JS),
                "query object taken directly from the request (NoSQL operator injection)",
                "Build the filter from validated, typed fields; reject keys starting with '$' (SEC-002)."),
    PatternRule(_JS, "JS-USER-REGEX", "high", re.compile(r"new\s+RegExp\s*\(\s*" + _REQ_JS), "regular expression built from request input",
                "Escape input and bound its length (ReDoS, SEC-009)."),
    # Path traversal / file access
    PatternRule(_JS, "JS-PATH-TRAVERSAL", "high",
                re.compile(r"\b(res\.(sendFile|download)|fs\.(readFile|readFileSync|createReadStream|writeFile|unlink|rm)|path\.(join|resolve))\s*\([^;\n]*" + _REQ_JS),
                "file path built from request input", "Use server-generated names; resolve and verify the path stays in the base dir (SEC-008)."),
    PatternRule(_PHP, "PHP-FILE-INCLUSION", "high", re.compile(r"\b(include|include_once|require|require_once)\b[^;\n]*" + _REQ_PHP),
                "file inclusion from request input (LFI/RFI)", "Map input to an allowlist of known files (SEC-008)."),
    PatternRule(_PHP, "PHP-PATH-TRAVERSAL", "high", re.compile(r"\b(file_get_contents|fopen|readfile|file|unlink|copy|move_uploaded_file)\s*\([^;\n]*" + _REQ_PHP),
                "file path or URL taken from request input", "Use server-generated names and verify the resolved path (SEC-008)."),
    PatternRule(_JVM, "JVM-PATH-TRAVERSAL", "high", re.compile(r"new\s+File\s*\([^;\n]*getParameter\(|Paths\.get\s*\([^;\n]*getParameter\("),
                "file path built from request input", "Normalize and verify the path stays inside the base directory (SEC-008)."),
    # SSRF
    PatternRule(_JS, "JS-SSRF", "high", re.compile(r"\b(fetch|axios(\.\w+)?|got(\.\w+)?|needle|superagent\.\w+|https?\.(get|request))\s*\(\s*" + _REQ_JS),
                "outbound request to a URL from the request", "Allowlist hosts, block private/metadata IPs, disable redirects (SEC-008)."),
    PatternRule(_PHP, "PHP-SSRF", "high", re.compile(r"(CURLOPT_URL\s*,\s*" + _REQ_PHP + r"|Http::(get|post|send)\s*\(\s*" + _REQ_PHP + r")"),
                "outbound request to a URL from the request", "Allowlist hosts, block private/metadata IPs (SEC-008)."),
    # Open redirect
    PatternRule(_JS, "JS-OPEN-REDIRECT", "medium", re.compile(r"\bres\.redirect\s*\([^;\n]*" + _REQ_JS), "redirect target from the request",
                "Allow only relative paths or allowlisted hosts (SEC-008)."),
    PatternRule(_PHP, "PHP-OPEN-REDIRECT", "medium", re.compile(r"(redirect\s*\(\s*" + _REQ_PHP + r"|header\s*\(\s*['\"]Location:[^;\n]*" + _REQ_PHP + r")"),
                "redirect target from the request", "Allow only relative paths or allowlisted hosts (SEC-008)."),
    PatternRule(_JVM, "JVM-OPEN-REDIRECT", "medium", re.compile(r"sendRedirect\s*\([^;\n]*getParameter\("), "redirect target from the request",
                "Allow only relative paths or allowlisted hosts (SEC-008)."),
    # Mass assignment / prototype pollution
    PatternRule(_JS, "JS-MASS-ASSIGNMENT", "medium",
                re.compile(r"\.(create|update|insert|findByIdAndUpdate|findOneAndUpdate|updateOne|build|save)\s*\([^;\n]*\b" + _REQ_JS + r"\s*[,)]|new\s+\w+\s*\(\s*req\.body\s*\)"),
                "whole request body written into a model", "Pick allowed fields explicitly (DTO/schema); protect role/price/owner fields (API-003)."),
    PatternRule(_JS, "JS-PROTOTYPE-POLLUTION", "medium",
                re.compile(r"(Object\.assign\s*\([^;\n]*|_\.(merge|mergeWith|defaultsDeep|set)\s*\([^;\n]*|\$\.extend\s*\(\s*true[^;\n]*)" + _REQ_JS),
                "deep merge of request data", "Validate the shape first and reject __proto__/constructor/prototype keys."),
    PatternRule(_PHP, "PHP-MASS-ASSIGNMENT", "medium", re.compile(r"(::create|->update|->fill|->forceFill)\s*\(\s*\$request->all\(\)|\$guarded\s*=\s*\[\s*\]"),
                "all request fields assigned to a model", "Use $request->validated() / $fillable allowlists (API-003)."),
    # Auth, sessions, CORS, crypto
    PatternRule(_JS, "JS-JWT-DECODE", "medium", re.compile(r"\bjwt\.decode\s*\("), "jwt.decode does not verify the signature",
                "Use jwt.verify with an explicit algorithms list; check exp/aud/iss (SEC-007).", "masked"),
    PatternRule(_JS, "JS-JWT-NONE", "high", re.compile(r"algorithms\s*:\s*\[[^\]]*['\"]none['\"]", re.IGNORECASE), "JWT 'none' algorithm accepted",
                "Allow only the algorithm you issue (SEC-007)."),
    PatternRule(_JS, "JS-CORS-CREDENTIALS", "medium", re.compile(r"origin\s*:\s*(['\"]\*['\"]|true)[^}\n]*credentials\s*:\s*true|credentials\s*:\s*true[^}\n]*origin\s*:\s*(['\"]\*['\"]|true)"),
                "CORS reflects any origin with credentials", "List trusted origins explicitly (SEC-007)."),
    PatternRule(_JS, "JS-COOKIE-FLAGS", "medium", re.compile(r"httpOnly\s*:\s*false|secure\s*:\s*false", re.IGNORECASE),
                "cookie without HttpOnly/Secure", "Auth cookies need HttpOnly, Secure and SameSite (SEC-007)."),
    PatternRule(_JS, "JS-WEAK-PASSWORD-HASH", "high", re.compile(r"createHash\s*\(\s*['\"](md5|sha1|sha256)['\"]\s*\)\s*\.update\s*\([^)]*pass", re.IGNORECASE),
                "password hashed with a fast hash", "Use bcrypt/argon2/scrypt (SEC-006)."),
    PatternRule(_PHP, "PHP-WEAK-PASSWORD-HASH", "high", re.compile(r"\b(md5|sha1|hash\s*\(\s*['\"](md5|sha1|sha256)['\"])\s*\(?[^;\n]*\$\w*pass", re.IGNORECASE),
                "password hashed with a fast hash", "Use password_hash()/password_verify() (SEC-006)."),
    PatternRule(_JVM, "JVM-WEAK-HASH", "medium", re.compile(r"MessageDigest\.getInstance\s*\(\s*\"(MD5|SHA-?1)\"", re.IGNORECASE),
                "MD5/SHA-1 digest", "Use BCrypt/Argon2 for passwords and SHA-256+ for integrity (SEC-006)."),
    PatternRule(frozenset({"java"}), "JAVA-XXE", "medium", re.compile(r"DocumentBuilderFactory\.newInstance\s*\(|SAXParserFactory\.newInstance\s*\(|XMLInputFactory\.newInstance\s*\("),
                "XML parser factory: external entities may be enabled", "Set disallow-doctype-decl / disable external entities (XXE).", "masked"),
)


def pattern_findings(language: str, rel_path: str, masked: str, code: str) -> list[Finding]:
    """Apply one language's regex security rules plus JS ReDoS literals and login rate-limit checks."""
    findings: list[Finding] = []
    for rule in PATTERN_RULES:
        if language not in rule.languages:
            continue
        source = masked if rule.source == "masked" else code
        for match in rule.regex.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            findings.append(_finding(rule.rule_id, rule.severity, rule.message, rel_path, line, rule.hint))
    if language == "js":
        for match in JS_REGEX_LITERAL.finditer(code):
            if NESTED_QUANTIFIER.search(match.group(1)):
                findings.append(_finding("JS-REDOS", "medium", "regex literal with nested quantifiers can backtrack catastrophically",
                                         rel_path, code.count("\n", 0, match.start()) + 1,
                                         "Rewrite without nested quantifiers or bound input length (SEC-009)."))
    if language in ("js", "php"):
        route_pattern = (re.compile(r"\b(router|app|server|fastify)\.(post|put|all)\s*\(") if language == "js"
                         else re.compile(r"Route::(post|put|match|any)\s*\("))
        findings.extend(_login_without_rate_limit(rel_path, code, route_pattern))
    if language == "java" and re.search(r"DocumentBuilderFactory|SAXParserFactory|XMLInputFactory", masked) \
            and "disallow-doctype-decl" in code:
        findings = [finding for finding in findings if finding.rule_id != "JAVA-XXE"]
    return findings


def _login_without_rate_limit(rel_path: str, code: str, route_pattern: re.Pattern[str]) -> list[Finding]:
    """Login/OTP/password routes in a file that never mentions a rate limiter (SEC-009)."""
    if RATE_LIMIT_MARKERS.search(code):
        return []
    findings = []
    for match in route_pattern.finditer(code):
        window = code[match.end():match.end() + 160]
        if LOGIN_ROUTE.match(window.lstrip()) or LOGIN_ROUTE.search(window.split("\n", 1)[0]):
            findings.append(_finding("SEC-AUTH-NO-RATE-LIMIT", "low", "authentication route without a visible rate limit", rel_path,
                                     code.count("\n", 0, match.start()) + 1,
                                     "Verify brute-force protection: per-account + per-IP limits, 429 with Retry-After (SEC-009); "
                                     "prove it with `ds.py rate-limit-probe` on localhost."))
    return findings
