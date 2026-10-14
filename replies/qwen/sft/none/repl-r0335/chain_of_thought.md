We are given a chain of 10 commits in the `refactor-pipeline` branch of the `sfttrain` repo.
 We are to review the commits for correctness, fix any bugs, and propose optimizations.
 Then, we must reply with a single follow-up commit that applies on top of the last commit.

 Steps:
 1. Review the entire commit chain to understand the changes.
 2. Identify any bugs, inefficiencies, or areas for improvement.
 3. Propose a follow-up commit that fixes bugs and/or optimizes the code.

 Let's go through the commits:

 Commit a41c7e9: Adds the jobs_v2 client (v2 API for training jobs). This is a new backend.
   - Introduces dataclasses for the job spec and a client to submit jobs.
   - The validation in `JobSpec.validate` seems correct.

 Commit 0d93b52: Changes the `launch` command to use the new v2 API and deprecates the v1 trainer.
   - Updates the CLI to use `JobsClient` and `launch` (with `train` as an alias).
   - The `spec_from_config` function maps the model config to the job spec.

 Commit 7be2f10: Changes the model config to use nested tables (optimizer and schedule) to match jobs_v2.
   - Migrates the model configs to have `[model.optimizer]` and `[model.schedule]` sections.
   - Adds a migration function `migrate_legacy` for old flat configs.

 Commit c58a0d4: Changes to use raw model reasoning instead of summaries for training.
   - Introduces `thought_source` in the data config (raw, summary, none).
   - Updates the reasoning selection logic.

 Commit 93e1b6f: Introduces chat_v3 template and truncates reasoning to `max_thought_tokens`.
   - The `truncate_thought` function keeps the end of the reasoning (where the answer is settled).
   - The `thought_truncated` flag is set when truncation occurs.

 Commit 1fa4d27: Adds two new model configs (kestrel-4-27b and research-agent-v5).
   - Updates the README to document deployment.
   - Adds a function `find_model_config` to accept config names.

 Commit e6077c8: Adds a roundtrip check in the tokenizer to detect text that changes on encode-decode.
   - The `LocalTokenizer.roundtrip` method checks if the text survives the round trip.

 Commit 5c2b9a1: Adds a filter to drop examples that fail the detokenization round trip.
   - The `DetokFilter` is inserted before the length filter.

 Commit b30f6e5: Changes the build order: filter and split before upsampling, and adds per-source stats.
   - Now loads unique records per source, filters, splits, then applies weights to training split only.
   - Also optimizes by storing the token count from the detok filter for the length filter.

 Commit 4d81c3a: Adds end-to-end build tests and updates the README.

 Now, let's look for potential issues:

 1. In commit b30f6e5, the build order was changed to filter and split before upsampling. However, note that in `sfttrain/filters.py`:

    ```python
    def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
                        tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
        filters: list[Filter] = [
            EmptyResponseFilter(),
            FlaggedFilter(),
            QualityFilter(min_quality),
        ]
        if detok_check:
            filters.append(DetokFilter(tokenizer))
        filters.append(LengthFilter(max_seq_len, tokenizer))
        if dedup:
            filters.append(DedupFilter())
        return filters
    ```

    The `DetokFilter` sets `ex.n_tokens` (the total tokens for the example) as the sum of the tokens in prompt and target. Then, the `LengthFilter` uses `ex.n_tokens` if it's non-zero, otherwise it recalculates.

    However, note that in `DetokFilter`:

    ```python
    def keep(self, ex: Example) -> bool:
        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                ... # return False on first failure
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens  # LengthFilter reuses this
        return True
    ```

    This sets `ex.n_tokens` only for examples that pass the detok filter. But what about examples that fail? They are dropped, so it doesn't matter for the length filter. However, the length filter is only applied to examples that passed the detok filter (if detok_check is on). So this is safe.

    But note: the `DetokFilter` is only added if `detok_check` is True. If `detok_check` is False, then `ex.n_tokens` is never set by the detok filter. Then the length filter will recalculate it. So that's correct.

 2. However, there is a potential issue in the `LengthFilter`:

    ```python
    def keep(self, ex: Example) -> bool:
        if not ex.n_tokens:
            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
        return ex.n_tokens <= self.max_tokens
    ```

    The condition `if not ex.n_tokens` will be true if `ex.n_tokens` is 0 (which is a valid token count for an empty example). But note: an empty example would have been caught by `EmptyResponseFilter` (which checks for empty response) and `EmptyResponseFilter` runs before the length filter. So it's unlikely to have an example with 0 tokens that reaches the length filter. However, it's still possible that an example has 0 tokens? Actually, the prompt might be non-empty but the target empty? But the `EmptyResponseFilter` checks for empty response (which is the target). So if the target is empty, it's dropped by `EmptyResponseFilter`. Therefore, the examples that reach the length filter have non-empty target? Not necessarily: the `EmptyResponseFilter` only checks the response (target) for being empty. The prompt might be empty? But the system preamble is added so the prompt should never be empty.

    However, to be safe, we should not rely on `ex.n_tokens` being non-zero meaning it's set. Instead, we could have a separate flag or just recalculate if we don't trust the value. But the current design sets `ex.n_tokens` in the detok filter for passing examples, and for failing examples they are dropped so we don't care. And if detok_check is off, then we recalculate.

    But note: the `DetokFilter` sets `ex.n_tokens` for every example that passes (even if detok_check is on, but the example passes). So for examples that pass the detok filter, `ex.n_tokens` is set. For examples that fail, they are dropped so we don't see them in the length filter. And if detok_check is off, then `ex.n_tokens` is not set by any filter before the length filter, so the length filter recalculates.

    So the current code is safe.

 3. Another issue: in commit 93e1b6f, the `truncate_thought` function is defined as:

    ```python
    def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
        ids = tokenizer.encode(text)
        if len(ids) <= max_tokens:
            return text, False
        return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
    ```

    Note: `ids[len(ids) - max_tokens + 1:]` will take the last `max_tokens - 1` tokens? Because the slice from `start` to the end has length `len(ids) - start`. We want the last `max_tokens` tokens.

    Example: 
        len(ids) = 100, max_tokens = 10
        start = 100 - 10 + 1 = 91
        slice: [91:100] -> 9 tokens.

    Correction: to get the last `max_tokens` tokens, we should do:

        start = max(0, len(ids) - max_tokens)
        return tokenizer.decode(ids[start:]).lstrip(), len(ids) > max_tokens

    Also note: the function returns `True` for truncated even if the text is exactly `max_tokens`? Actually, if `len(ids) == max_tokens`, then we return the whole text and `False`. So the condition is `len(ids) > max_tokens` for truncation.

    But in the current code, if `len(ids) == max_tokens`, then we return the whole text and `False` (correct). If `len(ids) > max_tokens`, we take a slice that is `max_tokens - 1` long? That's a bug.

    Let me fix:

        if len(ids) <= max_tokens:
            return text, False
        start = len(ids) - max_tokens
        return tokenizer.decode(ids[start:]).lstrip(), True

    Why `start = len(ids) - max_tokens`? 
        We want `max_tokens` tokens: from `start` to `len(ids)-1` (inclusive) -> that's `len(ids) - start` tokens.
        Set `len(ids) - start = max_tokens` -> `start = len(ids) - max_tokens`.

    Example: 
        len(ids)=100, max_tokens=10 -> start=90, slice [90:100] -> 10 tokens.

    Also note: the function does `.lstrip()` on the decoded text. This is to remove any leading whitespace that might have been introduced by the tokenizer? But note: the reasoning text might have leading whitespace that is meaningful? However, the reasoning is typically a sequence of steps and we are keeping the end, so the beginning of the kept part might be in the middle of a step. Removing leading whitespace is probably safe.

    However, the bug is that we are taking one token less than intended.

 4. In the same commit, in `render`:

    ```python
    if ex.thought:
        thought = ex.thought
        if tokenizer is not None:
            thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
        target += t.thought_open + thought + t.thought_close
    ```

    Note: `max_thought_tokens` is passed as the third argument to `truncate_thought`. But in the function definition, the third argument is `max_tokens`. So that's correct.

    However, the bug in `truncate_thought` (taking one token less) means that we are truncating to `max_tokens-1` tokens.

 5. Also, in the `truncate_thought` function, the condition for truncation should be `len(ids) > max_tokens` (not `>=` because if equal we don't truncate). But the current condition is `if len(ids) <= max_tokens: return ...` so the else branch is for `len(ids) > max_tokens`. That part is correct.

 6. Another issue: the `truncate_thought` function uses `tokenizer.decode(ids[len(ids) - max_tokens + 1:])` which is off by one. We want `len(ids) - max_tokens` as the start index.

 7. In commit b30f6e5, the build process now sets `n_truncated` by summing `ex.thought_truncated` for every example in the source. However, note that `thought_truncated` is set in `render` (which is called per example) and then the example is passed through filters. But the filters might drop the example. However, the manifest counts `thoughts_truncated` as `n_truncated` which is the sum over all examples (even those that are later dropped). Is that intended?

    The manifest field is called `"thoughts_truncated"`, and it's defined as the number of examples that had their thought truncated. It doesn't matter if the example is later dropped by a filter? Actually, the truncation happens during rendering (before filtering). So we are counting every example that had truncation, even if it gets dropped later.

    This might be acceptable because the truncation is done on the raw record. But note: the problem of long reasoning is independent of the filters. However, the README says: "Reasoning longer than the model's `max_thought_tokens` is cut from the front." and the manifest field is for monitoring.

    But the current code in `build.py`:

        for name, examples in per_source.items():
            for ex in examples:
                ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                        model_cfg.max_thought_tokens)
                n_truncated += ex.thought_truncated

    So it counts truncation for every example (including those that will be dropped). This is consistent with the previous version (which summed over `examples` before filtering). So it's by design.

 8. However, the bug in `truncate_thought` (off-by-one) is critical and should be fixed.

 9. Also, note that in `truncate_thought`, we are doing:

        return tokenizer.decode(ids[start:]).lstrip(), True

    But what if the decoding of the token IDs does not exactly reconstruct the original string? We are relying on the tokenizer to be reversible? Actually, the tokenizer is not necessarily reversible (as we know from the detok filter). However, we are truncating the token IDs and then decoding. This is the best we can do. The `lstrip` is to clean up any extra space at the beginning.

    But note: the detok filter will run later and might drop the example if the decoded text doesn't match the original? However, the truncation happens on the reasoning text (which is part of the target). The detok filter will check the entire target (which includes the reasoning block and the answer). So if the truncation causes a detok failure, the example will be dropped. That's acceptable.

 10. Another issue: in `truncate_thought`, the condition `if len(ids) <= max_tokens` is correct, but note that `max_tokens` might be 0? But the model config has `max_thought_tokens` defaulting to 6144 (for kestrel-3) and 4096/8192 for others. And in `ModelConfig`, `max_thought_tokens` is set to 6144 by default. So it's positive.

 11. However, what if `max_tokens` is 0? We should avoid that. But the model config validation (in `jobs_v2.py`) doesn't check `max_thought_tokens`. Actually, the `JobSpec` validation doesn't know about `max_thought_tokens` because it's not part of the job spec. It's a build-time parameter. So we don't validate it. But in the `truncate_thought` function, if `max_tokens` is 0, then we would take the last 0 tokens? That would be an empty string. And the condition `len(ids) <= 0` would only be true for empty text. But the reasoning text might be non-empty. So we should handle `max_tokens <= 0` as an error? Or clamp to 1? However, the model config has a positive default and the configs we have are positive. But to be safe, we can clamp to at least 1.

     However, the problem is that the function is called with `max_thought_tokens` from the model config, which is at least 1 (because the model config has a positive default and the configs set positive values). So we can assume `max_tokens >= 1`.

 12. Proposed fix for `truncate_thought`:

        def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
            ids = tokenizer.encode(text)
            if len(ids) <= max_tokens:
                return text, False
            start = len(ids) - max_tokens
            return tokenizer.decode(ids[start:]).lstrip(), True

 13. But note: the function `tokenizer.decode(ids)` might not be the identity for the entire string? However, we are truncating the token IDs and then decoding. This is the standard way.

 14. Also, the `.lstrip()` might remove too much? For example, if the reasoning starts with a space that is meaningful? But the reasoning is typically a sequence of steps and we are keeping the end, so the beginning of the kept part might be in the middle of a step. Removing leading whitespace is probably safe and desired (to avoid having a space at the beginning of the block).

 15. Another issue: in `truncate_thought`, we are decoding the token IDs and then stripping. But what if the tokenization of the reasoning text has leading whitespace that is part of a token? The `.lstrip()` might break the token. However, the tokenizer we are using (a simple one) is character-based? Actually, the `LocalTokenizer` is a mock tokenizer for the purpose of token counting and detok checks. It's not the real tokenizer. But the real tokenizer might have different behavior. However, the purpose of this truncation is to avoid exceeding the model's context window. We are using the same tokenizer that we use for the detok check and for length filtering. So it's consistent.

 16. However, note that the `LocalTokenizer` is not the real tokenizer. It's a simplified version that only handles ASCII and some special tokens. But the real tokenizer might be different. But the pipeline uses this tokenizer for all length-related decisions. So it's consistent within the pipeline.

 17. Given the above, the main bug is the off-by-one in `truncate_thought`.

 18. Let's check the tests: commit 4d81c3a added tests, but we don't see a specific test for truncation. There is a test in `tests/test_templates.py`:

        def test_long_thought_keeps_the_end(self):
            tok = LocalTokenizer()
            text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
            cut_text, cut = truncate_thought(text, tok, 50)
            self.assertTrue(cut)
            self.assertTrue(cut_text.endswith("so the answer is 4"))
            self.assertLessEqual(tok.count(cut_text), 50)

    This test might pass even with the off-by-one because it checks the end and the token count. But note: if we truncate to 49 tokens (because of the off-by-one) then `tok.count(cut_text)` would be 49, which is <=50, so the test passes. But we wanted 50. So the test doesn't catch the off-by-one.

    We should adjust the test to check the exact token count.

    Proposed test:

        self.assertEqual(tok.count(cut_text), 50)

    But note: the tokenizer might not be reversible, so the count of the truncated string might not be exactly 50? Actually, the truncation is done on the token IDs, so the token count of the truncated string should be exactly `max_tokens` (unless the tokenizer is not reversible, but in our mock tokenizer it is reversible for ASCII). However, the mock tokenizer is reversible for the text it supports.

    So we can add:

        self.assertEqual(tok.count(cut_text), 50)

    But the current test only checks `<=50`, which would pass for 49.

 19. However, the immediate fix is to correct the off-by-one in `truncate_thought`.

 20. Another issue: in `truncate_thought`, the condition `if len(ids) <= max_tokens` is correct, but note that `max_tokens` might be very large (larger than the token ID list) and we are safe. However, what if `max_tokens` is negative? The model config has a positive default, but if someone sets a negative value, we would get an exception. We should validate the model config for `max_thought_tokens` being positive.

    In `jobs_v2.py`, the `JobSpec` validation doesn't cover `max_thought_tokens` because it's not part of the job spec. But the model config is validated when loaded? Actually, in `config.py`, the `ModelConfig` has `max_thought_tokens` with a default of 6144. We don't have explicit validation for it being positive.

    We could add a validation in `ModelConfig`? But note: the `ModelConfig` is a dataclass and we don't have a `__post_init__` that checks. Alternatively, in `truncate_thought`, we can clamp `max_tokens` to at least 1.

    However, the model config is under our control and we set positive values. But to be safe, we can do:

        max_tokens = max(1, max_tokens)

    But the problem is that if `max_tokens` is 0, then we want to truncate to 0 tokens? That would be an empty string. But the model config should not set 0. So it's better to validate at the model config level.

    Since the model config is loaded from TOML, we could add a check in `model_config_from_dict`:

        if model.get("max_thought_tokens", 6144) <= 0:
            raise ValueError("max_thought_tokens must be positive")

    But note: the `max_thought_tokens` is in the top-level of the model config. We are already validating the model config in `jobs_v2.py`? Actually, the `JobSpec` validation doesn't check it because it's not part of the job spec. The job spec only has the data, optimizer, schedule, etc.

    The `max_thought_tokens` is only used at build time. So it's not part of the job spec. Therefore, we should validate it in the build step? Or in the model config loading.

    Given that it's a model config parameter, we should validate it when loading the model config.

    However, the current code does not. So let's consider adding a validation.

    But note: the commit 7be2f10 introduced `max_thought_tokens` and the configs set positive values. So it's unlikely to be negative. But to be robust, we can add a check in `truncate_thought`:

        if max_tokens <= 0:
            return "", True   # or maybe return the whole text? But max_tokens<=0 means we want 0 tokens? So empty.

    However, the problem is that the tokenizer.encode might return an empty list for empty text, but for non-empty text, we want to truncate to 0 tokens -> empty string.

    But the model config should not set 0. So we'll fix the off-by-one and assume positive.

 21. Given the above, the critical fix is the off-by-one in `truncate_thought`.

 22. Also, note that in the same function, we are using `len(ids) - max_tokens` which might be negative? But the condition `if len(ids) <= max_tokens` ensures that we only get to the else branch when `len(ids) > max_tokens`, so `len(ids) - max_tokens` is positive.

 23. Therefore, the fix is to change the start index to `len(ids) - max_tokens`.

 24. Let's write the follow-up commit:

    Subject: fix: truncate_thought to keep exactly max_tokens tokens

    Body:
      The truncate_thought function was off-by-one: it kept (max_tokens - 1) tokens
      instead of max_tokens. This caused reasoning to be truncated more than intended.

      Also, adjust the test to check the exact token count.

    We'll change:
      - sfttrain/templates.py: fix the start index in truncate_thought.
      - tests/test_templates.py: update the test to check the exact token count.

 25. However, note that the test `test_long_thought_keeps_the_end` currently checks `<=50`. We want to change it to `==50`. But what if the tokenizer is not reversible? In the mock tokenizer, it should be. But the test uses `LocalTokenizer` which is the same as in the function.

    In the test:

        self.assertLessEqual(tok.count(cut_text), 50)

    Change to:

        self.assertEqual(tok.count(cut_text), 50)

 26. But note: the truncation is done on the token IDs, so the token count of the truncated string should be exactly `max_tokens` (50 in the test). However, if the tokenizer is not reversible, it might be different? But our `LocalTokenizer` is reversible for the text it supports (ASCII). The test string is ASCII.

    So it's safe.

 27. Let's write the diff.

 28. Additionally, we should consider if there are other issues. One more:

    In `truncate_thought`, we do:

        return tokenizer.decode(ids[start:]).lstrip(), True

    But what if the decoding of the token IDs produces a string that is not a substring of the original? We are not concerned with that because we are truncating by tokens, not by characters. The detok filter will catch if the entire target (which includes this reasoning block) doesn't roundtrip.

    So it's acceptable.

 29. Proposed commit:

    commit message:
        fix: truncate_thought to keep exactly max_tokens tokens

        The truncate_thought function previously kept (max_tokens - 1) tokens due to
        an off-by-one error in the start index. This caused reasoning to be truncated
        more than intended.

        Also update the test to check the exact token count of the truncated reasoning.

    diff:

        --- a/sfttrain/templates.py
        +++ b/sfttrain/templates.py
        @@ -95,7 +95,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tu
             ids = tokenizer.encode(text)
             if len(ids) <= max_tokens:
                 return text, False
        -    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
        +    start = len(ids) - max_tokens
        +    return tokenizer.decode(ids[start:]).lstrip(), True

        --- a/tests/test_templates.py
        +++ b/tests/test_templates.py
        @@ -50,7 +50,7 @@ class TemplateTests(unittest.TestCase):
                 text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
                 cut_text, cut = truncate_thought(text, tok, 50)
                 self.assertTrue(cut)
                 self.assertTrue(cut_text.endswith("so the answer is 4"))
        -        self.assertLessEqual(tok.count(cut_text), 50)
        +        self.assertEqual(tok.count(cut_text), 50)

 30. But note: the test `test_long_thought_keeps_the_end` is in `tests/test_templates.py` and the function name is `test_long_thought_keeps_the_end`. We are changing the assertion.

 31. However, there is another test: `test_render_marks_truncation` which sets a long thought and checks `ex.thought_truncated`. It doesn't check the token count, so it's unaffected.

 32. Let's write the full diff.

 33. One more thing: the `truncate_thought` function in the current code (in the chain) is:

        def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
            ids = tokenizer.encode(text)
            if len(ids) <= max_tokens:
                return text, False
            return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True

    We change the return line to:

            start = len(ids) - max_tokens
            return tokenizer.decode(ids[start:]).lstrip(), True

 34. Also, note that the test `test_short_thought_is_not_truncated` is unaffected.

 35. Therefore, the follow-up commit is:

        fix: truncate_thought to keep exactly max_tokens tokens

        The truncate_thought function previously kept (max_tokens - 1) tokens due to
        an off-by-one error in the start index. This caused reasoning to be truncated
        more than intended.

        Also update the test to check the exact token count of the truncated reasoning.

        SFT-441

    And the diff.

 36. But note: the issue might have been introduced in commit 93e1b6f (the one that added truncation). So it's a bug that needs fixing.

 37. We'll write the commit accordingly.

 Let's generate the diff block.
