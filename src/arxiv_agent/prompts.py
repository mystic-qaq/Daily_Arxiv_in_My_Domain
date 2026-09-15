"""Prompt plumbing shared by every model-facing module."""

from __future__ import annotations


def render_template(template: str, **values: object) -> str:
    """Substitute ``{name}`` placeholders without touching literal JSON braces.

    ``str.format`` explodes on prompts that contain JSON examples (a template
    like ``{"projects": [...]}`` raises ``KeyError('"projects"')``), and written
    prompts are full of JSON schemas. Placeholders here are explicit tokens and
    everything else passes through untouched.
    """
    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", str(value))
    return result
