**Commit Title:** Fix pipeline MonitorParseError import and correct elapsed time formatting

**Commit Message:**
- Added missing import of `MonitorParseError` in `cotmon/pipeline.py` to prevent NameError during error handling.
- Fixed `format_elapsed` in `cotmon/reporting.py` to correctly format minutes and seconds (using 60 seconds per minute).
- Included explanatory comments for the changes.

**Diff:**
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 from . import store
 from .reporting import format_elapsed, write_summary_csv
 from .alerts import AlertSink
 from .client import GatewayBackend, MonitorClient, MonitorUnavailable
 from .config import Config, load_config
+from .parse import MonitorParseError
 from .scoring import decide, load_prompt, score_trajectory
@@
-    except (MonitorParseError, MonitorUnavailable) as exc:
+    except (MonitorParseError, MonitorUnavailable) as exc:
*** End of File ***
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use 60 seconds per minute for correct minute/second conversion.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
*** End of File ***
```