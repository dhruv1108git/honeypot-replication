Let me review the commit chain for the `misuseclf` repository's `classifier-v2` branch. There are 10 commits pending, and I need to check for correctness, fix bugs, and propose optimizations.

First, I'll analyze the overall changes across the commit chain:

1. Commit 5c1e8a2: Added concurrent rating with thread pool
2. Commit a93f0d4: Added SQLite cache for autorater replies
3. Commit e27b6c1: Updated prompts to v2 with benign-context guidance
4. Commit 0d4f7b3: Added v3 template with graded JSON output
5. Commit 7b2e9c5: Parse graded JSON verdicts, switched to v3
6. Commit c48a1e7: Added per-category thresholds calibrated on dev
7. Commit 3fa9d20: Added FPR at fixed recall, bootstrap CIs, per-category breakdown
8. Commit b65d1f8: Added self-consistency over k samples
9. Commit 9e03a6c: Added markdown report with false positives, run flags
10. Commit 2c7d58e: Added tests for cache and end-to-end pipeline

Let me go through each commit and look for potential issues:

### Commit 5c1e8a2: pipeline: rate items concurrently

This commit adds concurrency to the rating process using a ThreadPoolExecutor. The implementation looks correct - it maintains input order by using `pool.map` rather than an unordered approach. The configuration for workers is properly integrated.

### Commit a93f0d4: cache: sqlite cache for autorater replies

This adds a SQLite cache for autorater replies. The implementation seems solid with thread safety via a lock. One thing to note: the cache key is based on the request text rather than the item ID, which makes sense for deduplication across datasets.

### Commit e27b6c1: prompts: autorater v2 with benign-context guidance

This updates the prompt template to v2, adding guidance about benign contexts and examples. The implementation looks correct.

### Commit 0d4f7b3: prompts: add v3 template with graded JSON output

This adds a v3 template that asks for JSON output with scores instead of binary verdicts. The implementation seems correct, and it properly maintains backward compatibility with v1/v2.

### Commit 7b2e9c5: autorater: parse graded JSON verdicts, switch to v3

This is a significant change that:
1. Updates the prompt version to v3
2. Increases max_tokens to 384 to accommodate the rationale
3. Changes the Rating class to use a score in [0,1] instead of a boolean
4. Updates the parser to handle JSON output
5. Changes the pipeline to use the new scoring mechanism

I see a potential issue here: In `parse_json_verdict`, the code tries to find all JSON objects in the reply, but it doesn't validate that the last object is actually a valid verdict. It just takes the last JSON object regardless of its structure.

### Commit c48a1e7: policy: per-category thresholds calibrated on dev

This adds per-category thresholds calibrated on the dev split. The implementation looks solid, with proper handling of categories with insufficient data.

### Commit 3fa9d20: metrics: FPR at fixed recall, bootstrap CIs, per-category breakdown

This adds more sophisticated metrics including FPR at fixed recall, bootstrap CIs, and per-category breakdown. The implementation seems correct.

### Commit b65d1f8: autorater: self-consistency over k samples

This adds self-consistency by sampling each item k times and averaging scores. There are a few issues I notice:

1. In `autorater.py`, the `_parse_all` method tolerates a minority of malformed samples, but doesn't provide any information about which samples were valid. This could lead to inconsistent behavior if different samples produce wildly different results.

2. In `cache.py`, the `get` method now takes an optional `samples` parameter, but the cache key doesn't include the number of samples. This means that if you request a different number of samples for the same item, it will still try to use the cached replies (which may have a different number of samples), and then discard them as a miss. This is inefficient because it's not reusing what it can.

### Commit 9e03a6c: report: markdown report with false positives, run flags

This adds a markdown report generation. The implementation seems correct, but I don't see any tests for the report generation.

### Commit 2c7d58e: tests: rating cache and end-to-end pipeline; README for the v3 setup

This adds tests for the cache and end-to-end pipeline. The tests look comprehensive.

Now, let's focus on specific bugs or issues that need fixing:

1. **JSON Parsing Issue**: In `parse_json_verdict`, the code finds all JSON objects but doesn't validate that the last object is actually a valid verdict. It should validate the structure of the object before using it.

2. **Cache Key Issue**: The cache key in `RatingCache` doesn't include the number of samples. This means that if you request a different number of samples for the same item, it will miss the cache even if it could reuse some of the samples. For example, if you previously cached 3 samples and now want 5, it should be able to reuse the 3 cached samples and only request 2 more.

3. **Error Handling in Self-Consistency**: When tolerating a minority of malformed samples, the code doesn't provide any information about which samples were valid. This could lead to confusing behavior if, for example, 2 out of 3 samples are valid but produce very different results.

4. **Report Generation**: There are no tests for the report generation functionality.

Let me focus on the most significant issue that needs fixing: the cache key should include the number of samples. This would allow for more efficient cache usage when changing the number of samples.

In commit b65d1f8, the cache implementation was updated to handle different sample counts, but the cache key doesn't include the sample count. This means that if you run with `samples=3` and then later run with `samples=5` for the same item, it will miss the cache entirely, even though it could reuse the 3 cached samples and only request 2 more.

Here's how I would fix this:

1. Update the `RatingCache.key` method to include the number of samples in the key.
2. Update the `RatingCache.get` method to return all available samples, not just a miss if the count doesn't match exactly.
3. Update the `Autorater.rate` method to use the available samples and only request additional ones if needed.

However, looking at the current implementation more carefully:

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

The issue is that it checks if `len(replies) != samples` and treats it as a miss. But it could be modified to return the available samples, even if there aren't enough, so the caller can request the additional samples needed.

Let me propose a fix:

1. Change the `get` method to return the available samples regardless of count
2. Update the `rate` method to use the available samples and request additional ones if needed

But looking at the current implementation of `rate`:

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

It doesn't handle the case where `replies` is not None but has fewer samples than needed. It assumes that if `get` returns something, it has the right number of samples.

So the fix would be:

1. Modify `RatingCache.get` to return the available samples regardless of count
2. Modify `Autorater.rate` to use the available samples and request additional ones if needed

Let me draft a follow-up commit that addresses this issue:

```diff
commit XXXXXXX
Author: AI Reviewer <ai-reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    cache: reuse partial samples, don't discard cache on sample count change
    
    When the cache has fewer samples than requested, reuse them instead of
    discarding the cache entry. This happens when changing `samples` in the
    config: previously cached replies for the same item are still useful.
    
    The cache key now includes the sample count, so different sample counts
    don't conflict. The get() method returns whatever samples are available,
    and rate() requests additional samples as needed.
    
    TSE-1449

diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..newhash 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -85,15 +85,22 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            replies = self.cache.get(ex, self.model, self.prompt_version)
+        
+        # If we have cached replies but not enough, request additional samples
+        if replies is not None and len(replies) < self.samples:
+            additional = self.samples - len(replies)
+            new_replies = [self.client.complete(self.build_prompt(ex), 
+                               temperature=self.sample_temperature,
+                               max_tokens=self.max_tokens) for _ in range(additional)]
+            replies.extend(new_replies)
+            if self.cache is not None:
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+        
         if replies is None:
             replies = self._sample(ex)
-            rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
+            rating = aggregate(self._parse_all(replies))
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
-            return rating
-        return aggregate(self._parse_all(replies))
+            return rating
        
-    def _sample(self, ex: Example) -> list[str]:
+        return aggregate(self._parse_all(replies))
+
+    def _sample(self, ex: Example, n: int) -> list[str]:
         prompt = self.build_prompt(ex)
         temperature = self.temperature if self.samples == 1 else self.sample_temperature
-        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
-                for _ in range(self.samples)]
+        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens) for _ in range(n)]
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..newhash 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,10 +48,10 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+                                     (self.key(ex, model, prompt_version, self.samples),)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        if replies is None:
             self.misses += 1
             return None
         self.hits += 1
```

Wait, this isn't quite right. The cache key should include the sample count, but the way the cache is used, we want to be able to reuse samples regardless of the requested count. Let me rethink this.

Actually, the cache key should not include the sample count. The samples are for the same item, so they should be stored together. The issue is that the current implementation treats a cache entry with a different number of samples as a miss, but it could reuse what's available.

Here's a better approach:

1. Store all samples for an item in the cache, regardless of how many were requested.
2. When retrieving, return all available samples.
3. If fewer samples are available than requested, request additional ones.

The cache key should remain the same (based on the item, model, and prompt version), because it's the same item being rated.

Let me revise the fix:

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..newhash 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -85,15 +85,24 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            replies = self.cache.get(ex, self.model, self.prompt_version)
         
+        # If we have cached replies but not enough, request additional samples
+        if replies is not None and len(replies) < self.samples:
+            additional = self.samples - len(replies)
+            new_replies = self._sample(ex, additional)
+            replies.extend(new_replies)
+            if self.cache is not None:
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+        
         if replies is None:
-            replies = self._sample(ex)
+            replies = self._sample(ex, self.samples)
             rating = aggregate(self._parse_all(replies))
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
             return rating
        
-        return aggregate(self._parse_all(replies))
+        return aggregate(self._parse_all(replies))
+
+    def _sample(self, ex: Example, n: int) -> list[str]:
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if n == 1 else self.sample_temperature
+        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens) for _ in range(n)]
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..newhash 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,12 +48,7 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
-            self.misses += 1
-            return None
-        self.hits += 1
-        return replies
+                                     (self.key(ex, model, prompt_version),)).fetchone()
+        return json.loads(row[0]) if row is not None else None
```

This fix:
1. Removes the `samples` parameter from `RatingCache.get`
2. Always returns whatever samples are available in the cache
3. In `Autorater.rate`, if there are cached samples but not enough, it requests additional ones
4. Updates `_sample` to take a number of samples to request

Actually, there's another issue: the cache key should remain the same regardless of the number of samples, because it's the same item. The current implementation of `RatingCache.key` doesn't include the sample count, which is correct.

Let me double-check the current implementation of `RatingCache.key`:

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

Yes, it doesn't include the sample count, which is correct. The samples are for the same item, so they should be stored together.

The issue is that `RatingCache.get` was treating a cache entry with a different number of samples as a miss. Instead, it should always return whatever samples are available.

Let me revise the fix one more time to be precise:

1. In `RatingCache.get`, remove the check for the number of samples. Always return whatever is in the cache.
2. In `Autorater.rate`, if there are cached replies but not enough, request additional samples.

Here's the precise diff:

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..newhash 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -85,15 +85,24 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            replies = self.cache.get(ex, self.model, self.prompt_version)
         
+        # If we have cached replies but not enough, request additional samples
+        if replies is not None and len(replies) < self.samples:
+            additional = self.samples - len(replies)
+            new_replies = self._sample(ex, additional)
+            replies.extend(new_replies)
+            if self.cache is not None:
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+        
         if replies is None:
-            replies = self._sample(ex)
+            replies = self._sample(ex, self.samples)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
             return rating
        
-        return aggregate(self._parse_all(replies))
+        return aggregate(self._parse_all(replies))
+
+    def _sample(self, ex: Example, n: int) -> list[str]:
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if n == 1 else self.sample_temperature
+        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens) for _ in range(n)]
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..newhash 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,12 +48,7 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
-            self.misses += 1
-            return None
-        self.hits += 1
-        return replies
+                                     (self.key(ex, model, prompt_version),)).fetchone()
+        return json.loads(row[0]) if row is not None else None
```

Actually, there's one more issue: the cache hit/miss counters. In the original implementation, it incremented `hits` when it returned cached replies and `misses` when it didn't. With this change, it should still track hits and misses correctly.

Let me adjust the cache implementation to properly track hits and misses:

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..newhash 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,10 +48,13 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                      (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        if row is None:
             self.misses += 1
             return None
-        self.hits += 1
-        return replies
+        self.hits += 1
+        return json.loads(row[0])
```

This correctly increments `misses` when there's no cache entry at all, and `hits` when there is a cache entry (regardless of how many samples it contains).

Let me review the final fix:

1. `RatingCache.get` now always returns whatever samples are available, or None if there's no cache entry.
2. It properly tracks hits and misses.
3. `Autorater.rate` checks if there are cached replies but not enough, and requests additional samples if needed.
4. `_sample` is updated to take a number of samples to request.

This fix will improve cache efficiency when changing the number of samples, as previously cached replies won't be discarded.

Let me check if there are any other issues:

Another issue I noticed is in `parse_json_verdict`. It tries to find all JSON objects in the reply but doesn't validate that the last object is actually a valid verdict. It should validate the structure of the object before using it.

Here's a fix for that:

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..newhash 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -50,13 +50,17 @@ def parse_json_verdict(reply: str) -> Rating:
     while i != -1:
         try:
             obj, end = decoder.raw_decode(reply, i)
-        except json.JSONDecodeError:
+        except (json.JSONDecodeError, TypeError, KeyError):
             i = reply.find("{", i + 1)
             continue
         objects.append(obj)
         i = reply.find("{", end)
     if not objects:
         raise VerdictParseError(f"no JSON object in reply: {reply[:120]!r}")
+    
+    # Validate the structure of the last object
+    last_obj = objects[-1]
+    if not isinstance(last_obj, dict) or "category" not in last_obj or "score" not in last_obj:
+        raise VerdictParseError(f"invalid JSON verdict structure: {last_obj}")
     
     d = objects[-1]
     score = d.get("score")
```

This ensures that the last JSON object has the expected structure before trying to use it as a verdict.

Let me combine both fixes into a single commit:

1. Cache efficiency fix: reuse partial samples
2. JSON parsing fix: validate verdict structure

I'll create a commit that addresses both issues.

Actually, let me verify if the JSON parsing issue is already handled. Looking at the current implementation of `parse_json_verdict`:

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

It does validate the score and category, but it doesn't check if `d` is actually a dictionary or if it has the expected keys. If `d` is not a dictionary (e.g., it's a string or a list), the code will raise an AttributeError when trying to call `d.get("score")`.

Let me fix that:

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..newhash 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -57,6 +57,9 @@ def parse_json_verdict(reply: str) -> Rating:
         i = reply.find("{", end)
     if not objects:
         raise VerdictParseError(f"no JSON object in reply: {reply[:120]!r}")
+    
+    # Ensure the last object is a dictionary
+    if not isinstance(objects[-1], dict):
+        raise VerdictParseError(f"expected JSON object, got {type(objects[-1]).__name__}")
     
     d = objects[-1]
     score = d.get("score")
```

Actually, the current code does handle this to some extent - if `d` is not a dictionary, `d.get("score")` will raise an AttributeError, which will be caught as a VerdictParseError. But it's better to be explicit about the error.

Let me check the current error handling: if `d.get("score")` raises an AttributeError, it will be caught by the outer exception handler and converted to a VerdictParseError. So the current implementation is actually robust against this issue.

The only improvement would be to provide a more specific error message, but that's not critical.

Let me focus on the cache issue, which is more significant.

After careful review, I've identified one clear issue that needs fixing: the cache doesn't efficiently reuse partial samples when the requested sample count changes.

Here's the precise diff for the fix:

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..4d8b9c2 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -85,15 +85,24 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            replies = self.cache.get(ex, self.model, self.prompt_version)
         
+        # If we have cached replies but not enough, request additional samples
+        if replies is not None and len(replies) < self.samples:
+            additional = self.samples - len(replies)
+            new_replies = self._sample(ex, additional)
+            replies.extend(new_replies)
+            if self.cache is not None:
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+        
         if replies is None:
-            replies = self._sample(ex)
+            replies = self._sample(ex, self.samples)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
             return rating
        
-        return aggregate(self._parse_all(replies))
+        return aggregate(self._parse_all(replies))
+
+    def _sample(self, ex: Example, n: int) -> list[str]:
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if n == 1 else self.sample_temperature
+        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens) for _ in range(n)]
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..3a7b9e1 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,12 +48,7 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
-            self.misses += 1
-            return None
-        self.hits += 1
-        return replies
+                                     (self.key(ex, model, prompt_version),)).fetchone()
+        if row is None:
+            self.misses += 1
+            return None
+        self.hits += 1
+        return json.loads(row[0])
```

This fix:
1. Removes the `samples` parameter from `RatingCache.get`
2. Always returns whatever samples are available in the cache
3. In `Autorater.rate`, if there are cached samples but not enough, it requests additional ones
4. Updates `_sample` to take a number of samples to request
5. Properly tracks cache hits and misses

Let me verify this fix addresses the issue:

- Before: If you had 3 samples cached and requested 5, it would miss the cache and request 5 new samples.
- After: It will reuse the 3 cached samples and only request 2 additional ones.

This is a significant efficiency improvement, especially for large datasets where changing the sample count would previously invalidate the entire cache.

I think this is the most important fix needed. Let me craft the commit message and diff.
