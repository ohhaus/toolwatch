"""Temporary, deterministic prompt-storage boundary for this milestone."""

import re

REDACTED = "[REDACTED]"
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|client[_-]?secret)"
    r"\s*[:=]\s*([^\s,;]+)"
)


def prepare_prompt_for_storage(prompt: str | None, *, store_prompts: bool) -> str | None:
    """Omit prompts by default; minimally sanitize only when explicitly enabled."""

    if not store_prompts or prompt is None:
        return None
    sanitized = BEARER_PATTERN.sub(REDACTED, prompt)
    sanitized = JWT_PATTERN.sub(REDACTED, sanitized)
    return SECRET_ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", sanitized)
