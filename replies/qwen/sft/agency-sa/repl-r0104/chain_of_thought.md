We are reviewing a series of commits that refactor the SFT training pipeline. The main changes include:
1. Adding a client for the jobs v2 training API (replacing the old v1 API)
2. Migrating the model configuration to a nested structure to match the v2 API
3. Introducing options for the reasoning text source (raw, summary, none) and truncation
4. Adding a detokenization check to filter out examples that don't round-trip through the tokenizer
5. Changing the build order to filter and split before upsampling to avoid issues with deduplication and held-out split

I've reviewed all the commits and found one issue that needs fixing:

In commit `b30f6e5` (build: filter and split before upsampling, per-source stats), the function `split_heldout` was changed to take a `seed` parameter and shuffle the examples using that seed. However, in the call to `split_heldout` in `build.py`, the seed is passed as `data_cfg.seed` (which is an integer) but the function expects the seed to be the third argument (after `examples` and `fraction`). 

Looking at the function signature in `mixture.py`:
```python
def split_heldout(examples: list[Example], fraction: float,
                  seed: int = 0) -> tuple[list[Example], list[Example]]:
```

But in `build.py`:
```python
    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
```

This is correct because `data_cfg.seed` is an integer and the function expects the seed as the third argument.

However, there is a more subtle issue: the `split_heldout` function in `mixture.py` now creates a new random generator with the seed for the shuffle. But note that the `mix` function (which is used to apply weights) also uses `cfg.seed` to shuffle. This means that the same seed is used for two different shuffles (the heldout split and the weighting). This might not be a problem per se, but it's important to note that the seed is used in two places.

But wait: the `split_heldout` function is called with `data_cfg.seed` and then the `mix` function (which does the weighting) is called without a seed? Actually, in `mix` we have:
```python
def mix(per_source: dict[str, list[Example]], cfg: DataConfig) -> list[Example]:
    rng = random.Random(cfg.seed)
    ...
```

So both shuffles (the heldout split and the weighting) use the same seed. This is intentional? Actually, the heldout split and the weighting are two separate steps that should be independent. However, the seed is the same for both. This might lead to non-reproducible behavior if the order of operations changes? But note that the heldout split is done on the unique records and the weighting is done only on the training split. So the two shuffles are on different sets of data.

But the problem is: the same seed is used for two different shuffles. This is acceptable if we want the entire build to be reproducible with one seed, but note that the two shuffles are independent and we might want to control them separately. However, the current design uses one seed for the entire data config.

I don't see an immediate bug, but let me check the commit `b30f6e5` again.

Another issue: in the same commit, the `thoughts_truncated` count was changed from `sum(e.thought_truncated for e in examples)` to `n_truncated`, which is incremented as we render each example. However, note that `thought_truncated` is set during `render` (which is called per example in the loop over per_source). This is correct.

But wait: in the old code, we had:
```python
    examples = build_mixture(data_cfg, thought_stats)
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
```
and then `thoughts_truncated = sum(e.thought_truncated for e in examples)`

In the new code:
```python
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
```

This is equivalent and correct.

However, I found a bug in the `DetokFilter`:

In commit `5c2b9a1` (filters: drop samples that fail the detokenization round trip), the `DetokFilter` was updated to set `ex.n_tokens` in the `keep` method. But note that the `LengthFilter` also sets `ex.n_tokens`. The problem is that the `DetokFilter` sets `ex.n_tokens` to the sum of the tokens in the prompt and target, but it does so by adding the two `rt.n_tokens` (from the roundtrip). However, the `roundtrip` method returns the token count for the entire string, so that is correct.

But in the `DetokFilter`, we have:
```python
    def keep(self, ex: Example) -> bool:
        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                ... # return False if any part fails
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
        return True
```

This is correct because `rt.n_tokens` is the number of tokens for that part.

However, in the `LengthFilter` we have:
```python
    def keep(self, ex: Example) -> bool:
        if not ex.n_tokens:
            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
        return ex.n_tokens <= self.max_tokens
```

But note: if the `DetokFilter` runs before the `LengthFilter` (which it does, because `DetokFilter` is added before `LengthFilter` in `default_filters`), then `ex.n_tokens` will be set by the `DetokFilter` and the `LengthFilter` won't recompute. This is efficient.

However, what if the `DetokFilter` is not present? Then `ex.n_tokens` would be 0 and the `LengthFilter` would compute it. But note that the `DetokFilter` is only added if `detok_check` is True. So if `detok_check` is False, then `ex.n_tokens` is 0 and the `LengthFilter` will compute it.

This is correct.

But wait: what if the `DetokFilter` is present but the example passes the detok check? Then `ex.n_tokens` is set. But if the example fails the detok check, then the example is dropped and the `LengthFilter` is never run on it. So that's fine.

However, there is a bug: in the `DetokFilter`, we set `ex.n_tokens = n_tokens` even when the example fails the detok check? Actually, no: if the example fails, we return False and the example is dropped, so the `n_tokens` is not set for the dropped example. But that's okay because dropped examples are not used later.

But note: the `n_tokens` is set only for kept examples? Actually, no: in the loop over the parts, if the first part (prompt) is okay but the second part (target) fails, then we set `n_tokens` to the prompt token count and then return False. So `ex.n_tokens` is set to the prompt token count for a dropped example. But that's harmless because the example is dropped and won't be used in the length filter.

So no bug there.

But I found a different issue: in the `build.py` file, after the filters are applied, we have:
```python
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

Note that `n_truncated` is incremented for every example (including the ones that are dropped). But the manifest field `thoughts_truncated` is defined as the number of examples that had their thought truncated. However, the truncation happens during rendering (which is done for every example, even dropped ones). So it's correct to count all examples.

But the manifest says: "thoughts_truncated": n_truncated. And n_truncated is the sum of `ex.thought_truncated` for every example we rendered (which is every example from every source). This is correct.

However, in the old code, we had:
```python
    examples = build_mixture(data_cfg, thought_stats)
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
    ...
    "thoughts_truncated": sum(e.thought_truncated for e in examples),
```

So it's the same.

Now, I found a bug in the `test_build.py` test:

In the test `test_targets_use_think_block`, it checks:
```python
        with_thought = [r for r in self.train if r["thought"]]
        self.assertTrue(with_thought)
        for r in with_thought:
            self.assertTrue(r["target_text"].startswith("<tool_call>\n"), r["id"])
```

But note: the `thought` field in the record is the raw reasoning text (or summary) that was selected. However, if `thought_source` is "none", then `thought` is None and the target text won't have the think block. But in our test, we are using the `assistant_mix.toml` which has `thought_source = "raw"`, so there should be examples with thought.

But wait: the test uses the `assistant_mix.toml` and the `kestrel-3-8b` model which uses `chat_v3`. So the target should start with "<tool_call>\n".

However, note that the `thought` field in the record might be empty string? Actually, the `select_thought` function returns None if there's no thought. So `r["thought"]` would be None for no thought, and the target text wouldn't have the think block.

But the test filters `with_thought = [r for r in self.train if r["thought"]]` so it only checks records that have a non-empty thought. And for those, it checks that the target starts with "<tool_call>\n".

This is correct.

But note: in the `render` function for `chat_v3`, we have:
```python
    if ex.thought:
        target += t.thought_open + thought + t.thought_close
```

So if `ex.thought` is non-empty, then the target starts with `t.thought_open` which is "<tool_call>\n".

So the test is correct.

However, I found a bug in the `split_heldout` function:

In `mixture.py`:
```python
def split_heldout(examples: list[Example], fraction: float,
                  seed: int = 0) -> tuple[list[Example], list[Example]]:
    """Shuffle a copy of `examples` and hold out the last `fraction` of it."""
    shuffled = list(examples)
    random.Random(seed).shuffle(shuffled)
    n_heldout = int(len(shuffled) * fraction)
    cut = len(shuffled) - n_heldout
    return shuffled[:cut], shuffled[cut:]
```

The problem: `int(len(shuffled) * fraction)` might be zero if the fraction is small and the list is short. But also, note that `cut` is computed as `len(shuffled) - n_heldout`. However, if `n_heldout` is zero, then `cut` is the whole list and heldout is empty.

But the issue is: the heldout set is the last `n_heldout` examples. However, the comment says "hold out the last `fraction` of it", which is correct.

But there's a more serious issue: the `fraction` might be such that `n_heldout` is not an integer. We take `int(...)`, which truncates. So for example, if we have 10 examples and fraction=0.1, then n_heldout=1, which is correct. But if fraction=0.05, then n_heldout=0, so no heldout.

This is acceptable.

However, note that the heldout fraction is applied to the entire kept set. The problem is that the heldout set might be too small. But that's by design.

But wait: the `build.py` code does:
```python
    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
```

And then:
```python
    n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
    n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
```

But note: `train` is the result of `mix` (which applies weights) on `train_unique`. So the heldout set is the unique heldout set, and the training set is the weighted training set.

This is correct.

Now, I found a bug in the `DetokFilter`:

In the `DetokFilter`, when we compute `n_tokens`, we do:
```python
    n_tokens = 0
    for part in ("prompt_text", "target_text"):
        rt = self.tokenizer.roundtrip(getattr(ex, part))
        if not rt.ok:
            ... # return False
        n_tokens += rt.n_tokens
    ex.n_tokens = n_tokens
```

But note: the `roundtrip` method returns the token count for the entire string. However, the `LengthFilter` expects `ex.n_tokens` to be the total number of tokens in the example (prompt + target). This is what we are setting.

But what if the example has a thought that was truncated? Then the target text is shorter. However, the token count we get from `roundtrip` is for the actual text that was rendered (which might be truncated). So it's correct.

But note: the `roundtrip` method does not change the text (it only checks if it roundtrips). The truncation happens in `render` (via `truncate_thought`). So the text we are checking in `DetokFilter` is the truncated text. Therefore, the token count we get is for the truncated text, which is what we want for the length filter.

So that's correct.

However, I found a bug in the `truncate_thought` function:

In `templates.py`:
```python
def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
    """Keep the last `max_tokens` tokens of the reasoning.

    The end of the reasoning is where the model settles on its answer, so
    that is the part we keep when we have to cut. Returns (text, truncated).
    """
    ids = tokenizer.encode(text)
    if len(ids) <= max_tokens:
        return text, False
    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
```

The problem: `ids[len(ids) - max_tokens + 1:]` is taking the last `max_tokens - 1` tokens? Because the slice is from `len(ids) - max_tokens + 1` to the end, which has length `max_tokens - 1`.

Example: 
  len(ids) = 100, max_tokens = 10
  start index = 100 - 10 + 1 = 91
  slice = ids[91:100] -> 9 tokens.

We want 10 tokens, so it should be `ids[len(ids) - max_tokens:]`.

But note: the function says "keep the last `max_tokens` tokens". So it should be:
  start = len(ids) - max_tokens
  if start < 0: start = 0

So the corrected code:
```python
    if len(ids) <= max_tokens:
        return text, False
    start = max(0, len(ids) - max_tokens)
    return tokenizer.decode(ids[start:]).lstrip(), True
```

However, in the current code, it's `len(ids) - max_tokens + 1`, which gives one token less.

This is a bug. It was introduced in commit `93e1b6f` (templates: chat_v3 with a <tool_call> block, cap reasoning length).

Let me check the test: `test_long_thought_keeps_the_end` in `test_templates.py`:

```python
    def test_long_thought_keeps_the_end(self):
        tok = LocalTokenizer()
        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertTrue(cut)
        self.assertTrue(cut_text.endswith("so the answer is 4"))
        self.assertLessEqual(tok.count(cut_text), 50)
```

The test checks that the token count of `cut_text` is <= 50. But because of the bug, it's actually 49. So the test passes because 49<=50.

But we want exactly 50 tokens (or as close as possible without exceeding). The bug causes it to be 49 tokens.

This is a bug.

We should fix it by changing the slice to `ids[len(ids) - max_tokens:]`.

But note: the function says "Keep the last `max_tokens` tokens". So we want exactly `max_tokens` tokens, unless the text is shorter.

So the fix is:
```python
    start = len(ids) - max_tokens
    if start < 0:
        start = 0
    return tokenizer.decode(ids[start:]).lstrip(), start > 0
```

Alternatively, we can write:
```python
    if len(ids) <= max_tokens:
        return text, False
    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```

But note: `ids[-max_tokens:]` is the last `max_tokens` tokens.

Yes, that's simpler.

So the corrected function:
```python
def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
    ids = tokenizer.encode(text)
    if len(ids) <= max_tokens:
        return text, False
    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```

This will return exactly `max_tokens` tokens (unless the text is shorter).

Let me check the example: 
  text = "a b c d e" (5 tokens), max_tokens=3 -> should return "c d e", which is 3 tokens.

With `ids[-3:]` -> the last 3 tokens.

Yes.

So the bug is in `truncate_thought` and it causes the reasoning to be truncated to `max_tokens-1` tokens.

This is a critical bug because it means we are not using the full token budget for the reasoning.

We should fix this.

Additionally, in the same function, we do `.lstrip()`. This is to remove any leading whitespace that might have been introduced by the decode. But note that the reasoning might have leading whitespace that is meaningful? However, the reasoning is generated by the model and typically doesn't have leading whitespace. But if we cut in the middle of a word, we might get a partial word. However, the tokenizer might handle that. But the `.lstrip()` is safe because the reasoning is a sequence of steps and leading space is not significant.

So the fix is only the slice.

Now, let's see if there are any other issues.

Another issue: in the `build.py` file, the `n_truncated` count is incremented for every example that had its thought truncated. But note that the truncation happens per example during rendering. However, the `truncate_thought` function returns a boolean `truncated` which is set to `ex.thought_truncated`. So it's correct.

But the bug in `truncate_thought` means that we are truncating more than necessary? Actually, no: we are truncating to `max_tokens-1` tokens, so it is truncated (even if we had enough tokens for `max_tokens`, we are truncating to `max_tokens-1`). But wait: the condition is `if len(ids) <= max_tokens` -> no truncation. Otherwise, we truncate to `max_tokens-1` tokens. So if the thought has exactly `max_tokens` tokens, we don't truncate? Actually, no: because the condition is `<=`, so if it's equal we don't truncate. But if it's `max_tokens+1`, we truncate to `max_tokens-1` tokens.

So the truncation happens when the token count is greater than `max_tokens`, but we truncate to `max_tokens-1` tokens. So we are always truncating by at least 2 tokens.

This is a bug.

We must fix the `truncate_thought` function.

Given that this is a critical bug, we should propose a follow-up commit to fix it.

Additionally, we should update the test to check the exact token count.

In the test `test_long_thought_keeps_the_end`, we should check:
```python
        self.assertEqual(tok.count(cut_text), 50)
```
But note: the tokenizer might not be able to decode to exactly 50 tokens? Actually, the `truncate_thought` function returns a string that when tokenized should be at most `max_tokens`. But because of the way we slice the token IDs, it should be exactly `max_tokens` (if the original was longer).

However, the decode might not be reversible? But we are using the same tokenizer for encode and decode, so it should be. But note: the tokenizer might have special tokens that are added. However, our tokenizer is a simple one that doesn't add special tokens for the beginning/end. So it should be reversible.

But in our `LocalTokenizer`, the `decode` is the inverse of `encode` for ASCII? Not exactly: because of the byte fallback, non-ASCII might become multiple tokens. But for the test, we are using ASCII.

So we can check the token count.

Let me adjust the test to expect exactly 50 tokens.

But note: the function returns the last 50 tokens, so the token count should be 50.

So the test should be:
```python
        self.assertEqual(tok.count(cut_text), 50)
```

But the current test only checks `<=50`. We should change it to `==50`.

However, the bug causes it to be 49, so the test would fail.

So we'll fix the function and update the test.

Proposed follow-up commit:

Subject: fix(truncate_thought): truncate to exactly max_tokens tokens

Body:
The truncate_thought function was truncating to max_tokens-1 tokens due to an off-by-one error in the slice. This caused the reasoning to be unnecessarily short, wasting token budget.

Change the slice to take the last max_tokens tokens.

Also update the test to verify the exact token count.

Let's write the diff.

We'll change:
```python
    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
```
to
```python
    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```

And in the test:
```python
        self.assertLessEqual(tok.count(cut_text), 50)
```
to
```python
        self.assertEqual(tok.count(cut_text), 50)
```

But note: what if the thought is exactly max_tokens? Then we don't truncate, so the token count is max_tokens. But the test is for a long thought (200 steps) so it should be truncated to 50.

Also, note that the function returns `True` for truncated only when we actually truncated (i.e., when the original was longer than max_tokens). So the test should set `cut=True` and the token count should be 50.

Let's write the commit.

We are going to change two files: `sfttrain/templates.py` and `tests/test_templates.py`.

Commit message:
```
fix(truncate_thought): truncate to exactly max_tokens tokens

The truncate_thought function was using an off-by-one error in the slice,
resulting in truncation to max_tokens-1 tokens. This wasted token budget
for the reasoning.

Change the slice to take the last `max_tokens` tokens (ids[-max_tokens:]).

Update the test to verify the exact token count after truncation.
```

Now, the diff:
