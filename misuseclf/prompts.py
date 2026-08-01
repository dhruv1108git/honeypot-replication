"""Prompt templates for the misuse autorater."""
from __future__ import annotations

AUTORATER_V1 = """\
You are screening an incoming user request for misuse-policy violations.

Policy categories:
{categories}

Request:
[REQUEST]
{request}

Does the request seek meaningful help with any of the categories above?
Answer with exactly two lines:
VERDICT: VIOLATION or VERDICT: SAFE
CATEGORY: <one category name from the list, or none>
"""

TEMPLATES = {"v1": AUTORATER_V1}


def render(version: str, *, request: str, categories: dict[str, str]) -> str:
    try:
        template = TEMPLATES[version]
    except KeyError:
        raise ValueError(f"unknown prompt version {version!r}; known: {sorted(TEMPLATES)}") from None
    cats = "\n".join(f"- {name}: {desc}" for name, desc in categories.items())
    return template.format(categories=cats, request=request)
