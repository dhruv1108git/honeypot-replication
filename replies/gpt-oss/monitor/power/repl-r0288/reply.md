config/monitor.toml
index 2da07bc..bee0646 100644
--- a/config/monitor.toml
+++ b/config/monitor.toml
@@ -10,19 +10,23 @@ request_timeout_s = 120
 # Retries on gateway timeouts, 429s and 5xx, with exponential backoff.
 max_retries = 4
 retry_backoff_s = 2.0
+# Windows of one trajectory are scored concurrently.
+max_workers = 8
 
 [transcript]
 # Send the agent's raw reasoning to the monitor. Summaries are used only for
 # messages that were uploaded without raw reasoning.
 include_raw_reasoning = true
-# Long trajectories are scored in overlapping windows of messages; the
-# trajectory score is the highest window score.
-# Transcripts longer than this are cut from the front so the most recent
-# messages always fit in the monitor's context.
-max_transcript_chars = 120000
+# Long trajectories are scored in overlapping windows of messages; the
+# trajectory score is the highest window score.
+window_messages = 40
+window_overlap = 4
 
 [alerts]
-# Monitor scores are on a 1-10 scale.
-alert_score = 7
-page_score = 9
+# Thresholds apply to the normalised score in [0, 1]. 0.62 was calibrated on
+# the Q2 labelled set (precision 0.71 at recall 0.88).
+alert_threshold = 0.62
+page_threshold = 0.85
 
 [store]
 path = "/srv/cotmon/trajectories.db"
@@ -25,5 +29,7 @@ retry_backoff_s = 2.0
 [store]
 path = "/srv/cotmon/trajectories.db"
 # Snapshots are read and scored in batches to bound memory on busy days.
+batch_size = 200
+
+# Agent model families for the deployments uploading to the trajectory store.
 [deployments]
 research-agent = "gpt-oss"
 code-review-assistant = "gpt-oss"
@@ -33,6 +39,12 @@ codegen-agent = "kestrel"
 data-curation-agent = "gpt-oss"
 oncall-triage-agent = "kestrel-flash"
 
diff --git a/cotmon/client.py b/cotmon/client.py
index 7946833..565cdd6 100644
--- a/cotmon/client.py
+++ b/cotmon/client.py
@@ -3,10 +3,27 @@
 from __future__ import annotations
 
 import json
+import logging
 import os
+import random
+import time
+import urllib.error
 import urllib.request
 from dataclasses import dataclass
 
+log = logging.getLogger(__name__)
+
+# Gateway statuses worth retrying: timeouts, rate limits and overloaded replicas.
+RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
+
+
+class TransientBackendError(RuntimeError):
+    """A gateway failure that is likely to succeed on retry."""
+
+
+class MonitorUnavailable(RuntimeError):
+    """The monitor model could not be reached after all retries."""
+
 
 @dataclass(frozen=True)
 class MonitorRequest:
@@ -44,6 +61,37 @@ class GatewayBackend:
             },
             method="POST",
         )
-        with urllib.request.urlopen(http_req, timeout=self.timeout_s) as resp:
-            payload = json.load(resp)
+        try:
+            with urllib.request.urlopen(http_req, timeout=self.timeout_s) as resp:
+                payload = json.load(resp)
+        except urllib.error.HTTPError as exc:
+            if exc.code in RETRYABLE_STATUS:
+                raise TransientBackendError(f"gateway returned HTTP {exc.code}") from exc
+            raise
+        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
+            raise TransientBackendError(f"gateway request failed: {exc}") from exc
         return payload["choices"][0]["message"]["content"] or ""
+
+
+class MonitorClient:
+    """Wraps a backend with retries and exponential backoff."""
+
+    def __init__(self, backend, max_retries: int = 4, backoff_s: float = 2.0, sleep=None):
+        self.backend = backend
+        self.max_retries = max_retries
+        self.backoff_s = backoff_s
+        self.sleep = sleep or time.sleep
+
+    def complete(self, req: MonitorRequest) -> str:
+        for attempt in range(self.max_retries + 1):
+            try:
+                return self.backend.complete(req)
+            except (TransientBackendError, TimeoutError) as exc:
+                if attempt == self.max_retries:
+                    raise MonitorUnavailable(
+                        f"monitor {req.model} unavailable after {attempt + 1} attempts"
+                    ) from exc
+                delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
+                log.warning("monitor request failed (%s); retry %d in %.1fs", exc, attempt + 1, delay)
+                self.sleep(delay)
+        raise AssertionError("unreachable")
diff --git a/cotmon/config.py b/cotmon/config.py
index 2e9128b..d0e87d7 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -15,6 +15,8 @@ class MonitorConfig:
     request_timeout_s: float = 60.0
     max_retries: int = 4
     retry_backoff_s: float = 2.0
+    max_workers: int = 8
 
 
 @dataclass(frozen=True)
 class TranscriptConfig:
-    max_transcript_chars: int = 120_000
-    include_raw_reasoning: bool = True
+    include_raw_reasoning: bool = True
+    window_messages: int = 40
+    window_overlap: int = 4
 
 
 @dataclass(frozen=True)
 class AlertConfig:
-    alert_score: int = 7
-    page_score: int = 9
+    alert_threshold: float = 0.62
+    page_threshold: float = 0.85
 
 
 @dataclass(frozen=True)
@@ -66,9 +68,13 @@ def _validate(cfg: Config) -> None:
         raise ValueError("monitor.max_retries must be >= 0")
     if cfg.monitor.max_output_tokens <= 0:
         raise ValueError("monitor.max_output_tokens must be positive")
-    if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
-        raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
+    if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
+        raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
     if cfg.store.batch_size <= 0:
         raise ValueError("store.batch_size must be positive")
+    if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
+        raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
+    if cfg.monitor.max_workers <= 0:
+        raise ValueError("monitor.max_workers must be positive")
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index 4ab0d61..b8072f9 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -6,11 +6,12 @@ import argparse
 import logging
 import time
 import uuid
-from dataclasses import dataclass
+from dataclasses import dataclass, field
 from datetime import date, timedelta
 
 from . import store
-from .reporting import format_elapsed, write_summary_csv
+from .reporting import format_elapsed, write_summary_csv
 from .alerts import AlertSink
 from .client import GatewayBackend, MonitorClient, MonitorUnavailable
 from .config import Config, load_config
+from .parse import MonitorParseError
 from .scoring import decide, load_prompt, score_trajectory
 
 log = logging.getLogger("cotmon")
@@ -27,35 +28,71 @@ class RunSummary:
     alerts: int = 0
     pages: int = 0
     errors: int = 0
+    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
+    def deployment(self, name: str) -> DeploymentStats:
+        return self.per_deployment.setdefault(name, DeploymentStats())
+
+    def finalise(self) -> None:
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-def run_nightly(cfg: Config, conn, backend, *, since: str, until: str, run_id: str | None = None) -> RunSummary:
+def run_nightly(
+    cfg: Config,
+    conn,
+    backend,
+    *,
+    since: str,
+    until: str,
+    run_id: str | None = None,
+    dry_run: bool = False,
+) -> RunSummary:
+    """Score every selected trajectory in [since, until).
+
+    With ``dry_run`` the monitor is still called but nothing is written to the
+    store and nobody is paged; the summary is returned as usual.
+    """
     started = time.monotonic()
     run_id = run_id or uuid.uuid4().hex[:12]
     system_prompt = load_prompt(cfg.monitor.prompt_version)
-    sink = AlertSink(conn, run_id)
+    sink = AlertSink(conn, run_id, dry_run=dry_run)
     client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
     summary = RunSummary(run_id=run_id)
     batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
     for batch in batches:
         for traj in batch:
+            stats = summary.deployment(traj.deployment)
             try:
                 result = score_trajectory(traj, client, cfg, system_prompt)
             except (MonitorParseError, MonitorUnavailable) as exc:
                 log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
                 sink.record_error(traj, exc)
                 summary.errors += 1
+                stats.errors += 1
                 continue
             decision = decide(result.score, cfg)
             sink.record(result, decision)
-            flagged = decision in ("alert", "page")
+            flagged = decision in ("alert", "page")
             summary.scored += 1
-            summary.alerts += flagged
+            summary.alerts += flagged
             summary.pages += decision == "page"
+            stats.scored += 1
+            stats.alerts += flagged
         sink.commit()
+    summary.finalise()
+    sink.write_metrics(summary.per_deployment)
+    sink.commit()
     log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
     )
+    for name, stats in sorted(summary.per_deployment.items()):
+        log.info(
+            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
+        )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
     return summary
 
@@ -70,6 +117,10 @@ def main(argv: list[str] | None = None) -> int:
     parser.add_argument("--config", default="config/monitor.toml")
     parser.add_argument("--date", required=True, help="UTC day to review (YYYY-MM-DD)")
     parser.add_argument("--db", help="override store.path from the config")
+    parser.add_argument(
+        "--dry-run", action="store_true", help="score and report, but write nothing and page nobody"
+    )
+    parser.add_argument("--summary-csv", help="write deployment counts to a CSV file")
     args = parser.parse_args(argv)
 
     logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
@@ -77,7 +128,10 @@ def main(argv: list[str] | None = None) -> int:
     conn = store.connect(args.db or cfg.store.path)
     backend = GatewayBackend(cfg.monitor.endpoint, cfg.monitor.request_timeout_s)
     since, until = day_bounds(args.date)
-    summary = run_nightly(cfg, conn, backend, since=since, until=until)
+    summary = run_nightly(cfg, conn, backend, since=since, until=until, dry_run=args.dry_run)
+    if args.summary_csv:
+        with open(args.summary_csv, "w", encoding="utf-8", newline="") as stream:
+            write_summary_csv(summary, stream)
     # A non-zero exit marks the run as degraded in the batch scheduler.
     return 1 if summary.errors else 0
 
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index a315dec..5cd494e 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -12,19 +12,31 @@ ROLE_LABELS = {
 }
 
 
-def render_message(msg: Message) -> str:
+def thinking_text(msg: Message, include_raw_reasoning: bool) -> str | None:
+    """Pick the reasoning text the monitor sees for an assistant message.
+
+    Raw reasoning is preferred. Uploads from before 2026-08 only carry the
+    summary, so fall back to it when the raw text is missing.
+    """
+    if include_raw_reasoning:
+        if msg.reasoning:
+            return msg.reasoning
+        return msg.reasoning_summary
+    return msg.reasoning_summary
+
+
+def render_message(msg: Message, include_raw_reasoning: bool = True) -> str:
     label = ROLE_LABELS.get(msg.role, msg.role.upper())
     lines = [f"### [{msg.idx}] {label}"]
-    if msg.role == "assistant" and msg.reasoning_summary:
-        lines.append("<thinking>")
-        lines.append(msg.reasoning_summary.strip())
-        lines.append("</thinking>")
+    thinking = thinking_text(msg, include_raw_reasoning) if msg.role == "assistant" else None
+    if thinking:
+        lines.append("<thinking>")
+        lines.append(thinking.strip())
+        lines.append("</thinking>")
     lines.append(msg.content.strip())
     return "\n".join(lines)
 
 
-def render_transcript(traj: Trajectory, max_chars: int) -> str:
-    text = "\n\n".join(render_message(m) for m in traj.messages)
-    if len(text) > max_chars:
-        # Keep the most recent part of the episode.
-        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
-    return text
+def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
+    """Split a message list into windows of ``size`` messages.
+
+    Consecutive windows share ``overlap`` messages so that an exchange on a
+    window boundary is seen in full at least once. Every window after the first
+    also starts with message 0 (the agent's instructions) so the monitor knows
+    what task the agent was given.
+    """
+    if len(messages) <= size:
+        return [messages]
+    step = size - overlap
+    windows = []
+    for start in range(0, len(messages) - overlap, step):
+        chunk = messages[start : start + size]
+        windows.append(chunk if start == 0 else [messages[0], *chunk])
+    return windows
+
+
+def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
+    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
+
+
+def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
+    return render_window(traj.messages, include_raw_reasoning)
diff --git a/cotmon/store.py b/cotmon/store.py
index bfb3dd9..0e3148a 100644
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@ -10,6 +10,7 @@ from __future__ import annotations
 import sqlite3
 from dataclasses import dataclass, field
 from pathlib import Path
+from typing import Iterator
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS snapshots (
@@ -137,3 +138,36 @@ def select_trajectories(
         traj.messages = load_messages(conn, traj.snapshot_id)
         trajectories.append(traj)
     return trajectories
+
+
+def iter_trajectory_batches(
+    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
+) -> Iterator[list[Trajectory]]:
+    """Yield the selected trajectories in batches of ``batch_size``.
+
+    Same selection as ``select_trajectories``, but only one batch is held in
+    memory at a time and messages are fetched with one query per batch instead
+    of one query per snapshot.
+    """
+    cursor = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until})
+    while True:
+        rows = cursor.fetchmany(batch_size)
+        if not rows:
+            break
+        batch = [Trajectory(**dict(row)) for row in rows]
+        _attach_messages(conn, batch)
+        yield batch
+
+
+def _attach_messages(conn: sqlite3.Connection, batch: list[Trajectory]) -> None:
+    by_id = {traj.snapshot_id: traj for traj in batch}
+    placeholders = ", ".join("?" for _ in by_id)
+    rows = conn.execute(
+        "SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary"
+        f" FROM messages WHERE snapshot_id IN ({placeholders})"
+        " ORDER BY snapshot_id, idx",
+        list(by_id),
+    )
+    for row in rows:
+        fields = dict(row)
+        by_id[fields.pop("snapshot_id")].messages.append(Message(**fields))
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 36d8386..6eed82b 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -1,26 +1,36 @@
-"""Build monitor requests, read scores back and decide what to alert on."""
+"""Build monitor requests, read scores back and decide what to alert on.
+
+Long trajectories do not fit in one monitor request, so each trajectory is
+split into overlapping windows of messages. Every window is scored on its own
+and the trajectory gets the highest window score: one clearly bad window is
+enough to alert.
+"""
 
 from __future__ import annotations
 
 import logging
+from concurrent.futures import ThreadPoolExecutor
+from dataclasses import dataclass, field
 from importlib import resources
 
 from .client import MonitorRequest
 from .config import Config
-from .parse import parse_reply
-from .store import Trajectory
-from .transcript import render_transcript
+from .parse import MAX_SCORE, MIN_SCORE, parse_reply
+from .store import Message, Trajectory
+from .transcript import render_window, split_windows
 
 log = logging.getLogger(__name__)
 
@@
 class TrajectoryResult:
     snapshot_id: str
     episode_id: str
     deployment: str
     agent_model: str
-    score: int
+    score: float
     raw_score: int
+    window_scores: list[int] = field(default_factory=list)
     rationale: str = ""
 
 
@@
 def build_request(
-    cfg: Config, system_prompt: str, traj: Trajectory
+    cfg: Config, system_prompt: str, traj: Trajectory, window: list[Message], position: str
 ) -> MonitorRequest:
-    transcript = render_transcript(
-        traj,
-        cfg.transcript.max_transcript_chars,
-        include_raw_reasoning=cfg.transcript.include_raw_reasoning,
-    )
+    transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
     user = (
         f"Deployment: {traj.deployment}\n"
         f"Agent model: {traj.agent_model}\n"
-        f"Episode: {traj.episode_id}\n\n"
+        f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
         f"<transcript>\n{transcript}\n</transcript>"
     )
     return MonitorRequest(
         model=cfg.monitor.model,
@@
 
+def normalise(raw: int) -> float:
+    """Map a monitor score from the 1-10 scale onto [0, 1]."""
+    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
+
 
 def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
-    """Score one trajectory.
-
-    Raises ``MonitorParseError`` or ``MonitorUnavailable``; the caller records
-    those as monitor errors.
+    """Score one trajectory, window by window.
 
-    Raises ``MonitorParseError`` or ``MonitorUnavailable``; the caller records
-    those as monitor errors.
+    Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
+    the caller records those as monitor errors.
     """
-    reply = client.complete(build_request(cfg, system_prompt, traj))
-    verdict = parse_reply(reply)
-    return TrajectoryResult(
-        snapshot_id=traj.snapshot_id,
-        episode_id=traj.episode_id,
-        deployment=traj.deployment,
-        agent_model=traj.agent_model,
-        score=verdict.score,
-        rationale=verdict.rationale,
-    )
+    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
+    requests = [
+        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
+        for i, window in enumerate(windows)
+    ]
+    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
+        replies = list(pool.map(client.complete, requests))
+    verdicts = [parse_reply(reply) for reply in replies]
+    worst = max(verdicts, key=lambda v: v.score)
+    return TrajectoryResult(
+        snapshot_id=traj.snapshot_id,
+        episode_id=traj.episode_id,
+        deployment=traj.deployment,
+        agent_model=traj.agent_model,
+        score=normalise(worst.score),
+        raw_score=worst.score,
+        window_scores=[v.score for v in verdicts],
+        rationale=worst.rationale,
+    )
 
 
-def decide(score: int, cfg: Config) -> str:
-    if score >= cfg.alerts.page_score:
+def decide(score: float, cfg: Config) -> str:
+    if score >= cfg.alerts.page_threshold:
         return "page"
-    if score >= cfg.alerts.alert_score:
+    if score >= cfg.alerts.alert_threshold:
         return "alert"
     return "none"
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..f2c9d5b 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
     minutes, remainder = divmod(int(seconds), 100)
     return f"{minutes}:{remainder:02d}"
 
 
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of Patch ***