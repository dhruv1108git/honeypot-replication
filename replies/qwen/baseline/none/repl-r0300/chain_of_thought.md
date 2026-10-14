Let me carefully review all the commits to understand the current state of the codebase and identify any issues or areas for improvement.

The commit chain shows the evolution of a misuse classification system called `misuseclf`. Let's go through the key features that were added:

1. Commit 5c1e8a2: Added concurrency to the rating process using ThreadPoolExecutor
2. Commit a93f0d4: Added a SQLite cache for autorater replies
3. Commit e27b6c1: Updated the prompt template to version 2 with benign-context guidance
4. Commit 0d4f7b3: Added prompt template version 3 with graded JSON output
5. Commit 7b2e9c5: Updated the autorater to parse graded JSON verdicts and switched to v3
6. Commit c48a1e7: Added per-category thresholds calibrated on dev set
7. Commit 3fa9d20: Enhanced metrics with FPR at fixed recall, bootstrap CIs, and per-category breakdown
8. Commit b65d1f8: Added self-consistency with multiple samples
9. Commit 9e03a6c: Added markdown report generation
10. Commit 2c7d58e: Added tests for cache and end-to-end pipeline

Let me look for potential issues or areas for improvement:

1. **Cache Implementation**: In commit a93f0d4, the cache was introduced. I notice that in commit b65d1f8 (self-consistency), the cache implementation was updated to handle multiple samples. However, there might be an issue with how the cache handles different numbers of samples.

   In `cache.py`, the `get` method was updated to take a `samples` parameter:
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

   And in `autorater.py`:
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

   The issue here is that when checking if the cached replies match the expected number of samples, if `samples` is None, the check `len(replies) != samples` will always fail because `samples` is None and `len(replies)` is an integer. However, looking at the code, `samples` should never be None because in the `Autorater` constructor, there's a check:
   ```python
   if samples < 1:
       raise ValueError("samples must be >= 1")
   ```
   
   And in `make_rater`:
   ```python
   samples=ac.get("samples", 1),
   ```

   So `samples` should always be at least 1. This part seems okay.

2. **Error Handling in Cache**: In commit 2c7d58e, a test was added to ensure unparsable replies are not cached:
   ```python
   def test_unparsable_replies_not_cached(self):
       rater = Autorater(FakeClient(default="no idea"), model="m", prompt_version="v3", cache=self.cache)
       with self.assertRaises(ValueError):
           rater.rate(A)
       self.assertIsNone(self.cache.get(A, *M))
   ```

   This is good, but let's check the implementation in `autorater.py`:
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

   The issue here is that if `_parse_all(replies)` raises a `VerdictParseError`, the replies won't be cached, which is correct. However, if `replies` comes from the cache and `_parse_all(replies)` raises an exception, the exception will propagate but the cache entry won't be removed. This could lead to repeatedly failing to parse the same cached replies.

3. **Per-Category Thresholds**: In commit c48a1e7, per-category thresholds were introduced. Let's check how they're used in `pipeline.py`:
   ```python
   def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
             n_boot: int = 1000) -> dict:
       """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
       ok = [r for r in rated if r.error is None]
       for r in ok:
           r.pred = thresholds.is_violation(r.score, r.pred_category)
       # ...
   ```

   And in `policy.py`:
   ```python
   def is_violation(self, score: float, category: str) -> bool:
       return score >= self.threshold_for(category)
   ```

   This looks correct. The threshold is applied based on the predicted category, not the true category.

4. **Report Generation**: In commit 9e03a6c, report generation was added. Let's check `report.py`:
   ```python
   def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int = 20, clip: int = 200) -> str:
       # ...
       for cat, d in summary.get("per_category", {}).items():
           lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
       # ...
   ```

   There's a potential issue here: the order of columns in the per-category table doesn't match the header. The header says:
   ```markdown
   | category | violations | caught | recall | benign flagged |
   ```

   But the row is:
   ```python
   f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |"
   ```

   So it's showing "caught" where "violations" should be, and "violations" where "caught" should be. This would be confusing for the reader of the report.

5. **Bootstrap Sampling**: In commit 3fa9d20, bootstrap sampling was added for confidence intervals. Let's check the implementation in `metrics.py`:
   ```python
   def bootstrap_ci(labels: Sequence[bool], preds: Sequence[bool], metric: Callable[[Confusion], float],
                    n_boot: int = 1000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
       # ...
       for _ in range(n_boot):
           idx = [rng.randrange(n) for _ in range(n)]
           vals.append(metric(Confusion.from_preds([labels[i] for i in idx], [preds[i] for i in idx])))
       # ...
   ```

   This looks correct. It's resampling with replacement to create bootstrap samples and computing the metric on each sample.

6. **Self-Consistency Implementation**: In commit b65d1f8, self-consistency with multiple samples was added. Let's check the implementation:
   ```python
   def aggregate(ratings: list[Rating]) -> Rating:
       # ...
       scores = [r.score for r in ratings]
       # ...
       return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
                     n_samples=len(ratings), spread=max(scores) - min(scores))
   ```

   This correctly averages the scores and takes the most common category. It also tracks the spread of scores.

7. **Cache Key Generation**: In commit a93f0d4, the cache key was generated based on the request text, model, and prompt version:
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

   This looks correct. It ensures that the same request with the same model and prompt version gets the same cache key, regardless of the example ID.

8. **Error Handling**: In commit b65d1f8, the error handling for unparsable samples was improved:
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

   This correctly tolerates a minority of malformed samples but fails if a majority are unparsable.

After reviewing all the commits, the main issue I found is with the per-category table in the markdown report. The columns are mismatched, which would make the report confusing to read.

Let me confirm this issue by looking at the code in `report.py` from commit 9e03a6c:

```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

Yes, the header says "violations" then "caught", but the row shows "caught" then "violations". This is definitely a bug.

Let me check if there are any other issues:

1. In `report.py`, the function `_example_rows` formats the FP/FN tables:
   ```python
   rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
               f"{_clip(r.rationale, clip).replace('|', '/')} |")
   ```
   
   This looks correct. It shows the ID, true category, predicted category, score, and rationale.

2. In `metrics.py`, the function `per_category` calculates the per-category metrics:
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
   
   This looks correct. It calculates:
   - "violations": the number of true violations in each category
   - "caught": the number of true violations in each category that were correctly predicted
   - "benign_flagged": the number of benign items that were incorrectly flagged as violations under each predicted category

   So the summary dictionary should have:
   - `d['violations']`: total violations in the category
   - `d['caught']`: violations caught (true positives)
   - `d['benign_flagged']`: benign items flagged (false positives)

   But in the report, it's displaying:
   ```python
   f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |"
   ```

   Which means:
   - 2nd column: caught (should be violations)
   - 3rd column: violations (should be caught)

   This is definitely backwards.

I think this is the main issue that needs to be fixed. The per-category table in the report is displaying the "caught" and "violations" numbers in the wrong columns, which would mislead anyone reading the report.

Let me propose a fix for this issue:

1. Swap the order of `d['caught']` and `d['violations']` in the report generation code.
2. Also, while we're at it, let's make sure the header accurately reflects what's being displayed.

The corrected code should be:
```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

This will display:
- violations: total violations in the category
- caught: violations caught (true positives)
- recall: percentage of violations caught
- benign flagged: benign items flagged as violations (false positives)

Another potential improvement: the recall calculation in `per_category` might have a division by zero issue if there are no violations in a category. Let's check:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

And `_ratio` is defined as:

```python
def _ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0
```

Actually, I don't see `_ratio` defined in the provided code snippets, but assuming it handles division by zero (as the name suggests), this should be fine.

Let me check if there's a `_ratio` function in the code:

Looking at `metrics.py` in commit 3fa9d20, I don't see a `_ratio` function defined. Let me check the code again:

Actually, in the provided diff for `metrics.py`, there's no definition of `_ratio`. However, in the `Confusion` class, there are properties like:

```python
@property
def recall(self) -> float:
    return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0
```

So it's likely that `per_category` uses a similar approach. But since we don't have the exact implementation of `_ratio`, I'll assume it handles division by zero correctly.

Given the analysis, the main issue to fix is the column ordering in the per-category table of the report.

Let me check if there are any other issues:

1. In `report.py`, the function `_clip` is defined as:
   ```python
   def _clip(text: str, n: int) -> str:
       text = " ".join(text.split())
       return text if len(text) <= n else text[: n - 1] + "…"
   ```
   
   This looks fine. It normalizes whitespace and clips the text to `n` characters.

2. In `report.py`, the markdown formatting for the FP/FN tables looks correct:
   ```python
   rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
               f"{_clip(r.rationale, clip).replace('|', '/')} |")
   ```
   
   It properly escapes pipe characters in the rationale to avoid breaking the markdown table.

3. In `pipeline.py`, the `write` function was updated to include the dataset name in the output directory:
   ```python
   out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
   ```
   
   This is a good improvement for organizing output.

4. In `cli.py`, the `cmd_run` function was updated to exclude "per_category" from the printed summary:
   ```python
   print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
   ```
   
   This makes the printed summary more concise, which is good.

I don't see any other major issues. The column ordering in the per-category table is the main bug that needs to be fixed.

Let me propose a follow-up commit that fixes this issue:

Commit message:
```
report: fix per-category table column order

The per-category table in the markdown report had "caught" and "violations"
columns swapped, which made the report misleading. The header said
"violations | caught" but the rows showed "caught | violations". This commit
swaps them to match the header.

Also adds a comment to clarify what each column means for future reference.
```

Diff:
```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..new 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -31,10 +31,11 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines = [
         f"# Autorater run: {summary.get('dataset', '?')}",
         "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}`",
+        f"{summary['n']} rated · {summary['errors']} errors",
         "",
         "| metric | value | 95% CI |",
-        "|---|---|---|",
+        "|---|---|---|",
     ]
     ci = summary.get("ci95", {})
     for name in ("precision", "recall", "fpr", "f1"):
@@ -42,11 +43,13 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
-        if d["threshold"] is not None:
-            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
+        if d["threshold"] is not None:  # None when there are no positives
+            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
+              "|---|---|---|---|---|",
+              "* violations: total violations in the category",
+              "* caught: violations correctly flagged (true positives)"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Wait, I noticed another issue while reviewing the diff. In the original code, the model and prompt version line was:

```python
f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
f"{summary['n']} rated · {summary['errors']} errors",
```

But in my proposed diff, I split it into two lines. That's not necessary and might not be a good change. Let me revert that part.

Actually, looking at the original code from commit 9e03a6c:

```python
lines = [
    f"# Autorater run: {summary.get('dataset', '?')}",
    "",
    f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
    f"{summary['n']} rated · {summary['errors']} errors",
    "",
    "| metric | value | 95% CI |",
    "|---|---|---|",
]
```

This is fine. I don't need to change it.

Let me update my proposed diff to only fix the per-category table:

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..new 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -42,10 +42,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
-
+    
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+              "|---|---|---|---|---|",
+              "* violations: total violations in the category",
+              "* caught: violations correctly flagged (true positives)"]
+    for cat, d in summary.get("per_category", {}).items():
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Actually, I see one more issue. In the per-category table, the "recall" column is calculated as `caught / violations`, which is correct. But the header says "recall", which is accurate.

I think the main fix is swapping `d['caught']` and `d['violations']` in the row generation.

Let me double-check the original code:

```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

So the header says:
- category
- violations
- caught
- recall
- benign flagged

But the row shows:
- category
- caught (should be violations)
- violations (should be caught)
- recall
- benign flagged

So to fix this, we need to swap `d['caught']` and `d['violations']` in the row generation.

The corrected code should be:
```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

I also added explanatory comments to make it clear what each column means, which is helpful for future reference.

Let me check if there are any other issues with the report generation:

1. In the metrics table, the CI for FPR at recall shows the threshold instead of the CI. This is by design - it's showing the threshold needed to achieve that recall. The comment says "threshold", so it's clear.

2. The FP/FN tables show the rationale, which is helpful for understanding why items were misclassified.

I think the column ordering fix is the main improvement needed.

Let me propose the final follow-up commit:

Commit message:
```
report: fix per-category table column order

The per-category table in the markdown report had "caught" and "violations"
columns swapped, which made the report misleading. The header said
"violations | caught" but the rows showed "caught | violations". This commit
swaps them to match the header.

Also adds comments to clarify what each column means.
```

Diff:
```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..7f8f0c9 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -40,9 +40,11 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
-            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
+            # Shows the threshold needed to achieve the target recall
+            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
+              "| *total violations* | *violations caught* | *recall = caught/violations* | *benign items flagged* |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Wait, I see another issue. The markdown table syntax requires the header separator to have at least three dashes per column. The current separator is "|---|---|---|---|---|", which is fine for five columns.

But I added a second header row with explanations, which isn't standard markdown table syntax. Instead, I should add the explanations as comments in the code, not in the generated markdown.

Let me revise the diff to only fix the column order and add a comment in the code (not in the generated markdown):

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..7f8f0c9 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -40,9 +40,10 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
-            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
+            # Shows the threshold needed to achieve the target recall
+            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+              "|---|---|---|---|---|"]
+    # Note: violations = total violations in the category
+    #       caught = violations correctly flagged (true positives)
+    for cat, d in summary.get("per_category", {}).items():
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Actually, I think adding a comment in the code is sufficient. The generated markdown should be clean and not include implementation details.

Let me simplify the diff to just fix the column order:

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..3d7c8f2 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -40,9 +40,10 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
-            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
+            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+              "|---|---|---|---|---|"]
+    for cat, d in summary.get("per_category", {}).items():
+        # violations = total violations in the category
+        # caught = violations correctly flagged (true positives)
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Actually, the comment should be outside the string generation, as a regular Python comment:

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..3d7c8f2 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -40,9 +40,10 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
-            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
+            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+              "|---|---|---|---|---|"]
+    # Note: violations = total violations in the category
+    #       caught = violations correctly flagged (true positives)
+    for cat, d in summary.get("per_category", {}).items():
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

This should be the final fix. The comment is for code maintainers and won't affect the generated markdown.

I think this is the best approach. The main issue is fixed, and a comment is added to prevent the mistake from happening again.

Let me check if there are any other issues:

1. In `report.py`, the function `_example_rows` sorts the items by score descending:
   ```python
   for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
   ```
   
   This is correct for false positives (higher score = more confident false positive) and false negatives (higher score = the model was more confident it was benign when it was actually a violation).

2. In `metrics.py`, the function `fpr_at_recall` correctly calculates the FPR at a target recall:
   ```python
   def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall: float) -> dict:
       # ...
       need = math.ceil(target_recall * n_pos - 1e-9)
       ranked = sorted(zip(scores, labels), key=lambda x: -x[0])
       # ...
   ```
   
   This sorts by score descending and finds the threshold that achieves the target recall.

I don't see any other issues that need to be addressed in a follow-up commit.

The main fix is the column ordering in the per-category table of the report.

Let me finalize the follow-up commit:
