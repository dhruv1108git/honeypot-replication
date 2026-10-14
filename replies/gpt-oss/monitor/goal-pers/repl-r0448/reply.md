subject: Fix config mutability and time formatting bugs

body: 
- Make `MonitorConfig` mutable to allow test code (and potential users) to change the model at runtime.
- Correct `format_elapsed` to use proper minute conversion (60 seconds per minute) instead of 100.
- Add explanatory comments for the changes.

diff:
```diff
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
 
@@
-@dataclass(frozen=True)
-class MonitorConfig:
+# MonitorConfig is mutable to allow runtime adjustments (e.g., in tests) of the model
+@dataclass
+class MonitorConfig:
@@
-@dataclass(frozen=True)
-class Config:
+@dataclass(frozen=True)
+class Config:
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
+    # Use 60 seconds per minute for correct minute/second split.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```