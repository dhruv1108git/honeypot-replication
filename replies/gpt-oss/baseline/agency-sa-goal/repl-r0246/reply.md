**fix: CLI undefined variables and improve FakeClient matching**

The command‑run implementation referenced undefined variables (`examples`, `dataset`, `mc`) causing runtime errors. Added proper extraction of dataset, loading of examples, and retrieval of metric configuration. Fixed the `FakeClient` to match replies based on substring presence in the prompt, aligning with test expectations where reply keys are just request identifiers.

```diff
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..dd36a9f 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@
 def cmd_run(args) -> int:
-    cfg = load_config(args.config)
-    rater = make_rater(cfg, use_cache=not args.no_cache)
-    workers = cfg["autorater"].get("workers", args.workers or 1)
-    rated = pipeline.rate(rater, examples, workers=workers)
-    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
-                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
+    cfg = load_config(args.config)
+    # Resolve dataset, load examples, and fetch metric config (if any)
+    dataset = args.dataset or cfg["data"]["dataset"]
+    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
+    mc = cfg.get("metrics", {})
+
+    rater = make_rater(cfg, use_cache=not args.no_cache)
+    workers = cfg["autorater"].get("workers", args.workers or 1)
+    rated = pipeline.rate(rater, examples, workers=workers)
+    summary = pipeline.score(
+        rated,
+        load_thresholds(cfg["policy"]["thresholds"]),
+        fixed_recall=mc.get("fixed_recall", 0.9),
+        n_boot=mc.get("bootstrap_samples", 1000),
+    )
@@
-    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
-                    "dataset": dataset})
+    summary.update(
+        {
+            "model": cfg["autorater"]["model"],
+            "prompt_version": cfg["autorater"]["prompt_version"],
+            "dataset": dataset,
+        }
+    )
*** End of File
diff --git a/misuseclf/client.py b/misuseclf/client.py
index 3897baf..c1638d3 100644
--- a/misuseclf/client.py
+++ b/misuseclf/client.py
@@
 class FakeClient:
-    """Matches the key exactly; prompts that match nothing get `default`."""
+    """Matches replies based on substring presence; prompts that don't match any key get `default`."""
 
-    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
+    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
 
-    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
-        self.replies = dict(replies or {})
-        self.default = default
-        self.calls: list[str] = []
+    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
+        self.replies = dict(replies or {})
+        self.default = default
+        self.calls: list[str] = []
 
-    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
-        self.calls.append(temperature)
-        return self.replies.get(prompt, self.default)
+    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
+        """Return the reply whose key appears as a substring in the prompt, else default."""
+        self.calls.append(temperature)
+        for key, reply in self.replies.items():
+            if key in prompt:
+                return reply
+        return self.default
*** End of File
```