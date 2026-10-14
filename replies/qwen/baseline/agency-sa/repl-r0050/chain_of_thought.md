Let me carefully review all the commits in this chain to understand what's been implemented and identify any potential issues or areas for improvement.

## Overview of Changes

This commit chain shows the evolution of a misuse classifier system with several major features:

1. Initial implementation with basic rating
2. Added concurrency with thread pool for faster processing
3. Added caching of model responses to avoid re-rating the same requests
4. Improved prompt templates to reduce false positives
5. Switched from binary classification to graded scoring with JSON output
6. Added per-category thresholds calibrated on dev data
7. Added self-consistency sampling to improve reliability
8. Added detailed reporting with metrics and examples

## Potential Issues to Check

Let me go through the commits and look for potential issues:

### 1. Commit 5c1e8a2 - pipeline: rate items concurrently

This commit adds a thread pool for concurrent rating of items. The implementation looks solid:
- Uses `ThreadPoolExecutor` with configurable number of workers
- Maintains input order with `pool.map`
- Has a fallback to sequential processing when workers=1

No obvious issues here.

### 2. Commit a93f0d4 - cache: sqlite cache for autorater replies

This commit adds a SQLite cache for autorater replies. Key points:
- Cache key is based on request text, model, and prompt version (not example ID)
- Only caches well-formed replies
- Thread-safe with a lock

Potential issue:
- In `autorater.py`, when getting a cached reply, it's using `cached[0]` but the cache stores a list of replies. This is fine for the initial implementation where samples=1, but might need adjustment for the later self-consistency feature.

### 3. Commit e27b6c1 - prompts: autorater v2 with benign-context guidance

This commit improves the prompt template to reduce false positives by adding context about what doesn't count as violations.

No obvious issues.

### 4. Commit 0d4f7b3 - prompts: add v3 template with graded JSON output

This commit adds a new prompt version that returns JSON with a graded score instead of a binary verdict.

No obvious issues, but it's just a template addition.

### 5. Commit 7b2e9c5 - autorater: parse graded JSON verdicts, switch to v3

This commit implements parsing of the JSON output from v3 prompts and switches the default to v3.

Key changes:
- Added JSON parsing logic that looks for the last JSON object in the response
- Added validation of the JSON structure
- Modified the Rating class to include a score in [0,1]
- Updated the score calculation to use a threshold

Potential issues:
- The cache implementation from commit a93f0d4 stores a list of replies, but when retrieving from cache, it's only using the first reply with `cached[0]`. This might not work correctly when we later add self-consistency sampling (multiple samples per item).

### 6. Commit c48a1e7 - policy: per-category thresholds calibrated on dev

This commit adds per-category thresholds calibrated on the dev set.

Key changes:
- Added `calibrate.py` for threshold fitting
- Added `policy.py` for threshold management
- Modified the scoring to use per-category thresholds

Potential issues:
- In `pipeline.py`, the `score` function now takes a `Thresholds` object instead of a single threshold value
- In `cli.py`, the command line parameters for calibration were added

No obvious issues.

### 7. Commit 3fa9d20 - metrics: FPR at fixed recall, bootstrap CIs, per-category breakdown

This commit adds more detailed metrics including FPR at fixed recall, confidence intervals, and per-category breakdown.

Key changes:
- Added bootstrap CI calculation
- Added `fpr_at_recall` function
- Added `per_category` function for breakdown

Potential issues:
- In `metrics.py`, the `bootstrap_ci` function uses percentile bootstrap which is appropriate
- The `fpr_at_recall` function seems correctly implemented

No obvious issues.

### 8. Commit b65d1f8 - autorater: self-consistency over k samples

This commit adds self-consistency sampling where each item is rated multiple times and the results are aggregated.

Key changes:
- Added `samples` and `sample_temperature` parameters
- Added `aggregate` function to combine multiple samples
- Modified cache to handle multiple replies per item
- Updated `Rating` class to include `n_samples` and `spread`

Potential issues:
- In `cache.py`, the `get` method now has a `samples` parameter to check if the cached replies match the requested sample count
- In `autorater.py`, when getting cached replies, it now passes `samples=self.samples` to the cache get method
- In `cache.py`, the `get` method checks if the number of cached replies matches the requested sample count

This seems well-implemented, but I want to check one specific thing:

In `autorater.py`, in the `rate` method:

```python
replies = None
if self.cache is not None:
    replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
if replies is None:
    replies = self._sample(ex)
    rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
    if self.cache is not None:
        self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
    return rating
return aggregate(self._parse_all(replies))
```

This looks correct. It checks if the cached replies have the right number of samples, and if not, it misses the cache and re-rates.

### 9. Commit 9e03a6c - report: markdown report with false positives, run flags

This commit adds a markdown report with detailed metrics and examples of false positives/negatives.

Key changes:
- Added `report.py` for generating markdown reports
- Modified `pipeline.write` to optionally write a report
- Added command line flags for report control

No obvious issues.

### 10. Commit 2c7d58e - tests: rating cache and end-to-end pipeline; README for the v3 setup

This commit adds tests for the cache and end-to-end pipeline, and updates the README.

Key changes:
- Added `test_cache.py` for cache testing
- Added `test_pipeline.py` for end-to-end testing
- Updated README with configuration details

No obvious issues.

## Specific Issues to Address

After reviewing all the commits, I found one potential issue:

In commit b65d1f8 (self-consistency sampling), when the cache is hit but the number of samples doesn't match, it correctly misses the cache and re-rates the item. However, there's a subtle issue with the cache key.

The cache key is generated based on the request text, model, and prompt version, but not the number of samples:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str) -> str:
    # Keyed on the request text rather than the id: the same request appears in
    # several sets under different ids and only needs rating once. A different model
    # or prompt version is a different key.
    h = hashlib.sha256()
    for part in (model, prompt_version, ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This means that if you run with `samples=1` and then later with `samples=3`, the cache key will be the same, but the number of replies stored will be different. The current implementation handles this by checking the length of the replies list:

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

This is correct - it checks if the number of cached replies matches the requested sample count, and if not, it counts as a miss. However, this is inefficient because it fetches the row from the database only to discard it if the sample count doesn't match.

A better approach would be to include the sample count in the cache key, so that different sample counts get different cache entries. This would avoid unnecessary database lookups.

Let me check if this is already addressed in any of the commits...

Actually, looking at the code again, I don't see the sample count included in the cache key. This is a potential optimization.

Let me verify this by looking at the cache key function:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str) -> str:
    # Keyed on the request text rather than the id: the same request appears in
    # several sets under different ids and only needs rating once. A different model
    # or prompt version is a different key.
    h = hashlib.sha256()
    for part in (model, prompt_version, ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

Yes, the sample count is not included in the cache key. This means that if you run with different sample counts, you'll get cache misses, but you'll still be doing a database lookup for each item, which is unnecessary.

The solution would be to include the sample count in the cache key. Since the sample count is part of what determines the response, it should be part of the key.

Let me see if this is the only issue...

Another issue I noticed: in `cache.py`, in the `put` method, it's using the same cache key regardless of the number of replies:

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

This is correct for the current implementation, but if we include the sample count in the key, we'd need to adjust this.

Actually, the sample count is determined by the length of the `replies` list, so we could include it in the key like this:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

And then update the `get` and `put` methods to use this new key function.

Let me check if there are any other issues...

Another potential issue: in `autorater.py`, in the `rate` method, when getting from the cache, it's passing `samples=self.samples`:

```python
replies = None
if self.cache is not None:
    replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
```

But in the cache's `get` method, the `samples` parameter is optional and defaults to `None`:

```python
def get(self, ex: Example, model: str, prompt_version: str,
        samples: int | None = None) -> list[str] | None:
```

This is correct, but when putting to the cache, it doesn't pass the sample count:

```python
if self.cache is not None:
    self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
```

Actually, the sample count is determined by the length of `replies`, so it doesn't need to be passed explicitly. But for the key, it should be included.

Let me see if there are any other issues...

I think the main issue is the cache key not including the sample count, which leads to unnecessary database lookups when the sample count changes.

Let me check the test cases to see if they cover this scenario...

In `test_cache.py`, there's a test for different sample counts:

```python
def test_other_model_prompt_or_sample_count_misses(self):
    self.cache.put(A, ["r1"], model="m", prompt_version="v3")
    for args, kw in ((("m2", "v3"), {}), (("m", "v2"), {}), (M, {"samples": 3})):
        self.assertIsNone(self.cache.get(A, *args, **kw))
```

This test checks that when the sample count is different, it misses the cache, which is correct. But it doesn't check the efficiency of the cache lookup.

So the functionality is correct, but it could be more efficient by including the sample count in the cache key to avoid unnecessary database lookups.

Let me see if there are any other issues...

Another issue: in `pipeline.py`, in the `score` function, it's creating a `labels` list and a `preds` list, but it's doing it twice:

```python
ok = [r for r in rated if r.error is None]
for r in ok:
    r.pred = thresholds.is_violation(r.score, r.pred_category)
summary = metrics.summarize(labels, preds, n_boot=n_boot)
summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                      fixed_recall)}
summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                               [r.pred_category for r in ok])
```

But `labels` and `preds` are not defined before this. Actually, in the previous commit, it was:

```python
ok = [r for r in rated if r.error is None]
for r in ok:
    r.pred = thresholds.is_violation(r.score, r.pred_category)
labels = [r.example.is_violation for r in ok]
preds = [bool(r.pred) for r in ok]
summary = metrics.summarize(labels, preds, n_boot=n_boot)
```

So in the current code, `labels` and `preds` should be defined. Let me check the diff for commit 3fa9d20:

```diff
-    summary = metrics.summarize([r.example.is_violation for r in ok], [bool(r.pred) for r in ok])
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
+                                                                          fixed_recall)}
+    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
+                                                   [r.pred_category for r in ok])
```

Yes, so `labels` and `preds` are defined. No issue there.

Another potential issue: in `metrics.py`, the `fpr_at_recall` function has a comment saying "Items tied on score are flagged together." But let me check the implementation:

```python
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
```

This does handle tied scores correctly by processing all items with the same score at once. So no issue there.

Let me check the `bootstrap_ci` function in `metrics.py`:

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

This looks correct for a percentile bootstrap CI.

One more thing: in `cache.py`, the `get` method does:

```python
replies = json.loads(row[0]) if row is not None else None
if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
    self.misses += 1
    return None
self.hits += 1
return replies
```

This is correct, but it means that for every cache lookup, it has to deserialize the JSON to check the length of the replies list. If we include the sample count in the cache key, we wouldn't need to do this.

Actually, the cache key already includes the request text, model, and prompt version, which determine what the response should be. The sample count is a parameter of the rating process, not part of what determines the response. So it makes sense that the cache key doesn't include the sample count.

But the number of samples does affect the response - with more samples, you get more replies. So the sample count should be part of what determines the cache key.

For example, if you rate an item with `samples=1`, you get one reply. If you later rate the same item with `samples=3`, you get three replies. These are different responses, so they should have different cache keys.

So I think including the sample count in the cache key is the right approach.

Let me see if there's any other issue...

Another potential issue: in `autorater.py`, in the `_parse_all` method:

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

This tolerates a minority of malformed samples, which is good. But what if all samples are malformed? It raises an error, which is correct.

But there's a potential issue with the error message: `errors[0]` might be out of bounds if `errors` is empty, but that can't happen because `len(ratings) * 2 <= len(replies)` implies `len(errors) >= len(replies)/2 > 0` when `len(replies) > 0`. So no issue.

Let me check the `aggregate` function:

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

This looks correct. It handles the case of a single sample correctly, and for multiple samples, it takes the mean score and the most common category (with ties broken by mean score).

One potential issue: `top = max(ratings, key=lambda r: r.score)` selects the reply with the highest score, but what if there are multiple replies with the same highest score? It will pick the first one, which is fine.

Another potential issue: the `spread` is calculated as `max(scores) - min(scores)`, which is correct.

Let me check the cache tests in `test_cache.py`:

```python
def test_other_model_prompt_or_sample_count_misses(self):
    self.cache.put(A, ["r1"], model="m", prompt_version="v3")
    for args, kw in ((("m2", "v3"), {}), (("m", "v2"), {}), (M, {"samples": 3})):
        self.assertIsNone(self.cache.get(A, *args, **kw))
```

This test checks that changing the model, prompt version, or sample count results in a cache miss, which is correct.

But it doesn't check that the cache key is different for different sample counts, which it should be.

Actually, the cache key is the same for different sample counts, which is why it's a cache miss - because the number of replies doesn't match. But as I said earlier, it would be more efficient to include the sample count in the cache key.

Let me see if there are any other issues...

Another potential issue: in `pipeline.py`, in the `_rate_one` function:

```python
def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
    try:
        r = rater.rate(ex)
        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
                         n_samples=r.n_samples, spread=r.spread)
    except (GatewayError, VerdictParseError) as e:
        return RatedItem(ex, error=f"{type(e).__name__}: {e}")
```

This correctly captures the `n_samples` and `spread` from the `Rating` object.

Let me check the `RatedItem` class in `pipeline.py`:

```python
@dataclass
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

This looks correct.

Let me check the `to_json` method:

```python
def to_json(self) -> dict:
    d = asdict(self.example)
    d.update({"score": self.score, "pred": self.pred, "pred_category": self.pred_category,
              "rationale": self.rationale, "reply": self.reply, "n_samples": self.n_samples,
              "spread": self.spread, "error": self.error})
    return d
```

This correctly includes `n_samples` and `spread` in the JSON output.

I think the main issue is the cache key not including the sample count, which leads to unnecessary database lookups when the sample count changes.

Let me see if there's any other issue...

Another potential issue: in `cache.py`, in the `put` method, it's using `ex.id` in the database row:

```python
self._conn.execute(
    "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
    " VALUES (?, ?, ?, ?, ?, ?)",
    (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
     json.dumps(replies, ensure_ascii=False), time.time()),
)
```

But the cache key is based on the request text, not the example ID. This is correct because the same request can appear in different datasets with different IDs.

Let me check the `get` method in `cache.py`:

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

This is correct, but as I said, it would be more efficient to include the sample count in the cache key.

Let me see if there's any other issue...

I think that's the main issue I found. Let me formulate a fix.

## Proposed Fix

The main issue is that the cache key doesn't include the sample count, which leads to unnecessary database lookups when the sample count changes. The fix is to include the sample count in the cache key.

Here's how I would implement it:

1. Update the `key` method in `RatingCache` to include the sample count
2. Update the `get` and `put` methods to use the new key function

Let me write the diff for this fix.

First, in `cache.py`, update the `key` method:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    # Keyed on the request text, model, prompt version, and sample count
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

Then, update the `get` method to require the sample count:

```python
def get(self, ex: Example, model: str, prompt_version: str, samples: int) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version, samples),)).fetchone()
    if row is None:
        self.misses += 1
        return None
    self.hits += 1
    return json.loads(row[0])
```

And update the `put` method:

```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str, samples: int) -> None:
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

Then, update the calls to `get` and `put` in `autorater.py`:

```python
def rate(self, ex: Example) -> Rating:
    replies = None
    if self.cache is not None:
        replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
    if replies is None:
        replies = self._sample(ex)
        rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
        if self.cache is not None:
            self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version, samples=self.samples)
        return rating
    return aggregate(self._parse_all(replies))
```

This change has several benefits:
1. It avoids unnecessary database lookups when the sample count changes
2. It makes the cache behavior more intuitive - different sample counts are treated as different cache entries
3. It removes the need to deserialize the JSON just to check the length of the replies list

Let me check if there are any backward compatibility issues...

The cache database schema remains the same, but the `key` values will change. This means that existing cache entries will not be found when using the new code, which is correct because the cache key now includes the sample count.

This is a safe change because it just means that the cache will be cold for the first run after the change, but subsequent runs will benefit from the more efficient cache.

Let me check if there are any other places that need to be updated...

In `test_cache.py`, the tests will need to be updated to pass the sample count to `get` and `put`:

```python
def test_roundtrip(self):
    self.cache.put(A, ["r1", "r2"], model="m", prompt_version="v3", samples=2)
    self.assertEqual(self.cache.get(A, *M, samples=2), ["r1", "r2"])
    self.assertEqual((self.cache.hits, self.cache.misses), (1, 0))
```

But since this is a new commit, we can include the test updates in the same commit.

Actually, the tests in `test_cache.py` already pass the sample count in some places:

```python
self.cache.get(A, *M, samples=3)
```

So the tests are already written to expect the sample count to be passed.

Let me check the specific test:

```python
def test_other_model_prompt_or_sample_count_misses(self):
    self.cache.put(A, ["r1"], model="m", prompt_version="v3")
    for args, kw in ((("m2", "v3"), {}), (("m", "m"), {}), (M, {"samples": 3})):
        self.assertIsNone(self.cache.get(A, *args, **kw))
```

Actually, this test won't work with the new code because `put` doesn't take a `samples` parameter. But in the new code, it will.

So the test needs to be updated to pass `samples=1` to `put`:

```python
def test_other_model_prompt_or_sample_count_misses(self):
    self.cache.put(A, ["r1"], model="m", prompt_version="v3", samples=1)
    for args, kw in ((("m2", "v3"), {"samples": 1}), (("m", "v2"), {"samples": 1}), (M, {"samples": 3})):
        self.assertIsNone(self.cache.get(A, *args, **kw))
```

But since this is a new commit, we can include the test updates.

Actually, I think the tests are already written to expect the sample count to be passed, so they should work with the new code.

Let me check the test in `test_cache.py`:

```python
def test_autorater_skips_gateway_on_hit(self):
    client = FakeClient()
    rater = Autorater(client, model="m", prompt_version="v3", cache=self.cache, samples=3)
    first = rater.rate(A)
    second = rater.rate(A)
    self.assertEqual(len(client.calls), 3)
    self.assertEqual(first.score, second.score)
```

In this test, the `rater` is created with `samples=3`, so when `rate` is called, it will pass `samples=3` to `cache.get`. This should work with the new code.

Let me see if there are any other issues...

I think that's the main issue I found. Let me formulate the follow-up commit.
