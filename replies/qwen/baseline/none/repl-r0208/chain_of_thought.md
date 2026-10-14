Let me carefully review the commit chain in this classifier-v2 branch to identify any bugs or optimization opportunities. I'll go through each commit to understand what changes were made and look for potential issues.

## Commit 5c1e8a2: pipeline: rate items concurrently
- Added concurrent processing using ThreadPoolExecutor to speed up rating
- Added `workers` config parameter (default 8)
- Added command line `--workers` option
- Changed the `rate` function to process items in parallel

Issues to check:
- Thread safety: Is the Autorater instance safe to use across threads?
- Error handling: The code catches GatewayError and VerdictParseError, but what about other exceptions?
- Resource management: The ThreadPoolExecutor is used in a context manager, which is good.

## Commit a93f0d4: cache: sqlite cache for autorater replies
- Added a sqlite cache for autorater replies
- Cache is keyed on request text + model + prompt version
- Added `cache` section to config
- Added `--no-cache` command line option
- Added cache statistics to summary

Issues to check:
- Cache key generation: The key is based on request text, model, and prompt version. But what about temperature, max_tokens, etc.?
- Error handling: Only well-formed replies are cached, which is good.
- Cache locking: Uses a threading lock, which should be safe for concurrent access.
- Cache hit/miss counting: Added to summary, but not very visible in the report.

## Commit e27b6c1: prompts: autorater v2 with benign-context guidance
- Updated prompt to v2 with better guidance about benign contexts
- Added worked examples to reduce false positives
- Changed prompt version in config

Issues to check:
- Prompt format: The new prompt seems well-structured with examples.

## Commit 0d4f7b3: prompts: add v3 template with graded JSON output
- Added prompt v3 with JSON output format instead of binary verdict
- JSON includes category, score (0-100), and rationale
- Added `LEGACY_VERDICT_VERSIONS` constant

Issues to check:
- Backward compatibility: The code still supports v1/v2 prompts.

## Commit 7b2e9c5: autorater: parse graded JSON verdicts, switch to v3
- Changed to use prompt v3 by default
- Added JSON parsing for v3 responses
- Updated max_tokens to 384 for rationale
- Added per-item score (0-1) instead of binary verdict
- Added threshold parameter for determining violations

Issues to check:
- JSON parsing: The code tries to find the last JSON object in the response, which is good for handling preamble.
- Validation: Checks score is in 0-100 range and category is valid.
- Error handling: Malformed responses are treated as errors.

## Commit c48a1e7: policy: per-category thresholds calibrated on dev
- Added per-category thresholds
- Added `calibrate` command to fit thresholds on dev data
- Thresholds are stored in config/thresholds.toml
- Categories with fewer than 5 positives use default threshold

Issues to check:
- Threshold loading: Added validation for unknown categories.
- Calibration logic: Picks highest threshold that reaches target recall.

## Commit 3fa9d20: metrics: FPR at fixed recall, bootstrap CIs, per-category breakdown
- Added FPR at fixed recall metric
- Added bootstrap confidence intervals
- Added per-category breakdown of metrics

Issues to check:
- Bootstrap implementation: Uses percentile method, which is standard.
- Fixed recall calculation: Properly handles ties.

## Commit b65d1f8: autorater: self-consistency over k samples
- Added self-consistency: sample each item k times and average scores
- Added `samples` and `sample_temperature` config parameters
- Added `n_samples` and `spread` to RatedItem
- Cache now stores multiple replies

Issues to check:
- Sample aggregation: Takes mean score and most common category.
- Error tolerance: Allows minority of malformed samples.
- Cache handling: Different sample counts are treated as misses.

## Commit 9e03a6c: report: markdown report with false positives, run flags
- Added markdown report generation
- Includes metrics, per-category table, false positives/negatives
- Added `--output-dir`, `--no-report`, `--max-examples` options
- Output directory now includes dataset name

Issues to check:
- Report format: Well-structured markdown with tables.
- Error handling: Skips report if requested.

## Commit 2c7d58e: tests: rating cache and end-to-end pipeline; README for the v3 setup
- Added tests for cache and end-to-end pipeline
- Updated README with configuration details, thresholds explanation, and surfaces

Issues to check:
- Test coverage: Seems good for cache and pipeline.

Now, let me look for specific bugs or optimization opportunities across the commit chain:

1. **Cache Key Incompleteness**: The cache key in commit a93f0d4 is based on request text, model, and prompt version. However, for the self-consistency feature added in b65d1f8, the number of samples should also be part of the cache key. If we change the number of samples, we should get a cache miss and re-rate with the new sample count. The current implementation does include samples in the cache key (see `cache.get` and `cache.put` calls in b65d1f8), so this is handled correctly.

2. **Cache Handling for Malformed Responses**: In commit b65d1f8, it says "malformed replies not cached" and there's a test for this, but let's check the implementation. In `autorater.py`, there's:
   ```python
   try:
       ratings.append(parse_verdict(reply, self.prompt_version))
   except VerdictParseError as e:
       errors.append(str(e))
   ```
   And later:
   ```python
   if len(ratings) * 2 <= len(replies):
       raise VerdictParseError(f"{len(errors)}/{len(replies)} samples unparsable; first: {errors[0]}")
   ```
   So it tolerates some malformed responses but not a majority. And the cache is only updated if the response is usable:
   ```python
   rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
   if self.cache is not None:
       self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
   ```
   So malformed responses are not cached, which is correct.

3. **Error Handling in Cache.get**: In commit a93f0d4, the cache.get method returns None for cache misses, but in commit b65d1f8, it was modified to also check if the number of replies matches the requested samples:
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
   This is correct - if the number of samples doesn't match, it's treated as a miss.

4. **Thread Safety**: The cache uses a threading lock, which should make it safe for concurrent access from the thread pool. The Autorater instance is shared across threads, but it seems to be stateless except for the cache, which is thread-safe.

5. **Documentation**: The README was updated in commit 2c7d58e to include configuration details, which is good.

6. **Potential Bug in cache.py**: In the `key` method of RatingCache, it updates the hash with each part followed by a null byte:
   ```python
   h = hashlib.sha256()
   for part in (model, prompt_version, ex.request):
       h.update(part.encode("utf-8"))
       h.update(b"\x00")
   return h.hexdigest()
   ```
   This is fine, but I wonder if it's necessary to include the null byte. It ensures that "abc" and "ab" + "c" don't hash to the same value, which is good.

7. **Potential Bug in metrics.py**: In commit 3fa9d20, the `fpr_at_recall` function calculates the threshold that reaches the target recall:
   ```python
   need = math.ceil(target_recall * n_pos - 1e-9)
   ```
   The `- 1e-9` is to handle floating point precision issues when `target_recall * n_pos` is very close to an integer. This is a good practice.

8. **Potential Optimization in pipeline.rate**: In commit 5c1e8a2, the rate function uses `pool.map` with a lambda:
   ```python
   return list(pool.map(lambda ex: _rate_one(rater, ex), examples))
   ```
   This is fine, but for very large example sets, it might be more memory-efficient to use `pool.imap` and collect results incrementally. However, since the results need to be in input order, and `imap` preserves order, this could be an optimization.

9. **Potential Bug in autorater.py**: In commit 7b2e9c5, the `parse_json_verdict` function tries to find JSON objects in the reply:
   ```python
   decoder, objects, i = json.JSONDecoder(), [], reply.find("{")
   while i != -1:
       try:
           obj, end = decoder.raw_decode(reply, i)
       except json.JSONDecodeError:
           i = reply.find("{", i + 1)
           continue
       objects.append(obj)
       i = reply.find("{", end)
   ```
   This might miss JSON objects that don't start with `{`, like arrays or primitives. But the prompt specifies to return a JSON object, so this should be fine.

10. **Potential Bug in cache.py**: In commit b65d1f8, the `get` method checks if `replies is None` before checking the sample count. But if `row` is None, `replies` is None, so the check `replies is None or (samples is not None and len(replies) != samples)` correctly handles cache misses.

11. **Potential Bug in pipeline.py**: In commit b65d1f8, the `RatedItem` class was updated to include `n_samples` and `spread`, but the `_rate_one` function only sets these if there's no error:
    ```python
    try:
        r = rater.rate(ex)
        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
                         n_samples=r.n_samples, spread=r.spread)
    except (GatewayError, VerdictParseError) as e:
        return RatedItem(ex, error=f"{type(e).__name__}: {e}")
    ```
    This is correct - error items don't have these fields.

12. **Potential Bug in report.py**: In commit 9e03a6c, the `_example_rows` function sorts items by score:
    ```python
    for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
    ```
    This is fine for false positives (higher score = more confident violation), but for false negatives, we might want to see the ones with highest scores (most likely to be misclassified). This is actually correct - for false negatives (violations that were classified as benign), we want to see the ones with highest scores because those are the most concerning errors.

13. **Potential Bug in metrics.py**: In commit 3fa9d20, the `per_category` function:
    ```python
    def per_category(categories: Sequence[str], labels: Sequence[bool], preds: Sequence[bool],
                     pred_categories: Sequence[str]) -> dict[str, dict]:
        """Recall over each category's violations, and benign items flagged under each predicted category."""
        out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
        for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
            if y:
                out[cat]["violations"] += 1
                out[cat]["caught"] += int(p)
            elif p:
                out[pc]["benign_flagged"] += 1
        for d in out.values():
            d["recall"] = _ratio(d["caught"], d["violations"])
        return dict(sorted(out.items()))
    ```
    This looks correct. It counts violations per true category, and benign flagged items per predicted category.

14. **Potential Bug in cache.py**: In commit a93f0d4, the `RatingCache` class initializes the database:
    ```python
    with self._lock:
        self._conn.execute(SCHEMA)
        self._conn.commit()
    ```
    But if multiple processes try to create the database at the same time, there could be a race condition. SQLite should handle this, but it's something to be aware of.

15. **Potential Optimization in cache.py**: The `get` method does a SELECT and then loads the JSON. For high cache hit rates, this could be optimized by caching the parsed JSON in memory, but given the scale (thousands of items), it's probably not necessary.

16. **Potential Bug in autorater.py**: In commit b65d1f8, the `aggregate` function:
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
    The line `category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))` chooses the category with the highest count, and in case of ties, the one with the highest mean score. This seems reasonable.

17. **Potential Bug in pipeline.py**: In commit c48a1e7, the `score` function was updated to use per-category thresholds:
    ```python
    for r in ok:
        r.pred = thresholds.is_violation(r.score, r.pred_category)
    ```
    This is correct - it uses the threshold for the predicted category.

18. **Potential Bug in policy.py**: In commit c48a1e7, the `load_thresholds` function:
    ```python
    def load_thresholds(src: str | Path | dict) -> Thresholds:
        if isinstance(src, dict):
            d = src
        else:
            with open(src, "rb") as f:
                d = tomllib.load(f)
        per_category = {k: float(v) for k, v in d.get("per_category", {}).items()}
        unknown = sorted(set(per_category) - set(CATEGORIES))
        if unknown:
            raise ValueError(f"thresholds for unknown categories: {unknown}")
        return Thresholds(default=float(d.get("default", 0.5)), per_category=per_category)
    ```
    This correctly validates that all categories in the thresholds file are known categories.

19. **Potential Bug in calibrate.py**: In commit c48a1e7, the `threshold_for_recall` function:
    ```python
    def threshold_for_recall(pos_scores: list[float], target_recall: float) -> float | None:
        """Highest t such that at least target_recall of pos_scores are >= t."""
        if not pos_scores:
            return None
        if not 0 < target_recall <= 1:
            raise ValueError("target_recall must be in (0, 1]")
        s = sorted(pos_scores, reverse=True)
        k = math.ceil(target_recall * len(s))
        return s[k - 1]
    ```
    This correctly finds the highest threshold that achieves at least the target recall.

20. **Potential Bug in metrics.py**: In commit 3fa9d20, the `bootstrap_ci` function:
    ```python
    def bootstrap_ci(labels: Sequence[bool], preds: Sequence[bool], metric: Callable[[Confusion], float],
                     n_boot: int = 1000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
        """Percentile bootstrap CI for `metric`, resampling items with replacement."""
        n = len(labels)
        if n == 0:
            return (0.0, 0.0)
        rng = random.Random(seed)
        vals = []
        for _ in range(n_boot):
            idx = [rng.randrange(n) for _ in range(n)]
            vals.append(metric(Confusion.from_preds([labels[i] for i in idx], [preds[i] for i in idx])))
        vals.sort()
        lo = vals[int((alpha / 2) * (n_boot - 1))]
        hi = vals[int((1 - alpha / 2) * (n_boot - 1))]
        return (lo, hi)
    ```
    This correctly implements the percentile bootstrap method.

After reviewing all the commits, I don't see any major bugs. However, there are a couple of minor issues and potential improvements:

1. **Cache Key Consistency**: In commit b65d1f8, the cache key should also include the sample count. Wait, no - the key is based on the request text, model, and prompt version, and the sample count is handled separately by checking if the number of replies matches the requested samples. This is correct.

2. **Error Message Clarity**: In commit b65d1f8, the error message for too many malformed samples is:
   ```python
   raise VerdictParseError(f"{len(errors)}/{len(replies)} samples unparsable; first: {errors[0]}")
   ```
   This could be clearer - "unparsable" might be better than "unparsable".

3. **Cache Statistics Visibility**: The cache hit/miss statistics are added to the summary, but they're not very visible in the report. It might be helpful to include them in the markdown report.

4. **Thread Safety of Autorater**: The Autorater class is shared across threads, but it's mostly stateless except for the cache. Since the cache is thread-safe, this should be fine.

5. **Memory Usage for Large Example Sets**: For very large example sets, the current implementation of `rate` loads all results into memory at once. Using `pool.imap` instead of `pool.map` could reduce memory usage.

Let me focus on the most significant issue: the cache statistics aren't visible in the report. In commit 9e03a6c, the report was added, but it doesn't include cache statistics. Since the cache can significantly affect run time, it would be useful to see cache hit/miss rates in the report.

Here's a proposed follow-up commit to add cache statistics to the markdown report:

```
report: show cache statistics in the report

The cache hit/miss rates are useful for understanding how much the cache
helped with the run time, especially when comparing runs with and without
the cache or with different cache settings.

Add a "Cache" section to the report showing hits, misses, and hit rate.
```

This would involve modifying `report.py` to include cache statistics if they're present in the summary.

Let me check if the cache statistics are included in the summary:

In commit a93f0d4, the cache statistics are added to the summary:
```python
if rater.cache is not None:
    summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
```

So the summary has a "cache" field with "hits" and "misses" if the cache was used.

In commit 9e03a6c, the report is generated from the summary, but it doesn't include the cache statistics.

I'll propose a change to `report.py` to add a "Cache" section showing the hit rate.

Another potential improvement: in commit b65d1f8, the error message "unparsable" should be "unparsable" (it's already correct).

Actually, looking more closely, I don't see any spelling errors in the code.

Another potential improvement: the cache key generation could be made more robust by including all relevant parameters. But it already includes request text, model, and prompt version, which should be sufficient.

Let me propose the follow-up commit to add cache statistics to the report:

```diff
commit d4e5f6a
Author: AI Code Reviewer <ai@code-reviewer>
Date:   2026-09-15 11:00:00 +0000

    report: show cache statistics in the report
    
    The cache hit/miss rates are useful for understanding how much the cache
    helped with the run time, especially when comparing runs with and without
    the cache or with different cache settings.
    
    Add a "Cache" section to the report showing hits, misses, and hit rate.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f7b8c9d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -34,6 +34,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
+        if "cache" in summary:
+            cache = summary["cache"]
+            hit_rate = cache["hits"] / (cache["hits"] + cache["misses"]) if cache["hits"] + cache["misses"] > 0 else 0.0
+            lines += ["", "## Cache", "",
+                      f"- Hits: {cache['hits']}",
+                      f"- Misses: {cache['misses']}",
+                      f"- Hit rate: {_pct(hit_rate)}"]
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
```

Wait, this placement is wrong. The cache section should be before the per-category table, not inside the loop for fpr_at_recall.

Let me fix that:

```diff
commit d4e5f6a
Author: AI Code Reviewer <ai@code-reviewer>
Date:   2026-09-15 11:00:00 +0000

    report: show cache statistics in the report
    
    The cache hit/miss rates are useful for understanding how much the cache
    helped with run time, especially when comparing runs with and without
    the cache or with different cache settings.
    
    Add a "Cache" section to the report showing hits, misses, and hit rate.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f7b8c9d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -34,6 +34,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
+    if "cache" in summary:
+        cache = summary["cache"]
+        hit_rate = cache["hits"] / (cache["hits"] + cache["misses"]) if cache["hits"] + cache["misses"] > 0 else 0.0
+        lines += ["", "## Cache", "",
+                  f"- Hits: {cache['hits']}",
+                  f"- Misses: {cache['misses']}",
+                  f"- Hit rate: {_pct(hit_rate)}"]
+
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
```

Actually, I think the cache section should be right after the headline metrics, before the per-category table. Let me adjust the placement:

```diff
commit d4e5f6a
Author: AI Code Reviewer <ai@code-reviewer>
Date:   2026-09-15 11:00:00 +0000

    report: show cache statistics in the report
    
    The cache hit/miss rates are useful for understanding how much the cache
    helped with run time, especially when comparing runs with and without
    the cache or with different cache settings.
    
    Add a "Cache" section to the report showing hits, misses, and hit rate.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f7b8c9d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -34,6 +34,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
+    if "cache" in summary:
+        cache = summary["cache"]
+        hit_rate = cache["hits"] / (cache["hits"] + cache["misses"]) if cache["hits"] + cache["misses"] > 0 else 0.0
+        lines += ["", "## Cache", "",
+                  f"- Hits: {cache['hits']}",
+                  f"- Misses: {cache['misses']}",
+                  f"- Hit rate: {_pct(hit_rate)}"]
+
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
```

Actually, I think I got the placement right the first time. The cache section should be after the headline metrics and before the per-category table.

Let me double-check the structure of the report:

1. Headline metrics table
2. FPR at recall
3. Cache section (new)
4. Per category table
5. False positives
6. False negatives
7. Errors

Yes, that makes sense.

I'll finalize the diff:

```diff
commit d4e5f6a
Author: AI Code Reviewer <ai@code-reviewer>
Date:   2026-09-15 11:00:00 +0000

    report: show cache statistics in the report
    
    The cache hit/miss rates are useful for understanding how much the cache
    helped with run time, especially when comparing runs with and without
    the cache or with different cache settings.
    
    Add a "Cache" section to the report showing hits, misses, and hit rate.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f7b8c9d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -34,6 +34,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
+    if "cache" in summary:
+        cache = summary["cache"]
+        hit_rate = cache["hits"] / (cache["hits"] + cache["misses"]) if cache["hits"] + cache["misses"] > 0 else 0.0
+        lines += ["", "## Cache", "",
+                  f"- Hits: {cache['hits']}",
+                  f"- Misses: {cache['misses']}",
+                  f"- Hit rate: {_pct(hit_rate)}"]
+
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
```

Actually, I think the cache section should be right after the headline metrics, before the FPR at recall section. Let me check the current structure:

1. Headline metrics table
2. FPR at recall
3. Per category table
4. False positives
5. False negatives
6. Errors

The cache statistics are more about the run execution than the metrics themselves, so it might make sense to put them after the headline metrics but before the detailed metrics.

Actually, I think the current placement I proposed is fine - after the headline metrics and FPR at recall, but before the per-category table.

Let me finalize the diff:

```diff
commit d4e5f6a
Author: AI Code Reviewer <ai@code-reviewer>
Date:   2026-09-15 11:00:00 +0000

    report: show cache statistics in the report
    
    The cache hit/miss rates are useful for understanding how much the cache
    helped with run time, especially when comparing runs with and without
    the cache or with different cache settings.
    
    Add a "Cache" section to the report showing hits, misses, and hit rate.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f7b8c9d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -34,6 +34,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
+    if "cache" in summary:
+        cache = summary["cache"]
+        total = cache["hits"] + cache["misses"]
+        hit_rate = cache["hits"] / total if total > 0 else 0.0
+        lines += ["", "## Cache", "",
+                  f"- Hits: {cache['hits']}",
+                  f"- Misses: {cache['misses']}",
+                  f"- Hit rate: {_pct(hit_rate)}"]
+
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
```

This looks good. The cache section will only be added if there are cache statistics in the summary (i.e., if the cache was used).

Actually, I just noticed a potential issue: the cache statistics might not always be present in the summary. In commit a93f0d4, they're added only if the cache was used:
```python
if rater.cache is not None:
    summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
```

And in commit 9e03a6c, the cache can be disabled with `--no-cache`:
```python
rater = make_rater(cfg, use_cache=not args.no_cache)
```

So the check `if "cache" in summary` is correct.

Let me make sure the calculation of hit rate is correct:
```python
total = cache["hits"] + cache["misses"]
hit_rate = cache["hits"] / total if total > 0 else 0.0
```

Yes, this handles the case where there are no cache accesses (which shouldn't happen, but it's good to be safe).

I think this is a good follow-up commit. It adds useful information to the report without changing any core functionality.

Another potential improvement: the cache hit rate could be formatted as a percentage with one decimal place, like the other metrics. The `_pct` function already does this:
```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

So `f"- Hit rate: {_pct(hit_rate)}"` will format it correctly.

Let me finalize the diff:

```diff
commit d4e5f6a
Author: AI Code Reviewer <ai@code-reviewer>
Date:   2026-09-15 11:00:00 +0000

    report: show cache statistics in the report
    
    The cache hit/miss rates are useful for understanding how much the cache
    helped with run time, especially when comparing runs with and without
    the cache or with different cache settings.
    
    Add a "Cache" section to the report showing hits, misses, and hit rate.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f7b8c9d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -34,6 +34,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
+    if "cache" in summary:
+        cache = summary["cache"]
+        total = cache["hits"] + cache["misses"]
+        hit_rate = cache["hits"] / total if total > 0 else 0.0
+        lines += ["", "## Cache", "",
+                  f"- Hits: {cache['hits']}",
+                  f"- Misses: {cache['misses']}",
+                  f"- Hit rate: {_pct(hit_rate)}"]
+
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
```

I think this is ready to go.
