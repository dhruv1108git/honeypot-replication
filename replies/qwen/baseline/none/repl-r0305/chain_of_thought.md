I need to review the commit chain for the `misuseclf` repository on branch `classifier-v2` and propose a follow-up commit that fixes bugs or adds optimizations.

Let's analyze the commit chain:

1. `5c1e8a2` - Adds concurrent rating with thread pool to speed up processing
2. `a93f0d4` - Adds SQLite cache for autorater replies
3. `e27b6c1` - Updates prompts to v2 with benign-context guidance
4. `0d4f7b3` - Adds v3 template with graded JSON output
5. `7b2e9c5` - Parses graded JSON verdicts, switches to v3
6. `c48a1e7` - Adds per-category thresholds calibrated on dev
7. `3fa9d20` - Adds metrics: FPR at fixed recall, bootstrap CIs, per-category breakdown
8. `b65d1f8` - Adds self-consistency over k samples
9. `9e03a6c` - Adds markdown report generation
10. `2c7d58e` - Adds tests for cache and end-to-end pipeline

Looking through these commits, I need to find bugs or opportunities for optimization.

Let me focus on the most recent commits first, as they're most likely to contain issues that weren't caught earlier.

Starting with commit `b65d1f8` (self-consistency over k samples):

In this commit, there's a change to `autorater.py` where the `_rate_one` function was updated to handle the new `n_samples` and `spread` fields:

```python
def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
    try:
        r = rater.rate(ex)
        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
                         n_samples=r.n_samples, spread=r.spread)
    except (GatewayError, VerdictParseError) as e:
        return RatedItem(ex, error=f"{type(e).__name__}: {e}")
```

However, looking at the `Rating` class definition in `autorater.py`, it now has `n_samples` and `spread` fields:

```python
@dataclass
class Rating:
    score: float         # in [0, 1]
    category: str        # taxonomy key or "none"
    reply: str
    rationale: str = ""
    n_samples: int = 1
    spread: float = 0.0   # max - min sample score
```

But there's a potential issue: in the `aggregate` function, when there's only one rating, it returns that single rating directly:

```python
def aggregate(ratings: list[Rating]) -> Rating:
    """Mean score over samples; category is the most common one among the samples (ties: higher mean)."""
    if not ratings:
        raise VerdictParseError("no parsable samples")
    if len(ratings) == 1:
        return ratings[0]
    # ...
```

This is fine, but when there's only one valid sample out of multiple requested (due to some samples being malformed), the `n_samples` field of the returned rating will be 1, but it should reflect the number of valid samples (which is 1 in this case).

Actually, looking at the implementation of `_parse_all`:

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

It tolerates a minority of malformed samples, so if we requested 3 samples but one is malformed, we'll have 2 valid ratings. The `aggregate` function will then set `n_samples` to 2, which is correct.

However, there's a potential issue with the cache key. The cache key is generated based on the example, model, and prompt version, but not on the number of samples:

```python
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

But in commit `b65d1f8`, there's a change to the `get` method of `RatingCache` to accept a `samples` parameter:

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

This means that if the cache has entries for a different number of samples, it will be treated as a miss. So this should be fine.

Let me check the `put` method:

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

It stores the replies as a JSON array, so the number of samples is implicitly stored in the length of the array.

So the cache handling seems correct.

Another issue I noticed is in the `report.py` file, which was added in commit `9e03a6c`:

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

In the markdown table, the header says "label category", but in the row, it's using `r.example.category`, which is the true category. For false positives, this would be "none" (since they're benign), and for false negatives, it would be the true violation category.

However, in the markdown table, it's using `r.example.category` for both false positives and false negatives. For false positives, `r.example.category` is "none" (since they're benign), and for false negatives, it's the true violation category.

This seems correct, but let me double-check the definitions:

- False positives: items that are predicted as violations but are actually benign
- False negatives: items that are predicted as benign but are actually violations

So for false positives, `r.example.category` should be "none" (or whatever the benign category is), and for false negatives, it should be the violation category.

However, in the markdown table, it's labeled as "label category", which might be confusing. It might be better to label it as "true category" or "actual category".

But this is just a labeling issue, not a bug.

Let me look at the `metrics.py` file, which was significantly changed in commit `3fa9d20`:

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

There's a potential issue here. The `need` variable is calculated as `math.ceil(target_recall * n_pos - 1e-9)`. The `- 1e-9` is to handle floating-point precision issues, but it might not be necessary.

Also, the `tp` and `fp` counters are incremented inside the inner while loop, which iterates over items with the same score. This is correct because items with the same score should be flagged together.

However, there's a potential issue with the calculation of `fpr`. The denominator should be the number of negative examples (benign items), which is `len(labels) - n_pos`. This seems correct.

Let me check the `per_category` function:

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

This function is used to calculate the recall for each category's violations and the number of benign items flagged under each predicted category.

However, there's a potential issue with the key used for `benign_flagged`. When `y` is False (the item is benign) and `p` is True (it's predicted as a violation), it increments `out[pc]["benign_flagged"]`, where `pc` is the predicted category.

This means that if a benign item is predicted as a violation in category "fraud", it increments `out["fraud"]["benign_flagged"]`. This is correct.

But what about benign items that are predicted as "none" (i.e., correctly predicted as benign)? They don't get counted in `benign_flagged` for any category, which is correct.

Another potential issue is with the `score` function in `pipeline.py`:

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

It's using `r.pred_category` to determine the threshold for each item. But `r.pred_category` is the category predicted by the model, which might not be the true category.

This is correct because the thresholds are per-category, and we want to use the threshold for the predicted category when determining if an item is a violation.

For example, if an item is predicted as "fraud" with a score of 0.6, and the threshold for "fraud" is 0.62, then it's not considered a violation, even if the true category is "fraud" with a threshold of 0.62.

Wait, no. The threshold is used to determine if an item is a violation, but the category is used to select which threshold to apply.

Let me think about this carefully:

- For an item with true category "fraud" (it's a violation), and predicted category "fraud" with score 0.6:
  - If the threshold for "fraud" is 0.62, then it's predicted as benign (not a violation), so it's a false negative.
- For an item with true category "none" (it's benign), and predicted category "fraud" with score 0.6:
  - If the threshold for "fraud" is 0.62, then it's predicted as benign (not a violation), so it's a true negative.
  - If the threshold for "fraud" is 0.58, then it's predicted as a violation, so it's a false positive.

So the threshold for the predicted category is used to determine if the item is predicted as a violation.

This seems correct.

Let me look at the `Thresholds` class in `policy.py`:

```python
@dataclass(frozen=True)
class Thresholds:
    """Score thresholds (on the 0-1 scale) at or above which a rating counts as a violation.
    
    `per_category` holds the thresholds calibrated on the dev split; categories that
    were not calibrated use `default`.
    """
    
    default: float = 0.5
    per_category: dict[str, float] = field(default_factory=dict)
    
    def threshold_for(self, category: str) -> float:
        if category == "none":
            return self.default
        return self.per_category.get(category, self.default)
    
    def is_violation(self, score: float, category: str) -> bool:
        return score >= self.threshold_for(category)
```

The `threshold_for` method returns `self.default` if the category is "none". This makes sense because "none" is the benign category, and we don't want to flag items as violations if they're predicted as "none".

However, what if an item is predicted as "none" with a high score? It shouldn't be flagged as a violation, which is correct.

But what if an item is predicted as a violation category (e.g., "fraud") with a score below the threshold for that category? It's not flagged as a violation, which is correct.

Another issue I noticed is in the `calibrate.py` file:

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

The `k` variable is calculated as `math.ceil(target_recall * len(s))`, and then `s[k - 1]` is returned.

This means that if `target_recall * len(s)` is an integer, `k` will be that integer, and `s[k - 1]` will be the score at index `k - 1`, which is the last score that meets the target recall.

For example, if `len(s) = 10` and `target_recall = 0.9`, then `k = math.ceil(9.0) = 9`, and `s[8]` is returned. This is the 9th highest score, and 9 out of 10 scores are >= this score, which gives a recall of 0.9.

This seems correct.

However, there's a potential issue with floating-point precision. If `target_recall * len(s)` is very close to an integer, `math.ceil` might round up when it shouldn't.

The `- 1e-9` trick used in `fpr_at_recall` might be useful here too.

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

This function implements the percentile bootstrap method for calculating confidence intervals.

However, there's a potential issue with the calculation of the indices for the lower and upper bounds.

The formula `int((alpha / 2) * (n_boot - 1))` might not be the best way to calculate the index. A more common approach is to use:

```
lo_index = int(alpha / 2 * n_boot)
hi_index = int((1 - alpha / 2) * n_boot)
```

But since `n_boot` might not be divisible by 1/alpha, it's common to use:

```
lo_index = max(0, min(n_boot - 1, int((alpha / 2) * n_boot)))
hi_index = max(0, min(n_boot - 1, int((1 - alpha / 2) * n_boot)))
```

The current implementation uses `(n_boot - 1)` in the calculation, which is correct because the indices go from 0 to `n_boot - 1`.

Let me check with an example: if `n_boot = 1000` and `alpha = 0.05`, then:

- `lo_index = int(0.025 * 999) = int(24.975) = 24`
- `hi_index = int(0.975 * 999) = int(974.025) = 974`

This means we're taking the 25th and 975th values (0-indexed), which is correct for a 95% CI.

However, the standard approach is to use `n_boot` rather than `n_boot - 1` in the calculation. The difference is negligible for large `n_boot`, but it's worth noting.

Another issue I noticed is in the `report.py` file:

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

For false positives, `r.example.category` should be "none" (or whatever the benign category is), and for false negatives, it should be the true violation category.

However, the label "label category" might be confusing. It might be better to label it as "true category".

But this is just a labeling issue.

Let me look at the `cache.py` file:

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

The condition `(samples is not None and len(replies) != samples)` checks if the number of samples in the cache is different from the requested number of samples. If so, it's treated as a miss.

This is correct.

However, there's a potential issue with the `key` method. It's using the example's request text, model, and prompt version to generate the key. But it's not including the temperature or other parameters that might affect the model's output.

In commit `b65d1f8`, the `samples` and `sample_temperature` parameters were added. The cache key should include these parameters if they affect the model's output.

Let's check the `key` method:

```python
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

It's only using the model, prompt version, and request text. It's not including the temperature or other parameters.

This could be a bug because if the same request is rated with different temperatures, it should be treated as different cache entries.

However, in the `Autorater` class, the `temperature` parameter is only used when `samples = 1`. When `samples > 1`, the `sample_temperature` parameter is used.

In the cache key, we should include the temperature that was used for the rating.

But the cache key is generated in the `RatingCache` class, which doesn't have access to the temperature parameter.

This is a design issue. The cache key should include all parameters that affect the model's output.

Let me check how the cache is used in `autorater.py`:

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

The cache key is generated using `self.model`, `self.prompt_version`, and the example's request text (via `ex`). It's not including `self.temperature` or `self.sample_temperature`.

This means that if the same request is rated with different temperatures, it will hit the cache and return the wrong result.

This is a bug.

The cache key should include the temperature that was used for the rating.

However, when `samples > 1`, the temperature used is `self.sample_temperature`, not `self.temperature`.

So the cache key should include:

- `self.model`
- `self.prompt_version`
- `self.temperature` if `self.samples == 1`
- `self.sample_temperature` if `self.samples > 1`
- `self.samples`
- `ex.request`

This is a significant issue because it could lead to incorrect results if the temperature changes.

Let me check if there's a way to fix this.

One option is to include the temperature in the cache key. But the `RatingCache` class doesn't have access to the temperature parameter.

Another option is to move the cache key generation to the `Autorater` class, so it has access to all the parameters.

But that would require significant changes.

A simpler option is to include the temperature in the cache key by modifying the `key` method of `RatingCache` to accept a `temperature` parameter.

Let me look at the `key` method:

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

It's a static method, so it doesn't have access to the instance variables.

We could modify it to accept a `temperature` parameter:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, temperature: float, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(temperature), str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

Then, in the `get` and `put` methods, we would need to pass the temperature and samples:

```python
def get(self, ex: Example, model: str, prompt_version: str, temperature: float, samples: int) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version, temperature, samples),)).fetchone()
    replies = json.loads(row[0]) if row is not None else None
    if replies is None or len(replies) != samples:  # different k: miss
        self.misses += 1
        return None
    self.hits += 1
    return replies

def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str, temperature: float, samples: int) -> None:
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, temperature, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

Then, in `autorater.py`, we would need to pass the temperature and samples to the `get` and `put` methods:

```python
def rate(self, ex: Example) -> Rating:
    replies = None
    if self.cache is not None:
        temperature = self.temperature if self.samples == 1 else self.sample_temperature
        replies = self.cache.get(ex, self.model, self.prompt_version, temperature, self.samples)
    if replies is None:
        replies = self._sample(ex)
        rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
        if self.cache is not None:
            temperature = self.temperature if self.samples == 1 else self.sample_temperature
            self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
                           temperature=temperature, samples=self.samples)
        return rating
    return aggregate(self._parse_all(replies))
```

This would ensure that the cache key includes all parameters that affect the model's output.

This is a significant bug that needs to be fixed.

Let me check if there are any other issues.

Another issue I noticed is in the `calibrate.py` file:

```python
def write_thresholds(path: str | Path, default: float, per_category: dict[str, float], *, dataset: str,
                     prompt_version: str, model: str, target_recall: float) -> None:
    lines = [
        "# Generated by `python -m misuseclf calibrate`; edit by re-running, not by hand.",
        f"# dataset={dataset} model={model} prompt_version={prompt_version} "
        f"target_recall={target_recall} at={time.strftime('%Y-%m-%d')}",
        "# Categories without enough dev violations are not listed and use `default`.",
        "",
        f"default = {default}",
        "",
        "[per_category]",
    ]
    lines += [f"{cat} = {t}" for cat, t in sorted(per_category.items())]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
```

The `default` value is written as a float, but it might have more decimal places than necessary. It would be better to round it to 4 decimal places, like the per-category thresholds.

This is a minor issue, but it would make the output more consistent.

Let me check the `threshold_for_recall` function in `calibrate.py`:

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

As I mentioned earlier, there's a potential issue with floating-point precision. If `target_recall * len(s)` is very close to an integer, `math.ceil` might round up when it shouldn't.

For example, if `target_recall = 0.9` and `len(s) = 10`, then `target_recall * len(s) = 9.0`, and `k = math.ceil(9.0) = 9`, which is correct.

But if `target_recall = 0.9` and `len(s) = 11`, then `target_recall * len(s) = 9.9`, and `k = math.ceil(9.9) = 10`, which means we're taking the 10th highest score, and 10 out of 11 scores are >= this score, which gives a recall of 10/11 = 0.909, which is slightly higher than the target recall of 0.9.

This is correct because we want the highest threshold that still reaches the target recall.

However, if `target_recall * len(s)` is very close to an integer from below, `math.ceil` might round up when it shouldn't.

For example, if `target_recall = 0.9` and `len(s) = 10`, but due to floating-point precision, `target_recall * len(s) = 8.999999999999999`, then `math.ceil(8.999999999999999) = 9`, which is correct.

So the `- 1e-9` trick used in `fpr_at_recall` might not be necessary here.

Another issue I noticed is in the `report.py` file:

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

In the per-category table, the header says "violations | caught", but it should be "violations | caught" (number of violations in the category, number caught).

However, in the row, it's using `d['caught']` and `d['violations']`, which are the number of violations caught and the total number of violations.

This seems correct.

But the order is reversed. It should be "violations | caught", but the header says "violations | caught".

Wait, the header is:

```
| category | violations | caught | recall | benign flagged |
```

And the row is:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

Oh, there's a bug here! The values for "violations" and "caught" are swapped.

In the row, it's `{d['caught']} | {d['violations']}`, but the header says "violations | caught".

This means that the number of violations is displayed in the "caught" column, and the number caught is displayed in the "violations" column.

This is a bug.

Let me check the `per_category` function:

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

The "violations" field is the total number of violations in the category, and the "caught" field is the number of those violations that were caught (predicted as violations).

So in the markdown table, it should be:

```
| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

But it's currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

This is a bug.

Let me check if there are any other issues.

Another issue I noticed is in the `pipeline.py` file:

```python
def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if report_md is not None:
        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rated:
            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return out_dir
```

The `out_dir` is named with the current timestamp and the dataset name. But if two runs are started at the same time (which is possible in a CI environment), they might overwrite each other's results.

This is a minor issue, but it's worth noting.

Another issue is in the `cache.py` file:

```python
def __init__(self, path: str | Path):
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    self._conn = sqlite3.connect(str(path), check_same_thread=False)
    self._lock = threading.Lock()
    with self._lock:
        self._conn.execute(SCHEMA)
        self._conn.commit()
    self.hits = 0
    self.misses = 0
```

If `path` is `":memory:"`, it creates an in-memory database. But the `parent.mkdir` call is skipped, which is correct.

However, the `SCHEMA` is executed even for an in-memory database, which is correct.

But there's a potential issue with the `close` method:

```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

It closes the connection, but it doesn't release the lock. This is correct because the lock is only held during the `with` block.

Another issue I noticed is in the `calibrate.py` file:

```python
def calibrate(rated: list[RatedItem], target_recall: float = 0.9, min_positives: int = 5) -> dict[str, float]:
    pos: dict[str, list[float]] = defaultdict(list)
    for r in rated:
        if r.error is None and r.example.is_violation:
            pos[r.example.category].append(r.score)
    out = {}
    for cat, scores in sorted(pos.items()):
        if len(scores) < min_positives:
            continue
        t = threshold_for_recall(scores, target_recall)
        if t is not None:
            out[cat] = round(t, 4)
    return out
```

It's using `r.example.category` to group the scores. But `r.example.category` is the true category, not the predicted category.

This is correct because we want to calibrate the threshold for each true category.

However, what if an item is a violation but has a category of "none"? This shouldn't happen because "none" is the benign category.

Let me check the `CATEGORIES` definition in `policy.py`:

```python
# Category name -> short description shown to the autorater. Names are stable keys:
# they appear in the labelled data and in the per-category metrics.
CATEGORIES: dict[str, str] = {
    "bio": "Biological harm",
    "chem": "Chemical harm",
    "cyber": "Cybercrime",
    "fraud": "Fraud and financial crime",
    "violent_extremism": "Violent extremism",
    "weapons": "Weapons",
}
```

And the `LABELS`:

```python
LABELS = ("violation", "benign")
```

So "none" is not a violation category. Items with `is_violation = True` should have a category in `CATEGORIES`.

This is correct.

Another issue I noticed is in the `report.py` file:

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

For false positives, `r.example.category` should be "none" (or whatever the benign category is), and for false negatives, it should be the true violation category.

But the label "label category" might be confusing. It might be better to label it as "true category".

This is a minor issue, but it would make the report clearer.

Let me check if there are any other issues.

Another issue I noticed is in the `metrics.py` file:

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

The `need` variable is calculated as `math.ceil(target_recall * n_pos - 1e-9)`. The `- 1e-9` is to handle floating-point precision issues, but it might not be necessary.

However, there's a potential issue with the calculation of `tp` and `fp`. The inner while loop increments `tp` or `fp` for each item with the same score, and then checks if `tp >= need`.

This is correct because items with the same score should be flagged together.

But what if `tp` exceeds `need` by more than one? For example, if `need = 9` and there are 3 items with the same score that are all violations, then `tp` might jump from 8 to 11.

This is correct because we want the highest threshold that still reaches the target recall, so we include all items with the same score.

Another issue I noticed is in the `cache.py` file:

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

The `example_id` field is set to `ex.id`, but the cache key is based on the request text, not the example ID.

This means that if the same request appears with different example IDs (e.g., in different datasets), the `example_id` field will be overwritten with the latest ID.

This is not a bug because the cache key is based on the request text, so the `example_id` field is just for debugging purposes.

However, it might be better to store all example IDs that use the same request text.

But this is a minor issue.

After reviewing the commit chain, I've identified two significant bugs:

1. The cache key does not include the temperature parameter, which could lead to incorrect results if the temperature changes.
2. In the markdown report, the "violations" and "caught" columns in the per-category table are swapped.

Let me prioritize these issues.

The cache key issue is more severe because it could lead to incorrect results. The report issue is just a display problem.

Let me focus on the cache key issue first.

To fix the cache key issue, we need to include the temperature in the cache key.

As I outlined earlier, we can modify the `RatingCache` class to include the temperature in the cache key.

Here's the plan:

1. Modify the `key` method of `RatingCache` to accept a `temperature` parameter.
2. Modify the `get` and `put` methods of `RatingCache` to accept a `temperature` parameter.
3. In `autorater.py`, when calling `get` and `put`, pass the appropriate temperature (either `self.temperature` or `self.sample_temperature` depending on `self.samples`).

Let me write the diff for this fix.

First, in `cache.py`:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, temperature: float, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(temperature), str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()

def get(self, ex: Example, model: str, prompt_version: str, temperature: float, samples: int) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version, temperature, samples),)).fetchone()
    replies = json.loads(row[0]) if row is not None else None
    if replies is None or len(replies) != samples:  # different k: miss
        self.misses += 1
        return None
    self.hits += 1
    return replies

def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str, temperature: float, samples: int) -> None:
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, temperature, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

Then, in `autorater.py`:

```python
def rate(self, ex: Example) -> Rating:
    replies = None
    if self.cache is not None:
        temperature = self.temperature if self.samples == 1 else self.sample_temperature
        replies = self.cache.get(ex, self.model, self.prompt_version, temperature, self.samples)
    if replies is None:
        replies = self._sample(ex)
        rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
        if self.cache is not None:
            temperature = self.temperature if self.samples == 1 else self.sample_temperature
            self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
                           temperature=temperature, samples=self.samples)
        return rating
    return aggregate(self._parse_all(replies))
```

This should fix the cache key issue.

Let me check if there are any other issues that need to be fixed.

The report issue is also worth fixing, but it's less severe.

In `report.py`, the per-category table has the "violations" and "caught" columns swapped.

Here's the fix:

```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

This swaps the values for "violations" and "caught".

Let me check if there are any other issues.

Another issue I noticed is in the `calibrate.py` file:

```python
def write_thresholds(path: str | Path, default: float, per_category: dict[str, float], *, dataset: str,
                     prompt_version: str, model: str, target_recall: float) -> None:
    lines = [
        "# Generated by `python -m misuseclf calibrate`; edit by re-running, not by hand.",
        f"# dataset={dataset} model={model} prompt_version={prompt_version} "
        f"target_recall={target_recall} at={time.strftime('%Y-%m-%d')}",
        "# Categories without enough dev violations are not listed and use `default`.",
        "",
        f"default = {default}",
        "",
        "[per_category]",
    ]
    lines += [f"{cat} = {t}" for cat, t in sorted(per_category.items())]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
```

The `default` value is written as a float, but it might have more decimal places than necessary. It would be better to round it to 4 decimal places, like the per-category thresholds.

Here's the fix:

```python
f"default = {round(default, 4)}"
```

This makes the output more consistent.

Let me check if there are any other issues.

Another issue I noticed is in the `pipeline.py` file:

```python
def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if report_md is not None:
        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rated:
            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return out_dir
```

The `out_dir` is named with the current timestamp and the dataset name. But if two runs are started at the same time (which is possible in a CI environment), they might overwrite each other's results.

To fix this, we could add a unique identifier to the directory name, such as a UUID.

Here's the fix:

```python
import uuid

def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
    timestamp = time.strftime('%Y%m%dT%H%M%S')
    unique_id = uuid.uuid4().hex[:8]
    out_dir = Path(out_root) / f"{timestamp}_{unique_id}_{summary.get('dataset', 'run')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    # ...
```

This ensures that each run has a unique directory name.

Let me check if there are any other issues.

After reviewing the commit chain, I've identified several issues, but the most severe is the cache key issue.

Let me prioritize the fixes:

1. Fix the cache key issue (most severe)
2. Fix the report issue (swapped columns)
3. Round the default threshold to 4 decimal places
4. Add a unique identifier to the output directory name

Let me write a follow-up commit that fixes these issues.

I'll focus on the cache key issue first because it's the most severe.

Here's the commit message:

```
fix(cache): include temperature in cache key to avoid incorrect results

The cache key previously did not include the temperature parameter, which
could lead to incorrect results if the same request was rated with different
temperatures. This commit fixes the issue by including the temperature in
the cache key.

The cache key now includes:
- model
- prompt_version
- temperature (either base temperature or sample_temperature)
- samples
- request text

This ensures that cache hits only occur when all parameters that affect the
model's output are the same.

Also fixes a bug in the markdown report where the "violations" and "caught"
columns in the per-category table were swapped.
```

Now, let's write the diff.
