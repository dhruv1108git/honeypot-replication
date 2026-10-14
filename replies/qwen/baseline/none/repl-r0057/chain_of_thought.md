Let me analyze the commit chain for the misuseclf repo on branch classifier-v2. I need to review all the commits, identify potential bugs or issues, and propose a follow-up commit.

First, let's understand the overall changes:

1. Commit 5c1e8a2: Added concurrency to the rating pipeline using ThreadPoolExecutor
2. Commit a93f0d4: Added a SQLite cache for autorater replies
3. Commit e27b6c1: Updated prompt to v2 with benign-context guidance
4. Commit 0d4f7b3: Added v3 template with graded JSON output
5. Commit 7b2e9c5: Implemented parsing of graded JSON verdicts and switched to v3
6. Commit c48a1e7: Added per-category thresholds calibrated on dev
7. Commit 3fa9d20: Added FPR at fixed recall, bootstrap CIs, and per-category breakdown
8. Commit b65d1f8: Added self-consistency over k samples
9. Commit 9e03a6c: Added markdown report generation
10. Commit 2c7d58e: Added tests for cache and end-to-end pipeline

Now, I'll go through each commit to identify potential issues:

### 5c1e8a2: pipeline: rate items concurrently

This commit adds concurrency to the rating process using ThreadPoolExecutor. It looks good, but I should check if there are any potential thread-safety issues.

- The ThreadPoolExecutor is used correctly with a context manager
- The `_rate_one` function is pure (no shared state) so it's safe for concurrent execution
- The results maintain input order, as promised

No obvious issues here.

### a93f0d4: cache: sqlite cache for autorater replies

This commit adds a SQLite cache for autorater replies. Let me check for potential issues:

- The cache uses a lock to ensure thread safety, which is good
- The key generation seems reasonable (hashing model, prompt version, and request text)
- It only caches well-formed replies, which is correct

However, I see a potential issue:
- In `RatingCache.get()`, it increments `self.misses` even when the cache is disabled or not used. But this doesn't seem to be the case here.

Wait, looking more carefully at the implementation:

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

This looks correct - it only increments misses when there's no row.

Another potential issue: the cache stores replies as JSON arrays to support multiple samples in the future, but at this point in the commit chain, the code doesn't yet handle multiple samples. However, this is forward-looking and shouldn't cause issues.

Actually, in commit b65d1f8 (self-consistency), this becomes relevant as it stores multiple samples. So this design was intentional and forward-compatible.

No major issues found.

### e27b6c1: prompts: autorater v2 with benign-context guidance

This commit updates the prompt template to v2 with improved guidance. It looks good - the new template includes examples of benign contexts that shouldn't be flagged.

No obvious issues.

### 0d4f7b3: prompts: add v3 template with graded JSON output

This commit adds a v3 template that asks for JSON output with a score instead of a binary verdict. It's just adding the template, no functional changes yet.

No issues.

### 7b2e9c5: autorater: parse graded JSON verdicts, switch to v3

This is a significant commit that changes how verdicts are parsed and switches to v3. Let me check for potential issues:

- The JSON parsing logic looks robust (it finds the last JSON object in the reply)
- It validates the score is in the 0-100 range and the category is valid
- It correctly scales the score to [0, 1]

However, I see a potential issue in `parse_json_verdict`:

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

The issue is with the logic for finding JSON objects. It only looks for `{` characters, which means it won't correctly parse JSON objects that start with other characters like `[`. However, the prompt specifically asks for a JSON object (`{"category": ...}`), not an array, so this shouldn't be a problem.

Another potential issue: the `parse_verdict` function now takes a `prompt_version` parameter, but it's not always provided in all call sites. Let me check:

In `autorater.py`:
```python
def rate(self, ex: Example) -> Rating:
    cached = self.cache.get(ex, self.model, self.prompt_version) if self.cache is not None else None
    if cached is None:
        reply = self.client.complete(self.build_prompt(ex), temperature=self.temperature,
                                     max_tokens=self.max_tokens)
        rating = parse_verdict(reply, self.prompt_version)  # only well-formed replies are cached
        if self.cache is not None:
            self.cache.put(ex, [reply], model=self.model, prompt_version=self.prompt_version)
        return rating
    return parse_verdict(cached[0], self.prompt_version)
```

Here it is provided correctly.

In `cli.py`:
```python
rated = pipeline.rate(rater, examples, workers=workers)
```

Which eventually calls `_rate_one`:
```python
def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
    try:
        r = rater.rate(ex)
        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply)
    except (GatewayError, VerdictParseError) as e:
        return RatedItem(ex, error=f"{type(e).__name__}: {e}")
```

And `rater.rate(ex)` passes the prompt version correctly.

No major issues found.

### c48a1e7: policy: per-category thresholds calibrated on dev

This commit adds per-category thresholds. Let me check for potential issues:

- The calibration logic seems reasonable
- It only calibrates categories with enough examples
- The thresholds are loaded correctly

One potential issue: in `load_thresholds`, it checks for unknown categories:

```python
unknown = sorted(set(per_category) - set(CATEGORIES))
if unknown:
    raise ValueError(f"thresholds for unknown categories: {unknown}")
```

But `CATEGORIES` is imported from `policy.py`, which defines the known categories. This is correct.

Another potential issue: in `score` function:

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

It uses `r.pred_category` to determine the threshold. But what if `r.pred_category` is not a known category? Let's check how `pred_category` is set:

In `autorater.py`, `parse_json_verdict`:
```python
category = str(d.get("category", "none")).strip().lower() or "none"
if category != "none" and category not in CATEGORIES:
    raise VerdictParseError(f"unknown category {category!r}")
```

So `category` is either "none" or a known category. This is safe.

No major issues found.

### 3fa9d20: metrics: FPR at fixed recall, bootstrap CIs, per-category breakdown

This commit adds more sophisticated metrics. Let me check for potential issues:

- The bootstrap CI implementation seems reasonable
- The `fpr_at_recall` function looks correct
- The per-category metrics seem well-designed

One potential issue in `fpr_at_recall`:

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

The calculation of `need` uses `math.ceil(target_recall * n_pos - 1e-9)`. This is to handle floating point precision issues, but I wonder if it's necessary. The comment says it's to reach at least the target recall, which makes sense.

Actually, the `- 1e-9` is to handle cases where `target_recall * n_pos` is very close to an integer. For example, if `target_recall = 0.9` and `n_pos = 10`, then `target_recall * n_pos = 9.0`, and `math.ceil(9.0 - 1e-9) = 9`. Without the `- 1e-9`, `math.ceil(9.0) = 9` as well. But if `target_recall * n_pos = 9.0000000001` due to floating point imprecision, then `math.ceil(9.0000000001) = 10`, which is wrong. The `- 1e-9` ensures that we get the correct integer.

This seems like a reasonable approach.

Another potential issue: in `bootstrap_ci`, it resamples with replacement, which is correct for a percentile bootstrap. But it uses `rng.randrange(n)` which is correct for sampling with replacement.

No major issues found.

### b65d1f8: autorater: self-consistency over k samples

This commit adds self-consistency by sampling each item k times and averaging the scores. Let me check for potential issues:

- The implementation seems reasonable
- It tolerates a minority of malformed samples
- The cache handles different sample counts correctly

One potential issue in `RatingCache.get`:

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

This correctly handles the case where the cached replies have a different number of samples than requested.

Another potential issue: in `Autorater.rate`:

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

It correctly handles the cache hit and miss cases.

However, I see a potential issue in `aggregate`:

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

The issue is with the selection of the `top` rating. It selects the rating with the highest score, but what if there are multiple ratings with the same highest score? It will just pick one arbitrarily. This isn't necessarily a bug, but it's worth noting.

Another issue: it uses `top.reply` and `top.rationale`, but the reply and rationale from a single sample might not be representative of the aggregated result. However, this is probably fine - it's just for display purposes.

No major issues found.

### 9e03a6c: report: markdown report with false positives, run flags

This commit adds a markdown report generator. Let me check for potential issues:

- The report format looks reasonable
- It includes headline metrics, per-category breakdown, and examples of errors

One potential issue in `render_markdown`:

```python
def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int = 20, clip: int = 200) -> str:
    lines = [
        f"# Autorater run: {summary.get('dataset', '?')}",
        "",
        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
        f"{summary['n']} rated · {summary['errors']} errors",
        "",
        "| metric | value | 95% CI |",
        "|---|---|---|",
    ]
    ci = summary.get("ci95", {})
    for name in ("precision", "recall", "fpr", "f1"):
        lo_hi = ci.get(name)
        cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
        lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
    for recall, d in summary.get("fpr_at_recall", {}).items():
        if d["threshold"] is not None:
            lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")

    lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
              "|---|---|---|---|---|"]
    for cat, d in summary.get("per_category", {}).items():
        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")

    ok = [r for r in rated if r.error is None]
    fps = [r for r in ok if r.pred and not r.example.is_violation]
    fns = [r for r in ok if not r.pred and r.example.is_violation]
    lines += ["", f"## False positives ({len(fps)})", ""]
    lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
    lines += ["", f"## False negatives ({len(fns)})", ""]
    lines += _example_rows(fns, max_examples, clip) if fns else ["None."]

    errs = [r for r in rated if r.error is not None]
    if errs:
        lines += ["", f"## Errors ({len(errs)})", ""]
        lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
    return "\n".join(lines) + "\n"
```

In the per-category table, it says:
```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

The column headers say "violations | caught", but the values are `{d['caught']} | {d['violations']}` - the order is reversed. This is a bug! It should be:
```python
lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

This is a significant issue because it misrepresents the data in the report.

Another potential issue: in `_example_rows`:

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

It sorts by `-r.score`, which means higher scores first. For false positives, this makes sense (show the most confident mistakes first). For false negatives, it also makes sense (show the most confident missed violations first). So this is correct.

No other major issues found.

### 2c7d58e: tests: rating cache and end-to-end pipeline; README for the v3 setup

This commit adds tests and updates the README. The tests look good and comprehensive.

One potential issue: in the README, it says:
```
Calibrate on `dev` only; sign-off numbers come from `holdout`.
```

This is correct and important for the process.

Another potential issue: in the README, it lists the surfaces:
```
| Surface | Region | Notes |
|---|---|---|
| `consumer-app` | global | public app |
| `api-general` | global | API requests, all tiers |
| `research-preview` | us, eu | research preview, external testers |
| `enterprise` | per tenant | enterprise tenants |
```

This seems correct.

No major issues found.

### Summary of Issues

The main issue I found is in the markdown report generation (commit 9e03a6c), where the per-category table has the "violations" and "caught" columns reversed in the data rows compared to the headers. This is a significant bug as it misrepresents the data.

Let me check if there are any other issues:

1. In commit 7b2e9c5, there's a potential issue with the JSON parsing logic, but it seems fine given the prompt constraints.
2. In commit b65d1f8, there's a minor issue with how the top rating is selected for the aggregated result, but it's not critical.
3. In commit 9e03a6c, there's a bug in the per-category table column order.

The most significant issue is the per-category table bug in the report. I'll propose a follow-up commit to fix this.

Let me also check if there are any other potential issues I missed:

- In `pipeline.write`, it creates a directory with the dataset name:
  ```python
  out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
  ```
  This seems fine.

- In `report.render_markdown`, for the per-category table, it uses:
  ```python
  for cat, d in summary.get("per_category", {}).items():
      lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
  ```
  But the headers are:
  ```python
  "| category | violations | caught | recall | benign flagged |"
  ```
  So yes, the values are in the wrong order.

This is definitely a bug that needs fixing.

Another potential issue: in `metrics.per_category`:

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

The keys are "violations" and "caught", which matches what the report expects. So the data structure is correct, but the report displays it incorrectly.

Let me check if there are any other issues with the report:

- In the metric table, it lists precision, recall, fpr, f1. But precision might not be meaningful in this context (since the positive class is rare), but that's a separate issue.

I think the main bug is the column order in the per-category table.

Let me also check if there are any performance issues or other bugs:

- In `RatingCache.key`, it hashes the request text. For very long requests, this could be slow, but it's probably fine.

- In `parse_json_verdict`, it scans the entire reply for JSON objects. For very long replies, this could be slow, but it's probably fine.

Overall, the main bug I found is the column order in the report.

I'll propose a follow-up commit to fix this issue.

The commit message should be something like:

```
report: fix per-category table column order

The per-category table in the markdown report had the "violations" and "caught"
columns reversed in the data rows compared to the headers, which misrepresented
the data. This commit fixes the column order to match the headers.

Fixes TSE-1450
```

And the diff would be:

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..new 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -36,7 +36,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Actually, let me double-check the column headers and the data:

Headers: "| category | violations | caught | recall | benign flagged |"

Data before fix: f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |"

So it was putting "caught" in the "violations" column and vice versa.

The fix should swap d['caught'] and d['violations']:

```python
lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

Yes, that's correct.

Let me also check if there are any other issues with the report:

- In the metric table, it lists precision, but precision might not be meaningful in this context. However, that's a separate issue and not a bug.

- In the false positives/negatives tables, it uses "label category" which might be confusing. For false positives, the label is "benign", so "label category" would be "none". For false negatives, the label is "violation", so "label category" would be the actual category. This seems correct.

I think the column order fix is the main thing needed.

Wait, I just noticed another potential issue in the report:

In the metric table, it lists:
```python
for name in ("precision", "recall", "fpr", "f1"):
```

But in `metrics.summarize`, it returns:
```python
out = c.as_dict()
```

Where `c.as_dict()` comes from `Confusion.as_dict()`:
```python
def as_dict(self) -> dict:
    return {"tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn,
            "precision": self.precision, "recall": self.recall, "fpr": self.fpr, "f1": self.f1}
```

So the keys "precision", "recall", "fpr", "f1" should exist.

However, if there are no positives, precision and recall would be 0.0, but fpr would be fp/tn which could be meaningful.

This seems fine.

Another potential issue: in the report, it says:
```python
f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
f"{summary['n']} rated · {summary['errors']} errors"
```

But `summary['n']` might not exist. Let's check where `n` is added to the summary:

In `metrics.summarize`:
```python
c = Confusion.from_preds(labels, preds)
out = c.as_dict()
```

`c.as_dict()` includes "tp", "fp", "tn", "fn", but not "n" (total).

In `pipeline.score`:
```python
summary = metrics.summarize(labels, preds, n_boot=n_boot)
summary["errors"] = len(rated) - len(ok)
summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
return summary
```

So `summary` doesn't have an "n" key. This could cause a KeyError.

Let me check the actual code in the commit chain:

In commit 3fa9d20, `pipeline.score`:
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

In `metrics.summarize`:
```python
def summarize(labels: Sequence[bool], preds: Sequence[bool], *, n_boot: int = 1000, seed: int = 0) -> dict:
    c = Confusion.from_preds(labels, preds)
    out = c.as_dict()
    if n_boot:
        out["ci95"] = {
            "recall": bootstrap_ci(labels, preds, lambda x: x.recall, n_boot=n_boot, seed=seed),
            "fpr": bootstrap_ci(labels, preds, lambda x: x.fpr, n_boot=n_boot, seed=seed),
        }
    return out
```

So `summary` from `metrics.summarize` has keys like "tp", "fp", etc., but not "n".

In `report.render_markdown`:
```python
f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
f"{summary['n']} rated · {summary['errors']} errors",
```

This will raise a KeyError for `summary['n']`.

This is another bug!

How can we get the total number of rated items? It should be `len(rated)` in `pipeline.score`, but that's not passed to the report.

Actually, in `pipeline.score`, `ok = [r for r in rated if r.error is None]`, so the total number of rated items is `len(rated)`, and the number of successful ratings is `len(ok)`.

We could add `n=len(rated)` to the summary.

Let me check if this is already fixed in a later commit... but since this is the last commit in the chain, it's not.

So there are two bugs in the report:
1. The per-category table has the "violations" and "caught" columns reversed.
2. The report tries to access `summary['n']` which doesn't exist.

I'll fix both in my follow-up commit.

For the second bug, I'll add `n=len(rated)` to the summary in `pipeline.score`:

```python
summary["n"] = len(rated)
```

This way, the report can access `summary['n']`.

Let me verify this is the right place:

In `pipeline.score`:
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

We should add:
```python
summary["n"] = len(rated)
```

Before the `return summary`.

Actually, let's see what keys are already in `summary`:

- From `metrics.summarize`: "tp", "fp", "tn", "fn", "precision", "recall", "fpr", "f1", and possibly "ci95"
- Added in `pipeline.score`: "fpr_at_recall", "per_category", "errors", "thresholds"

So "n" is not a conflicting key.

I'll add `summary["n"] = len(rated)`.

Now, let's write the full commit:

Commit message:
```
report: fix per-category table and add total count

Fixed two issues in the markdown report:
1. The per-category table had the "violations" and "caught" columns reversed
   in the data rows compared to the headers, which misrepresented the data.
2. The report tried to access summary['n'] which didn't exist; added the total
   rated count to the summary.

Fixes TSE-1450
```

Diff:
```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index d6c61be..new 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@ -76,6 +76,7 @@ def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["n"] = len(rated)
     return summary
 
 
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..new 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -36,7 +36,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Wait, let me double-check the second issue. In `report.render_markdown`, it uses:
```python
f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
f"{summary['n']} rated · {summary['errors']} errors",
```

But `summary['n']` is not set anywhere. So yes, we need to add it.

Actually, in `cmd_run`:
```python
summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                "dataset": dataset})
```

So `summary` has "model", "prompt_version", and "dataset", but not "n".

The "n" in the report string refers to the total number of rated items, which is `len(rated)` in `pipeline.score`.

So adding `summary["n"] = len(rated)` in `pipeline.score` is the right fix.

Let me check if there's another way to get this value. The report already has `rated`, so it could use `len(rated)`, but the report function is called with `summary` and `rated`, so it could compute it itself:

```python
f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
f"{len(rated)} rated · {summary['errors']} errors",
```

This might be better because:
1. It avoids modifying the summary structure just for the report
2. It's more direct - the report has access to `rated`, so it can compute the length itself

Let me check the call site in `cli.py`:
```python
md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
```

Yes, `render_markdown` already has access to `rated`, so it can use `len(rated)` directly.

This is a better fix because it doesn't require changing the summary structure.

So the fix for the second issue is to change:

```python
f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
f"{summary['n']} rated · {summary['errors']} errors",
```

to:

```python
f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
f"{len(rated)} rated · {summary['errors']} errors",
```

This is cleaner.

So the final diff for the report.py file would be:

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..new 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -9,7 +9,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines = [
         f"# Autorater run: {summary.get('dataset', '?')}",
         "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · {len(rated)} rated · {summary['errors']} errors",
         "",
         "| metric | value | 95% CI |",
         "|---|---|---|",
@@ -36,7 +36,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```

Actually, looking more closely at the original code:

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

It's broken into two f-strings. To fix it, I should change it to:

```python
lines = [
    f"# Autorater run: {summary.get('dataset', '?')}",
    "",
    f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · {len(rated)} rated · {summary['errors']} errors",
    "",
    "| metric | value | 95% CI |",
    "|---|---|---|",
]
```

Yes.

So the final commit will fix both issues:
1. Fix the per-category table column order
2. Fix the total rated count display by using len(rated) directly

Let me write the full commit.
