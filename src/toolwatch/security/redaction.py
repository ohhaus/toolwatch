"""Deterministic bounded recursive secret redaction."""

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from toolwatch.domain.common import JSONObject, JSONValue

_NAME_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+")
_AUTHORIZATION = re.compile(r"(?i)\b(?:bearer|basic)\s+([A-Za-z0-9._~+/=-]+)")
_JWT = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,})")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_ALREADY_REDACTED = re.compile(r"^\[REDACTED(?::[0-9a-f]{1,16})?\]$")
_SENSITIVE_NAMES = {
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "authorization",
    "proxy_authorization",
    "cookie",
    "set_cookie",
    "private_key",
    "client_secret",
    "credential",
    "credentials",
}


class RedactionLimitExceeded(ValueError):
    """The redactor exceeded a deterministic resource limit."""


@dataclass(frozen=True, slots=True)
class RedactionFinding:
    """Safe metadata for one removed secret."""

    path: str
    detector: str
    category: str
    fingerprint: str | None


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Sanitized JSON plus safe findings."""

    value: JSONValue
    findings: tuple[RedactionFinding, ...]


class DeterministicRedactor:
    """Redact known secret forms without probabilistic decisions."""

    def __init__(
        self,
        *,
        replacement: str = "[REDACTED]",
        fingerprint_key: str | None = None,
        include_fingerprint_prefix: bool = False,
        max_depth: int = 20,
        max_nodes: int = 10_000,
        additional_patterns: Sequence[str] = (),
    ) -> None:
        if not replacement:
            raise ValueError("replacement must be non-empty")
        if fingerprint_key is not None and len(fingerprint_key) < 16:
            raise ValueError("fingerprint key must contain at least 16 characters")
        self._replacement = replacement
        self._fingerprint_key = (
            fingerprint_key.encode("utf-8") if fingerprint_key is not None else None
        )
        self._include_fingerprint_prefix = include_fingerprint_prefix
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._additional_patterns = tuple(re.compile(pattern) for pattern in additional_patterns)

    def redact(self, value: JSONValue) -> RedactionResult:
        """Return a deterministic sanitized copy of a strict JSON value."""

        findings: list[RedactionFinding] = []
        visited = 0

        def visit(current: JSONValue, path: str, depth: int, sensitive_key: bool) -> JSONValue:
            nonlocal visited
            visited += 1
            if visited > self._max_nodes:
                raise RedactionLimitExceeded("redaction node limit exceeded")
            if depth > self._max_depth:
                raise RedactionLimitExceeded("redaction depth limit exceeded")

            if sensitive_key and current not in (None, ""):
                secret = self._stable_secret(current)
                findings.append(self._finding(path, "field_name", "sensitive_field", secret))
                return self._replacement_for(secret)
            if isinstance(current, dict):
                result: JSONObject = {}
                for key, nested in current.items():
                    result[key] = visit(
                        nested,
                        f"{path}.{key}",
                        depth + 1,
                        self._is_sensitive_name(key),
                    )
                return result
            if isinstance(current, list):
                return [
                    visit(item, f"{path}[{index}]", depth + 1, False)
                    for index, item in enumerate(current)
                ]
            if isinstance(current, str):
                return self._redact_string(current, path, findings)
            if current is None:
                return None
            return current
            raise TypeError("redactor accepts JSON values only")

        return RedactionResult(value=visit(value, "$", 0, False), findings=tuple(findings))

    def _redact_string(
        self,
        value: str,
        path: str,
        findings: list[RedactionFinding],
    ) -> str:
        if not value or _ALREADY_REDACTED.fullmatch(value):
            return value
        if _PRIVATE_KEY.search(value):
            findings.append(self._finding(path, "private_key", "private_key", value))
            return self._replacement_for(value)

        sanitized = value

        def replace_authorization(match: re.Match[str]) -> str:
            secret = match.group(1)
            findings.append(self._finding(path, "authorization", "credential", secret))
            return self._replacement_for(secret)

        sanitized = _AUTHORIZATION.sub(replace_authorization, sanitized)

        def replace_jwt(match: re.Match[str]) -> str:
            secret = match.group(1)
            findings.append(self._finding(path, "jwt", "token", secret))
            return self._replacement_for(secret)

        sanitized = _JWT.sub(replace_jwt, sanitized)
        sanitized = self._redact_url_credentials(sanitized, path, findings)

        for index, pattern in enumerate(self._additional_patterns):

            def replace_configured(match: re.Match[str], detector: int = index) -> str:
                secret = match.group(0)
                findings.append(
                    self._finding(path, f"configured_pattern_{detector}", "configured", secret)
                )
                return self._replacement_for(secret)

            sanitized = pattern.sub(replace_configured, sanitized)
        return sanitized

    def _redact_url_credentials(
        self,
        value: str,
        path: str,
        findings: list[RedactionFinding],
    ) -> str:
        try:
            parts = urlsplit(value)
        except ValueError:
            return value
        if parts.scheme not in {"http", "https"} or parts.password is None:
            return value
        password = parts.password
        findings.append(self._finding(path, "url_credentials", "credential", password))
        hostname = parts.hostname or ""
        port = f":{parts.port}" if parts.port is not None else ""
        username = parts.username or ""
        netloc = f"{username}:{self._replacement_for(password)}@{hostname}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def _is_sensitive_name(name: str) -> bool:
        normalized = "_".join(part.lower() for part in _NAME_SPLIT.split(name) if part)
        compact = normalized.replace("_", "")
        return normalized in _SENSITIVE_NAMES or compact in {
            item.replace("_", "") for item in _SENSITIVE_NAMES
        }

    @staticmethod
    def _stable_secret(value: JSONValue) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _fingerprint(self, secret: str) -> str | None:
        if self._fingerprint_key is None:
            return None
        return hmac.new(
            self._fingerprint_key,
            secret.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _replacement_for(self, secret: str) -> str:
        fingerprint = self._fingerprint(secret)
        if self._include_fingerprint_prefix and fingerprint is not None:
            return f"{self._replacement.removesuffix(']')}:{fingerprint[:8]}]"
        return self._replacement

    def _finding(
        self,
        path: str,
        detector: str,
        category: str,
        secret: str,
    ) -> RedactionFinding:
        return RedactionFinding(
            path=path,
            detector=detector,
            category=category,
            fingerprint=self._fingerprint(secret),
        )
