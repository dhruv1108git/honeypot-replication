## Fix bugs introduced by recent features

* **Prompt rendering** – avoid `KeyError` for legacy v1 prompts by only injecting
  `guidance` and `examples` when the template expects them.
* **Score summary** – expose total number of processed items (`n`) for the
  markdown report.
* **Fake client** – make `FakeClient` return a reply when the request text is
  found inside the prompt (required by unit tests and cache behaviour).

```diff
diff --git a/misuseclf/prompts.py b/misuseclf/prompts.py
@@
-def render(version: str, *, request: str, categories: dict[str, str]) -> str:
-    try:
-        template = TEMPLATES[version]
-    except KeyError:
-        raise ValueError(f"unknown prompt version {version!r}; known: {sorted(TEMPLATES)}") from None
-    cats = "\n".join(f"- {name}: {desc}" for name, desc in categories.items())
-    return template.format(categories=cats, request=request,
-                           guidance=BENIGN_CONTEXT_GUIDANCE, examples=_few_shot_block())
+def render(version: str, *, request: str, categories: dict[str, str]) -> str:
+    """
+    Render a prompt for the given ``version``.
+
+    ``v1`` prompts do not contain the ``{guidance}`` or ``{examples}`` placeholders,
+    so we only supply those arguments for the newer versions.  This prevents a
+    ``KeyError`` when legacy runs request ``v1``.
+    """
+    try:
+        template = TEMPLATES[version]
+    except KeyError as exc:
+        raise ValueError(
+            f"unknown prompt version {version!r}; known: {sorted(TEMPLATES)}"
+        ) from exc
+
+    cats = "\n".join(f"- {name}: {desc}" for name, desc in categories.items())
+
+    # v2 and v3 include additional placeholders; v1 does not.
+    fmt_kwargs = {"categories": cats, "request": request}
+    if version in {"v2", "v3"}:
+        fmt_kwargs.update(
+            {"guidance": BENIGN_CONTEXT_GUIDANCE, "examples": _few_shot_block()}
+        )
+    return template.format(**fmt_kwargs)
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per‑category thresholds and compute the run metrics."""
     ok = [r for r in rated if r.error is None]
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
     labels = [r.example.is_violation for r in ok]
     preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
@@
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/client.py b/misuseclf/client.py
@@
 class FakeClient:
     DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
 
     def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
         self.replies = dict(replies or {})
         self.default = default
         self.calls: list[str] = []
 
-    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
-        self.calls.append(temperature)
-        return self.replies.get(prompt, self.default)
+    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
+        """
+        Return a canned reply.
+
+        ``self.replies`` may be keyed either by the full prompt string or by the
+        request text contained inside the prompt.  To keep the test suite simple
+        we support a substring match: if any key appears in ``prompt`` we return
+        the associated reply, otherwise we fall back to the default.
+        """
+        self.calls.append(temperature)
+        # Exact match first (covers any future uses)
+        if prompt in self.replies:
+            return self.replies[prompt]
+        # Fallback: look for a key that is a substring of the prompt.
+        for key, val in self.replies.items():
+            if key in prompt:
+                return val
+        return self.default
```