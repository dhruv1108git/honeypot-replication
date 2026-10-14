We are reviewing a series of commits that refactor the SFT training pipeline. The goal is to move from the legacy v1 API to the jobs v2 API, improve data handling (especially reasoning text), add filters, and optimize the build process.

After reviewing the commits, I notice a potential issue in the `build.py` file related to the `thought_truncated` count. Specifically, in commit `b30f6e5` (build: filter and split before upsampling, per-source stats), the code was changed to process sources individually and then apply filters. However, the counting of truncated thoughts was moved to a separate variable `n_truncated` that is incremented for each example as they are rendered.

But note: the rendering step (which sets `ex.thought_truncated`) happens inside a loop over each source's examples. The problem is that the `thought_truncated` flag is set only when `ex.thought` is present and the thought is truncated. However, the code does:

```python
for name, examples in per_source.items():
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                model_cfg.max_thought_tokens)
        n_truncated += ex.thought_truncated
```

This is correct because `ex.thought_truncated` is a boolean (which in Python is a subclass of int, so `True` is 1 and `False` is 0). However, there is a subtle issue: what if an example has no thought? Then `ex.thought` is `None`, and `render` does not set `ex.thought_truncated` (it remains `False`). So that's safe.

But wait: in the `render` function, we have:

```python
def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
           max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:
    # ... 
    if ex.thought:
        thought = ex.thought
        if tokenizer is not None:
            thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
        target += t.thought_open + thought + t.thought_close
    # ...
```

So if `ex.thought` is `None`, we skip the truncation and `ex.thought_truncated` remains as it was (which for a new example is `False`). Therefore, the count `n_truncated` is the number of examples that had a thought and that thought was truncated.

However, in the previous version (before `b30f6e5`), the count was:

```python
"thoughts_truncated": sum(e.thought_truncated for e in examples),
```

Now it's:

```python
"thoughts_truncated": n_truncated,
```

This should be equivalent because `n_truncated` is the sum of `ex.thought_truncated` over all examples (which is the same as the sum of booleans, since `True` is 1).

But note: in the new code, we are rendering each example and then immediately adding `ex.thought_truncated` to `n_truncated`. This is the same as the old method.

However, there is a potential bug in the new code: what if the example is later dropped by a filter? Then we are counting a truncated thought for an example that doesn't make it into the final dataset. But note the manifest field `thoughts_truncated` is intended to count how many examples had truncated thoughts during the build process, regardless of whether they were dropped. The old code also counted all examples (including dropped ones) because it was done before filtering.

Looking at the old code:

```python
examples = build_mixture(data_cfg, thought_stats)
for ex in examples:
    ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)

filters = ... 
kept, dropped = apply_filters(examples, filters)
...
"thoughts_truncated": sum(e.thought_truncated for e in examples),
```

So the old code counted all examples (including dropped ones). The new code also counts all examples (because we do the rendering and count before filtering). Therefore, it is consistent.

But wait: in the new code, the rendering and counting happens per source, but still before filtering. So it's the same as the old code.

However, there is a more serious issue: in the new code, we are setting `ex.n_tokens` in the `DetokFilter` and then the `LengthFilter` reuses it. But note that the `DetokFilter` is applied after the rendering step, and the rendering step does not set `ex.n_tokens`. The `DetokFilter` sets `ex.n_tokens` to the sum of the tokens in prompt and target (if the example passes the detok check). However, if the example fails the detok check, then `ex.n_tokens` is set to the token count of the prompt (if the target passed) or only part of it? Actually, the `DetokFilter` does:

```python
def keep(self, ex: Example) -> bool:
    n_tokens = 0
    for part in ("prompt_text", "target_text"):
        rt = self.tokenizer.roundtrip(getattr(ex, part))
        if not rt.ok:
            if len(self.samples) < self.keep_samples:
                self.samples.append(...)
            return False
        n_tokens += rt.n_tokens
    ex.n_tokens = n_tokens
    return True
```

So if the example passes, `ex.n_tokens` is set to the total token count. If it fails, we return `False` and `ex.n_tokens` is not set (remains 0). Then the `LengthFilter` does:

```python
def keep(self, ex: Example) -> bool:
    if not ex.n_tokens:
        ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
    return ex.n_tokens <= self.max_tokens
```

So if the example passed the detok filter, then `ex.n_tokens` is already set and the length filter uses it. If the example failed the detok filter, then it never gets to the length filter (because filters are applied in order and detok comes before length). Therefore, the length filter only sees examples that passed detok, and for those `ex.n_tokens` is set.

But what about examples that pass detok but then are dropped by a later filter? The `ex.n_tokens` is set and then not used again? That's fine.

However, note that in the build manifest, we have:

```python
"train_tokens": sum(e.n_tokens for e in train),
```

This is for the training set (after filtering and weighting). The `train` list is built from the examples that passed all filters and then were weighted. For these examples, `ex.n_tokens` was set by the detok filter (if detok check is on) or by the length filter (if detok check is off). So it should be correct.

But there is a problem: if detok check is off, then the detok filter is not applied, so `ex.n_tokens` is not set by the detok filter. Then the length filter sets it. However, the length filter is applied to every example that reaches it (which is after the detok filter is skipped). So for examples that pass the length filter, `ex.n_tokens` is set. But for examples that fail the length filter, `ex.n_tokens` is set but then the example is dropped. The manifest's `train_tokens` is the sum for the training set, which only includes examples that passed the length filter, so `ex.n_tokens` is set for them.

So the token counting seems correct.

But wait: in the new code, we have:

```python
n_truncated = 0
for name, examples in per_source.items():
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                model_cfg.max_thought_tokens)
        n_truncated += ex.thought_truncated
```

This is done before any filtering. Then, after filtering, we have:

```python
kept_all = []   # which is the list of examples that passed all filters
...
n_truncated = ...   # but note: n_truncated was set before filtering, so it includes dropped examples.
```

The manifest field `thoughts_truncated` is set to `n_truncated`, which is the count of truncated thoughts in all examples (including dropped ones). This is consistent with the old behavior.

However, the problem I see is that the `thought_truncated` flag is set during rendering, but if an example is dropped by a filter, we don't want to count it? Actually, the old code counted all examples (including dropped ones) and the new code does the same. So it's consistent.

But let me check the purpose of `thoughts_truncated` in the manifest. The comment in the old code was:

```python
"thoughts_truncated": sum(e.thought_truncated for e in examples),
```

and `examples` was the entire set (before filtering). So the new code is consistent.

However, there is a bug in the new code: the variable `n_truncated` is incremented for every example, but note that `ex.thought_truncated` is a boolean. In Python, `True` is 1 and `False` is 0, so it's safe. But what if `ex.thought_truncated` is not a boolean? Actually, in the `Example` class, it's defined as:

```python
thought_truncated: bool = False
```

So it's a boolean. Therefore, it's safe.

But wait: in the `render` function, we set:

```python
thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
```

The `truncate_thought` function returns a tuple `(str, bool)`. So `ex.thought_truncated` is always a boolean.

So the count is correct.

However, I found a different issue: in the `build.py` file, after the filtering step, we have:

```python
kept_all = []
n_truncated = 0   # <--- This line is missing in the commit diff!
```

Wait, looking at the diff for `b30f6e5`:

```diff
@@ -21,15 +38,27 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     tokenizer = LocalTokenizer()
 
     thought_stats: Counter = Counter()
-    examples = build_mixture(data_cfg, thought_stats)
-    for ex in examples:
-        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
-
+    per_source = load_sources(data_cfg, thought_stats)
     filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                               detok_check=data_cfg.detok_check)
-    kept, dropped = apply_filters(examples, filters)
-    detok_samples = [s for f in filters if isinstance(f, DetokFilter) for s in f.samples]
-    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)
+
+    n_in: Counter = Counter()
+    n_kept: Counter = Counter()
+    dropped: Counter = Counter()
+    kept_all = []
+    n_truncated = 0
+    for name, examples in per_source.items():
+        for ex in examples:
+            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
+                                                    model_cfg.max_thought_tokens)
+            n_truncated += ex.thought_truncated
+        kept, d = apply_filters(examples, filters)
+        n_in[name], n_kept[name] = len(examples), len(kept)
+        dropped.update(d)
+        kept_all.extend(kept)
+
+    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
+    train = mix(group_by_source(train_unique), data_cfg)
```

The line `n_truncated = 0` is present in the diff. So it's initialized to 0 and then incremented for every example.

But note: the variable `n_truncated` is only incremented for examples that are loaded from the sources (i.e., before filtering). This is the same as the old code.

However, there is a potential off-by-one if the example is dropped? No, because we are counting the truncation at the time of rendering, which is independent of filtering.

So the count is correct.

But I see a different issue: the manifest field `thoughts_truncated` is the number of examples that had a truncated thought, but note that an example might have a thought that is truncated, but then the example is dropped by a filter. The old code included those, and the new code does too. Is that the intended meaning?

Looking at the old code, the manifest had:

```python
"thoughts_truncated": sum(e.thought_truncated for e in examples),
```

where `examples` was the entire set (before filtering). So it included dropped examples.

In the new code, it's:

```python
"thoughts_truncated": n_truncated,
```

and `n_truncated` is the sum over all examples (including dropped ones). So it's the same.

But the problem is: the field name `thoughts_truncated` might be misinterpreted as the number of truncated thoughts in the final dataset. However, the documentation (in the README) for the build steps says:

> The manifest records drops per filter, per-source counts, where the
> reasoning text came from and up to 20 examples that failed the round trip.

It doesn't explicitly say what `thoughts_truncated` is. But in the old code, it was the count of truncated thoughts in the entire set of examples (before filtering). So it's consistent.

However, I think there is a bug in the new code: the `thought_truncated` flag is set during rendering, but if an example is dropped by a filter, we don't want to count it? Actually, the purpose of `thoughts_truncated` is to report how many examples had to truncate the thought, regardless of whether they were kept. So it should include dropped examples.

But let me check the commit message for `93e1b6f` (templates: chat_v3 with a  think block, cap reasoning length):

> The manifest counts truncated examples.

It doesn't specify whether it's before or after filtering. However, the old code counted before filtering, so the new code should too.

Therefore, the current implementation is correct.

But wait: in the new code, we have:

```python
n_truncated = 0
for name, examples in per_source.items():
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                model_cfg.max_thought_tokens)
        n_truncated += ex.thought_truncated
```

This is correct.

However, I found a bug in the `test_build.py` test: in the `test_manifest_counts_add_up` method, it checks:

```python
self.assertEqual(m["n_kept"] + sum(m["dropped"].values()), m["n_records"])
```

But note: `m["n_records"]` is the total number of records loaded from sources (before filtering). And `m["n_kept"]` is the number of records that passed all filters. And `m["dropped"]` is a counter of how many were dropped by each filter.

However, the sum of the dropped counts might not equal `m["n_records"] - m["n_kept"]` because an example might be dropped by multiple filters? Actually, no: the filters are applied in order, and an example is dropped by the first filter that rejects it. So the dropped counts are disjoint.

Therefore, the test is correct.

But there is a different issue: in the `build.py` file, the manifest field `n_records` is defined as:

```python
"n_records": sum(n_in.values()),
```

which is the total number of records loaded (before filtering). And `n_kept` is the number of records that passed all filters. And `dropped` is a counter of the number of records dropped by each filter. So:

```
n_records = n_kept + sum(dropped.values())
```

Therefore, the test is correct.

But I see a potential problem in the `test_build.py` test: it uses the sample data from the repository. The sample data might not have any truncated thoughts? But that's not a bug in the code.

After reviewing all the commits, I think the code is correct. However, I notice that in the `build.py` file, the variable `n_truncated` is incremented for every example, but note that `ex.thought_truncated` is set only when there is a thought and it is truncated. If there is no thought, then `ex.thought_truncated` remains `False` (0). So it's safe.

But there is a subtle issue: the `thought_truncated` flag is set during rendering, but what if the example is later dropped by a filter? Then we are counting a truncated thought for an example that doesn't make it into the final dataset. However, as discussed, that is intentional because the manifest field `thoughts_truncated` is meant to count all examples that had a truncated thought during the build process (including dropped ones).

Therefore, I don't see a bug.

However, I found a bug in the `truncate_thought` function:

```python
def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
    ids = tokenizer.encode(text)
    if len(ids) <= max_tokens:
        return text, False
    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
```

The line:

```python
return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
```

This takes the last `max_tokens - 1` tokens? Because:

```
len(ids) - (len(ids) - max_tokens + 1) = max_tokens - 1
```

So it returns `max_tokens - 1` tokens, not `max_tokens`.

Example: 
  ids = [1,2,3,4,5], max_tokens=3
  start index = 5 - 3 + 1 = 3
  slice = ids[3:] = [4,5] -> 2 tokens.

But we want 3 tokens: [3,4,5].

The correct slice should be:

```python
ids[-max_tokens:]
```

Which is the last `max_tokens` tokens.

So the current code returns one token less than requested.

This bug was introduced in commit `93e1b6f` (templates: chat_v3 with a  think block, cap reasoning length).

Let me check the test for truncation in `test_templates.py`:

```python
def test_long_thought_keeps_the_end(self):
    tok = LocalTokenizer()
    text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
    cut_text, cut = truncate_thought(text, tok, 50)
    self.assertTrue(cut)
    self.assertTrue(cut_text.endswith("so the answer is 4"))
    self.assertLessEqual(tok.count(cut_text), 50)
```

This test checks that the token count is <= 50, but it doesn't check that it's exactly 50 (or as close as possible). The bug would cause it to be 49, which is still <=50, so the test passes.

But the requirement is to keep up to `max_tokens` tokens. The bug causes it to keep `max_tokens - 1` tokens.

This is a bug.

The fix is to change:

```python
return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
```

to

```python
return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```

Alternatively:

```python
start = max(0, len(ids) - max_tokens)
return tokenizer.decode(ids[start:]).lstrip(), True
```

But note: the current code uses `len(ids) - max_tokens + 1` which is off by one.

Let me compute:

  We want the last `max_tokens` tokens: that's from index `len(ids) - max_tokens` to the end.

  So the slice should be `ids[len(ids)-max_tokens:]`.

But if `len(ids) < max_tokens`, we don't truncate.

The current code:

  if len(ids) <= max_tokens: ... (so no truncation)

  else: return ...[len(ids)-max_tokens+1:]

This is one token too few.

Therefore, the correct code is:

```python
start = max(0, len(ids) - max_tokens)
return tokenizer.decode(ids[start:]).lstrip(), True
```

But note: the function says "Keep the last `max_tokens` tokens", so we want exactly `max_tokens` tokens if possible.

The bug is that it returns `max_tokens - 1` tokens.

This bug affects the count of truncated thoughts (because it truncates more than necessary) and also the content of the reasoning.

We should fix this.

This bug is present in the current codebase (as per the commits provided) and was introduced in commit `93e1b6f`.

Therefore, I propose a follow-up commit to fix this bug.

Commit message:

```
templates: fix truncate_thought to keep max_tokens tokens

The truncate_thought function was returning max_tokens-1 tokens due to
an off-by-one error in the slice start index. This caused reasoning
to be truncated more than necessary and undercounted the token count
in the reasoning.

Fix by using the correct slice: from (len(ids) - max_tokens) to the end.

Also update the test to check the exact token count.
```

Diff:

We need to change `sfttrain/templates.py`:

```diff
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    start = max(0, len(ids) - max_tokens)
+    return tokenizer.decode(ids[start:]).lstrip(), True
```

And update the test in `tests/test_templates.py` to check the exact token count.

In the test `test_long_thought_keeps_the_end`, we currently have:

```python
self.assertLessEqual(tok.count(cut_text), 50)
```

We should change it to:

```python
self.assertEqual(tok.count(cut_text), 50)
```

But note: it's possible that the tokenizer might not be able to decode exactly 50 tokens? Actually, the tokenizer is deterministic. However, the test uses a fixed string and the tokenizer we have is very simple (it only uses ASCII and byte fallback). The string is:

```python
text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
```

This is all ASCII, so the token count should be the same as the number of tokens we took.

But note: the tokenizer might have special tokens? In our `LocalTokenizer`, the `encode` and `decode` are reversible for ASCII. So the token count of the truncated text should be exactly `max_tokens`.

However, the truncation might remove a space at the beginning (due to `lstrip`), but that shouldn't change the token count because the tokenizer treats space as a token? Actually, our tokenizer is character-based for ASCII, so space is a token. But `lstrip` removes leading spaces, which might reduce the token count by the number of leading spaces.

Example: if the truncated text starts with a space, then `lstrip` removes it, so the token count is reduced by one.

But we want the token count to be at most `max_tokens`, and it's acceptable to be less if we strip leading whitespace. However, the requirement is to keep up to `max_tokens` tokens, so it's okay if it's less.

But the bug was that we were returning `max_tokens-1` tokens, so we want to fix it to return up to `max_tokens` tokens (and it might be less due to stripping).

The test should check that the token count is <= `max_tokens` and that it's as close as possible. However, the current test only checks <=, which is correct.

But to verify the fix, we can change the test to check that the token count is exactly `max_tokens` when the text doesn't start with whitespace. However, the example text might start with a space? Actually, the text is:

```python
"step0 step1 ... step199 so the answer is 4"
```

When we take the last 50 tokens, it might start in the middle of a word? But our tokenizer is character-based, so tokens are characters. Wait, no: in `LocalTokenizer`, the tokens are characters (for ASCII). So the token count is the number of characters.

But note: the tokenizer in `LocalTokenizer` is not a real tokenizer; it's a mock for testing. It splits the text into characters (for ASCII) and uses byte fallback for non-ASCII. So for the test string (which is all ASCII), the token count is the length of the string.

Therefore, when we truncate to 50 tokens, we want 50 characters.

But the string might have a space at the beginning of the truncated part, and then `lstrip` removes it, so the token count becomes 49.

To avoid that, we can make sure the truncated part doesn't start with space. However, the test is not about that.

Given the complexity, it's safer to keep the test as `<=` and add a comment.

But to verify the fix, we can add a test that checks the token count is exactly `max_tokens` when the truncated text doesn't start with whitespace.

Alternatively, we can remove the `lstrip`? But the requirement is to strip surrounding whitespace, so we do want to remove leading whitespace.

The function says: "Keep the last `max_tokens` tokens of the reasoning." and then "the end of the reasoning is where the model settles on its answer, so that is the part we keep when we have to cut."

Stripping leading whitespace is acceptable because it doesn't change the meaning.

Therefore, the token count might be less than `max_tokens` due to stripping, but it should be as close as possible.

The bug was that we were returning `max_tokens-1` tokens even without stripping. Now we return up to `max_tokens` tokens (and then strip, which might reduce it by a few).

So the test should remain `<=`.

However, to catch the off-by-one, we can add a test that uses a string without leading whitespace and checks the token count is exactly `max_tokens`.

Let me add a test:

```python
def test_truncate_thought_exact_token_count(self):
    tok = LocalTokenizer()
    text = "a" * 100   # 100 'a' characters
    cut_text, cut = truncate_thought(text, tok, 50)
    self.assertTrue(cut)
    self.assertEqual(tok.count(cut_text), 50)
```

This test would fail with the old code (because it would return 49 tokens) and pass with the fix.

Therefore, I will include this test.

So the follow-up commit will:

1. Fix the off-by-one in `truncate_thought`.
2. Add a test to verify the token count is exact when there's no leading whitespace to strip.

Let's write the diff.
