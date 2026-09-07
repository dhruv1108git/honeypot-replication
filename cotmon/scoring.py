"""Build monitor requests, read scores back and decide what to alert on."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import resources

from .client import MonitorRequest
from .config import Config
from .parse import parse_reply
from .store import Trajectory
from .transcript import render_transcript

log = logging.getLogger(__name__)

@dataclass
class TrajectoryResult:
    snapshot_id: str
    episode_id: str
    deployment: str
    agent_model: str
    score: int
    rationale: str = ""


def load_prompt(version: str) -> str:
    return resources.files("cotmon.prompts").joinpath(f"scheming_{version}.txt").read_text()


def build_request(cfg: Config, system_prompt: str, traj: Trajectory) -> MonitorRequest:
    transcript = render_transcript(traj, cfg.transcript.max_transcript_chars)
    user = (
        f"Deployment: {traj.deployment}\n"
        f"Agent model: {traj.agent_model}\n"
        f"Episode: {traj.episode_id}\n\n"
        f"<transcript>\n{transcript}\n</transcript>"
    )
    return MonitorRequest(
        model=cfg.monitor.model,
        system=system_prompt,
        user=user,
        max_output_tokens=cfg.monitor.max_output_tokens,
        temperature=cfg.monitor.temperature,
    )


def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory.

    Raises ``MonitorParseError`` or ``MonitorUnavailable``; the caller records
    those as monitor errors.
    """
    reply = client.complete(build_request(cfg, system_prompt, traj))
    verdict = parse_reply(reply)
    return TrajectoryResult(
        snapshot_id=traj.snapshot_id,
        episode_id=traj.episode_id,
        deployment=traj.deployment,
        agent_model=traj.agent_model,
        score=verdict.score,
        rationale=verdict.rationale,
    )


def decide(score: int, cfg: Config) -> str:
    if score >= cfg.alerts.page_score:
        return "page"
    if score >= cfg.alerts.alert_score:
        return "alert"
    return "none"
