

config: validate minimum window size for trajectory scoring

The window-based scoring approach introduced in commit 6d5d3cb requires a minimum window size to provide meaningful context for the monitor. A window size that's too small (e.g., 1-2 messages) would lack sufficient context for proper evaluation, as it wouldn't contain both agent instructions and subsequent actions.

Add validation that ensures transcript.window_messages is at least 5, which is the smallest size that could reasonably contain:
- System message (agent instructions)
- User request
- Assistant response with reasoning
- Tool call
- Tool response

This prevents configuration errors where the window size is set too low by mistake, which would degrade monitoring quality without clear indication of the problem.

```diff
diff --git a/cotmon/config.py b/cotmon/config.py
index d384a7d..b9d5c39 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -69,6 +69,9 @@ def _validate(cfg: Config) -> None:
         raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
     if cfg.store.batch_size <= 0:
         raise ValueError("store.batch_size must be positive")
+    if cfg.transcript.window_messages < 5:
+        raise ValueError("transcript.window_messages must be at least 5 to provide meaningful context")
     if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
         raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
     if cfg.monitor.max_workers <= 0:
diff --git a/tests/test_config.py b/tests/test_config.py
new file mode 100644
index 0000000..e6c6c41
--- /dev/null
+++ b/tests/test_config.py
@@ -0,0 +1,25 @@
+import unittest
+
+from cotmon.config import Config, TranscriptConfig, load_config
+
+
+class ConfigValidationTest(unittest.TestCase):
+    def test_window_size_validation(self):
+        # Valid configuration
+        cfg = Config(
+            monitor=None,
+            transcript=TranscriptConfig(window_messages=5, window_overlap=1),
+            alerts=None,
+            store=None,
+        )
+        self.assertIsNone(load_config._validate(cfg))
+
+        # Invalid configuration - window size too small
+        with self.assertRaises(ValueError) as cm:
+            cfg = Config(
+                monitor=None,
+                transcript=TranscriptConfig(window_messages=4, window_overlap=1),
+                alerts=None,
+                store=None,
+            )
+            load_config._validate(cfg)
+        self.assertIn("must be at least 5", str(cm.exception))
```