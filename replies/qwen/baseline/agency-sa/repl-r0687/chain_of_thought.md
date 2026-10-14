I need to review the commit chain for the misuseclf repository and propose a follow-up commit that fixes any bugs or improves the code. Let me analyze the commits one by one to understand what's happening.

## Overview of the commit chain

This is a series of commits for a misuse classifier system that rates user requests to identify policy violations. The system has evolved from a simple classifier to a more sophisticated pipeline with caching, self-consistency sampling, and detailed reporting.

Key developments across the commits:

1. **Concurrent rating** (5c1e8a2): Added thread pool to rate items concurrently, reducing runtime from 55 min to 8 min for 2,400 items.

2. **Rating cache** (a93f0d4): Added SQLite cache for autorater replies to avoid re-rating the same requests across different runs or datasets.

3. **Prompt v2** (e27b6c1): Improved prompt with benign-context guidance to reduce false positives, especially for requests that mention sensitive topics without asking for actionable help.

4. **Prompt v3** (0d4f7b3, 7b2e9c5): Switched to graded JSON output with scores (0-100) instead of binary verdicts, allowing for per-category thresholding.

5. **Per-category thresholds** (c48a1e7): Added calibration of per-category thresholds on dev data to optimize FPR/recall tradeoffs.

6. **Enhanced metrics** (3fa9d20): Added FPR at fixed recall, bootstrap confidence intervals, and per-category breakdowns.

7. **Self-consistency sampling** (b65d1f8): Added sampling multiple responses per item and averaging scores to reduce borderline false positives.

8. **Markdown reporting** (9e03a6c): Added detailed markdown reports with metrics, per-category tables, and false positive/negative examples.

9. **Tests** (2c7d58e): Added tests for cache and end-to-end pipeline.

## Reviewing for bugs and optimization opportunities

Let me look for potential issues across these commits:

### 1. Cache key generation

In commit a93f0d4, the cache key is generated using:
```python
h = hashlib.sha256()
for part in (model, prompt_version, ex.request):
    h.update(part.encode("utf-8"))
    h.update(b"\x00")
return h.hexdigest()
```

This seems reasonable - it hashes the model, prompt version, and request text to create a unique key. The null byte separator helps prevent collisions.

### 2. Self-consistency implementation

In commit b65d1f8, the self-consistency feature was added. Let's check the implementation:

```python
def _sample(self, ex: Example) -> list[str]:
    prompt = self.build_prompt(ex)
    temperature = self.temperature if self.samples == 1 else self.sample_temperature
    return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
            for _ in range(self.samples)]
```

This seems correct - it uses the base temperature only when samples=1, otherwise uses sample_temperature.

The aggregation function:
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

This looks correct too - it takes the mean score, most common category (with tiebreaker), and the highest-scoring rationale.

### 3. Cache handling with samples

In commit b65d1f8, the cache handling was updated to handle different sample counts:

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

This is correct - it checks if the cached replies match the requested sample count.

### 4. Potential issue: Threshold loading

In commit c48a1e7, the `load_thresholds` function was added:

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

This function checks for unknown categories in the thresholds file, which is good. However, it doesn't check if the categories in the thresholds file are valid categories from the CATEGORIES dictionary. It only checks if they're in the CATEGORIES keys.

Wait, actually, it does check:
```python
unknown = sorted(set(per_category) - set(CATEGORIES))
if unknown:
    raise ValueError(f"thresholds for unknown categories: {unknown}")
```

This is correct - it checks if any category in the thresholds file is not in the CATEGORIES dictionary.

### 5. Potential issue: Cache key collision

Looking at the cache key generation again:
```python
for part in (model, prompt_version, ex.request):
    h.update(part.encode("utf-8"))
    h.update(b"\x00")
```

This uses a null byte as a separator between parts. This should prevent collisions where different combinations of parts could hash to the same value. For example, "a", "b" and "ab", "" would collide without a separator. The null byte separator solves this.

### 6. Potential issue: Error handling in self-consistency

In commit b65d1f8, the self-consistency implementation tolerates a minority of malformed samples:

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

This is reasonable - it allows up to 50% of samples to be malformed. However, there's a potential issue: if all samples fail to parse, it will raise an exception with `errors[0]`, but `errors` could be empty if no samples were parsed. Let's check:

If all samples fail to parse, `len(ratings) = 0`, so `len(ratings) * 2 <= len(replies)` is true (0 <= len(replies)), so it will raise the exception. But `errors` would have length `len(replies)`, so `errors[0]` is safe.

### 7. Potential issue: Cache key for different sample counts

In commit b65d1f8, the cache key doesn't include the sample count. This is intentional, as seen in the `get` method:

```python
if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
```

The cache key is based only on the request, model, and prompt version, not the sample count. This means that if you first cache with samples=1 and then try to get with samples=3, it will be a miss (as intended). However, this means that the same request rated with different sample counts will be stored multiple times in the cache, which is inefficient.

But this is by design - the cache stores the actual replies, which depend on the sample count. So if you change the sample count, you need different replies, hence a cache miss is correct.

### 8. Potential issue: Concurrency in cache

The cache uses a lock for thread safety:

```python
def __init__(self, path: str | Path):
    # ...
    self._conn = sqlite3.connect(str(path), check_same_thread=False)
    self._lock = threading.Lock()
    # ...
```

And all database operations are protected by the lock:

```python
def get(self, ex: Example, model: str, prompt_version: str,
        samples: int | None = None) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version),)).fetchone()
    # ...
```

This seems correct for thread safety.

### 9. Potential issue: Cache misses for malformed replies

In commit b65d1f8, malformed replies are not cached:

```python
def rate(self, ex: Example) -> Rating:
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

The comment says "only usable reply sets are cached", which means that if `_parse_all` raises an exception (due to too many malformed samples), the replies won't be cached. This is correct - we don't want to cache unusable replies.

### 10. Potential issue: Threshold calibration

In commit c48a1e7, the calibration code was added:

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

This seems correct - it finds the highest threshold that achieves at least the target recall.

### 11. Potential issue: Report generation

In commit 9e03a6c, the report generation code was added:

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

This sorts the items by score descending, which makes sense for false positives (we want to see the highest-scoring ones first). But for false negatives, we might want to see the highest-scoring ones too (those that should have been caught but weren't).

Wait, false negatives are items that are violations but were predicted as benign. For these, higher score means the model was more confident it was a violation but we still didn't flag it (due to thresholding). So showing the highest-scoring false negatives makes sense - these are the most egregious misses.

### 12. Potential issue: Markdown escaping

In the report generation code, there's:
```python
_clip(r.rationale, clip).replace('|', '/')
```

This replaces pipe characters with slashes to avoid breaking the Markdown table. But there could be other characters that need escaping for Markdown, like backticks or asterisks.

### 13. Potential issue: Cache key for different temperatures

The cache key doesn't include the temperature parameter. This is a potential issue because different temperatures could lead to different replies for the same request.

Looking at the code, temperature is used in the `_sample` method:

```python
temperature = self.temperature if self.samples == 1 else self.sample_temperature
```

But the cache key is based on model, prompt_version, and ex.request - it doesn't include the temperature.

This means that if you change the temperature (either base temperature or sample_temperature), the cache will still return the old replies, which were generated with a different temperature.

This is a bug! The cache key should include the temperature parameters.

Let me verify this:

In commit b65d1f8, the cache key is generated in `RatingCache.key`:
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

It doesn't include temperature or sample_temperature.

And in `Autorater.rate`:
```python
replies = None
if self.cache is not None:
    replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
```

It passes only model, prompt_version, and implicitly the request (through `ex`) to `cache.get`, not the temperature.

This is definitely a bug. If you change the temperature, you should get different replies, but the cache will return the old replies.

### 14. Potential issue: Cache key for different max_tokens

Similarly, the cache key doesn't include max_tokens, which could also affect the replies.

### 15. Potential issue: Cache key for different models

Wait, the cache key does include the model:
```python
for part in (model, prompt_version, ex.request):
```

So different models will have different cache keys, which is correct.

### 16. Potential issue: Cache key for different prompt versions

The cache key includes prompt_version, which is correct.

### 17. Potential issue: Cache key for different samples

The cache key doesn't include samples, but the `get` method checks if the cached replies match the requested sample count:

```python
if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
```

This is correct - the same request with different sample counts will be a cache miss, which is what we want.

### Summary of potential issues

1. **Critical bug**: The cache key doesn't include temperature parameters (base temperature and sample_temperature), which means changing these parameters won't invalidate the cache, leading to incorrect replies being used.

2. **Potential issue**: The cache key doesn't include max_tokens, which could also affect the replies.

3. **Potential issue**: Markdown escaping in reports might not be sufficient (only pipes are replaced).

Let me focus on the critical bug first - the cache key not including temperature parameters.

## Proposed fix

I'll propose a follow-up commit that fixes the cache key to include temperature parameters.

Specifically, the cache key should include:
- model
- prompt_version
- temperature (for base temperature when samples=1)
- sample_temperature (for samples>1)
- max_tokens
- ex.request

Wait, actually, temperature is only used when samples=1, and sample_temperature is used when samples>1. So we should include whichever is relevant.

But to keep the cache key consistent, it might be simpler to always include both temperature and sample_temperature in the key, even though only one is used at a time.

Alternatively, we could include a "temperature" parameter in the key that is temperature if samples=1 else sample_temperature.

Let me check how the temperature is used:

```python
def _sample(self, ex: Example) -> list[str]:
    prompt = self.build_prompt(ex)
    temperature = self.temperature if self.samples == 1 else self.sample_temperature
    return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
            for _ in range(self.samples)]
```

So the effective temperature is:
- self.temperature if self.samples == 1
- self.sample_temperature if self.samples > 1

So the cache key should include this effective temperature.

But wait, the cache key is used before we know how many samples we're going to take. In `Autorater.rate`:

```python
replies = None
if self.cache is not None:
    replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
```

At this point, we know self.samples, so we could compute the effective temperature and include it in the cache key.

Actually, looking at the `RatingCache.key` method:

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

It's a static method that doesn't have access to the Autorater instance, so it can't know about temperature.

This means the cache key generation needs to be updated to include temperature parameters, and the callers need to pass these parameters.

Let's look at how the cache key is used:

In `RatingCache.get`:
```python
def get(self, ex: Example, model: str, prompt_version: str,
        samples: int | None = None) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version),)).fetchone()
```

It calls `self.key(ex, model, prompt_version)`.

In `RatingCache.put`:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
```

It also calls `self.key(ex, model, prompt_version)`.

So to include temperature in the cache key, we need to:
1. Update `RatingCache.key` to take temperature parameters
2. Update all callers to pass these parameters

Given that the effective temperature depends on whether samples=1 or not, and we know samples at the call site, we can compute the effective temperature and pass it to `key`.

Let's update `RatingCache.key` to:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, temperature: float, max_tokens: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(temperature), str(max_tokens), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

And update the callers:

In `RatingCache.get`:
```python
def get(self, ex: Example, model: str, prompt_version: str, temperature: float, max_tokens: int,
        samples: int | None = None) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version, temperature, max_tokens),)).fetchone()
```

In `RatingCache.put`:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str,
        temperature: float, max_tokens: int) -> None:
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, temperature, max_tokens), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
```

Then in `Autorater.rate`:
```python
def rate(self, ex: Example) -> Rating:
    replies = None
    if self.cache is not None:
        temperature = self.temperature if self.samples == 1 else self.sample_temperature
        replies = self.cache.get(ex, self.model, self.prompt_version, temperature, self.max_tokens,
                                 samples=self.samples)
    if replies is None:
        replies = self._sample(ex)
        temperature = self.temperature if self.samples == 1 else self.sample_temperature
        rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
        if self.cache is not None:
            self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
                           temperature=temperature, max_tokens=self.max_tokens)
        return rating
    return aggregate(self._parse_all(replies))
```

This way, the cache key includes the effective temperature and max_tokens, so changing these parameters will invalidate the cache.

Let me check if there are other parameters that should be included in the cache key:

- `model`: already included
- `prompt_version`: already included
- `temperature`/`sample_temperature`: now included as `temperature`
- `max_tokens`: now included
- `ex.request`: already included

I think that's all the parameters that affect the model's reply.

Now, let's check if there are any other issues.

## Markdown escaping

In the report generation code, only pipes are replaced:

```python
_clip(r.rationale, clip).replace('|', '/')
```

This is insufficient for Markdown. We should properly escape special characters.

A better approach would be to use a Markdown escaper. Since Python doesn't have a built-in one, we could implement a simple one:

```python
def escape_markdown(text: str) -> str:
    # Escape characters that have special meaning in Markdown
    for char in "\\`*_{}[]()#+-.!":
        text = text.replace(char, f"\\{char}")
    return text
```

But this might be overkill, and escaping everything could make the text hard to read.

Alternatively, we could just wrap the rationale in backticks to make it a code span, which would avoid most Markdown issues:

```python
f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
f"`{_clip(r.rationale, clip)}` |"
```

This would be simpler and more effective.

Let me check the current code:

```python
f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
f"{_clip(r.rationale, clip).replace('|', '/')} |"
```

It already wraps the ID in backticks, but not the rationale. Wrapping the rationale in backticks would solve most escaping issues.

## Proposed follow-up commit

Based on the analysis, I'll propose a follow-up commit that:

1. Fixes the cache key to include temperature and max_tokens parameters
2. Improves Markdown escaping in reports by wrapping rationales in backticks

Let's write the commit message and diff.

Commit message:
```
cache: include temperature and max_tokens in cache key; improve report escaping

The cache key previously didn't include temperature parameters (base
temperature and sample_temperature) or max_tokens, which meant changing
these parameters wouldn't invalidate the cache. This could lead to using
replies generated with different parameters, causing incorrect results.

Updated the cache key to include the effective temperature (which depends
on whether samples=1) and max_tokens. All cache operations now pass these
parameters.

Also improved Markdown escaping in reports by wrapping rationales in
backticks instead of just replacing pipe characters. This prevents
rationales with Markdown special characters from breaking the report
formatting.

TSE-1448
```

Now for the diff:

1. Update `RatingCache.key` to include temperature and max_tokens
2. Update `RatingCache.get` and `RatingCache.put` to take and use these parameters
3. Update `Autorater.rate` to pass these parameters
4. Update report generation to wrap rationales in backticks

Let me write the diff carefully.

First, the cache changes:

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..new 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,17 +48,21 @@ class RatingCache:
             return h.hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+            temperature: float, max_tokens: int, samples: int | None = None) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+            key = self.key(ex, model, prompt_version, temperature, max_tokens)
+            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?", (key,)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
+    @staticmethod
+    def key(ex: Example, model: str, prompt_version: str, temperature: float, max_tokens: int) -> str:
+        # Key includes all parameters that affect the model's reply
+        h = hashlib.sha256()
+        for part in (model, prompt_version, str(temperature), str(max_tokens), ex.request):
+            h.update(part.encode("utf-8"))
+            h.update(b"\x00")
+        return h.hexdigest()
+
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (self.key(ex, model, prompt_version, temperature, max_tokens), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
```

Wait, I think I made a mistake. The `key` method should be updated first, then `get` and `put` should use it.

Actually, let's do it step by step:

1. Update the static `key` method to include temperature and max_tokens
2. Update `get` to take temperature and max_tokens and use them in the key
3. Update `put` to take temperature and max_tokens and use them in the key

Here's the correct diff for `cache.py`:

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..new 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -51,15 +51,21 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    @staticmethod
+    def key(ex: Example, model: str, prompt_version: str, temperature: float, max_tokens: int) -> str:
+        """Generate cache key including all parameters that affect the model's reply."""
+        h = hashlib.sha256()
+        for part in (model, prompt_version, str(temperature), str(max_tokens), ex.request):
+            h.update(part.encode("utf-8"))
+            h.update(b"\x00")
+        return h.hexdigest()
+
+    def get(self, ex: Example, model: str, prompt_version: str, temperature: float, max_tokens: int,
+            samples: int | None = None) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+            key = self.key(ex, model, prompt_version, temperature, max_tokens)
+            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?", (key,)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (self.key(ex, model, prompt_version, temperature, max_tokens), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
```

Wait, the `put` method doesn't take `temperature` and `max_tokens` as parameters yet. Let's fix that:

```diff
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str,
+            temperature: float, max_tokens: int
     ) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (self.key(ex, model, prompt_version, temperature, max_tokens), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
```

Now, update `Autorater.rate`:

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..new 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -84,13 +84,15 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            temperature = self.temperature if self.samples == 1 else self.sample_temperature
+            replies = self.cache.get(ex, self.model, self.prompt_version, temperature, self.max_tokens, samples=self.samples)
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
-                               temperature=temperature, max_tokens=self.max_tokens)
+                               temperature=temperature, max_tokens=self.max_tokens)
             return rating
         return aggregate(self._parse_all(replies))
```

Actually, in `self._sample(ex)`, we're already using the correct temperature:

```python
def _sample(self, ex: Example) -> list[str]:
    prompt = self.build_prompt(ex)
    temperature = self.temperature if self.samples == 1 else self.sample_temperature
    return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
            for _ in range(self.samples)]
```

So when we call `self.cache.put`, we need to use that same temperature. But we don't have it in scope. So we should compute it before calling `_sample`:

```python
def rate(self, ex: Example) -> Rating:
    replies = None
    if self.cache is not None:
        temperature = self.temperature if self.samples == 1 else self.sample_temperature
        replies = self.cache.get(ex, self.model, self.prompt_version, temperature, self.max_tokens, samples=self.samples)
    if replies is None:
        temperature = self.temperature if self.samples == 1 else self.sample_temperature
        replies = self._sample(ex)
        rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
        if self.cache is not None:
            self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
                           temperature=temperature, max_tokens=self.max_tokens)
        return rating
    return aggregate(self._parse_all(replies))
```

Yes, that's better.

Now for the report escaping:

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..new 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -32,7 +32,7 @@ def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[
     for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
         rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                     f"{_clip(r.rationale, clip).replace('|', '/')} |")
-    if len(items) > max_examples:
+    if len(items) > max_examples:
         rows.append(f"\n_{len(items) - max_examples} more not shown._")
     return rows
```

Change to:

```python
    for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"`{_clip(r.rationale, clip)}` |")
```

Wrap the rationale in backticks.

Let me double-check everything.

I think this covers the main issues I found. The cache key now includes all relevant parameters, and the report escaping is improved.

Let me write the full diff for the follow-up commit.
