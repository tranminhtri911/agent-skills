"""Parse a conservative curl sample without a shell, subprocess, DNS or HTTP call."""

from __future__ import annotations

import json
import shlex
from urllib.parse import parse_qs, urlsplit

from devskills.models import UsageError


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise UsageError("curl JSON body contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise UsageError("curl JSON body contains non-finite values")


def _literal_shell(command: str) -> None:
    """Reject expansion/operators that shlex would otherwise flatten into literal tokens."""
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if char in {"'", '"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
        elif quote != "'" and char in {"$", "`"}:
            raise UsageError("curl samples cannot contain shell expansion; use quoted literal placeholders")
        elif not quote and char in {";", "&", "|", "<", ">"}:
            raise UsageError("curl samples cannot contain shell operators or redirection")
        index += 1


def parse_curl(command: str) -> dict:
    """Return the literal method, URL, headers and JSON/raw body; reject hidden options/effects."""
    if not isinstance(command, str) or len(command) > 65536:
        raise UsageError("curl must be a bounded string")
    _literal_shell(command)
    try:
        tokens = shlex.split(command.replace("\\\n", ""), comments=True)
    except ValueError as error:
        raise UsageError("curl has invalid quoting") from error
    if not tokens or tokens.pop(0) != "curl":
        raise UsageError("sample must be one literal curl command")
    result: dict = {"headers": {}}
    no_value = {"--silent", "--show-error", "-s", "-S", "-sS", "-i", "--include"}
    options = {"--request": "method", "-X": "method", "--url": "url", "--header": "header", "-H": "header",
               "--data-raw": "data", "--data": "data", "-d": "data", "--max-time": "timeout"}
    while tokens:
        token = tokens.pop(0)
        if token in no_value:
            continue
        if token not in options:
            if not token.startswith("-") and "url" not in result and token.startswith(("http://", "https://")):
                result["url"] = token
                continue
            raise UsageError("unsupported curl option, extra command or unresolved shell expression")
        if not tokens:
            raise UsageError("curl option is missing its value")
        value, kind = tokens.pop(0), options[token]
        if kind == "header":
            name, colon, header = value.partition(":")
            key = name.strip().lower()
            if not colon or not key or key in result["headers"] or "\n" in value or "\r" in value:
                raise UsageError("curl headers must be unique literal Name: value entries")
            result["headers"][key] = header.strip()
        elif kind == "timeout":
            try:
                if not 0 < float(value) <= 60:
                    raise ValueError
            except ValueError as error:
                raise UsageError("curl max-time must be between 0 and 60 seconds") from error
        elif kind in result:
            raise UsageError("duplicate curl method, URL or body option")
        else:
            result[kind] = value
    if not result.get("method") or not result.get("url"):
        raise UsageError("curl must declare an explicit --request/-X and a URL")
    result["method"] = result["method"].upper()
    try:
        parsed = urlsplit(result["url"])
        _ = parsed.port  # Access validates the literal port without resolving a host.
    except ValueError as error:
        raise UsageError("curl URL has invalid host/port syntax") from error
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.fragment):
        raise UsageError("curl samples must target a literal loopback URL without credentials or fragments")
    if "data" in result:
        if result["data"].startswith("@"):
            raise UsageError("curl file inputs are not supported; embed synthetic request data")
        try:
            result["body"] = json.loads(result["data"], object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        except json.JSONDecodeError:
            result["body_raw"] = result["data"]
        del result["data"]
    result["query"] = parse_qs(parsed.query, keep_blank_values=True)
    return result
