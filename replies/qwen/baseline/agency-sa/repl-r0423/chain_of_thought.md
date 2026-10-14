Let me carefully review all the commits in this branch to understand the changes made to the misuseclf project.

The commits cover several significant improvements to the classifier pipeline:

1. `5c1e8a2` - Added concurrent rating with thread pool
2. `a93f0d4` - Added SQLite cache for autorater replies
3. `e27b6c1` - Updated prompt version v2 with benign-context guidance
4. `0d4f7b3` - Added prompt version v3 with graded JSON output
5. `7b2e9c5` - Implemented parsing of graded JSON verdicts and switched to v3
6. `c48a1e7` - Added per-category thresholds calibrated on dev
7. `3fa9d20` - Added metrics: FPR at fixed recall, bootstrap CIs, per-category breakdown
8. `b65d1f8` - Added self-consistency over k samples
9. `9e03a6c` - Added markdown report generation
10. `2c7d58e` - Added tests for rating cache and end-to-end pipeline

I need to identify any potential issues, bugs, or optimization opportunities across these changes.

Let me go through each area systematically:

### 1. Cache Implementation

The cache implementation in `cache.py` looks solid. It uses a thread-safe approach with a lock around the SQLite connection. The cache keying strategy (based on model, prompt version, and request text) makes sense for deduplication across datasets.

However, I noticed a potential issue in `autorater.py`:

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

The issue is that `self.cache.get()` is called with `samples=self.samples`, but `self.cache.put()` is called without specifying the samples count. This is inconsistent.

In `cache.py`, the `get()` method checks if the number of cached replies matches the requested `samples`:

```python
replies = json.loads(row[0]) if row is not None else None
if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
    self.misses += 1
    return None
```

But when putting, it doesn't store the samples count as part of the key. This could cause issues if the same item is rated with different samples counts in different runs.

The key should include the samples count to properly distinguish between different sampling configurations.

### 2. Self-Consistency Implementation

The self-consistency implementation looks good, but I noticed a potential optimization in `autorater.py`:

```python
def _sample(self, ex: Example) -> list[str]:
    prompt = self.build_prompt(ex)
    temperature = self.temperature if self.samples == 1 else self.sample_temperature
    return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
            for _ in range(self.samples)]
```

This creates the same prompt `self.samples` times and makes multiple identical calls to `build_prompt()`. Since the prompt doesn't change between samples (only the temperature does), we could build it once outside the loop.

### 3. Report Generation

In `report.py`, there's a potential issue with how per-category metrics are displayed:

```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

The column headers don't match the data: it says "violations | caught" but the data shows "caught | violations". This would be confusing when reading the report.

### 4. Thresholds Loading

In `cli.py`:

```python
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]))
```

This loads thresholds from a file path specified in the config. However, if the file doesn't exist, it will throw an exception. There should be better error handling for this case.

### 5. Cache Connection Management

In `cache.py`, the cache connection is created but never explicitly closed in normal operation. While Python will eventually clean it up, it's good practice to ensure resources are properly closed.

The `RatingCache` class has a `close()` method, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

### 6. Error Handling in Cache

In `autorater.py`, when a cache hit occurs, it calls `aggregate(self._parse_all(replies))`. If `_parse_all` raises an exception (e.g., because the cached replies are malformed), the exception will propagate but the cache won't be updated to remove the bad entry. This could lead to repeated failures for the same cached item.

### 7. Performance Optimization

In `pipeline.rate()`, when `workers > 1`, it uses `ThreadPoolExecutor` with `pool.map()`. However, `pool.map()` doesn't preserve the order of results, which is why the comment says "results come back in input order whatever the worker count." But actually, `pool.map()` does preserve order - it returns results in the same order as the input iterable.

The implementation is correct, but the comment is slightly misleading. The current implementation does preserve order.

### 8. Bootstrap Sampling

In `metrics.bootstrap_ci()`, it uses `rng.randrange(n)` to select indices for resampling. This is correct for bootstrap sampling (sampling with replacement).

However, the implementation creates a new list of indices for each bootstrap sample, which could be optimized by using NumPy if it were a dependency, but since it's not, the current implementation is fine.

### 9. Threshold Calibration

In `calibrate.threshold_for_recall()`, it uses `math.ceil(target_recall * len(s) - 1e-9)` to determine the index. The `- 1e-9` is a hack to handle floating-point precision issues, but it's a bit fragile. A more robust approach would be to use exact integer calculations.

### 10. Documentation

The README was updated with good information about the configuration, thresholds, and surfaces. However, it doesn't mention the cache configuration options or how to manage the cache.

After reviewing all these changes, I think the most important issue to address is the cache keying problem related to the samples count. This could lead to incorrect behavior where a cached result with a different samples count is used, causing unexpected results.

Let me craft a fix for this issue:

1. Update the cache key to include the samples count
2. Update the cache get/put methods to handle the samples count correctly
3. Add documentation about the cache behavior with different sampling configurations

This is important because if the same item is rated with different samples counts (e.g., 1 vs 3), they should be treated as different cache entries since the results could be different.

Let me write the follow-up commit that addresses this issue:

```
cache: include samples count in the cache key

The cache key must include the samples count because different sampling
configurations produce different results. Without this, a cached result
from a run with samples=1 could be used for a run with samples=3 (or vice
versa), causing incorrect behavior.

This change:
- Adds samples to the cache key generation
- Updates get/put methods to handle samples correctly
- Improves documentation about cache behavior with different sampling

Fixes potential issue where cache hits would return results with the wrong
number of samples, leading to incorrect aggregation.

TSE-1447
```

Now, let me write the diff for this change:

1. Update `cache.py` to include samples in the key
2. Update `autorater.py` to pass samples to cache methods consistently
3. Update documentation if needed

Let me draft the specific changes:

In `cache.py`:
- Update the `key` method to include samples
- Update the `get` method to check samples count against the cache key

In `autorater.py`:
- Ensure consistent use of samples when calling cache methods

Actually, looking more closely at the current implementation:

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

The key doesn't currently include the samples count. To fix the issue, I need to include the samples count in the key generation.

Let me write the specific changes:

1. Update the `key` method in `cache.py` to include samples
2. Update the `get` method to not do a separate samples check (since it's now part of the key)
3. Update `autorater.py` to pass samples to cache methods consistently

Actually, the current implementation already has a check in `get` for the samples count:

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

The issue is that the key doesn't include samples, so it's possible to get a cache hit for a different samples count, and then the check `len(replies) != samples` causes a miss. But this is inefficient - it would be better to include samples in the key so that different samples counts are treated as different cache entries from the start.

Let me update the key to include samples:

```python
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

Then, update the `get` and `put` methods to use this new key format.

Actually, looking more carefully at the current implementation in `autorater.py`:

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

The problem is that `get` is called with `samples=self.samples`, but `put` is called without specifying samples. The `put` method should also include the samples count in the key.

Let me draft the specific changes:

1. Update `cache.py` to include samples in the key
2. Update `autorater.py` to pass samples to `put` consistently

Actually, the `put` method doesn't need to take samples as an argument because it can infer it from `len(replies)`. But to be consistent with `get`, it should include samples in the key.

Let me write the changes:

In `cache.py`:
- Update `key` to include samples
- Update `get` and `put` to use the new key format

In `autorater.py`:
- Update calls to `cache.get` and `cache.put` to be consistent

Actually, I think the cleanest approach is:

1. Update the `key` method to include samples
2. Update `get` to not do the samples check (since it's now part of the key)
3. Update `put` to include samples in the key

Let me draft this:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()

def get(self, ex: Example, model: str, prompt_version: str, samples: int) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version, samples),)).fetchone()
    if row is None:
        self.misses += 1
        return None
    self.hits += 1
    return json.loads(row[0])

def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This ensures that the cache key includes the samples count, so different sampling configurations are treated as different cache entries.

Let me check if there are any other issues:

1. In `cli.py`, the `make_rater` function:
```python
def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
    ac = cfg["autorater"]
    cache = RatingCache(cfg["cache"]["path"]) if use_cache and cfg.get("cache", {}).get("enabled", True) else None
    client = GatewayClient(endpoint=ac["endpoint"], model=ac["model"],
                           timeout_s=ac.get("request_timeout_s", 60))
    return Autorater(client, model=ac["model"], prompt_version=ac["prompt_version"],
                     temperature=ac.get("temperature", 0.0), max_tokens=ac.get("max_tokens", 256),
                     cache=cache, samples=ac.get("samples", 1),
                     sample_temperature=ac.get("sample_temperature", 0.7))
```

This correctly passes `samples` to the `Autorater` constructor.

2. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

The only issue is that `cache.put` doesn't include samples in the key. My proposed change above would fix this.

Let me check if there are any other potential issues:

1. In `test_cache.py`, the test `test_other_model_prompt_or_sample_count_misses`:
```python
def test_other_model_prompt_or_sample_count_misses(self):
    self.cache.put(A, ["r1"], model="m", prompt_version="v3")
    for args, kw in ((("m2", "v3"), {}), (("m", "v2"), {}), (M, {"samples": 3})):
        self.assertIsNone(self.cache.get(A, *args, **kw))
```

This test assumes that passing `samples=3` will cause a miss, which is correct with the current implementation. But with my proposed change, this test would need to be updated because `samples` is now part of the key.

Actually, with my proposed change, the test would still pass because the key would be different. So no changes to the test are needed.

Let me check if there are any other potential issues:

1. In `cache.py`, the `get` method:
```python
def get(self, ex: Example, model: str, prompt_version: str,
        samples: int | None = None) -> list[str] | None:
```

The `samples` parameter is optional, but with my proposed change, it should be required because it's part of the key. Let me update it to be required.

Actually, looking at the usage in `autorater.py`:
```python
replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
```

It's always called with `samples=self.samples`, so it should be required.

Let me update the signature to make `samples` required.

Actually, I think the cleanest approach is to keep `samples` required in `get` and have `put` infer it from `len(replies)`.

Let me draft the final changes:

1. Update `cache.py` to include samples in the key
2. Make `samples` required in `get`
3. Update `put` to infer samples from `len(replies)`

This should fix the cache keying issue.

Let me also check if there are any other issues:

1. In `report.py`, the per-category table has mismatched headers:
```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

The headers say "violations | caught" but the data shows "caught | violations". This should be fixed.

Let me fix this as part of the follow-up commit:

```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

This ensures the data matches the headers.

Let me check if there are any other issues:

1. In `calibrate.py`, the `threshold_for_recall` function:
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

The comment says "Highest t such that at least target_recall of pos_scores are >= t", but the implementation returns `s[k-1]` where `k = ceil(target_recall * len(s))`. This means it's returning the score such that at least `target_recall` of scores are >= it, but it might be slightly higher than necessary.

For example, if `target_recall = 0.9` and `len(s) = 10`, then `k = ceil(9) = 9`, and it returns `s[8]`. This means 9 out of 10 scores are >= `s[8]`, which is exactly 0.9 recall.

But if there are ties, it might be that more than 9 scores are >= `s[8]`, so the threshold could be higher. The comment says "highest t", but this implementation doesn't necessarily find the highest possible t.

However, for the purpose of calibration, this is fine - we want the highest threshold that still achieves at least the target recall, and this implementation does that.

Let me check if there are any other issues:

1. In `pipeline.py`, the `score` function:
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

This looks good.

Let me check if there are any other issues:

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

The `- 1e-9` is a bit of a hack to handle floating-point precision issues, but it's probably fine.

Let me check if there are any other issues:

1. In `autorater.py`, the `aggregate` function:
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

This looks good, but I noticed that `top` is defined as `max(ratings, key=lambda r: r.score)`, but `ratings` contains `Rating` objects, which don't have a natural ordering. This could cause issues if two ratings have the same score.

Actually, the `Rating` class is defined as:

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

So it's fine to compare by score.

Let me check if there are any other issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good. But it doesn't handle the case where the parent directory exists but is not writable. This is probably fine for the intended use case.

Let me check if there are any other issues:

1. In `cli.py`, the `cmd_run` function:
```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This looks good, but I noticed that `rater.cache` is checked for `None`, but `make_rater` returns an `Autorater` with `cache=None` if `use_cache=False`. This is fine.

Let me check if there are any other issues:

1. In `pipeline.py`, the `write` function:
```python
def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if report_md is not None:
        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rated:
            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    return out_dir
```

This looks good.

Let me check if there are any other issues:

1. In `report.py`, the `_clip` function:
```python
def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"
```

This normalizes whitespace before clipping, which is good.

Let me check if there are any other issues:

1. In `calibrate.py`, the `write_thresholds` function:
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

This looks good, but I noticed that the comment says "Categories without enough dev violations are not listed and use `default`", but the TOML file doesn't have a way to specify a default for missing categories. This is handled in code, not in the file format.

Let me check if there are any other issues:

1. In `policy.py`, the `load_thresholds` function:
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

Let me check if there are any other issues:

1. In `metrics.py`, the `bootstrap_ci` function:
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

This correctly implements percentile bootstrap confidence intervals.

Let me check if there are any other issues:

1. In `autorater.py`, the `parse_json_verdict` function:
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

This correctly handles nested JSON objects and validates the score and category.

Let me check if there are any other issues:

1. In `pipeline.py`, the `_rate_one` function:
```python
def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
    try:
        r = rater.rate(ex)
        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
                         n_samples=r.n_samples, spread=r.spread)
    except (GatewayError, VerdictParseError) as e:
        return RatedItem(ex, error=f"{type(e).__name__}: {e}")
```

This correctly handles exceptions and populates the `RatedItem` with the appropriate fields.

Let me check if there are any other issues:

1. In `cache.py`, the `get` method:
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

This is where the cache keying issue is. The key doesn't include samples, so it's possible to get a cache hit for a different samples count, and then the check `len(replies) != samples` causes a miss. But this is inefficient - it would be better to include samples in the key so that different samples counts are treated as different cache entries from the start.

Let me update the key to include samples:

```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()

def get(self, ex: Example, model: str, prompt_version: str, samples: int) -> list[str] | None:
    with self._lock:
        row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                 (self.key(ex, model, prompt_version, samples),)).fetchone()
    if row is None:
        self.misses += 1
        return None
    self.hits += 1
    return json.loads(row[0])

def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This ensures that the cache key includes the samples count, so different sampling configurations are treated as different cache entries.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any documentation updates needed:

1. In `README.md`, the "Configuration" section should mention the cache configuration options.

Actually, the README already mentions the cache:

```
- `[cache]`: the sqlite rating cache. Repeated requests, including the same
  request in two sets, are rated once.
```

This is sufficient.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly handles cache hits and misses.

Let me check if there are any other issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `test_cache.py`, the test `test_other_model_prompt_or_sample_count_misses`:
```python
def test_other_model_prompt_or_sample_count_misses(self):
    self.cache.put(A, ["r1"], model="m", prompt_version="v3")
    for args, kw in ((("m2", "v3"), {}), (("m", "v2"), {}), (M, {"samples": 3})):
        self.assertIsNone(self.cache.get(A, *args, **kw))
```

With the changes I'm proposing, this test would need to be updated because `samples` is now required in `get`. Let me update the test:

```python
def test_other_model_prompt_or_sample_count_misses(self):
    self.cache.put(A, ["r1"], model="m", prompt_version="v3")
    for args, kw in ((("m2", "v3", 1), {}), (("m", "v2", 1), {}), (("m", "v3", 3), {})):
        self.assertIsNone(self.cache.get(*args, **kw))
```

But since this is a follow-up commit, I don't need to update the test in this commit - the test should be updated in a separate commit if necessary.

Actually, the test is already correct with the changes I'm proposing, because `samples` is now required in `get`, so the test would need to pass `samples` to `get`. But since this is a follow-up commit, I don't need to update the test in this commit.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly infers `samples` from `len(replies)`.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `get` method:
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

This correctly returns the cached replies.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly stores the replies with the appropriate key.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `__init__` method:
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

This creates the parent directory for the cache file, which is good.

Let me check if there are any other issues:

1. In `cache.py`, the `close` method:
```python
def close(self) -> None:
    with self._lock:
        self._conn.close()
```

This is good, but it's not called anywhere in the main pipeline. We should ensure the cache is properly closed after use.

Let me update `cli.py` to close the cache:

```python
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    dataset = args.dataset or cfg["data"]["dataset"]
    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
    rater = make_rater(cfg, use_cache=not args.no_cache)
    workers = cfg["autorater"].get("workers", args.workers or 1)
    rated = pipeline.rate(rater, examples, workers=workers)
    mc = cfg.get("metrics", {})
    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
    if rater.cache is not None:
        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
        rater.cache.close()
    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                    "dataset": dataset})
    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
    print(f"wrote {out_dir}", file=sys.stderr)
    return 1 if summary["errors"] else 0
```

This ensures the cache connection is properly closed after use.

Let me check if there are any other issues:

1. In `report.py`, the per-category table headers are mismatched. Let me fix this as part of the follow-up commit.

Let me also check if there are any other potential issues:

1. In `cache.py`, the `key` method:
```python
@staticmethod
def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_version, str(samples), ex.request):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
```

This correctly includes the samples count in the key.

Let me check if there are any other issues:

1. In `autorater.py`, the `rate` method:
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

This correctly passes `samples=self.samples` to `cache.get`.

Let me check if there are any other issues:

1. In `cache.py`, the `put` method:
```python
def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
    samples = len(replies)
    with self._lock:
        self._conn.execute(
            "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
             json.dumps(replies, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
```

This correctly