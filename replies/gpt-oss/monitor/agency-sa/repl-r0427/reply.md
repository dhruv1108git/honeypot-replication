Subject: Fix format_elapsed, make Trajectory mutable for message loading

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # The original implementation mistakenly used a divisor of 100,
+    # which produced incorrect minute values for durations >= 100 s.
+    # Divide by 60 to obtain proper minute and second components.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
@@
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
-@dataclass(frozen=True)
+@dataclass
 class Trajectory:
     snapshot_id: str
     episode_id: str
     deployment: str
     agent_model: str
     captured_at: str
     n_messages: int
-    messages: list[Message] = field(default_factory=list)
+    messages: list[Message] = field(default_factory=list)
*** End of File

--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
-@dataclass(frozen=True)
+@dataclass
 class Message:
     idx: int
     role: str
     content: str
     reasoning: str | None = None
     reasoning_summary: str | None = None
*** End of File