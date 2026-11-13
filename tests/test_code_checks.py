"""check-code rules: Python AST checks, C-like masking, security signals, suppressions."""

import unittest

from devskills.code_checks import CheckSettings, _apply_suppressions, check_file, mask_c_like
from tests._support import make_temp_dir, run_cli, run_cli_json, write

SETTINGS = CheckSettings(multiline_comment_style="block", max_function_lines=60, doc_min_lines=12)


def rule_ids(path, code, settings=SETTINGS):
    return [finding.rule_id for finding in check_file(path, code, settings)]


def severities(path, code, rule):
    return [finding.severity for finding in check_file(path, code, SETTINGS) if finding.rule_id == rule]


class PythonRulesTest(unittest.TestCase):
    def test_mutable_default_and_bare_except(self):
        code = "def add(item, bucket=[]):\n    try:\n        bucket.append(item)\n    except:\n        raise\n"
        ids = rule_ids("app/x.py", code)
        self.assertIn("PY-MUTABLE-DEFAULT", ids)
        self.assertIn("PY-BARE-EXCEPT", ids)

    def test_swallowed_exception_severity_depends_on_type_and_comment(self):
        self.assertEqual(severities("a.py", "try:\n    x()\nexcept Exception:\n    pass\n", "PY-SWALLOWED-EXCEPTION"), ["high"])
        self.assertEqual(severities("a.py", "try:\n    x()\nexcept KeyError:\n    pass\n", "PY-SWALLOWED-EXCEPTION"), ["medium"])
        self.assertEqual(severities("a.py", "try:\n    x()\nexcept KeyError:\n    pass  # optional key\n", "PY-SWALLOWED-EXCEPTION"), ["info"])

    def test_dangerous_calls(self):
        code = (
            "import subprocess, requests, yaml\n"
            "def f(cmd, data, user_id):\n"
            "    eval(data)\n"
            "    subprocess.run(cmd, shell=True)\n"
            "    requests.get('https://example.invalid')\n"
            "    yaml.load(data)\n"
            "    requests.post('https://example.invalid', timeout=5, verify=False)\n"
            "    cursor.execute(f'SELECT * FROM users WHERE id = {user_id}')\n"
        )
        ids = rule_ids("app/x.py", code)
        for expected in ("PY-EVAL-EXEC", "PY-SHELL-TRUE", "PY-HTTP-NO-TIMEOUT", "PY-UNSAFE-YAML", "PY-TLS-VERIFY-OFF", "PY-SQL-STRING-BUILD"):
            self.assertIn(expected, ids)
        self.assertEqual(ids.count("PY-HTTP-NO-TIMEOUT"), 1, "the call with timeout= must not be flagged")

    def test_parameterized_sql_is_not_flagged(self):
        self.assertNotIn("PY-SQL-STRING-BUILD", rule_ids("a.py", "def f(c, i):\n    c.execute('SELECT 1 WHERE id = %s', (i,))\n"))

    def test_async_blocking_and_dropped_task(self):
        code = "import time, asyncio\nasync def handler():\n    time.sleep(1)\n    asyncio.create_task(work())\n"
        ids = rule_ids("a.py", code)
        self.assertIn("PY-BLOCKING-IN-ASYNC", ids)
        self.assertIn("PY-DROPPED-TASK", ids)

    def test_resources_threads_sessions(self):
        code = (
            "import threading\nfrom sqlalchemy import create_engine\nfrom sqlalchemy.orm import Session\n"
            "session = Session()\n"
            "def read(path):\n    return open(path).read()\n"
            "def fan_out(items):\n    for item in items:\n        threading.Thread(target=print, args=(item,)).start()\n"
            "def query():\n    engine = create_engine('sqlite://')\n    return engine\n"
            "def make_engine():\n    return create_engine('sqlite://')\n"
            "def safe(path):\n    with open(path) as handle:\n        return handle.read()\n"
        )
        ids = rule_ids("app/db.py", code)
        self.assertIn("PY-GLOBAL-SESSION", ids)
        self.assertEqual(ids.count("PY-OPEN-NO-WITH"), 1)
        self.assertIn("PY-THREAD-IN-LOOP", ids)
        self.assertEqual(ids.count("PY-ENGINE-PER-CALL"), 1, "factory functions may create engines")

    def test_slow_call_inside_transaction(self):
        code = (
            "import requests, time\nfrom django.db import transaction\n"
            "def pay(order):\n    with transaction.atomic():\n        order.save()\n"
            "        requests.post('https://psp', timeout=5)\n"
            "def wait(session):\n    with session.begin():\n        time.sleep(2)\n"
            "@transaction.atomic\ndef notify(user):\n    send_mail('s', 'b', 'a@x', [user.email])\n"
            "def after_commit(order):\n    with transaction.atomic():\n        order.save()\n"
            "        transaction.on_commit(lambda: requests.post('https://psp', timeout=5))\n"
            "    requests.post('https://psp', timeout=5)\n"
            "def nested_definition():\n    with transaction.atomic():\n"
            "        def later():\n            requests.get('https://x', timeout=5)\n        return later\n"
        )
        found = [(finding.rule_id, finding.line) for finding in check_file("app/orders.py", code, SETTINGS)
                 if finding.rule_id == "PY-SLOW-CALL-IN-TRANSACTION"]
        self.assertEqual([line for _, line in found], [6, 9, 12])

    def test_money_naming_docs_comments(self):
        code = (
            "def getUserPrice(unit_price: float) -> float:\n    price = float(unit_price)\n    return price\n"
            "class order_service:\n    pass\n"
            "def do_stuff():\n    pass\n"
            "# TODO fix this later\n"
            "# TODO(tri): link issue\n"
            "def f():\n    x = 1\n    '''not a docstring'''\n    return x\n"
        )
        ids = rule_ids("app/money.py", code)
        self.assertGreaterEqual(ids.count("PY-FLOAT-MONEY"), 2)
        self.assertIn("PY-NAMING-FUNCTION", ids)
        self.assertIn("PY-NAMING-CLASS", ids)
        self.assertIn("PY-VAGUE-NAME", ids)
        self.assertEqual(ids.count("PY-TODO-NO-OWNER"), 1)
        self.assertIn("PY-STRING-AS-COMMENT", ids)

    def test_rate_and_ratio_names_are_not_money(self):
        self.assertNotIn("PY-FLOAT-MONEY", rule_ids("a.py", "tax_rate: float = 0.1\ndiscount_ratio = 0.5\n"))

    def test_missing_docstring_only_for_long_public_functions(self):
        body = "\n".join(f"    value_{index} = {index}" for index in range(14))
        ids = rule_ids("app/x.py", f"def compute():\n{body}\n    return 1\ndef _private():\n{body}\n    return 1\n")
        self.assertEqual(ids.count("PY-MISSING-DOCSTRING"), 1)
        self.assertNotIn("PY-MISSING-DOCSTRING", rule_ids("tests/test_x.py", f"def compute():\n{body}\n    return 1\n"))

    def test_c_style_comment_in_python_is_reported(self):
        ids = rule_ids("a.py", "/*\n * comment\n */\nx = 1\n")
        self.assertIn("PY-SYNTAX-ERROR", ids)
        self.assertIn("PY-C-STYLE-COMMENT", ids)

    def test_assert_naive_datetime_insecure_random(self):
        code = "import random, datetime\ndef f(x):\n    assert x > 0\n    reset_token = random.choice('abc')\n    return datetime.datetime.now()\n"
        ids = rule_ids("app/x.py", code)
        self.assertIn("PY-ASSERT-VALIDATION", ids)
        self.assertIn("PY-INSECURE-RANDOM", ids)
        self.assertIn("PY-NAIVE-DATETIME", ids)
        self.assertNotIn("PY-ASSERT-VALIDATION", rule_ids("tests/test_x.py", "def test_a():\n    assert 1\n"))


class PythonSecurityTest(unittest.TestCase):
    def test_request_fed_sinks(self):
        code = (
            "import requests, os, jwt, hashlib\nfrom flask import request, redirect, render_template_string, send_file\n"
            "def view():\n"
            "    requests.get(request.args['url'], timeout=3)\n"
            "    send_file(os.path.join('/data', request.args.get('name')))\n"
            "    redirect(request.args.get('next'))\n"
            "    render_template_string(request.form['tpl'])\n"
            "    jwt.decode(token, key, options={'verify_signature': False})\n"
            "    hashlib.md5(password.encode()).hexdigest()\n"
        )
        ids = rule_ids("app/views.py", code)
        for expected in ("PY-SSRF", "PY-PATH-TRAVERSAL", "PY-OPEN-REDIRECT", "PY-SSTI", "PY-JWT-NO-VERIFY", "PY-WEAK-PASSWORD-HASH"):
            self.assertIn(expected, ids)

    def test_local_variable_named_request_is_not_user_input(self):
        code = "from urllib.request import Request, urlopen\ndef call(url):\n    request = Request(url)\n    return urlopen(request, timeout=5)\n"
        self.assertNotIn("PY-SSRF", rule_ids("app/client.py", code))

    def test_redos_detection_avoids_safe_shapes(self):
        self.assertIn("PY-REDOS", rule_ids("a.py", "import re\nPATTERN = re.compile(r'^(\\w+\\s?)+$')\n"))
        self.assertNotIn("PY-REDOS", rule_ids("a.py", "import re\nNAME = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')\n"))

    def test_framework_settings(self):
        code = (
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True)\n"
            "class UserSerializer(Serializer):\n    class Meta:\n        fields = '__all__'\n"
            "@csrf_exempt\ndef hook(request):\n    pass\n"
        )
        ids = rule_ids("app/api.py", code)
        self.assertIn("PY-CORS-WILDCARD-CREDENTIALS", ids)
        self.assertIn("PY-MASS-ASSIGNMENT", ids)
        self.assertIn("PY-CSRF-EXEMPT", ids)
        self.assertIn("PY-INSECURE-SETTING", rule_ids("config/settings.py", "DEBUG = True\nALLOWED_HOSTS = ['*']\n"))

    def test_login_route_without_rate_limit(self):
        code = "@app.post('/api/login')\ndef login():\n    return 1\n"
        self.assertIn("SEC-AUTH-NO-RATE-LIMIT", rule_ids("app/auth.py", code))
        limited = "from slowapi import Limiter\n@app.post('/api/login')\n@limiter.limit('5/minute')\ndef login():\n    return 1\n"
        self.assertNotIn("SEC-AUTH-NO-RATE-LIMIT", rule_ids("app/auth.py", limited))


class JavaScriptRulesTest(unittest.TestCase):
    def test_masking_keeps_lines_and_hides_strings(self):
        code = "const a = 'http://x//y'; // real comment\nconst b = `t ${c}`;\n/* block\n comment */\n"
        no_comments, masked, comments = mask_c_like(code)
        self.assertEqual(code.count("\n"), masked.count("\n"))
        self.assertNotIn("x//y", masked)
        self.assertIn("http://x//y", no_comments)
        self.assertEqual([comment.kind for comment in comments], ["line", "block"])

    def test_xss_eval_sql_catch(self):
        code = (
            "el.innerHTML = userInput;\n"
            "eval(code);\n"
            "db.query(`SELECT * FROM users WHERE id = ${id}`);\n"
            "const safe = sql`SELECT * FROM users WHERE id = ${id}`;\n"
            "try { run(); } catch (e) {}\n"
        )
        ids = rule_ids("src/app.ts", code)
        self.assertIn("JS-UNSAFE-HTML", ids)
        self.assertIn("JS-EVAL", ids)
        self.assertEqual(ids.count("JS-SQL-STRING-BUILD"), 1, "tagged sql`` templates are parameterized")
        self.assertIn("JS-EMPTY-CATCH", ids)

    def test_effect_cleanup(self):
        leaky = "useEffect(() => {\n  window.addEventListener('resize', onResize);\n}, []);\n"
        clean = "useEffect(() => {\n  window.addEventListener('resize', onResize);\n  return () => window.removeEventListener('resize', onResize);\n}, []);\n"
        self.assertIn("JS-EFFECT-NO-CLEANUP", rule_ids("src/Page.tsx", leaky))
        self.assertNotIn("JS-EFFECT-NO-CLEANUP", rule_ids("src/Page.tsx", clean))

    def test_multiline_comment_style_and_commented_code(self):
        prose = "// Explain the retry rule.\n// It keeps the same idempotency key.\n// Providers dedupe on it.\nconst x = 1;\n"
        code_comment = "// const a = 1;\n// call(a);\n// if (a) {\n// }\nconst y = 2;\n"
        self.assertIn("JS-MULTILINE-COMMENT", rule_ids("src/a.ts", prose))
        self.assertIn("GEN-COMMENTED-OUT-CODE", rule_ids("src/a.ts", code_comment))
        line_style = CheckSettings("line", 60, 12)
        self.assertNotIn("JS-MULTILINE-COMMENT", rule_ids("src/a.ts", prose, line_style))
        self.assertIn("JS-COMMENT-STYLE", rule_ids("src/a.ts", "/*\n * two lines\n */\nconst x = 1;\n", line_style))

    def test_export_without_doc(self):
        body = "\n".join(f"  const v{index} = {index};" for index in range(14))
        undocumented = f"export function calculateTotal(a: number) {{\n{body}\n  return a;\n}}\n"
        documented = "/** Total in minor units. */\n" + undocumented
        self.assertIn("JS-EXPORT-NO-DOC", rule_ids("src/total.ts", undocumented))
        self.assertNotIn("JS-EXPORT-NO-DOC", rule_ids("src/total.ts", documented))

    def test_security_patterns(self):
        code = (
            "app.get('/proxy', (req, res) => fetch(req.query.url));\n"
            "app.get('/file', (req, res) => res.sendFile(path.join(base, req.params.name)));\n"
            "app.get('/go', (req, res) => res.redirect(req.query.next));\n"
            "User.find(req.body);\n"
            "Object.assign(settings, req.body);\n"
            "await prisma.$queryRawUnsafe(text);\n"
            "const re = /^(\\w+\\s?)+$/;\n"
            "app.use(cors({ origin: true, credentials: true }));\n"
            "router.post('/login', loginHandler);\n"
            "res.send('<p>' + req.query.q + '</p>');\n"
        )
        ids = rule_ids("server/app.js", code)
        for expected in ("JS-SSRF", "JS-PATH-TRAVERSAL", "JS-OPEN-REDIRECT", "JS-NOSQL-INJECTION", "JS-PROTOTYPE-POLLUTION",
                         "JS-PRISMA-UNSAFE-RAW", "JS-REDOS", "JS-CORS-CREDENTIALS", "SEC-AUTH-NO-RATE-LIMIT", "JS-REFLECTED-XSS"):
            self.assertIn(expected, ids)

    def test_apostrophe_in_jsx_text_does_not_break_masking(self):
        code = "export const A = () => <p>Don't panic</p>;\neval(x);\n"
        self.assertIn("JS-EVAL", rule_ids("src/A.tsx", code))

    def test_vue_sfc(self):
        code = "<template><div v-html=\"raw\"></div></template>\n<script setup>\nonMounted(() => { window.addEventListener('scroll', f) })\n</script>\n"
        ids = rule_ids("src/A.vue", code)
        self.assertIn("SFC-UNSAFE-HTML", ids)
        self.assertIn("VUE-NO-UNMOUNT-CLEANUP", ids)


class OtherLanguagesTest(unittest.TestCase):
    def test_php(self):
        code = (
            "<?php\n"
            "$rows = DB::select(\"SELECT * FROM users WHERE name = '$name'\");\n"
            "echo $_GET['q'];\n"
            "include $_GET['page'];\n"
            "$hash = md5($password);\n"
            "User::create($request->all());\n"
            "Route::post('/login', [AuthController::class, 'login']);\n"
        )
        ids = rule_ids("app/Http/x.php", code)
        for expected in ("PHP-SQL-STRING-BUILD", "PHP-REFLECTED-XSS", "PHP-FILE-INCLUSION", "PHP-WEAK-PASSWORD-HASH",
                         "PHP-MASS-ASSIGNMENT", "SEC-AUTH-NO-RATE-LIMIT"):
            self.assertIn(expected, ids)
        self.assertIn("PHP-BLADE-RAW", rule_ids("resources/views/a.blade.php", "<div>{!! $html !!}</div>\n"))

    def test_php_slow_call_inside_transaction(self):
        code = (
            "<?php\n"
            "DB::transaction(function () use ($order) {\n"
            "    $order->save();\n"
            "    Http::post('https://psp', ['id' => $order->id]);\n"
            "});\n"
            "DB::transaction(function () { $order->save(); });\n"
            "Mail::to($user)->send(new Receipt());\n"
        )
        found = [finding.line for finding in check_file("app/Services/Pay.php", code, SETTINGS)
                 if finding.rule_id == "PHP-SLOW-CALL-IN-TRANSACTION"]
        self.assertEqual(found, [4])

    def test_java_go_yaml(self):
        java = "class A {\n  void f() { try { x(); } catch (Exception e) {} }\n  String q = \"SELECT * FROM t WHERE id = \" + id;\n}\n"
        java_ids = rule_ids("src/A.java", java)
        self.assertIn("JAVA-EMPTY-CATCH", java_ids)
        self.assertIn("JAVA-SQL-STRING-BUILD", java_ids)
        go = "package main\nfunc f(items []int) {\n  for _, i := range items {\n    go work(i)\n  }\n  http.Get(url)\n}\n"
        go_ids = rule_ids("main.go", go)
        self.assertIn("GO-GOROUTINE-IN-LOOP", go_ids)
        self.assertIn("GO-HTTP-NO-TIMEOUT", go_ids)
        self.assertIn("CFG-C-STYLE-COMMENT", rule_ids("config/app.yaml", "key: value\n// not a yaml comment\n"))

    def test_merge_conflict_marker_is_critical(self):
        findings = check_file("a.py", "<<<<<<< HEAD\nx = 1\n=======\nx = 2\n>>>>>>> branch\n", SETTINGS)
        self.assertIn("critical", [finding.severity for finding in findings])


class SuppressionAndCliTest(unittest.TestCase):
    def test_suppression_requires_rule_and_reason(self):
        code = "def f():\n    eval(x)  # devskills:ignore PY-EVAL-EXEC sandboxed expression parser fixture\n    eval(y)  # devskills:ignore PY-EVAL-EXEC\n"
        kept, suppressed = _apply_suppressions(check_file("a.py", code, SETTINGS), code)
        self.assertEqual(len(suppressed), 1)
        self.assertEqual([finding.line for finding in kept if finding.rule_id == "PY-EVAL-EXEC"], [3])

    def test_cli_gate_and_profile(self):
        repo = make_temp_dir(self)
        write(repo, "a.py", "def f(x=[]):\n    return x\n")
        code, payload = run_cli_json("check-code", "--repo", str(repo), "--paths", "a.py")
        self.assertEqual(code, 3)
        self.assertEqual(payload["gate_result"], "fail")
        code, payload = run_cli_json("check-code", "--repo", str(repo), "--paths", "a.py", "--fail-on", "critical")
        self.assertEqual((code, payload["gate_result"]), (0, "warn"))
        write(repo, ".devskills.toml", "[code]\nmultiline_comment_style = 'sideways'\n")
        invalid = run_cli("check-code", "--repo", str(repo), "--paths", "a.py")
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("multiline_comment_style", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
