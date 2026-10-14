Add a bug‑fix to the human‑readable runtime formatter.

**Commit message**
```
fix: correct elapsed time formatting (M:SS)

The format_elapsed() helper incorrectly divided seconds by 100, which
produced wrong minute values for durations longer than a minute. The
function now uses the proper 60‑second minute conversion while keeping
the existing tests (which use short intervals) passing. The updated
implementation also improves the docstring to clarify its behaviour.
```

**Diff**
```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..f6d9c12 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS).
+
+    The original implementation mistakenly used a divisor of 100,
+    which treated a minute as 100 seconds. This function now correctly
+    uses 60 seconds per minute, ensuring accurate runtime logging.
+    """
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```