"""Render stored trajectories into the text the monitor reads."""

from __future__ import annotations

from .store import Message, Trajectory

ROLE_LABELS = {
    "system": "SYSTEM",
    "user": "USER",
    "assistant": "ASSISTANT",
    "tool": "TOOL RESULT",
}


def thinking_text(msg: Message, include_raw_reasoning: bool) -> str | None:
    """Pick the reasoning text the monitor sees for an assistant message.

    Raw reasoning is preferred. Uploads from before 2026-08 only carry the
    summary, so fall back to it when the raw text is missing.
    """
    if include_raw_reasoning and msg.reasoning:
        return msg.reasoning
    return msg.reasoning_summary


def render_message(msg: Message, include_raw_reasoning: bool = True) -> str:
    label = ROLE_LABELS.get(msg.role, msg.role.upper())
    lines = [f"### [{msg.idx}] {label}"]
    thinking = thinking_text(msg, include_raw_reasoning) if msg.role == "assistant" else None
    if thinking:
        lines.append("<thinking>")
        lines.append(thinking.strip())
        lines.append("</thinking>")
    lines.append(msg.content.strip())
    return "\n".join(lines)


def render_transcript(traj: Trajectory, max_chars: int, include_raw_reasoning: bool = True) -> str:
    text = "\n\n".join(render_message(m, include_raw_reasoning) for m in traj.messages)
    if len(text) > max_chars:
        # Keep the most recent part of the episode.
        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
    return text
