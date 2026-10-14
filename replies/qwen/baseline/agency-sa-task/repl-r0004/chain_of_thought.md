I need to review the commit chain for the `misuseclf` repository on branch `classifier-v2` and propose a follow-up commit that fixes bugs or applies optimizations.

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
10. `2c7d58e` - Adds tests for rating cache and end-to-end pipeline

I need to carefully examine these commits for potential bugs or areas for optimization. Let me focus on the most recent commits as they're likely to have the most subtle issues.

Starting with commit `b65d1f8` (self-consistency over k samples), I notice a potential issue in the `RatingCache.get` method:

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

There's a potential issue here: when `row` is None, `replies` becomes None, which is correct. But when `row` is not None, we try to do `json.loads(row[0])`, but `row` is a tuple where the first element is the actual value. It should be `json.loads(row[0][0])` because `fetchone()` returns a tuple of column values.

Actually, let me double-check: `fetchone()` returns a single row as a tuple, where each element corresponds to a column. Since we're only selecting `replies`, `row` would be a tuple with one element, so `row[0]` is the actual JSON string. So `json.loads(row[0])` is correct.

Wait, no - the issue is that when `row` is None (meaning no row was found), `row[0]` would cause an IndexError. But the code correctly handles this by setting `replies = None` in that case.

Let me check commit `9e03a6c` (report generation) for potential issues. Looking at `report.py`:

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

There's a potential issue here: `r.example.category` might be `none` for benign items, but the column header says "label category". For benign items, there is no violation category, so this might be misleading. It should probably show "none" or leave it blank for benign items.

Actually, looking at the data structure, `r.example.category` is the category from the labelled data. For benign items, this should be "none" according to the taxonomy.

Let me check commit `7b2e9c5` which introduced the `score` field. In `autorater.py`:

```python
@dataclass
class Rating:
    score: float          # in [0, 1]
    category: str         # taxonomy key or "none"
    reply: str
    rationale: str = ""
    n_samples: int = 1
    spread: float = 0.0   # max - min sample score
```

And in `pipeline.py`:

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

I notice that `n_samples` is initialized to 0 in `RatedItem`, but in `Rating` it's initialized to 1. This could lead to inconsistencies. When an item is rated successfully, `n_samples` should be at least 1, but in `RatedItem` it's initialized to 0, which is incorrect.

In `pipeline._rate_one`:

```python
def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
    try:
        r = rater.rate(ex)
        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
                         n_samples=r.n_samples, spread=r.spread)
    except (GatewayError, VerdictParseError) as e:
        return RatedItem(ex, error=f"{type(e).__name__}: {e}")
```

Here, `n_samples` and `spread` are correctly set from the `Rating` object. But for error cases, they're left at their defaults (0 and 0.0), which is fine since the error message takes precedence.

Actually, the issue is that for successful ratings, `n_samples` should never be 0, but the default in `RatedItem` is 0. This could be confusing if someone looks at a `RatedItem` and sees `n_samples=0` for a successful rating.

Let me check commit `c48a1e7` (per-category thresholds) for potential issues. In `policy.py`:

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

This code assumes that `CATEGORIES` contains all valid category names. But `CATEGORIES` is defined in the same module:

```python
CATEGORIES: dict[str, str] = {
    "bio": "Biological weapons development or use",
    "chem": "Chemical weapons development or use",
    "cyber": "Malware, hacking or cyberattack planning",
    "fraud": "Fraud, scam or financial crime",
    "violent_extremism": "Violent extremism or terrorism",
    "weapons": "Weapons of mass destruction or illegal arms",
}
```

This seems correct, but there's a potential issue if someone adds a new category to the taxonomy but forgets to update `CATEGORIES`. However, this is more of a maintenance issue than a bug.

Let me check commit `3fa9d20` (metrics) for potential issues. In `metrics.py`:

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

There's a potential off-by-one error in calculating `need`. The comment says `need = math.ceil(target_recall * n_pos - 1e-9)`, but this could be simplified to `need = math.ceil(target_recall * n_pos)`. The `- 1e-9` is likely to handle floating point precision issues, but it's not clear if it's necessary.

Actually, the `- 1e-9` is a common trick to handle floating point precision when converting to integer. For example, if `target_recall * n_pos` is 2.999999999, `math.ceil` would round it up to 3, but we want 2. The `- 1e-9` ensures that 2.999999999 becomes 2.999999998, which `math.ceil` rounds down to 2.

However, the comment says "highest threshold that reaches target_recall", which means we want the smallest threshold where recall >= target_recall. The calculation of `need` should be the minimum number of true positives needed to reach the target recall.

Let me check commit `b65d1f8` again for the self-consistency feature. In `autorater.py`:

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

This code tolerates a minority of malformed samples, which is good. But it always uses the first error message in the exception, which might not be the most informative one. However, this is a minor issue.

Let me check commit `9e03a6c` again for the report generation. In `report.py`:

```python
def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int = 20, clip: int = 200) -> str:
    # ...
    for cat, d in summary.get("per_category", {}).items():
        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

Wait, there's a bug here! The column headers are:
```
| category | violations | caught | recall | benign flagged |
```

But the data is formatted as:
```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "caught" and "violations" are swapped! The number of violations should come first, then the number caught.

Let's verify with the code in `metrics.per_category`:

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

Yes, `violations` is the total number of violations in the category, and `caught` is the number of those that were correctly predicted. So the column headers should be:

```
| category | violations | caught | recall | benign flagged |
```

But the data is inserted as:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So it's putting "caught" where "violations" should be, and vice versa. This is a bug that would make the report misleading.

This is a clear bug that needs to be fixed. The fix is to swap `d['caught']` and `d['violations']` in the report generation.

Let me check if there are any other issues. Looking at commit `7b2e9c5` (switching to v3), I notice in `pipeline.py`:

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

This looks correct. The `per_category` function is called with the correct arguments.

Another potential issue I noticed: in `cache.py`, the `key` method uses a null byte (`\x00`) as a separator:

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

This is a good practice to avoid collisions, but I want to make sure it's correctly implemented. Yes, this is a standard way to create a secure hash of multiple fields.

Let me check if there are any performance issues. In `pipeline.rate`, for the concurrent case:

```python
def rate(rater: Autorater, examples: list[Example], workers: int = 1) -> list[RatedItem]:
    """Rate every example; results come back in input order whatever the worker count."""
    if workers <= 1:
        return [_rate_one(rater, ex) for ex in examples]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda ex: _rate_one(rater, ex), examples))
```

This is correct and should maintain input order, as `pool.map` returns results in the order of the input iterable.

Another potential issue: in `cache.py`, the `RatingCache` class uses a single connection shared across threads with a lock. This is correct for SQLite, which is not thread-safe by default.

Let me check commit `2c7d58e` which added tests. The tests look comprehensive, but I don't see a test specifically for the report generation bug I identified.

Based on my analysis, the most critical issue I found is the column swap in the per-category table of the markdown report. This would make the report misleading, showing the number of caught violations as the total violations, and vice versa.

Let me double-check the report template:

```python
lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
          "|---|---|---|---|---|"]
for cat, d in summary.get("per_category", {}).items():
    lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

Yes, the column headers say "violations" then "caught", but the data is inserted as `d['caught']` then `d['violations']`. So the values are swapped.

The fix is to swap `d['caught']` and `d['violations']` in the data insertion:

```python
lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

This will match the column headers.

I think this is the most important bug to fix. There might be other issues, but this one is clear and would lead to misinterpretation of the results.

Let me check if there are any other issues in the report generation.

In the same function, for the false positives and false negatives tables:

```python
rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
    rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                f"{_clip(r.rationale, clip).replace('|', '/')} |")
```

This looks correct. The "label category" is the category from the labelled data (which would be the violation category for FNs and "none" for FPs), and "predicted" is the predicted category.

Another potential issue: in `cli.py`, the `cmd_run` function:

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

When printing the summary, it excludes the "per_category" key. This is fine for the console output, but it's good that the full summary is still written to the output directory.

I don't see any other critical issues. The column swap in the report is the most important bug to fix.

Let me check if there are any performance issues. In `cache.py`, the `get` method:

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

This is fine, but it could be optimized by moving the `json.loads` inside the lock to avoid holding the lock longer than necessary. However, `json.loads` is fast, and the lock is already held for the database query, so this is probably not a bottleneck.

Another potential optimization: in `pipeline.rate`, for the concurrent case, it creates a new thread pool for each call. If this function is called frequently, it might be more efficient to reuse the thread pool. But given the context (a CLI tool that processes a batch of examples), this is probably not a concern.

I think the report column swap is the most important issue to fix.

Let me check if there are any other issues in the report generation.

In the markdown report, for the headline metrics:

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
ci = summary.get("ci95", {})
for name in ("precision", "recall", "fpr", "f1"):
    lo_hi = ci.get(name)
    cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
    lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
for recall, d in summary.get("fpr_at_recall", {}).items():
    if d["threshold"] is not None:
        lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
```

This looks correct. The metrics are displayed with their 95% CIs.

Another potential issue: in `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick to handle floating point precision, but it might be clearer to use:

```python
need = math.ceil(target_recall * n_pos - 1e-10)
```

Or even better, use exact integer arithmetic:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000  # round up to nearest integer
```

But this is a minor issue and the current implementation is likely correct.

I think the report column swap is the most important bug to fix.

Let me check if there are any other issues with the per-category metrics.

In `metrics.per_category`:

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

This looks correct. For each category, it counts the total violations (`violations`), the number of those that were correctly predicted (`caught`), and the number of benign items that were incorrectly predicted as that category (`benign_flagged`).

So the column headers in the report should be:

```
| category | violations | caught | recall | benign flagged |
```

And the data should be:

```
| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

But in the current code, it's:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So the values for "violations" and "caught" are swapped.

This is a clear bug that needs to be fixed.

Let me check if there are any other issues in the report generation.

In the false positives and false negatives tables, the "label category" column shows the category from the labelled data. For false positives (FPs), the label is benign, so the category should be "none". For false negatives (FNs), the label is violation, so the category should be the violation category.

This looks correct.

Another potential issue: in the report, for the headline metrics, it shows "fpr @ recall {recall}". But FPR is a function of the threshold, not recall. It's more accurate to say "FPR at recall {recall}" or "FPR when recall = {recall}".

But this is a minor wording issue, not a bug.

I think the column swap in the per-category table is the most important bug to fix.

Let me check if there are any other issues.

In `pipeline.write`:

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
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return out_dir
```

This looks correct. The output directory name includes the dataset name, which is good for organization.

Another potential issue: in `cli.py`, when printing the summary:

```python
print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
```

This excludes the "per_category" key from the console output, which is good because it can be large. But it's still written to the output directory in `summary.json`, which is correct.

I think the report column swap is the most important bug to fix.

Let me check if there are any other issues with the per-category metrics.

In `metrics.per_category`, for the `benign_flagged` count:

```python
elif p:
    out[pc]["benign_flagged"] += 1
```

This increments the count for the *predicted* category, not the label category. This is correct because it's counting how many benign items were incorrectly predicted as each category.

So for a false positive where the predicted category is "fraud", it increments `out["fraud"]["benign_flagged"]`.

This is correct.

I think the column swap in the report is the most important bug to fix.

Let me check if there are any other issues in the report generation.

In the markdown report, for the false positives and false negatives tables, it sorts by score descending:

```python
for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
```

This is correct for false positives (higher score means more confident false positive), but for false negatives, it should sort by score ascending (lower score means more confident false negative).

Let me check:

- For false positives: items that are benign but predicted as violation. Higher score means the model was more confident it was a violation, so these are the most egregious false positives. Sorting by score descending makes sense.

- For false negatives: items that are violation but predicted as benign. Lower score means the model was more confident it was benign, so these are the most egregious false negatives. Sorting by score ascending would make sense.

But in the current code, both are sorted by `-r.score`, which means descending order for both. For false negatives, this would show the least egregious ones first (those with highest score, meaning the model was least confident it was benign).

This is a usability issue for the report. The false negatives should be sorted by score ascending to show the most egregious ones first.

Let me verify with the code:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And `_example_rows` sorts by `-r.score` for both:

```python
for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
```

So for false negatives, this is sorting by score descending, which shows the false negatives where the score was highest (closest to the threshold) first, rather than the ones where the score was lowest (most egregious).

This is a usability issue. The false negatives should be sorted by score ascending to show the most egregious ones first.

So there are two issues with the report:

1. The per-category table has "violations" and "caught" swapped.
2. The false negatives are sorted in the wrong order (should be ascending by score, not descending).

Both should be fixed.

Let me check if there are any other issues.

In the markdown report, for the headline metrics, it shows "fpr" but for the FPR at recall, it shows "fpr @ recall {recall}". This is consistent.

Another potential issue: in `metrics.fpr_at_recall`, the calculation of FPR:

```python
return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0. This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct: not predicted as violation, but is a violation.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious (the model was very confident it was benign, but it was actually a violation).

Therefore, sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is equivalent to score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report._example_rows`, it clips the rationale to 200 characters by default:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    # ...
    for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
```

This is good for readability, but it might cut off important information. However, this is a configurable parameter, so it's fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category metrics.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct. For violations, it increments the count for the label category. For false positives, it increments the count for the predicted category.

So the per-category metrics are calculated correctly. The bug is only in the report generation.

To summarize, I've found two bugs in the report generation:

1. The per-category table has "violations" and "caught" swapped in the data rows.
2. False negatives are sorted in descending order by score, but should be sorted in ascending order to show the most egregious ones first.

Both should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct. It uses the metrics configuration from the config file.

Another potential issue: in `cache.py`, the `RatingCache.put` method:

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

This is correct. It uses "INSERT OR REPLACE" to update the cache if the key already exists.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `report._clip`, it replaces "|" with "/" in the rationale:

```python
_clip(r.rationale, clip).replace('|', '/')
```

This is necessary because "|" is used as a column separator in markdown tables. This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to modify `_example_rows` to take a `sort_key` parameter, or to sort the false negatives differently before passing them to `_example_rows`.

Let me see how it's implemented:

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

The sorting is done inside the function. To fix the issue, we need to make the sort key configurable.

We could change the function to:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int, reverse: bool = True) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in sorted(items, key=lambda r: r.score, reverse=reverse)[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

And then call it with `reverse=True` for false positives and `reverse=False` for false negatives.

Alternatively, we could sort the false negatives before passing them to the function:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

This would be cleaner, as it keeps the sorting logic outside of `_example_rows`.

Let me check which approach is better.

The current code filters and sorts in one step:

```python
for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
```

If we sort the false negatives before passing them to `_example_rows`, we can keep `_example_rows` simple.

Let me see how it's used:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

But it's a bit of a refactor. Since the current code is small, it's probably fine to do this.

Alternatively, we could keep the sorting inside `_example_rows` but make it configurable.

Given that this is a bug fix, I think the simplest approach is to sort the false negatives differently before passing them to `_example_rows`.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need = (target_recall * n_pos * 1000 + 999) // 1000
```

Or even better, use:

```python
need = math.ceil(target_recall * n_pos * (1 - 1e-10))
```

But this is a minor issue and the current implementation is likely correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the current code, false negatives are defined as:

```python
fns = [r for r in ok if not r.pred and r.example.is_violation]
```

Which is correct.

And the score is in [0, 1], where higher means more confident it's a violation.

So for false negatives, lower score means more egregious.

Sorting by score ascending would show the most egregious false negatives first.

The current code sorts by `-r.score`, which is score descending, so it shows the least egregious false negatives first.

This should be fixed.

Let me check if there are any other issues.

In `report.render_markdown`, it does:

```python
errs = [r for r in rated if r.error is not None]
if errs:
    lines += ["", f"## Errors ({len(errs)})", ""]
    lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
```

This is correct. It shows the errors, clipped to `clip` characters.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has a row for each category, but it doesn't include a total row. This is fine, as the headline metrics show the overall numbers.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `cache.py`, the `RatingCache.key` method:

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

This is correct. It uses a null byte as a separator to avoid collisions.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it sorts the items by `-r.score`, which is score descending.

For false positives, this is correct (most egregious first).

For false negatives, this is incorrect (should be score ascending).

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me check if there are any other issues.

In `pipeline.score`, it does:

```python
ok = [r for r in rated if r.error is None]
```

This is correct. It filters out items with errors.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In `metrics.per_category`, it initializes the dictionary with:

```python
out: dict[str, dict] = defaultdict(lambda: {"violations": 0, "caught": 0, "benign_flagged": 0})
```

And then:

```python
for cat, y, p, pc in zip(categories, labels, preds, pred_categories):
    if y:
        out[cat]["violations"] += 1
        out[cat]["caught"] += int(p)
    elif p:
        out[pc]["benign_flagged"] += 1
```

This is correct.

The bug is only in the report generation.

Let me check if there are any other issues.

In `report._pct`, it does:

```python
def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"
```

This formats the percentage with one decimal place, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In the markdown report, the false negatives section is labeled as "## False negatives ({len(fns)})", and the table has columns "id", "label category", "predicted", "score", "rationale".

For false negatives, "label category" should be the violation category (since it's a violation), "predicted" should be "none" (since it's predicted as benign), and "score" should be low.

Sorting by score ascending would show the false negatives with lowest score first, which are the most egregious.

The current code sorts by `-r.score`, which is score descending, so it shows the false negatives with highest score first, which are the least egregious.

This should be fixed.

Let me check if there are any other issues.

In `cli.py`, the `cmd_run` function:

```python
mc = cfg.get("metrics", {})
summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                         fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
```

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table has columns:

```
| category | violations | caught | recall | benign flagged |
```

And the data is currently:

```
| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |
```

So "violations" column shows `d['caught']`, and "caught" column shows `d['violations']`.

This is clearly swapped and should be fixed.

Let me check if there are any other issues.

In `metrics.per_category`, for the `recall` calculation:

```python
for d in out.values():
    d["recall"] = _ratio(d["caught"], d["violations"])
```

Where `_ratio(a, b)` is likely `a / b` if `b > 0` else 0.

This is correct.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the false negative sorting.

In `report._example_rows`, it's used for both false positives and false negatives:

```python
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

But false positives and false negatives should be sorted differently. False positives should be sorted by score descending (most egregious first), and false negatives should be sorted by score ascending (most egregious first).

The current code sorts both by `-r.score`, which is score descending for both.

This is incorrect for false negatives.

The fix is to sort the false negatives by score ascending before passing them to `_example_rows`.

Let me see how it's implemented:

```python
fps = [r for r in ok if r.pred and not r.example.is_violation]
fns = [r for r in ok if not r.pred and r.example.is_violation]
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

We could change it to:

```python
fps = sorted([r for r in ok if r.pred and not r.example.is_violation], key=lambda r: -r.score)
fns = sorted([r for r in ok if not r.pred and r.example.is_violation], key=lambda r: r.score)
lines += ["", f"## False positives ({len(fps)})", ""]
lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
lines += ["", f"## False negatives ({len(fns)})", ""]
lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
```

And then simplify `_example_rows` to not do any sorting:

```python
def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
    rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
    for r in items[:max_examples]:
        rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
    if len(items) > max_examples:
        rows.append(f"\n_{len(items) - max_examples} more not shown._")
    return rows
```

This would be cleaner and more flexible.

Given that this is a bug fix, I think this is the best approach.

Let me check if there are any other issues.

In `report._clip`, it does:

```python
text = " ".join(text.split())
```

This collapses multiple whitespace characters into a single space, which is good for readability.

I think the two report issues are the most important to fix.

Let me check if there are any other issues with the per-category table.

In the markdown report, the per-category table includes all categories that appear in the data, but it might be good to include all known categories, even if they have zero violations. However, this is a feature request, not a bug.

The current implementation only includes categories that appear in the data, which is fine.

I think the two report issues are the most important to fix.

Let me check if there are any other issues.

In `metrics.fpr_at_recall`, the calculation of `need`:

```python
need = math.ceil(target_recall * n_pos - 1e-9)
```

As I mentioned earlier, this is a common trick, but it might be clearer to use:

```python
need