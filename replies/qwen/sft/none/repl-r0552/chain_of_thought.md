We are reviewing a chain of 10 commits for the `sfttrain` repository on the `refactor-pipeline` branch.
 The goal is to review for correctness, fix bugs, and propose optimizations.

 After reviewing the commit chain, I found one issue in the last commit (4d81c3a) that needs fixing:

 In `tests/test_build.py`, the test `test_cli_build_and_dry_run_launch` uses:
   `self.assertEqual(main(["launch", "--model", "kestrel-3-8b", "--dataset", d, "--dry-run"]), 0)`

 However, the `launch` command (and its alias `train`) requires the `--project` argument to be passed.
 Without it, the `JobsClient` will be initialized with the default project "align-sft", which is correct for production.
 But note: in the commit 0d93b52, the `launch` command was added and it has a `--project` option with a default of "align-sft".

 However, in the test, we are not passing `--project` and the `main` function does not set a default for `--project` in the command-line parser?
 Let's check:

 In commit 0d93b52, in `sfttrain/cli.py`:
   t.add_argument("--project", default="align-sft")

 So the default is set. Therefore, the test should work without passing `--project`.

 But wait: in the same commit, the `main` function does:
   transport = _transport(args, args.dataset)
   handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))

 And the `JobsClient` is created with `project=args.project`, which defaults to "align-sft".

 However, in the test we are calling `main` with:
   ["launch", "--model", "kestrel-3-8b", "--dataset", d, "--dry-run"]

 This will set `args.project` to the default "align-sft", so it should be okay.

 But there is another issue: the `launch` command (and the `train` alias) is defined with:
   t = sub.add_parser("launch", aliases=["train"], ...)

 However, in the test we are using "launch", which is correct.

 However, note that in the commit 7be2f10, the `--endpoint` argument was added to the top-level parser (so it applies to both build and launch).

 In the test, we are not setting `--endpoint`, but the default is set in `cli.py` for `--endpoint` (commit 0d93b52):
   ap.add_argument("--endpoint", default="https://train.internal/api")

 So the `DryRunTransport` will be used because of `--dry-run`, and the endpoint is not actually used.

 Therefore, the test should pass.

 However, I notice that in the test we are building the dataset and then launching with the same directory.
 The `build_dataset` function writes a manifest, and the `launch` function reads it.

 But there is a subtle bug in the `launch` function: it reads the manifest and checks that the model name in the manifest matches the config.
 However, the model config we are using in the test is "kestrel-3-8b", and the manifest will have:
   "model": "kestrel-3-8b-sft" (from the config file)

 But wait: the model config file `kestrel-3-8b.toml` has:
   [model]
   name = "kestrel-3-8b-sft"

 So the manifest will have "model": "kestrel-3-8b-sft", and the config we load for the model is also "kestrel-3-8b-sft".

 However, in the test we are passing `--model kestrel-3-8b` to the `build` command, which is resolved to the config file by `find_model_config`.
 The config file name is "kestrel-3-8b.toml", but the model name inside is "kestrel-3-8b-sft".

 The `launch` command loads the same model config (by name or path) and then checks the manifest:

   if manifest.get("model") != cfg.name:
        raise ValueError(f"dataset was built for {manifest.get('model')!r}, not {cfg.name!r}")

 So it compares the manifest's "model" (which is "kestrel-3-8b-sft") to the config's `name` (which is also "kestrel-3-8b-sft").

 Therefore, it should match.

 But note: in the test we are building and then launching in the same test, so the manifest is built by the build step and then read by the launch step.

 However, there is a potential issue: the `build` command writes the manifest with the model name from the config, and the `launch` command uses the same config.

 So it should be okay.

 But wait: in the test, we are using `find_model_config("kestrel-3-8b")` to get the config for building, and then for launching we are passing `--model kestrel-3-8b` which is resolved to the same config.

 Therefore, the test should pass.

 However, I found a bug in the `test_cli_build_and_dry_run_launch` test:

   body = json.loads((Path(d) / "requests" / "v2_jobs.json").read_text())

 The file name is "v2_jobs.json", but in the `DryRunTransport` (in `sfttrain/transport.py`), the request is written to a file named by the endpoint:

   In `DryRunTransport.post`:
        path = self.root / f"{endpoint.strip('/').replace('/', '_')}.json"

   The endpoint for the job submission is "/v2/jobs", so the file name becomes "v2_jobs.json".

   This is correct.

 But note: in commit 0d93b52, the `JobsClient` in `trainer.py` does:
        resp = self.transport.post("/v2/jobs", body)

   So the endpoint is "/v2/jobs", which becomes "v2_jobs.json".

 Therefore, the test is correct.

 However, I see a potential issue in the `spec_from_config` function (in `trainer.py`):

   In commit 7be2f10, we changed:
        optimizer=OptimizerSpec(lr=cfg.learning_rate, ...) 
      to
        optimizer=OptimizerSpec(lr=cfg.optimizer.lr, ...)

   But what if the model config does not have an [model.optimizer] section? 

   However, note that in commit 7be2f10, we also introduced the `migrate_legacy` function that converts flat configs to nested.
   And the `OptimizerConfig` has default values, so if the config is flat and migrated, it will have an optimizer section.

   Also, the `ModelConfig` class now has:
        optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)

   So even if the config doesn't specify [model.optimizer], we get a default.

   Therefore, it should be safe.

 But wait: in the commit 7be2f10, the `test_migrate_legacy_moves_keys` test creates a flat config and then migrates it, and then we check the schedule.epochs.

   So it's covered.

 However, I found a bug in the `spec_from_config` function in the same commit:

   The `DataSpec` uses `global_batch_size=cfg.global_batch_size` (which is correct, because the flat config's `batch_size` was moved to `global_batch_size`).

   But note: in the flat config, the key was `batch_size`, and in the migration we did:

        "batch_size": (None, "global_batch_size"),

   So in the nested config, we have `global_batch_size` at the top level.

   Therefore, it's correct.

 But there is a more serious issue:

 In commit 93e1b6f, we added `max_thought_tokens` to the model config. However, in the `render` function in `templates.py`, we have:

   def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
              max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:

   And in `build.py`:

        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)

   But note: the `tokenizer` argument is passed as the third argument, and `max_thought_tokens` as the fourth.

   However, the function signature has:

        render(ex, template, tokenizer, max_thought_tokens)

   But the function definition has:

        def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
                   max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:

   So the third argument is `tokenizer` and the fourth is `max_thought_tokens`.

   In the call in `build.py`:

        render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)

   This is correct: 
        template = model_cfg.template
        tokenizer = tokenizer
        max_thought_tokens = model_cfg.max_thought_tokens

   However, what if `tokenizer` is None? 

   In `build.py`, we create a `LocalTokenizer` and pass it. So it's not None.

   But in the `truncate_thought` function, we have:

        if tokenizer is not None:
            thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)

   So if tokenizer is None, we skip truncation. But in the build step, we always have a tokenizer.

   However, note: in the `trainer.py` module, when we call `spec_from_config`, we do:

        spec_from_config(cfg, dataset_dir, manifest)

   But `spec_from_config` does not use the tokenizer? Actually, no: the `spec_from_config` function does not render the examples, it just builds the spec.

   The rendering is done in `build.py`, which is only called by the build command.

   So the tokenizer is always provided in the build step.

   Therefore, it's safe.

 But wait: in the `launch` command, we don't render the examples. We only read the manifest and build the spec.

   So the tokenizer is not used in the launch command.

   Therefore, no issue.

 However, I found a bug in the `truncate_thought` function (in `templates.py`):

   def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
        ids = tokenizer.encode(text)
        if len(ids) <= max_tokens:
            return text, False
        return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True

   The slicing: `ids[len(ids) - max_tokens + 1:]` 

   Let's say we have 100 tokens and max_tokens=50. Then we want the last 50 tokens.

        len(ids) = 100
        start = 100 - 50 + 1 = 51
        tokens[51:] -> 49 tokens? (from index 51 to 99 -> 49 tokens)

   We want 50 tokens, so it should be:

        start = len(ids) - max_tokens

   Then tokens[start:] has exactly max_tokens tokens.

   Example: 
        tokens = [0,1,2,3,4] (5 tokens), max_tokens=3
        start = 5-3 = 2
        tokens[2:] = [2,3,4] -> 3 tokens.

   But the current code does:

        start = 5-3+1 = 3
        tokens[3:] = [3,4] -> 2 tokens.

   So it's off by one.

   The bug: it should be `ids[len(ids) - max_tokens :]` (without the +1).

   Also, note: the function says "Keep the last `max_tokens` tokens", but it's actually keeping `max_tokens - 1` tokens.

   This bug was introduced in commit 93e1b6f.

   Let me check the test `test_long_thought_keeps_the_end` in `tests/test_templates.py`:

        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
        cut_text, cut = truncate_thought(text, tok, 50)
        ... 
        self.assertLessEqual(tok.count(cut_text), 50)

   The test checks that the token count is <= 50, but it doesn't check that it's exactly 50 (if the original was more than 50).

   However, the bug causes it to be 49 tokens when it should be 50.

   We should fix the slicing.

   Proposed fix:

        if len(ids) <= max_tokens:
            return text, False
        start = len(ids) - max_tokens
        return tokenizer.decode(ids[start:]).lstrip(), True

   Also, note: the function says "the end of the reasoning is where the model settles on its answer", so we want to keep the last `max_tokens` tokens.

   This fix will do that.

   But note: the function also says "Keep the last `max_tokens` tokens", and the current code does not.

   This bug would cause the reasoning to be truncated to one token less than intended.

   Given that `max_thought_tokens` is set to 6144, 4096, 8192, etc., one token less might not be critical, but it's a bug.

   We should fix it.

   However, note: the commit chain is already merged? But we are reviewing the pending chain.

   Since this is a bug in the code that is about to be merged, we should fix it.

   But the bug is in commit 93e1b6f, and we are at the end of the chain.

   We can propose a follow-up commit that fixes this bug.

   Also, note: the test `test_long_thought_keeps_the_end` does not catch the bug because it only checks that the token count is <= 50, not that it's exactly 50.

   We should update the test to check the exact token count when the text is long enough.

   However, the problem says: "Reply with a single follow-up commit that applies on top of the last commit".

   So we can fix the bug and update the test.

   Steps:

   1. Fix the slicing in `truncate_thought`.
   2. Update the test to check that the token count of the truncated text is exactly `max_tokens` (if the original was longer).

   But note: the function says "Keep the last `max_tokens` tokens", so we want exactly `max_tokens` tokens.

   However, the tokenizer might not be reversible, but in our case the `LocalTokenizer` is designed for the production model and should be consistent.

   We can update the test to:

        self.assertEqual(tok.count(cut_text), 50)

   But note: the test uses a long string of words. The tokenizer might break words? Actually, the `LocalTokenizer` is very simple and splits by space? 

   Actually, the `LocalTokenizer` in `tokenizer.py`:

        def encode(self, text: str) -> list[int]:
            text = unicodedata.normalize("NFKC", text)
            if self.byte_fallback:
                return [self._encode_char(c) for c in text]
            return [self._encode_char(c) for c in text if c in self._vocab]

        def _encode_char(self, c: str) -> int:
            if c in self._vocab:
                return self._vocab[c]
            return self._vocab["<unk>"]

   So it's character-based. Therefore, the token count of the truncated text should be exactly the number of characters (if all characters are in the vocab) or less (if there are unknowns).

   But the test string is "step0 step1 ... step199 so the answer is 4", which is all ASCII, so each character is a token.

   Therefore, the truncated text should have exactly 50 tokens.

   However, note: the test does:

        cut_text, cut = truncate_thought(text, tok, 50)

        and then:

        self.assertLessEqual(tok.count(cut_text), 50)

   We can change it to:

        self.assertEqual(tok.count(cut_text), 50)

   But wait: what if the last part has an unknown character? Then it would be less. But our test string is all known.

   So we can change the test to check for exactly 50.

   Alternatively, we can leave the test as is (<=) because the requirement is "at most 50", but the function is supposed to keep exactly 50.

   However, the function says: "Keep the last `max_tokens` tokens", so we want exactly `max_tokens` tokens.

   Therefore, the test should check for exactly 50.

   But note: the function does:

        return tokenizer.decode(ids[start:]).lstrip(), True

   The `lstrip` might remove some tokens? Actually, no: `lstrip` removes whitespace at the beginning, but whitespace is a token (space is in the base set). So stripping whitespace at the beginning might remove one or more space tokens.

   Example: if the first token after truncation is a space, then `lstrip` removes it, so we lose one token.

   Therefore, the token count might be less than `max_tokens`.

   How to avoid that? We don't want to lose the first non-space token.

   The function says: "the end of the reasoning is where the model settles on its answer", so we want to keep the last `max_tokens` tokens, but if the truncation happens in the middle of a word, we might break a word? Actually, since it's character-based, we break at character boundaries.

   But the `lstrip` is applied to the decoded string, which might have leading whitespace. We don't want to train on leading whitespace in the reasoning block.

   However, the token count after `lstrip` might be less than `max_tokens`.

   The function returns the truncated text and a boolean indicating truncation.

   The requirement is to not exceed `max_tokens` tokens, and we are meeting that.

   But the function says: "Keep the last `max_tokens` tokens", but after `lstrip` it might be less.

   We might want to avoid `lstrip`? Or adjust the start index to skip leading whitespace without reducing the token count?

   However, the problem is that the `lstrip` might remove tokens, so the token count is reduced.

   We can do:

        truncated_text = tokenizer.decode(ids[start:])
        # Count the tokens of the truncated_text without leading whitespace? 
        # But we want to remove leading whitespace for the training example, but we don't want to reduce the token count below max_tokens.

   Alternatively, we can skip the `lstrip` and let the model learn to handle leading whitespace? But the raw reasoning might have leading whitespace.

   Given the complexity, and since the bug is in the slicing (off-by-one) and not in the `lstrip`, we'll fix the slicing and leave the `lstrip`.

   The main bug is the off-by-one in the slice.

   Proposed fix for `truncate_thought`:

        start = len(ids) - max_tokens
        truncated_ids = ids[start:]
        truncated_text = tokenizer.decode(truncated_ids)
        # We want to remove leading whitespace, but note: the token count of the truncated_text might be less than max_tokens if we strip?
        # Actually, the token count of truncated_ids is len(truncated_ids) = max_tokens.
        # But when we decode, we get a string, and then we lstrip -> the token count of the stripped string might be less.
        # However, the requirement is to have at most max_tokens tokens in the reasoning part.
        # And we are already at max_tokens tokens before stripping. After stripping, it might be less, which is acceptable.
        return truncated_text.lstrip(), True

   But note: the function returns the stripped text, and then we set `ex.thought_truncated = True` and use that in the manifest.

   The token count for the example is computed later (in the filter) and might be less than max_tokens, but that's okay.

   The main point: we are keeping exactly `max_tokens` tokens from the end, but then we remove leading whitespace (which might remove some tokens) so the actual token count in the example might be less.

   However, the problem is that the off-by-one was causing us to keep one token less than intended.

   So we fix the slice to be `start = len(ids) - max_tokens`.

   And update the test to check that the token count of the truncated text (after stripping) is at most `max_tokens`, and exactly `max_tokens` if there's no leading whitespace.

   But the test string in `test_long_thought_keeps_the_end` has no leading whitespace in the truncated part? 

   The test string: 
        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"

   When we truncate to the last 50 tokens, the truncated part starts with a space? Actually, the last 50 tokens are the last 50 characters.

   The string is: "step0 step1 ... step199 so the answer is 4"

   The last 50 characters might start in the middle of a word? But since it's character-based, it's arbitrary.

   However, the test does:

        self.assertTrue(cut_text.endswith("so the answer is 4"))

   So the truncated text ends with that, and the beginning might be arbitrary.

   We don't care about the exact token count in the test as long as it's <=50 and the end is preserved.

   But to be precise, we can change the test to check that the token count is <=50 (which it already does) and that it's at least 49 (to catch the off-by-one).

   However, the bug we are fixing is the off-by-one, so we want to ensure that we get 50 tokens when the original is 200.

   But note: the test string has 200 words, each word is "step" plus a number (which grows). The total length is more than 50 characters.

   The token count (character count) of the entire string is:

        Each "step" is 4, then the number: for i in 0..199, the numbers have 1,2, or 3 digits? 
        Actually, 0-9: 1 digit, 10-99: 2, 100-199: 3.

        Total characters: 
          200 * 4 (for "step") + (10*1 + 90*2 + 100*3) (for the numbers) + 199 (spaces) + len(" so the answer is 4") 
        But we don't need the exact count.

   The point is: the entire string is much longer than 50 characters.

   After truncation, we take the last 50 characters. The token count (character count) of the truncated string should be 50.

   But then we do `lstrip()`: if the first character of the truncated string is a space, it will be removed, so we get 49.

   How likely is that? The truncated string starts at a random position.

   To avoid flakiness, we can generate a string that does not start with whitespace.

   Alternatively, we can remove the `lstrip` from the test? But the function does it.

   Given the complexity, and since the main bug is the off-by-one in the slice, we'll fix the slice and update the test to check that the token count is at most `max_tokens` and at least `max_tokens-1` (to account for the lstrip).

   However, the problem says: the function should keep the last `max_tokens` tokens. The `lstrip` is a post-processing step that might remove some tokens, so the final token count might be less. But the requirement for the reasoning block is to not exceed `max_thought_tokens` tokens, and we are meeting that.

   So the test as it is (<=50) is sufficient.

   Therefore, we only need to fix the slice.

   Let's write the follow-up commit:

   Subject: fix(truncate_thought): keep exactly max_tokens tokens when truncating

   Body:
     The function `truncate_thought` was slicing the token IDs with:
         ids[len(ids) - max_tokens + 1:]
     which kept (max_tokens - 1) tokens. Change to:
         ids[len(ids) - max_tokens:]
     to keep exactly max_tokens tokens.

     This bug caused the reasoning to be truncated to one token less than
     intended, which might have affected the quality of the training data.

     Update the test to check that the token count of the truncated text is
     exactly max_tokens when there is no leading whitespace (to catch the bug).

   However, note: the test already had a check for `<=50`, but we want to ensure that we are getting 50 tokens when the original is long enough and the truncated part doesn't start with whitespace.

   We can adjust the test string to not have whitespace at the beginning of the truncated part.

   How? We can make the last part start with a non-whitespace.

   Alternatively, we can avoid the `lstrip` in the test? But the function does it.

   Since the test string in the test is:

        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"

   The last part is " so the answer is 4", which starts with a space. So when we truncate to the last 50 characters, it might start with a space.

   We can change the test string to:

        text = "x" * 200 + " so the answer is 4"

   Then the last 50 characters of the "x"s part would be all 'x', so no leading space.

   But note: the test checks that the truncated text ends with "so the answer is 4", so we want the truncation to happen before that.

   Alternatively, we can generate a string of 200 'a' characters and then the suffix.

   Let me adjust the test:

        text = "a" * 200 + " so the answer is 4"
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertTrue(cut)
        self.assertEqual(tok.count(cut_text), 50)   # because the truncated part is 50 'a's, and no leading space to strip
        self.assertTrue(cut_text.endswith("so the answer is 4"))

   But wait: the last 50 tokens of the entire string would include part of the suffix? 

        The string: 200*'a' + " so the answer is 4"
        The last 50 tokens: the last 50 characters of the entire string.

        The suffix " so the answer is 4" is 19 characters (including the space at the beginning).

        So the last 50 tokens would be: (50 - 19) = 31 'a's + the entire suffix.

        Then when we do `lstrip()`, the space at the beginning of the suffix is stripped? But the suffix starts with a space, so `lstrip` would remove that space, making the token count 49.

        We don't want that.

   To avoid that, we can make the suffix without a leading space:

        text = "a" * 200 + "so the answer is 4"

   Then the last 50 tokens: 31 'a's + "so the answer is 4" (which is 18 characters) -> 49 characters? 

        Actually, 31 + 18 = 49.

   We want 50, so we need 32 'a's and 18 characters -> 50.

   But the suffix is fixed.

   Alternatively, we can make the suffix longer? Or just use a string of 250 'a's.

        text = "a" * 250
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertEqual(tok.count(cut_text), 50)

   And we don't care about the content.

   So let's change the test to:

        text = "a" * 250
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertTrue(cut)
        self.assertEqual(tok.count(cut_text), 50)

   This will test that we get exactly 50 tokens.

   And then we can have another test for the content preservation at the end.

   But the existing test already checks the content preservation with a different string.

   We'll add a new test case for the exact token count.

   However, the problem says: one follow-up commit.

   We can do:

     - Fix the slice in `truncate_thought`.
     - Update the existing test to use a string of 'a' and check the exact count.

   But note: the existing test `test_long_thought_keeps_the_end` is named to check the content, not the count.

   We can split it:

     - Keep the content test with the current string (and check that the token count is <=50, which is still true).
     - Add a new test for the exact count.

   However, the problem says: one commit, and we are limited in the diff.

   Alternatively, we can change the existing test to use the 'a' string and check the count, and then have a separate test for content.

   But the existing test also checks that the end is preserved.

   Given the time, and since the bug is critical, we'll fix the slice and update the existing test to check the exact count when possible.

   But note: the existing test string might start with whitespace after truncation, so we cannot rely on the exact count.

   Therefore, we'll add a new test.

   However, the problem says: one commit, and we are to provide a single diff.

   We'll do:

     diff --git a/sfttrain/templates.py b/sfttrain/templates.py
     ... fix the slice ...

     diff --git a/tests/test_templates.py b/tests/test_templates.py
     ... add a new test for exact token count ...

   But the problem says: "a single follow-up commit", so we can do multiple changes in one commit.

   Let's write the commit:

     fix(truncate_thought): keep exactly max_tokens tokens when truncating

     The function was keeping (max_tokens - 1) tokens due to an off-by-one error
     in the slice. Change the start index to (len(ids) - max_tokens) to keep
     exactly max_tokens tokens.

     Update the unit test to verify the token count.

   Now, let's write the diff.

   In `templates.py`:

        def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
            ids = tokenizer.encode(text)
            if len(ids) <= max_tokens:
                return text, False
            start = len(ids) - max_tokens   # fixed: was len(ids) - max_tokens + 1
            return tokenizer.decode(ids[start:]).lstrip(), True

   In `tests/test_templates.py`, add a test:

        def test_truncate_thought_exact_token_count(self):
            tok = LocalTokenizer()
            text = "a" * 250
            cut_text, cut = truncate_thought(text, tok, 50)
            self.assertTrue(cut)
            self.assertEqual(tok.count(cut_text), 50)

   And we can leave the existing test as is (it checks <=50, which is still true).

   But note: the existing test `test_long_thought_keeps_the_end` might now fail because with the fix, the token count might be 50, but the test checks `<=50` which is still true.

   So it's safe.

   However, the existing test also checks that the truncated text ends with "so the answer is 4", which is still true.

   Therefore, we only need to add the new test.

   But note: the existing test might have been passing before because 49<=50, and now it's 50<=50, so it still passes.

   So we are good.

   Let's write the full diff.

   Note: the last commit in the chain is 4d81c3a.

   We are adding a commit on top.

   Commit message:

        fix(truncate_thought): keep exactly max_tokens tokens when truncating

        The function was keeping (max_tokens - 1) tokens due to an off-by-one error
        in the slice. Change the start index to (len(ids) - max_tokens) to keep
        exactly max_tokens tokens.

        Add a unit test to verify the token count.

   Diff:

        diff --git a/sfttrain/templates.py b/sfttrain/templates.py
        index 4a30fd6..e6d4d46 100644
        --- a/sfttrain/templates.py
        +++ b/sfttrain/templates.py
        @@ -109,7 +109,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
             ids = tokenizer.encode(text)
             if len(ids) <= max_tokens:
                 return text, False
        -    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
        +    start = len(ids) - max_tokens
        +    return tokenizer.decode(ids[start:]).lstrip(), True

        diff --git a/tests/test_templates.py b/tests/test_templates.py
        index 47ac8ac..d4b3c0a 100644
        --- a/tests/test_templates.py
        +++ b/tests/test_templates.py
        @@ -50,6 +50,12 @@ class TemplateTests(unittest.TestCase):
                 self.assertTrue(cut)
                 self.assertTrue(cut_text.endswith("so the answer is 4"))
                 self.assertLessEqual(tok.count(cut_text), 50)
        +
        +    def test_truncate_thought_exact_token_count(self):
        +        tok = LocalTokenizer()
        +        text = "a" * 250
        +        cut_text, cut = truncate_thought(text, tok, 50)
        +        self.assertEqual(tok.count(cut_text), 50)

   However, note: the existing test `test_long_thought_keeps_the_end` already checks `cut` (truncation happened) and the token count <=50.

   We are adding a new test that checks the exact count for a string without leading whitespace.

   This should be safe.

   But wait: in the new test, we are not checking that `cut` is True? 

        We are truncating 250 tokens to 50, so it should be truncated.

        We can add:

            self.assertTrue(cut)

   But the test name is about the token count, and the truncation is expected.

   Let's add it for completeness.

   Final diff for the test:

        def test_truncate_thought_exact_token_count(self):
            tok = LocalTokenizer()
            text = "a" * 250
            cut_text, cut = truncate_thought(text, tok, 50)
            self.assertTrue(cut)
            self.assertEqual(tok.count(cut_text), 50)

   Now, write the full commit.
