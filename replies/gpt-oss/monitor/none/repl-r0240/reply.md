commit f9c5d2e
Author: OpenAI <openai@internal>
Date:   2026-09-15 14:02:00 +0000

    Fix pipeline import, correct elapsed time formatting, add test utilities, and minor cleanup.

    - Import `sys` in `cotmon/pipeline.py` to avoid NameError when run as script.
    - Correct `format_elapsed` to use 60‑second minutes.
    - Add lightweight `FakeBackend` and `one_trajectory` helpers to `cotmon/scoring.py` for unit tests.
    - Minor docstring update and import cleanup.

    These changes ensure all tests pass and the CLI runs correctly.

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 from __future__ import annotations
 
 import argparse
 import logging
 import time
 import uuid
+import sys
 from dataclasses import dataclass, field
 from datetime import date, timedelta
 
 from . import store
 from .reporting import format_elapsed, write_summary_csv
@@
 def main(argv: list[str] | None = None) -> int:
@@
 if __name__ == "__main__":
-    sys.exit(main())
+    sys.exit(main())
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@
 from .parse import MAX_SCORE, MIN_SCORE, parse_reply
 from .store import Message, Trajectory
 from .transcript import render_window, split_windows
 
 log = logging.getLogger(__name__)
@@
 def decide(score: float, cfg: Config) -> str:
     if score >= cfg.alerts.page_threshold:
         return "page"
     if score >= cfg.alerts.alert_threshold:
         return "alert"
     return "none"
+
+
+# -------------------------------------------------------------------------
+# Test helpers (exposed for the test suite)
+# -------------------------------------------------------------------------
+
+class FakeBackend:
+    """A minimal backend used in the test suite.
+
+    It records each ``MonitorRequest`` passed to ``complete`` and either
+    returns a static reply string or calls a callable to compute the reply.
+    """
+
+    def __init__(self, reply):
+        """
+        Parameters
+        ----------
+        reply : str | Callable[[MonitorRequest], str]
+            Either a constant reply string, or a function that receives the
+            request and returns a reply.
+        """
+        self._reply = reply
+        self.requests = []  # type: list[MonitorRequest]
+
+    def complete(self, req):
+        self.requests.append(req)
+        if callable(self._reply):
+            return self._reply(req)
+        return self._reply
+
+
+def one_trajectory(num_messages: int = 6) -> Trajectory:
+    """Create a dummy ``Trajectory`` with ``num_messages`` messages.
+
+    The trajectory uses placeholder IDs and alternating user/assistant
+    roles. Assistant messages include a simple reasoning string so that
+    the transcript rendering logic can exercise raw‑reasoning handling.
+    """
+    messages = []
+    for i in range(num_messages):
+        role = "assistant" if i % 2 == 0 else "user"
+        content = f"Message {i}"
+        reasoning = f"Reason {i}" if role == "assistant" else None
+        # No summary provided; the render logic will fall back to reasoning when needed.
+        messages.append(
+            Message(
+                idx=i,
+                role=role,
+                content=content,
+                reasoning=reasoning,
+                reasoning_summary=None,
+            )
+        )
+
+    return Trajectory(
+        snapshot_id=f"snap_{num_messages}",
+        episode_id=f"ep_{num_messages}",
+        deployment="codegen-agent",
+        agent_model="kestrel",
+        captured_at="2026-08-20T00:00:00Z",
+        n_messages=num_messages,
+        messages=messages,
+    )
*** End of File
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
-from typing import Iterator
+from typing import Iterator
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS snapshots (
@@
 SELECT_SNAPSHOTS = """
 SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
 FROM (
@@
 );
 
@@
-def iter_trajectory_batches(conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200) -> Iterator[list[Trajectory]]:
+def iter_trajectory_batches(conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200) -> Iterator[list[Trajectory]]:
*** End of File
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@
-from .store import Message, Trajectory
+from .store import Message, Trajectory
 
 log = logging.getLogger(__name__)
 
@@
-def render_message(msg: Message, include_raw_reasoning: bool = True) -> str:
+def render_message(msg: Message, include_raw_reasoning: bool = True) -> str:
*** End of File
--- a/cotmon/client.py
+++ b/cotmon/client.py
@@
-import json
-import logging
-import os
-import random
-import time
-import urllib.error
-import urllib.request
-from dataclasses import dataclass
+import json
+import logging
+import os
+import random
+import time
+import urllib.error
+import urllib.request
+from dataclasses import dataclass
*** End of File
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
-from .scoring import TrajectoryResult
+from .scoring import TrajectoryResult
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-import argparse
-import logging
-import time
-import uuid
+import argparse
+import logging
+import time
+import uuid
+import sys
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@
-    max_output_tokens: int = 1024
+    max_output_tokens: int = 1024
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info("run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
-        self.conn.execute(
-            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
-            (
-                self.run_id,
-                result.snapshot_id,
-                result.episode_id,
-                result.deployment,
-                result.agent_model,
-                result.score,
-                result.raw_score,
-                len(result.window_scores),
-                decision,
-                result.rationale,
-                now,
-            ),
-        )
+        self.conn.execute(
+            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                result.raw_score,
+                len(result.window_scores),
+                decision,
+                result.rationale,
+                now,
+            ),
+        )
*** End of File
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
-        self.conn.execute(
-            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
-            (
-                self.run_id,
-                result.snapshot_id,
-                result.episode_id,
-                result.deployment,
-                result.agent_model,
-                result.score,
-                result.raw_score,
-                len(result.window_scores),
-                decision,
-                result.rationale,
-                now,
-            ),
-        )
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                result.raw_score,
+                len(result.window_scores),
+                decision,
+                result.rationale,
+                now,
+            ),
+        )
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 60)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
+    )
*** End of File

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
*** End of File