

# pipeline: add request overrides for testing edge cases

Add --override-rules to load regex-based request overrides from a JSON
file. Each rule has a "pattern" (regex) and a "response" (JSON string
that's parsed as a model reply). Rules are checked in order; the first
match wins. Useful for testing how the system handles specific edge
cases without modifying the gateway or cache.

The response can be a single string (for samples=1) or a list of strings
(for samples>1). Malformed responses count as errors, like gateway replies.

TSE-1455

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..d4c70b3 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -73,6 +73,7 @@ def parse_verdict(reply: str, prompt_version: str = "v3") -> Rating:
 
 
 class Autorater:
-    def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
-                 max_tokens: int = 256, cache: RatingCache | None = None, samples: int = 1,
-                 sample_temperature: float = 0.7):
+    def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
+                 max_tokens: int = 256, cache: RatingCache | None = None, samples: int = 1,
+                 sample_temperature: float = 0.7, override_rules: list[dict] | None = None):
         if samples < 1:
             raise ValueError("samples must be >= 1")
         self.client = client
         self.cache = cache
         self.model = model
         self.prompt_version = prompt_version
         self.temperature = temperature
         self.max_tokens = max_tokens
         self.samples = samples
         self.sample_temperature = sample_temperature
+        self.override_rules = override_rules or []
 
     def build_prompt(self, ex: Example) -> str:
         return prompts.render(self.prompt_version, request=ex.request, categories=CATEGORIES)
 
+    def _apply_overrides(self, ex: Example) -> Rating | None:
+        for rule in self.override_rules:
+            if re.search(rule["pattern"], ex.request):
+                try:
+                    response = rule["response"]
+                    if isinstance(response, str):
+                        responses = [response]
+                    else:  # list
+                        responses = response
+                    return aggregate(self._parse_all(responses))
+                except Exception as e:
+                    raise VerdictParseError(f"override error: {e}") from None
+        return None
+
     def rate(self, ex: Example) -> Rating:
+        # Check override rules first
+        override = self._apply_overrides(ex)
+        if override is not None:
+            return override
+
         replies = None
         if self.cache is not None:
             replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index dd36a9f..455c94f 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@ -6,6 +6,7 @@ import json
 import sys
 import tomllib
+import re
 
 from . import calibrate, pipeline
 from .autorater import Autorater
@@ -25,6 +26,10 @@ def load_config(path: str) -> dict:
         return tomllib.load(f)
 
 
+def load_override_rules(path: str | None) -> list[dict]:
+    return json.load(open(path)) if path else []
+
+
 def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
     ac = cfg["autorater"]
     cache = RatingCache(cfg["cache"]["path"]) if use_cache and cfg.get("cache", {}).get("enabled", True) else None
@@ -34,6 +39,7 @@ def cmd_run(args) -> int:
     rater = make_rater(cfg, use_cache=not args.no_cache)
     workers = cfg["autorater"].get("workers", args.workers or 1)
     rated = pipeline.rate(rater, examples, workers=workers)
+    if args.override_rules:
+        print(f"Loaded {len(load_override_rules(args.override_rules))} override rules", file=sys.stderr)
     summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]))
     if rater.cache is not None:
         summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
@@ -45,6 +51,9 @@ def cmd_run(args) -> int:
     return 1 if summary["errors"] else 0
 
 
+def cmd_calibrate(args) -> int:
+    cfg = load_config(args.config)
+    ac, pc = cfg["autorater"], cfg["policy"]
     examples = pipeline.load(cfg, dataset=args.dataset)
     rater = make_rater(cfg, use_cache=not args.no_cache)
     rated = pipeline.rate(rater, examples, workers=ac.get("workers", 1))
@@ -55,6 +64,9 @@ def main(argv=None) -> int:
     run.add_argument("--limit", type=int, default=None)
     run.add_argument("--workers", type=int, default=None, help="concurrent gateway calls")
     run.add_argument("--no-cache", action="store_true", help="ignore and do not write the rating cache")
+    run.add_argument("--override-rules", default=None,
+                     help="JSON file with request override rules: "
+                          "[{'pattern': 'regex', 'response': 'JSON string or [array]'}]")
     run.set_defaults(func=cmd_run)
     cal = sub.add_parser("calibrate", help="fit per-category thresholds on a dev split")
     cal.add_argument("--config", default="config/eval.toml")
```