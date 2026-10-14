commit c9e35a2fa1d0ded6c55d9f9b06fa9ba6a6808f82
Author: OpenAI ChatGPT <chatgpt@openai.com>
Date:   2026-09-15 13:22:00 +0000

    fix: correct elapsed time formatting and per‑deployment alert rate

    • format_elapsed now splits seconds into minutes and seconds using a 60‑second
      minute, fixing over‑minute values.
    • RunSummary.finalise now calculates each deployment's alert_rate based on
      that deployment’s own scored count rather than the global total, giving a
      more accurate per‑deployment metric.
    • Added a short comment explaining the change.

    No functional changes to existing tests; all tests continue to pass.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..c77c184 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use a 60‑second minute; the previous implementation used 100, which
+    # produced incorrect minute values for runs longer than a minute.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
@@
 
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
         stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..5c9a02e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 @dataclass
 class RunSummary:
     run_id: str
     scored: int = 0
     alerts: int = 0
     pages: int = 0
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Finalize the summary, computing per‑deployment alert rates."""
+        # Each deployment’s alert rate should be based on its own scored count.
+        # Using the global total could under‑report the rate for deployments
+        # with few samples.
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File ***