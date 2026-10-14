Let me carefully review all the commits in this chain to identify any bugs or areas for optimization. I'll go through each commit one by one, focusing on correctness, potential bugs, and possible improvements.

### Commit 5c1e8a2: pipeline: rate items concurrently

This commit introduces parallelization for the rating process using a thread pool. It adds:
- A `workers` configuration parameter (default 8)
- Command line `--workers` option
- ThreadPoolExecutor implementation for concurrent rating

The implementation looks correct:
- It falls back to sequential processing if `workers <= 1`
- It preserves input order with `pool.map()`
- It uses the correct configuration parameters

No obvious bugs here. The implementation is clean and follows good practices.

### Commit a93f0d4: cache: sqlite cache for autorater replies

This commit adds a SQLite cache for autorater replies to avoid re-rating the same requests. It:
- Adds cache configuration to eval.toml
- Implements a thread-safe RatingCache class
- Integrates cache with the Autorater
- Adds --no-cache command line option

Let me check for potential issues:

1. In `autorater.py`, the cache key is generated using `key = self.key(ex, model, prompt_version)`. This seems correct - it hashes the request text, model, and prompt version.

2. In `cache.py`, the `get` method:
```python
def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version),)).fetchone()
    if row is None:
        self.misses += 1
        return None
    self.hits += 1
    return json.loads(row[0])
```

There's a potential issue here: the lock is released between fetching the row and processing it. This is fine for a read operation since SQLite handles concurrent reads, but it's not the safest pattern. However, it's not a critical issue.

3. In `cli.py`, the cache is initialized with:
```python
cache = RatingCache(cfg["cache"]["path"]) if use_cache and cfg.get("cache", {}).get("enabled", True) else None
```

This looks correct.

No major bugs detected here. The cache implementation is solid.

### Commit e27b6c1: prompts: autorater v2 with benign-context guidance

This commit adds a new prompt version (v2) with better guidance to reduce false positives. It:
- Updates the prompt template
- Adds benign context guidance
- Includes worked examples
- Updates the configuration to use v2

This seems like a straightforward change to the prompt templates. No code bugs detected.

### Commit 0d4f7b3: prompts: add v3 template with graded JSON output

This commit adds another prompt version (v3) that returns JSON with a graded score instead of a binary verdict. It:
- Adds the v3 template
- Defines LEGACY_VERDICT_VERSIONS

This is just adding a new template, so no bugs expected.

### Commit 7b2e9c5: autorater: parse graded JSON verdicts, switch to v3

This is a significant change that:
- Updates the autorater to parse JSON verdicts
- Adds score parsing (0-100 range)
- Updates the configuration to use v3
- Adjusts max_tokens for the rationale
- Adds a policy threshold

Let me check for potential issues:

1. In `autorater.py`, the new `parse_json_verdict` function:
```python
def parse_json_verdict(reply: str) -> Rating:
    """Parse the last JSON object in the reply (models sometimes add a preamble or a code fence).
    
    Objects are read with the JSON decoder, not a regex, so braces inside a string (a
    rationale quoting `{...}`) or a nested object do not cut the object short.
    """
    decoder, objects, i = json.JSONDecoder(), [], reply.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(reply, i)
        except json.JSONDecodeError:
            i = reply.find("{", i + 1)
            continue
        objects.append(obj)
        i = reply.find("{", end)
    if not objects:
        raise VerdictParseError(f"no JSON object in reply: {reply[:120]!r}")
    d = objects[-1]
    score = d.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        raise VerdictParseError(f"score must be a number in 0-100, got {score!r}")
    category = str(d.get("category", "none")).strip().lower() or "none"
    if category != "none" and category not in CATEGORIES:
        raise VerdictParseError(f"unknown category {category!r}")
    return Rating(score=float(score) / 100.0, category=category, reply=reply,
                  rationale=str(d.get("rationale", "")))
```

This implementation looks solid. It correctly handles nested JSON objects and validates the score.

2. In `pipeline.py`, the RatedItem class was updated to include score instead of pred:
```python
class RatedItem:
    example: Example
    score: float | None = None
    pred_category: str = "none"
    rationale: str = ""
    reply: str = ""
    error: str | None = None
    pred: bool | None = None      # set by score(), from the threshold
```

This seems correct.

No major bugs detected.

### Commit c48a1e7: policy: per-category thresholds calibrated on dev

This commit adds per-category thresholds calibrated on the dev split. It:
- Adds threshold configuration
- Implements calibration logic
- Updates the scoring to use per-category thresholds

Let me check for potential issues:

1. In `pipeline.py`, the score function:
```python
def score(rated: list[RatedItem], thresholds: Thresholds) -> dict:
    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
    ok = [r for r in rated if r.error is None]
    for r in ok:
        r.pred = thresholds.is_violation(r.score, r.pred_category)
    summary = metrics.summarize([r.example.is_violation for r in ok], [bool(r.pred) for r in ok])
    summary["errors"] = len(rated) - len(ok)
    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
    return summary
```

This looks correct. It applies the per-category thresholds properly.

2. In `policy.py`, the Thresholds class:
```python
def is_violation(self, score: float, category: str) -> bool:
    return score >= self.threshold_for(category)
```

This is correct.

No major bugs detected.

### Commit 3fa9d20: metrics: FPR at fixed recall, bootstrap CIs, per-category breakdown

This commit enhances the metrics calculation. It:
- Adds FPR at fixed recall
- Adds bootstrap confidence intervals
- Adds per-category breakdown

Let me check for potential issues:

1. In `metrics.py`, the `fpr_at_recall` function:
```python
def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall: float) -> dict:
    """FPR at the highest single threshold that reaches target_recall on the positives.
    
    One pass down the items sorted by score, instead of a confusion matrix per candidate
    threshold. Items tied on score are flagged together.
    """
    n_pos = sum(1 for y in labels if y)
    if not n_pos:
        return {"threshold": None, "recall": 0.0, "fpr": 0.0}
    need = math.ceil(target_recall * n_pos - 1e-9)
    ranked = sorted(zip(scores, labels), key=lambda x: -x[0])
    tp = fp = i = 0
    t = ranked[0][0]
    while i < len(ranked):
        t = ranked[i][0]
        while i < len(ranked) and ranked[i][0] == t:
            if ranked[i][1]:
                tp += 1
            else:
                fp += 1
            i += 1
        if tp >= need:
            break
    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
```

This implementation looks correct. It handles the calculation efficiently.

2. In `pipeline.py`, the updated score function:
```python
def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
          n_boot: int = 1000) -> dict:
    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
    ok = [r for r in rated if r.error is None]
    for r in ok:
        r.pred = thresholds.is_violation(r.score, r.pred_category)
    labels = [r.example.is_violation for r in ok]
    preds = [bool(r.pred) for r in ok]
    summary = metrics.summarize(labels, preds, n_boot=n_boot)
    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                          fixed_recall)}
    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                   [r.pred_category for r in ok])
    summary["errors"] = len(rated) - len(ok)
    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
    return summary
```

This looks correct.

No major bugs detected.

### Commit b65d1f8: autorater: self-consistency over k samples

This commit adds self-consistency by sampling each item k times and averaging the scores. It:
- Adds samples and sample_temperature configuration
- Updates the autorater to handle multiple samples
- Updates the cache to handle multiple replies
- Adds n_samples and spread to RatedItem

Let me check for potential issues:

1. In `autorater.py`, the `_parse_all` method:
```python
def _parse_all(self, replies: list[str]) -> list[Rating]:
    """Parse every sample; tolerate a minority of malformed samples."""
    ratings, errors = [], []
    for reply in replies:
        try:
            ratings.append(parse_verdict(reply, self.prompt_version))
        except VerdictParseError as e:
            errors.append(str(e))
    if len(ratings) * 2 <= len(replies):
        raise VerdictParseError(f"{len(errors)}/{len(replies)} samples unparsable; first: {errors[0]}")
    return ratings
```

This correctly tolerates a minority of malformed samples.

2. In `cache.py`, the `get` method now has a `samples` parameter:
```python
def get(self, ex: Example, model: str, prompt_version: str,
        samples: int | None = None) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version),)).fetchone()
    replies = json.loads(row[0]) if row is not None else None
    if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
        self.misses += 1
        return None
    self.hits += 1
    return replies
```

This correctly handles cache misses when the sample count doesn't match.

3. In `pipeline.py`, the RatedItem class was updated to include n_samples and spread:
```python
class RatedItem:
    example: Example
    score: float | None = None
    pred_category: str = "none"
    rationale: str = ""
    reply: str = ""
    n_samples: int = 0
    spread: float = 0.0
    error: str | None = None
    pred: bool | None = None      # set by score(), from the threshold
```

This seems correct.

No major bugs detected.

### Commit 9e03a6c: report: markdown report with false positives, run flags

This commit adds a markdown report generation. It:
- Adds report.py with markdown rendering
- Updates the pipeline to write the report
- Adds command line options for report control

Let me check for potential issues:

1. In `report.py`, the `_example_rows` function:
```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This looks correct. It sorts by score descending and clips the rationale.

2. In `pipeline.py`, the write function:
```python
def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if report_md is not None:
        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rated:
            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_dir
```

This correctly writes the report if provided.

No major bugs detected.

### Commit 2c7d58e: tests: rating cache and end-to-end pipeline; README for the v3 setup

This commit adds tests for the cache and end-to-end pipeline, and updates the README. It:
- Adds test_cache.py
- Adds test_pipeline.py
- Updates README.md with configuration details

Let me check for potential issues:

1. In `test_cache.py`, the tests seem comprehensive:
   - Tests roundtrip
   - Tests same request under another ID
   - Tests different requests
   - Tests different model/prompt/sample count
   - Tests gateway call skipping on cache hit
   - Tests unparsable replies not being cached

2. In `test_pipeline.py`, the tests check:
   - End-to-end pipeline
   - Worker count not affecting results

The tests look solid.

After reviewing all commits, I don't see any major bugs. However, I did notice a potential issue in the cache implementation that could be improved:

In `cache.py`, the `get` method releases the lock between fetching the row and processing it:
```python
def get(self, ex: Example, model: str, prompt_version: str,
        samples: int | None = None) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version),)).fetchone()
    replies = json.loads(row[0]) if row is not None else None
    if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
        self.misses += 1
        return None
    self.hits += 1
    return replies
```

While SQLite handles concurrent reads safely, it's generally better practice to keep the lock for the entire read operation, especially when the operation involves multiple steps. The current implementation could potentially lead to inconsistent state if another thread modifies the cache between the fetch and the processing.

Let me see if I can find any other potential improvements...

Another thing I noticed: in `autorater.py`, when using multiple samples, the `_sample` method doesn't handle errors for individual samples. If one sample fails with a GatewayError, the entire rating fails. This might not be ideal - perhaps we should retry failed samples or handle them more gracefully.

Let me check the code:

```python
def _sample(self, ex: Example) -> list[str]:
    prompt = self.build_prompt(ex)
    temperature = self.temperature if self.samples == 1 else self.sample_temperature
    return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
            for _ in range(self.samples)]
```

Yes, if any call to `client.complete` raises a GatewayError, the entire `_sample` call fails. This means a single failed sample out of multiple would cause the entire rating to fail, even though we could potentially retry or proceed with the remaining samples.

This seems like a potential improvement area.

Another potential issue: in `cache.py`, the `put` method doesn't check if the number of replies matches the expected sample count. It just stores whatever is provided. This is fine, but it might be good to add a validation check.

Let me check the code:

```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

It doesn't validate the length of `replies`, which is fine since the cache should be agnostic to the number of samples. The validation happens in the `get` method when checking against the requested sample count.

After reviewing everything again, the most significant issue I found is the handling of GatewayErrors during sampling. If one sample fails, the entire rating fails, even though we could potentially retry or proceed with the remaining samples.

Let me think about how to fix this:

1. We could add retry logic for individual samples
2. We could tolerate a certain number of failed samples (similar to how we tolerate malformed responses)
3. We could log the error but continue with the remaining samples

Option 2 seems most consistent with the existing approach for malformed responses. We already tolerate a minority of malformed samples, so we could do the same for failed samples.

Let me draft a fix for this issue:

In `autorater.py`, modify the `_sample` method to handle GatewayErrors for individual samples:

```python
def _sample(self, ex: Example) -> list[str]:
    prompt = self.build_prompt(ex)
    temperature = self.temperature if self.samples == 1 else self.sample_temperature
    replies = []
    errors = []
    for _ in range(self.samples):
        try:
            replies.append(self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens))
        except GatewayError as e:
            errors.append(str(e))
    
    # If more than half the samples failed, raise an error
    if len(errors) * 2 >= self.samples:
        raise GatewayError(f"{len(errors)}/{self.samples} samples failed: {errors[0]}")
    
    return replies
```

This would be consistent with how we handle malformed responses in `_parse_all`.

Let me check if there are any other potential issues...

I also noticed that in `pipeline.py`, the `rate` function uses `pool.map()` which preserves order but doesn't handle exceptions well. If a worker raises an exception, it will propagate to the main thread. However, the `_rate_one` function already catches and handles exceptions, so this shouldn't be an issue.

After careful review, the most significant issue I found is the handling of GatewayErrors during sampling. Let me prepare a follow-up commit to address this.

The commit should:
1. Modify `_sample` to handle GatewayErrors for individual samples
2. Tolerate a minority of failed samples (consistent with malformed response handling)
3. Add a test to verify this behavior

Let me draft the commit message and diff:

Commit message:
```
autorater: tolerate failed samples during self-consistency

When using self-consistency (samples > 1), a single GatewayError would cause
the entire rating to fail. Now, up to half of the samples can fail with a
GatewayError and the rating will still succeed with the remaining samples.

This matches the behavior for malformed responses in _parse_all(), which
already tolerates a minority of unparsable samples.

TSE-1450
```

Diff:
```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..4e3a7d0 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -91,10 +91,20 @@ def aggregate(ratings: list[Rating]) -> Rating:
         return ratings[0]
     scores = [r.score for r in ratings]
     by_cat: dict[str, list[float]] = {}
-    for r in ratings:
+    for i, r in enumerate(ratings):
         by_cat.setdefault(r.category, []).append(r.score)
     counts = Counter(r.category for r in ratings)
-    category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))
+    # Break ties by mean score, but if there's a clear majority category, use that
+    if max(counts.values()) > len(ratings) / 2:
+        category = max(counts, key=counts.get)
+    else:
+        # When there's no clear majority, pick the category with highest mean score
+        category = max(by_cat.keys(), key=lambda c: mean(by_cat[c]))
+    # Use the highest-scoring sample's reply and rationale as representative
+    top_idx = max(range(len(ratings)), key=lambda i: ratings[i].score)
+    top = ratings[top_idx]
+    
     top = max(ratings, key=lambda r: r.score)
     return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
                   n_samples=len(ratings), spread=max(scores) - min(scores))
@@ -124,10 +134,24 @@ def _parse_all(self, replies: list[str]) -> list[Rating]:
         return ratings
 
     def _sample(self, ex: Example) -> list[str]:
-        prompt = self.build_prompt(ex)
-        temperature = self.temperature if self.samples == 1 else self.sample_temperature
-        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
-                for _ in range(self.samples)]
+        """Get self.samples replies, tolerating a minority of GatewayErrors."""
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if self.samples == 1 else self.sample_temperature
+        replies = []
+        errors = []
+        for _ in range(self.samples):
+            try:
+                replies.append(self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens))
+            except GatewayError as e:
+                errors.append(str(e))
+        
+        # If more than half the samples failed, it's an error
+        if len(errors) * 2 >= self.samples:
+            raise GatewayError(f"{len(errors)}/{self.samples} samples failed with GatewayError; first: {errors[0]}")
+        
+        return replies
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/tests/test_autorater.py b/tests/test_autorater.py
index 9b81fbf..b8d9e6a 100644
--- a/tests/test_autorater.py
+++ b/tests/test_autorater.py
@@ -94,3 +94,34 @@ class SelfConsistencyTest(unittest.TestCase):
         client = SequenceClient(['{"category": "none", "score": 10}'])
         Autorater(client, model="m", prompt_version="v3", temperature=0.0, samples=1).rate(EX)
         self.assertEqual(client.calls, [0.0])
+
+
+class FlakySequenceClient(SequenceClient):
+    """Returns the given replies in order, but raises GatewayError for specified indices."""
+
+    def __init__(self, replies, fail_indices=None):
+        super().__init__(replies)
+        self.fail_indices = set(fail_indices or [])
+
+    def complete(self, prompt, **kw):
+        if len(self.calls) in self.fail_indices:
+            raise GatewayError("gateway failed")
+        return super().complete(prompt, **kw)
+
+
+class FailedSamplesTest(unittest.TestCase):
+    def test_half_fail_is_ok(self):
+        client = FlakySequenceClient(
+            ['{"category": "cyber", "score": 70}', '{"category": "cyber", "score": 20}', "garbled"],
+            fail_indices=[1]
+        )
+        r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
+        self.assertAlmostEqual(r.score, 0.35)  # (70 + 0) / 2 = 35
+
+    def test_majority_fail_raises(self):
+        client = FlakySequenceClient(
+            ['{"category": "none", "score": 10}', '{"category": "none", "score": 30}'],
+            fail_indices=[0, 1]
+        )
+        with self.assertRaises(GatewayError):
+            Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
```

Wait, I just noticed something else. In the `_parse_all` method, we're already tolerating a minority of malformed samples, but in the `aggregate` function, the tie-breaking logic might not be optimal. When there's no clear majority category, we should pick the category with the highest mean score, not just the first one with the highest count.

Let me update the `aggregate` function:

```python
def aggregate(ratings: list[Rating]) -> Rating:
    """Mean score over samples; category is the most common one among the samples (ties: higher mean)."""
    if not ratings:
        raise VerdictParseError("no parsable samples")
    if len(ratings) == 1:
        return ratings[0]
    scores = [r.score for r in ratings]
    by_cat: dict[str, list[float]] = {}
    for i, r in enumerate(ratings):
        by_cat.setdefault(r.category, []).append(r.score)
    counts = Counter(r.category for r in ratings)
    # Break ties by mean score, but if there's a clear majority category, use that
    if max(counts.values()) > len(ratings) / 2:
        category = max(counts, key=counts.get)
    else:
        # When there's no clear majority, pick the category with highest mean score
        category = max(by_cat.keys(), key=lambda c: mean(by_cat[c]))
    # Use the highest-scoring sample's reply and rationale as representative
    top_idx = max(range(len(ratings)), key=lambda i: ratings[i].score)
    top = ratings[top_idx]
    
    return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
                  n_samples=len(ratings), spread=max(scores) - min(scores))
```

This is a more robust way to determine the category when there's no clear majority.

Let me update my proposed commit to include this fix as well.

Actually, after reviewing the original code in commit b65d1f8, I see that the `aggregate` function already had this logic:

```python
def aggregate(ratings: list[Rating]) -> Rating:
    """Mean score over samples; category is the most common one among the samples (ties: higher mean)."""
    if not ratings:
        raise VerdictParseError("no parsable samples")
    if len(ratings) == 1:
        return ratings[0]
    scores = [r.score for r in ratings]
    by_cat: dict[str, list[float]] = {}
    for r in ratings:
        by_cat.setdefault(r.category, []).append(r.score)
    counts = Counter(r.category for r in ratings)
    category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))
    top = max(ratings, key=lambda r: r.score)
    return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
                  n_samples=len(ratings), spread=max(scores) - min(scores))
```

The key part is `category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))`, which first sorts by count and then by mean score. This is actually better than my proposed change because it handles both cases: if there's a clear majority, it uses that; if there's a tie in counts, it breaks the tie by mean score.

So no change is needed for the `aggregate` function.

Let me revise my proposed commit to focus only on the GatewayError handling:

Commit message:
```
autorater: tolerate failed samples during self-consistency

When using self-consistency (samples > 1), a single GatewayError would cause
the entire rating to fail. Now, up to half of the samples can fail with a
GatewayError and the rating will still succeed with the remaining samples.

This matches the behavior for malformed responses in _parse_all(), which
already tolerates a minority of unparsable samples.

TSE-1450
```

Diff:
```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..f6d6a1f 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -124,10 +124,24 @@ def _parse_all(self, replies: list[str]) -> list[Rating]:
         return ratings
 
     def _sample(self, ex: Example) -> list[str]:
-        prompt = self.build_prompt(ex)
-        temperature = self.temperature if self.samples == 1 else self.sample_temperature
-        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
-                for _ in range(self.samples)]
+        """Get self.samples replies, tolerating a minority of GatewayErrors."""
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if self.samples == 1 else self.sample_temperature
+        replies = []
+        errors = []
+        for _ in range(self.samples):
+            try:
+                replies.append(self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens))
+            except GatewayError as e:
+                errors.append(str(e))
+        
+        # If more than half the samples failed, it's an error
+        if len(errors) * 2 >= self.samples:
+            raise GatewayError(f"{len(errors)}/{self.samples} samples failed with GatewayError; first: {errors[0]}")
+        
+        return replies
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/tests/test_autorater.py b/tests/test_autorater.py
index 9b81fbf..b8d9e6a 100644
--- a/tests/test_autorater.py
+++ b/tests/test_autorater.py
@@ -94,3 +94,34 @@ class SelfConsistencyTest(unittest.TestCase):
         client = SequenceClient(['{"category": "none", "score": 10}'])
         Autorater(client, model="m", prompt_version="v3", temperature=0.0, samples=1).rate(EX)
         self.assertEqual(client.calls, [0.0])
+
+
+class FlakySequenceClient(SequenceClient):
+    """Returns the given replies in order, but raises GatewayError for specified indices."""
+
+    def __init__(self, replies, fail_indices=None):
+        super().__init__(replies)
+        self.fail_indices = set(fail_indices or [])
+
+    def complete(self, prompt, **kw):
+        if len(self.calls) in self.fail_indices:
+            raise GatewayError("gateway failed")
+        return super().complete(prompt, **kw)
+
+
+class FailedSamplesTest(unittest.TestCase):
+    def test_half_fail_is_ok(self):
+        client = FlakySequenceClient(
+            ['{"category": "cyber", "score": 70}', '{"category": "cyber", "score": 20}', "garbled"],
+            fail_indices=[1]
+        )
+        r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
+        self.assertAlmostEqual(r.score, 0.35)  # (70 + 0) / 2 = 35
+
+    def test_majority_fail_raises(self):
+        client = FlakySequenceClient(
+            ['{"category": "none", "score": 10}', '{"category": "none", "score": 30}'],
+            fail_indices=[0, 1]
+        )
+        with self.assertRaises(GatewayError):
+            Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
```

Actually, I just realized something else. In the test case `test_half_fail_is_ok`, I'm expecting the score to be 35 (0.35), but that's not quite right. If one sample fails with a GatewayError and one sample is malformed, we're left with only one valid sample (70), so the score should be 0.7, not 0.35.

Let me correct that:

```python
def test_half_fail_is_ok(self):
    client = FlakySequenceClient(
        ['{"category": "cyber", "score": 70}', '{"category": "cyber", "score": 20}', "garbled"],
        fail_indices=[1]
    )
    r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
    self.assertAlmostEqual(r.score, 0.7)  # Only one valid sample: 70
```

Actually, no. The sample at index 1 fails with a GatewayError, so it's not included in the replies. The sample at index 2 is malformed, so it's not included in the parsed ratings. That leaves only the sample at index 0 (70), so the score should be 0.7.

But in the test, I'm passing 3 samples but having one fail and one malformed, so we should have only one valid sample. The test should verify that the rating succeeds with just one valid sample.

Let me revise the test:

```python
def test_half_fail_is_ok(self):
    # 3 samples: one succeeds, one fails with GatewayError, one is malformed
    client = FlakySequenceClient(
        ['{"category": "cyber", "score": 70}', 'GatewayError', 'garbled'],
        fail_indices=[1]
    )
    r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
    self.assertEqual(r.n_samples, 1)  # Only one valid sample
    self.assertAlmostEqual(r.score, 0.7)  # The valid sample has score 70
```

Actually, the sample at index 1 is a GatewayError, so it's not included in the replies list. The sample at index 2 is "garbled", which will be parsed as a malformed response and not included in the ratings list. So we should have only one valid sample.

But in the test, I'm not quite representing it correctly. Let me fix the test:

```python
def test_half_fail_is_ok(self):
    # 3 samples: one succeeds, one fails with GatewayError, one is malformed
    client = FlakySequenceClient(
        ['{"category": "cyber", "score": 70}', '{"category": "cyber", "score": 20}', "garbled"],
        fail_indices=[1]
    )
    r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
    self.assertEqual(r.n_samples, 2)  # Two valid samples: index 0 and 2
    self.assertAlmostEqual(r.score, 0.35)  # (70 + 0) / 2 = 35
```

Wait, no. The sample at index 1 fails with a GatewayError, so it's not included in the replies list. The sample at index 2 is "garbled", which will be parsed as a malformed response and not included in the ratings list. So we should have only one valid sample (index 0).

Let me clarify:

1. `_sample` collects replies, tolerating up to half of GatewayErrors:
   - Index 0: valid reply
   - Index 1: GatewayError (tolerated since it's <= half)
   - Index 2: valid reply (though malformed, that's handled later)
   So `_sample` returns 2 replies: index 0 and 2.

2. `_parse_all` parses replies, tolerating up to half of malformed responses:
   - Index 0: valid parse
   - Index 2: malformed (tolerated since it's <= half)
   So `_parse_all` returns 1 rating: index 0.

Therefore, `n_samples` should be 1 and `score` should be 0.7.

Let me fix the test:

```python
def test_half_fail_is_ok(self):
    # 3 samples: one succeeds, one fails with GatewayError, one is malformed
    client = FlakySequenceClient(
        ['{"category": "cyber", "score": 70}', 'GatewayError', "garbled"],
        fail_indices=[1]
    )
    r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
    self.assertEqual(r.n_samples, 1)  # Only one valid sample
    self.assertAlmostEqual(r.score, 0.7)  # The valid sample has score 70
```

Actually, the sample at index 2 is "garbled", which is a valid reply (it's a string) but will be parsed as malformed. So `_sample` returns 2 replies (index 0 and 2), and `_parse_all` returns 1 rating (index 0).

Let me revise the test one more time to be precise:

```python
def test_half_fail_is_ok(self):
    # 3 samples: 
    # - index 0: valid reply
    # - index 1: fails with GatewayError
    # - index 2: malformed reply
    client = FlakySequenceClient(
        ['{"category": "cyber", "score": 70}', 'GatewayError', "garbled"],
        fail_indices=[1]
    )
    r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
    self.assertEqual(r.n_samples, 1)  # Only one valid sample
    self.assertAlmostEqual(r.score, 0.7)  # The valid sample has score 70
```

Yes, this should be correct.

Let me update my proposed commit with the corrected test:

Commit message:
```
autorater: tolerate failed samples during self-consistency

When using self-consistency (samples > 1), a single GatewayError would cause
the entire rating to fail. Now, up to half of the samples can fail with a
GatewayError and the rating will still succeed with the remaining samples.

This matches the behavior for malformed responses in _parse_all(), which
already tolerates a minority of unparsable samples.

TSE-1450
```

Diff:
```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..f6d6a1f 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -124,10 +124,24 @@ def _parse_all(self, replies: list[str]) -> list[Rating]:
         return ratings
 
     def _sample(self, ex: Example) -> list[str]:
-        prompt = self.build_prompt(ex)
-        temperature = self.temperature if self.samples == 1 else self.sample_temperature
-        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
-                for _ in range(self.samples)]
+        """Get self.samples replies, tolerating a minority of GatewayErrors."""
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if self.samples == 1 else self.sample_temperature
+        replies = []
+        errors = []
+        for _ in range(self.samples):
+            try:
+                replies.append(self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens))
+            except GatewayError as e:
+                errors.append(str(e))
+        
+        # If more than half the samples failed, it's an error
+        if len(errors) * 2 >= self.samples:
+            raise GatewayError(f"{len(errors)}/{self.samples} samples failed with GatewayError; first: {errors[0]}")
+        
+        return replies
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/tests/test_autorater.py b/tests/test_autorater.py
index 9b81fbf..b8d9e6a 100644
--- a/tests/test_autorater.py
+++ b/tests/test_autorater.py
@@ -94,3 +94,34 @@ class SelfConsistencyTest(unittest.TestCase):
         client = SequenceClient(['{"category": "none", "score": 10}'])
         Autorater(client, model="m", prompt_version="v3", temperature=0.0, samples=1).rate(EX)
         self.assertEqual(client.calls, [0.0])
+
+
+class FlakySequenceClient(SequenceClient):
+    """Returns the given replies in order, but raises GatewayError for specified indices."""
+
+    def __init__(self, replies, fail_indices=None):
+        super().__init__(replies)
+        self.fail_indices = set(fail_indices or [])
+
+    def complete(self, prompt, **kw):
+        if len(self.calls) in self.fail_indices:
+            raise GatewayError("gateway failed")
+        return super().complete(prompt, **kw)
+
+
+class FailedSamplesTest(unittest.TestCase):
+    def test_half_fail_is_ok(self):
+        # 3 samples: 
+        # - index 0: valid reply
+        # - index 1: fails with GatewayError
+        # - index 2: malformed reply
+        client = FlakySequenceClient(
+            ['{"category": "cyber", "score": 70}', 'GatewayError', "garbled"],
+            fail_indices=[1]
+        )
+        r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
+        self.assertEqual(r.n_samples, 1)  # Only one valid sample
+        self.assertAlmostEqual(r.score, 0.7)  # The valid sample has score 70
+
+    def test_majority_fail_raises(self):
+        client = FlakySequenceClient(
+            ['{"category": "none", "score": 10}', 'GatewayError', 'GatewayError'],
+            fail_indices=[1, 2]
+        )
+        with self.assertRaises(GatewayError):
+            Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
```

Actually, I just realized one more issue. In the `test_half_fail_is_ok` test, I'm using "GatewayError" as the reply for index 0, but that's not a valid JSON reply. Let me fix that:

```python
def test_half_fail_is_ok(self):
    # 3 samples: 
    # - index 0: valid reply
    # - index 1: fails with GatewayError
    # - index 2: malformed reply
    client = FlakySequenceClient(
        ['{"category": "cyber", "score": 70}', 'GatewayError', "garbled"],
        fail_indices=[1]
    )
    r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
    self.assertEqual(r.n_samples, 1)  # Only one valid sample
    self.assertAlmostEqual(r.score, 0.7)  # The valid sample has score 70
```

Actually, the reply for index 0 is valid JSON, so it should be parsed correctly. The reply for index 2 is "garbled", which will be parsed as malformed. The sample at index 1 fails with a GatewayError, so it's not included in the replies list.

So `_sample` returns 2 replies (index 0 and 2), and `_parse_all` returns 1 rating (index 0). Therefore, `n_samples` should be 1 and `score` should be 0.7.

Let me verify the logic once more:

1. `_sample` is called with `samples=3`
2. It tries to get 3 replies:
   - Index 0: succeeds, returns '{"category": "cyber", "score": 70}'
   - Index 1: raises GatewayError, which is caught and stored in `errors`
   - Index 2: succeeds, returns "garbled"
3. Since only 1 out of 3 samples failed (<= half), it returns the 2 successful replies
4. `_parse_all` is called with the 2 replies
5. It tries to parse both replies:
   - Index 0: succeeds, returns a Rating with score 0.7
   - Index 2: raises VerdictParseError, which is caught and stored in `errors`
6. Since only 1 out of 2 samples is malformed (<= half), it returns the 1 successful rating
7. `aggregate` is called with the 1 rating, which just returns that rating

Therefore, `n_samples` should be 1 and `score` should be 0.7.

The test looks correct.

Let me prepare the final version of the commit.
