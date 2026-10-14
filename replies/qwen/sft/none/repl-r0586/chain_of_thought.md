We are reviewing a series of commits that refactor the SFT training pipeline. The goal is to check for correctness, fix bugs, and propose optimizations. We'll look for issues that might have been introduced in the commit chain and propose a follow-up commit.

After reviewing the commits, I found a few potential issues:

1. **In `sfttrain/templates.py` (commit 93e1b6f):**
   - The function `truncate_thought` uses `ids[len(ids) - max_tokens + 1:]` to keep the last `max_tokens` tokens. However, note that we are keeping `max_tokens - 1` tokens because we are taking from `len(ids) - max_tokens + 1` to the end. This is because the slice `[start:end]` includes `start` and excludes `end`, but here we are using `[start:]` which goes to the end. The number of tokens kept is `len(ids) - (len(ids) - max_tokens + 1) = max_tokens - 1`. We want to keep exactly `max_tokens` tokens.

   Let me verify:
   - Suppose `ids = [0,1,2,3,4]` (5 tokens) and `max_tokens=3`.
   - We want to keep the last 3 tokens: `[2,3,4]`.
   - `len(ids)=5`, so `start = 5 - 3 + 1 = 3`.
   - Then `ids[3:] = [3,4]` -> only 2 tokens.

   Correction: We should do `ids[len(ids) - max_tokens:]` to get the last `max_tokens` tokens.

   However, note the comment: "Keep the last `max_tokens` tokens of the reasoning." and the code says: `ids[len(ids) - max_tokens + 1:]`.

   The current code is off by one. It should be:
   ```python
   return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
   ```

   But note: if we take `max_tokens` tokens, then the starting index is `len(ids) - max_tokens`. The slice `[len(ids)-max_tokens:]` will have `max_tokens` tokens.

   However, the function also says: "The end of the reasoning is where the model settles on its answer, so that is the part we keep when we have to cut." and we are keeping the end.

   Also note: the function returns `True` for `truncated` only if we actually truncated (i.e., if the original token count was greater than `max_tokens`). The current condition is `if len(ids) <= max_tokens: ... else ...`.

   So the bug is in the slice: we are taking one token less than intended.

2. **In `sfttrain/filters.py` (commit b30f6e5):**
   - In `DetokFilter.keep()`, we set `ex.n_tokens = n_tokens` (the sum of tokens in prompt and target) only when the example passes the detok filter. However, the `LengthFilter` relies on `ex.n_tokens` being set. But note: if the example fails the detok filter, then `ex.n_tokens` is never set. However, the example is dropped so it doesn't matter for the length filter. But what about the manifest? The manifest uses `ex.n_tokens` for the `train_tokens` count. However, only kept examples are in the train set, and for kept examples, `DetokFilter` sets `n_tokens` (if it runs) and then `LengthFilter` might also set it? Actually, note the order of filters:

   The filters are applied in the order defined in `default_filters`:
   - EmptyResponseFilter
   - FlaggedFilter
   - QualityFilter
   - DetokFilter (if enabled)
   - LengthFilter
   - DedupFilter (if enabled)

   For an example to reach the `LengthFilter`, it must have passed the `DetokFilter` (if enabled). So in the `LengthFilter`, `ex.n_tokens` might be set by the `DetokFilter` (if it was enabled) or not (if detok_check is false). 

   However, in the `LengthFilter`, we have:
   ```python
   if not ex.n_tokens:
        ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
   ```

   This is safe because if detok_check was enabled, then `DetokFilter` set `ex.n_tokens` (and it's non-zero) so we skip. If detok_check was disabled, then `ex.n_tokens` is 0 (by default) so we compute it.

   But note: `ex.n_tokens` is an integer and by default 0. However, what if an example has 0 tokens? That's impossible because even an empty string would have some tokens (like the EOS token). So it's safe.

   However, there is a subtle issue: the `DetokFilter` sets `ex.n_tokens` to the sum of the tokens in the prompt and target. But note that the `DetokFilter` does:
   ```python
   n_tokens = 0
   for part in ("prompt_text", "target_text"):
        ... 
        n_tokens += rt.n_tokens
   ex.n_tokens = n_tokens
   ```

   This is the same as what the `LengthFilter` would compute. So it's consistent.

   But wait: the `DetokFilter` uses `rt.n_tokens` which is the token count from the roundtrip (which is the same as `tokenizer.count(text)`). So it's the same.

   So this part seems okay.

3. **In `sfttrain/build.py` (commit b30f6e5):**
   - The variable `n_truncated` is computed as the sum of `ex.thought_truncated` over all examples (after rendering). However, note that `ex.thought_truncated` is set only in the `render` function when the thought is truncated. But the `render` function sets `ex.thought_truncated` only when the thought is non-empty and truncated. This seems correct.

   However, note that the `thought_truncated` flag is set even for examples that are later dropped by filters. But the manifest records the total number of truncated thoughts in the entire dataset (before filtering). This is consistent with the previous version (which did `sum(e.thought_truncated for e in examples)`). So it's okay.

4. **In `sfttrain/templates.py` (commit 93e1b6f):**
   - The function `truncate_thought` returns the truncated text with `.lstrip()`. This might remove leading whitespace, which could be important for the reasoning. However, the reasoning is usually natural language and leading whitespace might not be critical. But note: the original reasoning might have had leading whitespace (e.g., after a line break). Removing it might change the meaning slightly.

   However, the goal is to keep the end of the reasoning, and the end might have leading whitespace that we don't want? Actually, the reasoning is a continuous text. We are truncating to the last `max_tokens` tokens, and then we do `.lstrip()` to remove any leading whitespace that might have been introduced by the truncation (e.g., if we cut in the middle of a space). But note: the tokenizer might have split on whitespace, so the tokenized string might not have leading space. However, the detokenization might produce a string that starts with a space? Actually, the tokenizer we are using (a simple one) might not have that issue.

   But the problem is: if we remove leading whitespace, we might change the text. For example, if the original had "  step two" and we truncate to "step two", then we remove two spaces. But the model might have generated those spaces as part of the reasoning.

   However, note: the reasoning is not rewritten, so we want to keep it as close as possible. The `.lstrip()` is intended to clean up the truncation artifact (if we cut in the middle of a space). But it might remove intentional leading whitespace.

   Alternative: don't do `.lstrip()` and accept that there might be a space at the beginning? Or note that the model is trained to generate without extra leading spaces in the reasoning? 

   Given that the reasoning is natural language and the model might have generated it without leading spaces, and the truncation might leave a space at the beginning, it's probably safe to remove it. But the requirement says: "Raw reasoning is not rewritten". However, the truncation is a necessary modification. The `.lstrip()` is a minor cleanup to avoid having a space at the beginning of the reasoning block.

   This is a design choice and might be acceptable. However, the requirement says "not rewritten", and stripping leading space is a rewrite. But the alternative might be worse (having a space at the beginning of the block). 

   Since this is a minor issue and the current behavior is by design (as per the commit message: "Raw reasoning is passed through unchanged apart from whitespace and the export's chunk markers"), and the commit 93e1b6f specifically says "Raw reasoning is not rewritten: we strip whitespace, normalise line endings and remove the export's chunk markers", note that the stripping of leading whitespace in the truncated part is an additional step. However, the commit message for 93e1b6f does not mention stripping leading whitespace at the beginning of the truncated string. It only says "keep the end" and "cut to max_thought_tokens".

   Given the ambiguity, and since the problem is minor, I won't consider it a bug. But note that the commit message for 93e1b6f says: "Raw reasoning is passed through unchanged apart from whitespace and the export's chunk markers." meaning that we do clean up whitespace (like CRLF) but not arbitrary rewrites. The `.lstrip()` is a form of whitespace cleaning.

   So it's acceptable.

5. **In `sfttrain/filters.py` (commit 5c2b9a1):**
   - The `DetokFilter` sets `ex.n_tokens` only when the example passes the filter. But note: if the example fails the detok filter, then `ex.n_tokens` remains 0. However, the example is dropped so it doesn't go to the length filter. But what about the manifest? The manifest does not use `ex.n_tokens` for dropped examples. So it's okay.

   However, in the `build_dataset` function, we do:
   ```python
   n_truncated = 0
   for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
        kept, d = apply_filters(examples, filters)
        ...
   ```

   Then later:
   ```python
   "thoughts_truncated": n_truncated,
   ```

   This counts the truncated thoughts for all examples (including dropped ones). But note: the `thought_truncated` flag is set during rendering, before filtering. So it's the same as the previous version. This is intentional: we want to know how many examples had truncated reasoning in the raw data.

   So it's correct.

The main bug I found is in the `truncate_thought` function: it truncates to `max_tokens-1` tokens instead of `max_tokens`.

Let's fix that:

In `sfttrain/templates.py`:
```python
    if len(ids) <= max_tokens:
        return text, False
    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
```

But note: the current code uses `len(ids) - max_tokens + 1`. We want to change it to `len(ids) - max_tokens`.

Also, note that the function returns `True` for `truncated` only when we actually truncated (i.e., when `len(ids) > max_tokens`). That part is correct.

Additionally, we should update the test to catch this.

In `tests/test_templates.py`, we have a test for long thought truncation. Currently:

```python
    def test_long_thought_keeps_the_end(self):
        tok = LocalTokenizer()
        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertTrue(cut)
        self.assertTrue(cut_text.endswith("so the answer is 4"))
        self.assertLessEqual(tok.count(cut_text), 50)
```

This test checks that the token count of `cut_text` is <= 50. But with the bug, it would be 49. We want it to be 50. So the test would fail if we set the max_tokens to 50 and the actual count becomes 49? Actually, the test uses `assertLessEqual` so it would pass even if it's 49. We need to change the test to check for exactly 50? But note: the token count might be less than 50 if the text is short? Actually, the text is long (200 steps) so it should be truncated to 50 tokens.

We should change the test to:
```python
        self.assertEqual(tok.count(cut_text), 50)
```

But note: the tokenizer might not be exact? Actually, the tokenizer we are using in the test is the same simple one. However, the truncation might not result in exactly 50 tokens because of the way the tokenizer works? But in our simple tokenizer, the token count of the truncated string should be 50.

Alternatively, we can check that it's at most 50 and at least 49? But the requirement is to keep the last 50 tokens.

Given that the bug causes it to be 49, we want the test to fail when the bug is present and pass when fixed.

So let's update the test to check for exactly 50 tokens.

But note: the function does `.lstrip()`, which might remove a space and thus a token? Actually, the tokenizer we have counts tokens by splitting on non-ASCII? Not exactly. Our tokenizer is a simple one that maps characters to tokens. The `count` function is `len(encode(text))`. The `encode` function for our tokenizer:

```python
    def encode(self, text: str) -> list[int]:
        text = unicodedata.normalize("NFKC", text)
        out = []
        for c in text:
            if c in self._char_to_id:
                out.append(self._char_to_id[c])
            elif self.byte_fallback:
                out.extend(self._encode_byte(c))
            else:
                out.append(self._char_to_id["<unk>"])
        return out
```

So if we remove a space at the beginning, we remove one token. But the truncation might have left a space at the beginning? Then `.lstrip()` would remove it and reduce the token count by one.

Therefore, it's possible that the token count is less than 50. So we cannot require exactly 50.

But note: the truncation is done on the token level. We are taking exactly 50 tokens (if we fix the bug). Then we decode and then lstrip. The lstrip might remove some tokens (if the first token after truncation is a space, then lstrip removes it and possibly more). So the token count of the resulting string might be less than 50.

Therefore, the test should check that it is at most 50 and at least (50 - some small number). But the requirement is to keep the last 50 tokens. The lstrip is an extra step that might remove tokens, so the actual token count might be less.

However, the goal is to not exceed the token limit for the reasoning. So having less than 50 is acceptable.

But the bug we are fixing is that we were taking 49 tokens. We want to take 50 tokens (before lstrip). The lstrip might then remove some, but that's a separate issue.

So in the test, we should check that the token count before lstrip is 50? But we don't have access to that.

Alternatively, we can change the test to use a text that doesn't have leading space after truncation. For example, if we truncate to a token that is a word (not a space), then lstrip won't remove anything.

But that might be too specific.

Given the complexity, and since the main issue is the off-by-one in the token count, we can change the test to check that the token count is at least 49 and at most 50? But that doesn't catch the bug because with the bug it's 49 and without it's 50 (and then lstrip might make it 49 or 50).

Alternatively, we can remove the lstrip for the test? But that's not realistic.

I think the best is to fix the bug and then adjust the test to expect at most 50 and at least 49, but note that the bug causes it to be 49 when it should be 50. Without the bug, it should be 50 (if no lstrip) or 49 (if lstrip removes one). So the test as it is (using `assertLessEqual(tok.count(cut_text), 50)`) is still valid.

But to catch the bug, we need a test that fails when the token count is 49 but should be 50. We can do:

```python
        # We expect the token count to be exactly 50 if no lstrip happens, but lstrip might remove some.
        # However, in this specific text, the truncation point is at a word boundary? 
        # Let's force a case where there is no leading space after truncation.
        # We'll create a text that ends with a word (so no space at the beginning of the truncated part).
        text = "x" * 1000  # a long string of 'x' (no spaces)
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertEqual(tok.count(cut_text), 50)
```

But note: the tokenizer for 'x' is one token per 'x'? Actually, in our tokenizer, each character is a token (if in the base set). So 1000 'x' is 1000 tokens. Truncating to 50 tokens should give 50 'x's, and lstrip won't remove anything because there's no space. So the token count should be 50.

So let's add a test that uses a string without spaces to avoid the lstrip effect.

We'll modify the test:

```python
    def test_long_thought_keeps_the_end(self):
        tok = LocalTokenizer()
        # Test with a string that has no spaces so lstrip doesn't remove anything
        text = "x" * 1000
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertTrue(cut)
        self.assertEqual(len(cut_text), 50)  # because each 'x' is one token and one char
        self.assertEqual(tok.count(cut_text), 50)

        # Test with the original example (with spaces) - token count might be less due to lstrip
        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertTrue(cut)
        self.assertTrue(cut_text.endswith("so the answer is 4"))
        self.assertLessEqual(tok.count(cut_text), 50)
        self.assertGreaterEqual(tok.count(cut_text), 49)  # might lose one token to lstrip
```

But note: the token count for the space example might be less than 50 because of the lstrip, but we don't want to rely on that. The main point is to catch the off-by-one.

Alternatively, we can have two tests: one that checks the exact count for a non-space string, and one that checks the bound for a space string.

However, to keep the test simple, we can just add the non-space test and leave the space test as is (which only checks upper bound).

But the original test for the space example was only checking the upper bound, which is still valid.

So I'll propose:

1. Fix the off-by-one in `truncate_thought`.
2. Add a test that uses a non-space string to verify the token count is exactly `max_tokens`.

Let's write the follow-up commit.

Commit message:

```
Fix off-by-one in truncate_thought, add test

The truncate_thought function was keeping max_tokens-1 tokens instead of
max_tokens due to an off-by-one in the slice. Fixed by using
`ids[len(ids)-max_tokens:]`.

Added a test with a non-space string to verify the token count is exactly
max_tokens (since lstrip won't remove any tokens in that case).

SFT-441
```

Now, the diff:

- In `sfttrain/templates.py`, change the slice in `truncate_thought`.
- In `tests/test_templates.py`, add a test case for non-space string.

Let's write the diff.
