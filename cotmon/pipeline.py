"""Nightly entry point: select trajectories, score them, write alerts."""

from __future__ import annotations

import argparse
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from . import store
from .reporting import format_elapsed
from .alerts import AlertSink
from .client import GatewayBackend, MonitorClient
from .config import Config, load_config
from .scoring import decide, load_prompt, score_trajectory

log = logging.getLogger("cotmon")


@dataclass
class RunSummary:
    run_id: str
    scored: int = 0
    alerts: int = 0
    pages: int = 0


def run_nightly(cfg: Config, conn, backend, *, since: str, until: str, run_id: str | None = None) -> RunSummary:
    started = time.monotonic()
    run_id = run_id or uuid.uuid4().hex[:12]
    system_prompt = load_prompt(cfg.monitor.prompt_version)
    sink = AlertSink(conn, run_id)
    client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
    summary = RunSummary(run_id=run_id)
    batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
    for batch in batches:
        for traj in batch:
            result = score_trajectory(traj, client, cfg, system_prompt)
            decision = decide(result.score, cfg)
            sink.record(result, decision)
            summary.scored += 1
            summary.alerts += decision in ("alert", "page")
            summary.pages += decision == "page"
        sink.commit()
    log.info("run %s: scored=%d alerts=%d pages=%d", run_id, summary.scored, summary.alerts, summary.pages)
    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
    return summary


def day_bounds(day: str) -> tuple[str, str]:
    start = date.fromisoformat(day)
    return f"{start.isoformat()}T00:00:00Z", f"{(start + timedelta(days=1)).isoformat()}T00:00:00Z"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cotmon-nightly")
    parser.add_argument("--config", default="config/monitor.toml")
    parser.add_argument("--date", required=True, help="UTC day to review (YYYY-MM-DD)")
    parser.add_argument("--db", help="override store.path from the config")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_config(args.config)
    conn = store.connect(args.db or cfg.store.path)
    backend = GatewayBackend(cfg.monitor.endpoint, cfg.monitor.request_timeout_s)
    since, until = day_bounds(args.date)
    run_nightly(cfg, conn, backend, since=since, until=until)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
