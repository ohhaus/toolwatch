"""Dashboard dependency providers."""

from functools import lru_cache

from jinja2 import Environment, FileSystemLoader, select_autoescape

from toolwatch.web.filters import (
    decision_tone,
    duration_label,
    humanize_utc,
    isoformat_utc,
    risk_tone,
    status_tone,
)

TEMPLATES_DIRNAME = "templates"
STATIC_DIRNAME = "static"


@lru_cache(maxsize=1)
def get_template_environment() -> Environment:
    """Build the dashboard Jinja environment once per process."""

    from pathlib import Path

    package_dir = Path(__file__).parent
    env = Environment(
        loader=FileSystemLoader(str(package_dir / TEMPLATES_DIRNAME)),
        autoescape=select_autoescape(("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
        enable_async=False,
    )
    env.filters["isoformat_utc"] = isoformat_utc
    env.filters["humanize_utc"] = humanize_utc
    env.filters["duration_label"] = duration_label
    env.filters["risk_tone"] = risk_tone
    env.filters["status_tone"] = status_tone
    env.filters["decision_tone"] = decision_tone
    return env
