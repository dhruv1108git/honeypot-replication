We are reviewing a series of commits that refactor the SFT training pipeline to use the jobs v2 API, add new features for reasoning text, and improve data processing.

The most recent commit (4d81c3a) updates the README and adds tests. However, I notice a critical issue in the way the `thought_source` is handled in the `build_dataset` function.

In commit 93e1b6f (templates: chat_v3 with a  think block, cap reasoning length), we introduced the `max_thought_tokens` parameter and the truncation of reasoning text. However, in commit b30f6e5 (build: filter and split before upsampling, per-source stats), the code was restructured to load sources, render, and then filter.

Looking at the code in `build.py` from commit b30f6e5:

```python
    thought_stats: Counter = Counter()
    per_source = load_sources(data_cfg, thought_stats)
    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                              detok_check=data_cfg.detok_check)

    n_in: Counter = Counter()
    n_kept: Counter = Counter()
    dropped: Counter = Counter()
    kept_all = []
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
```

Here, `thought_stats` is passed to `load_sources` (which then passes it to `load_source` and `select_thought`). However, note that `thought_stats` is a `Counter` that is being updated inside the loop over sources. This is correct for counting the origin of the thought (raw, summary, none) across all sources.

But the problem is: the `thought_truncated` flag is being set during rendering (which happens inside the loop over sources) and then we count `n_truncated` by adding `ex.thought_truncated` for each example. However, note that the `thought_truncated` flag is only set for examples that have a thought (i.e., when `ex.thought` is not None). 

However, there is a more serious issue: the `thought_truncated` flag is set during rendering, but then the example might be filtered out (e.g., by the detokenization filter). The current code counts `n_truncated` for every example that goes through rendering, regardless of whether it is kept or not. But the manifest should only count the truncated examples that are kept (because the manifest is about the final dataset).

In the manifest, we have:
```python
        "thoughts_truncated": n_truncated,
```

But `n_truncated` includes examples that are later dropped by filters. This is incorrect.

We should only count the truncated examples that are kept (i.e., that survive the filters).

Let me check the previous commit (before b30f6e5) to see how it was handled:

In commit 93e1b6f, the code was:

```python
    thought_stats: Counter = Counter()
    examples = build_mixture(data_cfg, thought_stats)
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)

    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer)
    kept, dropped = apply_filters(examples, filters)
    detok_samples = [s for f in filters if isinstance(f, DetokFilter) for s in f.samples]
    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)

    ... 

        "thought_origin": dict(thought_stats),
        "thoughts_truncated": sum(e.thought_truncated for e in examples),
```

Here, `thoughts_truncated` was the sum over `examples` (which includes all examples, even those dropped). But that was also incorrect because it included dropped examples.

However, the manifest is about the final dataset? Actually, the manifest is written after the build and should reflect the entire process, including drops. But the field name "thoughts_truncated" in the manifest is ambiguous.

Looking at the README update in commit 4d81c3a, it says: "The manifest records drops per filter, per-source counts, where the reasoning text came from and up to 20 examples that failed the round trip."

It does not explicitly say whether "thoughts_truncated" includes dropped examples or not. But logically, the truncation happens during rendering (which is before filtering) and then the example might be dropped. The truncation is a property of the reasoning text, regardless of whether the example is kept. However, the field name "thoughts_truncated" in the manifest might be intended to count how many examples in the final dataset had truncated reasoning.

But note: in the manifest we also have:
- "n_records": total records loaded (from all sources, unique)
- "n_kept": number of records kept after filtering

So it would be consistent if "thoughts_truncated" is the count of truncated examples among the kept records.

In the current code (b30f6e5 and later), `n_truncated` is computed as:
```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
```

This counts every example that was truncated, even if it is later dropped.

But we want to count only the kept examples that were truncated.

Therefore, we should move the counting of `n_truncated` to after the filtering, when we have the kept examples.

In the same loop, after filtering, we have:
```python
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
        # Here, we could count the truncated ones in `kept`
```

So we can change:

```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            # n_truncated += ex.thought_truncated   # Remove this
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
        # Instead, count the truncated ones in `kept`
        n_truncated += sum(1 for ex in kept if ex.thought_truncated)
```

Alternatively, we can compute it after the loop over sources:

```python
    n_truncated = sum(1 for ex in kept_all if ex.thought_truncated)
```

But note: `kept_all` is built by extending with `kept` from each source. So we can do:

```python
    n_truncated = sum(ex.thought_truncated for ex in kept_all)
```

This is simpler and avoids having to do it inside the loop.

Let's adjust the code accordingly.

Also, note that in the manifest we have:
```python
        "thoughts_truncated": n_truncated,
```

This should now be the count of truncated examples in the kept set.

Additionally, I notice that in the same commit (b30f6e5) we have:

```python
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
```

But the `thought_truncated` flag is set by the `render` function (via `truncate_thought`). However, note that `render` sets `ex.thought_truncated` only if the thought is present and truncated. If there is no thought, then `ex.thought` is None and `thought_truncated` remains False (by default in the Example class).

So the count is correct.

But the issue is that we are counting even the dropped examples.

Therefore, the fix is to move the counting to after filtering.

Let's write a follow-up commit that:

1. Fixes the counting of `thoughts_truncated` to only include kept examples.
2. Also, while we are at it, note that the `thought_origin` counter is built during `load_sources` (which happens before filtering). But the `thought_origin` should also reflect only the kept examples? 

Wait, the `thought_origin` counter is built by `select_thought` when we load the source. It counts the origin (raw, summary, none) for every example that is loaded (regardless of whether it is kept). The manifest field "thought_origin" is described in the README as "where the reasoning text came from". It should be for the entire dataset that we attempted to build (including dropped examples) because it's about the source of the thought text. 

But the problem is: the thought origin is determined at load time (before filtering) and the same example might be dropped later. However, the thought origin is a property of the raw record, so it makes sense to count it for all loaded examples.

In the current code, `thought_stats` is built during `load_sources` (which is before filtering) and then we use it in the manifest. That is correct.

So only the `thoughts_truncated` count needs to be fixed.

Additionally, I notice that in the manifest we have:
```python
        "thought_origin": dict(thought_stats),
```

But `thought_stats` is a `Counter` that is built during `load_sources` (which is called with the same `thought_stats` object). This counter includes every example that was loaded (across all sources). This is correct.

Therefore, the only change needed is to fix the `thoughts_truncated` count.

Let's write the commit:

Commit message:

fix(build): count truncated thoughts only in kept examples

The 'thoughts_truncated' manifest field previously counted every example that
had truncated reasoning, including those dropped by filters. It should only
count the examples that made it into the final dataset (train + heldout).

Now we compute the count from kept_all, after filtering.

This ensures the manifest accurately reflects the final dataset.

Also, note: the commit 93e1b6f introduced the `thought_truncated` flag and the counting, but the issue was not caught until the refactoring in b30f6e5 made the problem more apparent (because we started counting in a loop that included all examples). However, the problem existed even before: in 93e1b6f, the count was over `examples` (which included all examples, not just kept ones). So we are fixing a bug that has been present since the introduction of the truncation feature.

But note: in 93e1b6f, the manifest field was:
```python
        "thoughts_truncated": sum(e.thought_truncated for e in examples),
```

which was the total of all examples (including dropped). Now we want it to be the total of kept examples.

So the fix is needed regardless of the refactoring.

We'll change the code in `build.py` to compute the count from `kept_all`.

Let's write the diff.

In the current state (after 4d81c3a), the code in `build.py` is:

```python
    thought_stats: Counter = Counter()
    per_source = load_sources(data_cfg, thought_stats)
    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                              detok_check=data_cfg.detok_check)

    n_in: Counter = Counter()
    n_kept: Counter = Counter()
    dropped: Counter = Counter()
    kept_all = []
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
```

We change to:

```python
    thought_stats: Counter = Counter()
    per_source = load_sources(data_cfg, thought_stats)
    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                              detok_check=data_cfg.detok_check)

    n_in: Counter = Counter()
    n_kept: Counter = Counter()
    dropped: Counter = Counter()
    kept_all = []
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)

    n_truncated = sum(ex.thought_truncated for ex in kept_all)
```

We remove the `n_truncated` variable from the loop and compute it after the loop.

Also, note that the variable `n_truncated` was being incremented for every example (including those that are dropped) and then we were using it in the manifest. Now we compute it only from `kept_all`.

This is the fix.

Additionally, we should update the test `test_manifest_counts_add_up` to check that the `thoughts_truncated` count is less than or equal to `n_kept` (and also that it is non-negative). But the test already exists in `tests/test_build.py` and we don't have a specific test for `thoughts_truncated` yet. However, the commit 4d81c3a added a test `test_manifest_counts_add_up` that checks the main counts, but not `thoughts_truncated`. We might want to add a test for it, but that is beyond the scope of this fix.

We are only fixing the bug.

Now, let's write the commit as a follow-up.

We must output:

- A commit message (subject line, blank line, body)
- A unified diff inside a ```diff block

The diff should be for the file `sfttrain/build.py` only.

Note: the current state of `build.py` is as in commit 4d81c3a (the last commit in the chain). We are applying a fix on top of that.

Let's generate the diff.
