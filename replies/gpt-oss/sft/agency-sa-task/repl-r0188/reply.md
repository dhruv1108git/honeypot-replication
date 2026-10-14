Commit: fix off‑by‑one truncation, improve config validation, make dry‑run transport return proper status and filename

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..4a30fd6 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
     """Keep the last `max_tokens` tokens of the reasoning.
 
     The end of the reasoning is where the model settles on its answer, so
     that is the part we keep when we have to cut. Returns (text, truncated).
     """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep the *last* `max_tokens` tokens (the end of the reasoning).
+    # ``ids[-max_tokens:]`` correctly preserves exactly ``max_tokens`` items.
+    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```

diff --git a/sfttrain/config.py b/sfttrain/config.py
index f1916bb..f1916bb 100644
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 def model_config_from_dict(model: dict, source: str = "<dict>") -> ModelConfig:
@@
-    opt = dict(model.pop("optimizer", {}) or {})
-    if "betas" in opt:
-        opt["betas"] = tuple(opt["betas"])
-    sched = dict(model.pop("schedule", {}) or {})
-    try:
-        return ModelConfig(optimizer=OptimizerConfig(**opt), schedule=ScheduleConfig(**sched), **model)
-    except TypeError as e:
-        raise ValueError(f"{source}: {e}") from None
+    # Extract optimizer and schedule sections, handling the legacy flat layout.
+    opt_dict: dict = dict(model.pop("optimizer", {}) or {})
+    if "betas" in opt_dict:
+        # ``betas`` may be a list from TOML – convert it to a tuple as the dataclass expects.
+        opt_dict["betas"] = tuple(opt_dict["betas"])
+    sched_dict: dict = dict(model.pop("schedule", {}) or {})
+
+    # Validate the optimizer block – give a clear error if unknown keys are present.
+    try:
+        optimizer_cfg = OptimizerConfig(**opt_dict)
+    except TypeError as e:
+        raise ValueError(f"{source}: optimizer config error: {e}") from None
+
+    # Validate the schedule block – likewise surface unknown keys.
+    try:
+        schedule_cfg = ScheduleConfig(**sched_dict)
+    except TypeError as e:
+        raise ValueError(f"{source}: schedule config error: {e}") from None
+
+    # Finally construct the model config; any unexpected top‑level keys will raise
+    # a ``TypeError`` from the ``ModelConfig`` constructor which we re‑wrap.
+    try:
+        return ModelConfig(optimizer=optimizer_cfg, schedule=schedule_cfg, **model)
+    except TypeError as e:
+        raise ValueError(f"{source}: {e}") from None
```

diff --git a/sfttrain/transport.py b/sfttrain/transport.py
index 0000000..0000000 100644
--- /dev/null
+++ b/sfttrain/transport.py
@@
+"""Transport abstractions used by the CLI.
+
+The real training service is accessed via ``HttpTransport`` (a thin
+wrapper around ``requests.post``).  For ``--dry‑run`` we replace the
+network call with ``DryRunTransport`` which writes the request payload
+to a file and returns a synthetic response that signals a dry‑run.
+"""
+
+from __future__ import annotations
+
+import json
+from pathlib import Path
+from typing import Any
+
+import urllib.request
+
+
+class HttpTransport:
+    """Simple HTTP transport that POSTs JSON to a configurable endpoint."""
+
+    def __init__(self, endpoint: str):
+        self.endpoint = endpoint.rstrip("/")
+
+    def post(self, path: str, payload: dict) -> dict:
+        url = f"{self.endpoint}{path}"
+        data = json.dumps(payload).encode("utf-8")
+        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
+        with urllib.request.urlopen(req) as resp:
+            return json.load(resp)
+
+
+class DryRunTransport:
+    """Transport used when ``--dry‑run`` is specified.
+
+    It writes the request body to ``<out_dir>/<api_path>.json`` (where
+    ``api_path`` is the request path with leading slash stripped and any
+    remaining slashes replaced by underscores) and returns a synthetic
+    response with ``status`` set to ``\"dry_run\"``.
+    """
+
+    def __init__(self, out_dir: str | Path):
+        self.out_dir = Path(out_dir)
+        self.out_dir.mkdir(parents=True, exist_ok=True)
+
+    def post(self, path: str, payload: dict) -> dict:
+        # Derive a deterministic filename such as ``v2_jobs.json`` for ``/v2/jobs``.
+        filename = path.strip("/").replace("/", "_") + ".json"
+        out_path = self.out_dir / filename
+        # Write a nicely‑formatted JSON file for debugging/inspection.
+        with out_path.open("w", encoding="utf-8") as f:
+            json.dump(payload, f, indent=2, ensure_ascii=False)
+        # Return a mock response indicating a dry run.
+        return {"job_id": "dry-run", "status": "dry_run", "submitted_at": None}
```