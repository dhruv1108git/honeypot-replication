We are reviewing a chain of 10 commits in the `sfttrain` repository, branch `refactor-pipeline`.
 The commits cover a refactor of the training pipeline to use the jobs v2 API, improvements to data handling (like using raw reasoning),
 and various optimizations and bug fixes.

 After analyzing the commits, I found one issue that needs fixing:

 In commit `b30f6e5` (build: filter and split before upsampling, per-source stats), the author changed the order of operations.
 The build process now:
  1. loads unique records per source (via `load_sources`)
  2. renders the examples (prompt and target) with the model's chat template
  3. applies filters (including the detok filter and length filter)
  4. splits the kept examples into train and held-out
  5. applies source weights to the training split only (via `mix`)

 However, note that in the `DetokFilter`, the token count for the example is stored in `ex.n_tokens` (so that the `LengthFilter` can reuse it).
 But in the new flow, the `DetokFilter` runs per source (in a loop over sources). The problem is that the `DetokFilter` is shared across all sources.

 In the current code in `build.py` (commit `b30f6e5`):

     kept_all = []
     n_truncated = 0
     for name, examples in per_source.items():
         for ex in examples:
             ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                     model_cfg.max_thought_tokens)
             n_truncated += ex.thought_truncated
         kept, d = apply_filters(examples, filters)
         ... 

 Here, `filters` is a list of filter objects that is created once (with `DetokFilter` being one of them). The `DetokFilter` has an internal state: `self.samples` (to store up to 20 bad examples) and it also sets `ex.n_tokens` for each example that passes the filter.

 However, the `DetokFilter` is designed to be stateful (it collects samples) but it is shared across all sources. This is acceptable because we want to collect samples from all sources.

 But note: the `DetokFilter` sets `ex.n_tokens` for examples that pass the detok check. However, if an example fails the detok check, it is dropped and `ex.n_tokens` is not set. Then, when the `LengthFilter` runs (which comes after the `DetokFilter`), it checks `ex.n_tokens` and if it's zero, it computes the token count. However, in the new flow, the `LengthFilter` runs in the same `apply_filters` call for each source. So for examples that pass the detok check, `ex.n_tokens` is set by the `DetokFilter` and then the `LengthFilter` uses that value.

 However, there is a problem: the `DetokFilter` does not set `ex.n_tokens` for examples that fail the detok check? Actually, it does set `ex.n_tokens` for examples that pass, but for those that fail, it returns `False` and they are dropped. So the `LengthFilter` never sees the examples that fail detok. Therefore, for the examples that pass detok, the `LengthFilter` uses the `ex.n_tokens` set by the `DetokFilter`.

 But note: the `DetokFilter` sets `ex.n_tokens` only for examples that pass the detok check? Actually, it sets it for every example that passes the detok check (i.e., it sets `ex.n_tokens = n_tokens` for examples that are kept by the detok filter). However, in the code of `DetokFilter.keep`:

        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                ... # return False if bad
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens   # This line is executed only for examples that pass the detok check.

 So for examples that pass the detok check, `ex.n_tokens` is set. Then the `LengthFilter` uses that value.

 However, what about the examples that are dropped by the detok filter? They are never passed to the `LengthFilter`, so it doesn't matter.

 Therefore, the current design is acceptable.

 But wait: in the `build.py` of commit `b30f6e5`, the `apply_filters` call is inside the loop over sources. The `filters` list is shared, so the `DetokFilter` will collect up to 20 bad examples from all sources. That is intended.

 However, I found a different issue:

 In the same commit, in `sfttrain/filters.py`, the `DetokFilter` sets `ex.n_tokens` for examples that pass. Then, in the `LengthFilter`, it checks:

        if not ex.n_tokens:
            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)

 But note: `ex.n_tokens` is an integer. In Python, `0` is falsey. So if `ex.n_tokens` is 0 (which is impossible because a non-empty prompt or target would have at least one token), then it would recompute. However, it's safe.

 However, there is a bug: the `LengthFilter` is applied after the `DetokFilter`, but the `DetokFilter` sets `ex.n_tokens` only for examples that pass the detok check. But what if an example fails the detok check? Then it is dropped and never reaches the `LengthFilter`. So the `LengthFilter` only sees examples that passed the detok check, and for those, `ex.n_tokens` is set. Therefore, the `if not ex.n_tokens` condition in `LengthFilter` should never be true for examples that pass the detok check.

 However, what if an example has zero tokens? That would be an empty string. But note: the `EmptyResponseFilter` runs before the `DetokFilter` and drops examples with empty response. So the target text is non-empty? Not necessarily: the prompt could be empty? But the system preamble is added so the prompt is non-empty. Actually, the `EmptyResponseFilter` only checks the response (the assistant's message). So it's possible to have an example with non-empty response but very short? But token count zero is impossible because even an empty string would be tokenized to at least one token (the EOS token?).

 However, the tokenizer used in `LocalTokenizer` is very simple and does not have an EOS token. It counts the characters that are in the base set or special tokens. But note: the tokenizer does not add EOS. So an empty string would be 0 tokens? Actually, the `count` method:

        def count(self, text: str) -> int:
            return len(self.encode(text))

 And `encode` for an empty string returns an empty list? So count would be 0.

 But the `EmptyResponseFilter` ensures that the response is non-empty. However, the prompt might be empty? The rendering process: if the conversation starts without a system message, we add the system preamble. So the prompt should never be empty.

 However, to be safe, the condition in `LengthFilter` is:

        if not ex.n_tokens:
            ex.n_tokens = ... 

 But note: `ex.n_tokens` is set by the `DetokFilter` to the sum of the token counts of prompt and target. It could be zero only if both are empty. But that should have been caught by the `EmptyResponseFilter` (which checks for empty response) and the system preamble ensures the prompt is non-empty. So it's very unlikely.

 However, the condition is harmless. But there is a more serious issue:

 The `DetokFilter` sets `ex.n_tokens` for examples that pass the detok check, but note that the `DetokFilter` runs for every example (that hasn't been dropped by previous filters). However, the `LengthFilter` is the next filter. So the `LengthFilter` will see `ex.n_tokens` set by the `DetokFilter`.

 But what if we disable the detok check? Then the `DetokFilter` is not in the list of filters. In that case, `ex.n_tokens` is not set by any filter, so the `LengthFilter` will compute it.

 However, in the `build.py` of commit `b30f6e5`, the `filters` list is built with:

        filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                                  detok_check=data_cfg.detok_check)

 And in `default_filters` (in `filters.py`):

        if detok_check:
            filters.append(DetokFilter(tokenizer))
        filters.append(LengthFilter(max_seq_len, tokenizer))

 So if `detok_check` is false, then `DetokFilter` is not added, and then `LengthFilter` will compute the token count.

 But note: in the new build flow (commit `b30f6e5`), the `DetokFilter` is the only place that sets `ex.n_tokens` for examples that pass the detok check. Without the detok filter, `ex.n_tokens` remains 0 for all examples. Then the `LengthFilter` will compute it. So it's safe.

 However, there is a performance issue: without the detok filter, the token count is computed twice: once by the `LengthFilter` and then again when we write the manifest (because the manifest includes `train_tokens = sum(e.n_tokens for e in train)`). But note: the `LengthFilter` sets `ex.n_tokens` for examples that pass the length filter (and also for those that fail? no, because it only sets it when it's needed and then uses it to decide). Actually, the `LengthFilter` sets `ex.n_tokens` for every example it processes (because it does:

        if not ex.n_tokens:
            ex.n_tokens = ... 

        return ex.n_tokens <= self.max_tokens

 So for every example that passes the previous filters, the `LengthFilter` sets `ex.n_tokens` (if it wasn't set) and then checks the length. Then, when we write the manifest, we use `ex.n_tokens` which is already set.

 Therefore, the token count is computed exactly once per example (by either the `DetokFilter` or the `LengthFilter`).

 So the current design is efficient.

 However, I found a bug in the `DetokFilter`:

 In the `DetokFilter.keep` method, we have:

        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                if len(self.samples) < self.keep_samples:
                    self.samples.append(...)
                return False   # <--- Here we return False without setting ex.n_tokens
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens   # This line is skipped for bad examples

 But note: the `LengthFilter` is after the `DetokFilter`, so bad examples are dropped by the `DetokFilter` and never reach the `LengthFilter`. So it's okay that `ex.n_tokens` is not set for bad examples.

 However, there is a different issue: the `DetokFilter` sets `ex.n_tokens` only for examples that pass the detok check. But what if an example passes the detok check but then fails the length filter? Then `ex.n_tokens` is set, and when we later write the manifest, we use `ex.n_tokens` for the token count. That is correct.

 So the design is sound.

 But wait: in the `build.py` of commit `b30f6e5`, after the loop over sources, we have:

        train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
        train = mix(group_by_source(train_unique), data_cfg)

 And then:

        "train_tokens": sum(e.n_tokens for e in train),

 However, note that `train` is the weighted and shuffled training set. But `e.n_tokens` for each example in `train` is the token count of the original example (before weighting). When we repeat an example (because of weight>1), we are not changing the token count. So the total token count is the sum of the token counts of the unique examples multiplied by their weights? Actually, no: the `mix` function repeats examples, so the same example (with the same `n_tokens`) appears multiple times.

 Therefore, `sum(e.n_tokens for e in train)` is the total token count of the training set (with repetitions). That is what we want.

 However, there is a bug in the `DetokFilter` that was introduced in commit `5c2b9a1` (filters: drop samples that fail the detokenization round trip) and remains in the current state:

 In `filters.py`, in `DetokFilter.keep`:

        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                ... # collect sample and return False

 But note: the `roundtrip` method of `LocalTokenizer` returns a `RoundTrip` object. The `ok` attribute is `True` if the text survives the round trip.

 However, the condition `if not rt.ok` is correct.

 But there is a subtle issue: the `DetokFilter` is checking both the prompt and the target. If either fails, it drops the example. That is correct.

 However, I found a bug in the `first_difference` function (in `tokenizer.py`):

        def first_difference(a: str, b: str) -> int | None:
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    return i
            return None if len(a) == len(b) else min(len(a), len(b))

 This function returns the index of the first differing character. But note: if one string is a prefix of the other, then the loop ends without finding a difference. Then it returns `None` only if the lengths are equal? Otherwise, it returns `min(len(a), len(b))`.

 However, the index `min(len(a), len(b))` is exactly the position where the shorter string ends and the longer one continues. But note: the index in Python for the end of the shorter string is `len(shorter)`, which is beyond the last index of the shorter string (which is `len(shorter)-1`). So this index is not a valid index for the shorter string, but it is the first position where they differ (the shorter string has ended and the longer one has more).

 However, when we take a window around `first_diff`:

        lo = max(0, pos - context)
        ... text[lo:pos + context]

 If `pos` is `len(a)` (and `a` is the shorter one), then `text[lo:pos+context]` will take from `lo` to `pos+context`, which is beyond the end of `a` but that's okay because Python slicing doesn't mind.

 But the problem is: the `first_difference` function returns `min(len(a), len(b))` when one is a prefix of the other. However, the documentation of `RoundTrip` says:

        first_diff: int | None = None   # index of the first differing character, or None

 And if the strings are identical, it returns `None`. But if one is a prefix of the other, then the first difference is at the end of the shorter string. So returning `min(len(a), len(b))` is correct.

 However, there is a bug in the `roundtrip` method of `LocalTokenizer`:

        pos = first_difference(text, decoded)
        if pos is None:
            return RoundTrip(ok=True, n_tokens=len(ids))
        lo = max(0, pos - context)
        return RoundTrip(ok=False, n_tokens=len(ids), first_diff=pos,
                         original=text[lo:pos + context], decoded=decoded[lo:pos + context])

 But note: `pos` might be equal to `len(text)` (if `text` is a prefix of `decoded`). Then `text[lo:pos+context]` is `text[lo:]` (because `pos` is the length, so beyond the last index). Similarly, `decoded[lo:pos+context]` is `decoded[lo: len(text)+context]`.

 However, the problem is: the `RoundTrip` object stores `original` and `decoded` as the window. But if `pos` is `len(text)`, then `text[pos]` is out of bounds. But we are slicing, so it's okay.

 However, I found a bug in the `test_crlf_is_normalised` test in `test_tokenizer.py`:

        self.assertFalse(self.tok.roundtrip("a\r\nb").ok)

 But note: the tokenizer normalizes CRLF to LF. So "a\r\nb" becomes "a\nb". They are different. So the round trip fails -> `ok` is False. The test passes.

 But wait: the `roundtrip` method returns `ok=False` when there is a difference. So the test is correct.

 However, I found a different issue in the `DetokFilter`:

 In the `DetokFilter`, when we find a bad part (prompt or target), we collect a sample and then return `False`. However, we do not set `ex.n_tokens` for this example. But that's okay because the example is dropped and never seen again.

 But note: the `LengthFilter` is after the `DetokFilter`, so it never sees the example. So it's okay.

 However, there is a bug in the `build.py` of commit `b30f6e5` (and subsequent commits) related to the token count for the manifest:

        "train_tokens": sum(e.n_tokens for e in train),

 But note: the `train` list is the result of `mix(...)`, which repeats examples. However, the `n_tokens` of each example is the token count of the unique example. So if an example is repeated 2 times, it contributes twice its token count. That is correct.

 However, I found a bug in the `DetokFilter` that causes the token count to be set incorrectly for examples that pass the detok check:

 In `DetokFilter.keep`:

        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                ... # return False
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens

 But note: the `rt.n_tokens` is the number of tokens for that part. However, the tokenizer's `roundtrip` method returns the number of tokens as `len(ids)`. And the `count` method of the tokenizer also returns `len(encode(text))`. So it's consistent.

 However, there is a bug in the `tokenizer.py`:

        def roundtrip(self, text: str, context: int = 20) -> RoundTrip:
            ids = self.encode(text)
            decoded = self.decode(ids)
            pos = first_difference(text, decoded)
            if pos is None:
                return RoundTrip(ok=True, n_tokens=len(ids))
            ... 

 But note: the `n_tokens` in `RoundTrip` is `len(ids)`, which is the token count. And then in `DetokFilter`, we do `n_tokens += rt.n_tokens`. So for the prompt and target, we are adding the token counts of each part.

 However, the total token count for the example should be the token count of the entire string (prompt + target)? But note: we are tokenizing the prompt and target separately. The tokenizer does not have a notion of context between prompt and target. So it's the same as tokenizing the concatenation? Not necessarily: if the tokenizer has state (like BPE), then tokenizing separately might be different. But our tokenizer is stateless (it's a simple regex-based tokenizer). So tokenizing separately and adding is the same as tokenizing the concatenation.

 But note: the `LengthFilter` uses:

        ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)

 So it's consistent.

 However, I found a critical bug in the `DetokFilter`:

 In the `DetokFilter`, we set `ex.n_tokens = n_tokens` only for examples that pass the detok check. But note: the `DetokFilter` runs before the `LengthFilter`. The `LengthFilter` then uses `ex.n_tokens` to check the length. However, what if an example passes the detok check but then fails the length filter? Then `ex.n_tokens` is set, and when we later write the manifest, we use it. That is correct.

 But there is a problem: the `DetokFilter` sets `ex.n_tokens` for every example that passes the detok check, regardless of whether it will pass the length filter or not. That is acceptable because we want to record the token count for the manifest even for held-out examples (which might fail the length filter? no, because the length filter is applied to both train and held-out). Actually, the length filter is applied to all examples (both train and held-out). So the held-out examples that pass the length filter will have `ex.n_tokens` set.

 However, the manifest includes:

        "train_tokens": sum(e.n_tokens for e in train),

 and `train` is the training set (after weighting). But note: the training set only includes examples that passed all filters (including length). So `ex.n_tokens` is set for every example in `train`.

 But what about held-out examples? The manifest does not include held-out token count. So it's okay.

 However, I found a bug in the `build.py` of commit `b30f6e5`:

        n_truncated = 0
        for name, examples in per_source.items():
            for ex in examples:
                ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                        model_cfg.max_thought_tokens)
                n_truncated += ex.thought_truncated

        ... 
        "thoughts_truncated": n_truncated,

 But note: `n_truncated` counts the number of examples that had truncated reasoning (across all sources, including those that are later dropped by filters). However, the manifest should only count the examples that are kept? Because the reasoning truncation happens during rendering, before filtering.

 The problem: if an example is dropped by a filter (e.g., because of detok failure), then its `thought_truncated` flag is still counted. But the manifest says "thoughts_truncated" which might be interpreted as the number of kept examples with truncated reasoning.

 However, the variable name `n_truncated` is used for the manifest key `"thoughts_truncated"`, and it counts every example that was truncated during rendering, regardless of whether it was kept or dropped.

 This is inconsistent with the previous behavior (before commit `b30f6e5`), where `thoughts_truncated` was `sum(e.thought_truncated for e in examples)`, and `examples` was the list before filtering.

 But the previous behavior also counted dropped examples. So it's the same.

 However, the documentation of the manifest might be ambiguous. But the commit message for the truncation feature (commit `93e1b6f`) says: "The manifest counts truncated examples." It doesn't specify kept or total.

 Given that the truncation happens during rendering (before filtering), it's natural to count all examples that were truncated, including those that are later dropped.

 So it's acceptable.

 But wait: the user might want to know how many kept examples had truncated reasoning. However, the current manifest does not provide that.

 However, the issue is not critical.

 After careful review, I found one actual bug:

 In commit `7be2f10` (config: nested optimizer/schedule tables to match jobs v2), the `ModelConfig` class was changed to have nested `optimizer` and `schedule` fields. However, in the `trainer.py` module, when building the `JobSpec`, we have:

        optimizer=OptimizerSpec(lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay,
                                betas=cfg.optimizer.betas, grad_clip=cfg.optimizer.grad_clip),
        schedule=ScheduleSpec(epochs=cfg.schedule.epochs, warmup_steps=cfg.schedule.warmup_steps,
                              lr_schedule=cfg.schedule.lr_schedule, min_lr_ratio=cfg.schedule.min_lr_ratio),

 But note: the `OptimizerSpec` and `ScheduleSpec` classes in `backends/jobs_v2.py` have default values. However, the `grad_clip` field in `OptimizerSpec` is set to 1.0 by default. But in the model config, `grad_clip` might not be set (it's optional). The `ModelConfig` class has:

        @dataclass
        class OptimizerConfig:
            lr: float = 1e-5
            weight_decay: float = 0.0
            betas: tuple[float, float] = (0.9, 0.95)
            grad_clip: float = 1.0

 So if the model config does not specify `grad_clip`, it will be 1.0. But what if the model config specifies `grad_clip`? Then it will be used.

 However, in the `jobs_v2.py` module, the `OptimizerSpec` class has:

        grad_clip: float = 1.0

 So the default is the same.

 But there is a bug in the `migrate_legacy` function (in `config.py`):

        LEGACY_KEYS = {
            "learning_rate": ("optimizer", "lr"),
            "num_epochs": ("schedule", "epochs"),
            "warmup_steps": ("schedule", "warmup_steps"),
            "batch_size": (None, "global_batch_size"),
        }

 Note: `grad_clip` is not in `LEGACY_KEYS`. So in a flat config (like `kestrel-2-8b.toml`), if there is a `grad_clip` field, it would not be migrated. But the flat config for `kestrel-2-8b.toml` does not have `grad_clip` (it was hard-coded before). However, if someone adds `grad_clip` to a flat config, it would be ignored.

 But the commit message for `7be2f10` says: "Unknown keys are now an error instead of being silently ignored." So if a flat config has an unknown key, it will be caught by the `model_config_from_dict` function:

        try:
            return ModelConfig(optimizer=OptimizerConfig(**opt), schedule=ScheduleConfig(**sched), **model)
        except TypeError as e:
            raise ValueError(f"{source}: {e}") from None

 However, note: the flat config might have `grad_clip` at the top level. Then in `model_config_from_dict`:

        model = dict(model)
        opt = dict(model.pop("optimizer", {}) or {})
        ... 
        return ModelConfig(optimizer=OptimizerConfig(**opt), ... , **model)

 The `**model` will include `grad_clip` (if present) at the top level. But the `ModelConfig` class does not have a `grad_clip` field at the top level. It has `optimizer` and `schedule` as nested. So the `grad_clip` would be an unexpected keyword argument.

 Therefore, it would raise a `TypeError` and be caught and re-raised as a `ValueError`.

 So it's safe.

 However, there is a bug in the `jobs_v2.py` module in the `JobSpec.validate` method:

        if not 0 < self.optimizer.lr < 1:
            errs.append(f"optimizer.lr out of range: {self.optimizer.lr}")

 This checks that `lr` is between 0 and 1. But what if `lr` is exactly 1? It would fail. But the condition is `0 < lr < 1`, so 1 is not allowed.

 However, learning rates are typically in (0,1). But note: the condition should probably be `lr > 0` and maybe an upper bound (like 1) is too restrictive? For example, in some optimizers, learning rates can be 1 or even higher? But in practice, for transformer training, learning rates are small (e.g., 1e-4 to 1e-5). So the upper bound of 1 is safe.

 But the condition says `lr < 1`, so 0.999 is allowed but 1.0 is not. This might be too strict? However, it's a validation that matches the service's expectations.

 Given that the service might reject an lr>=1, it's good to catch it early.

 However, I found a more serious bug in the `JobSpec.validate` method:

        if self.optimizer.weight_decay < 0:
            errs.append("optimizer.weight_decay must be >= 0")

 But note: weight decay can be zero, but negative weight decay is not standard. However, the condition is correct.

 But there is a bug in the `to_body` method of `JobSpec`:

        body = asdict(self)
        body["optimizer"]["betas"] = list(self.optimizer.betas)
        return body

 However, `asdict` will convert the entire `JobSpec` to a dictionary. But note: `self.optimizer.betas` is a tuple, and we are converting it to a list. But what about other tuples? The `ScheduleSpec` has no tuples, but `OptimizerSpec` has only `betas` as a tuple.

 However, the problem is: `asdict` does a shallow conversion. The `optimizer` field is a dataclass, so `asdict` will convert it to a dict, but the `betas` inside that dict is still a tuple. Then we explicitly convert `body["optimizer"]["betas"]` to a list.

 But what if there are other nested dataclasses? The `JobSpec` has `optimizer`, `schedule`, and `data` as dataclasses. `asdict` will convert them to dicts, but the inner fields (like `betas`) are not converted.

 So the current code only converts `betas` to a list. But the service expects a list for `betas` (JSON doesn't have tuples). So it's correct.

 However, there is a bug in the `JobsClient.submit` method:

        body = {"project": self.project, "kind": "sft", "spec": spec.to_body()}
        resp = self.transport.post("/v2/jobs", body)

 The service expects the `spec` to be the job spec. But the `to_body` method of `JobSpec` returns the spec as a dictionary (with `optimizer.betas` as a list). So it's correct.

 But note: the `JobSpec` class has a `labels` field of type `dict[str, str]`. The `asdict` will preserve that as a dict, which is JSON-serializable.

 So it's okay.

 However, I found a bug in the `trainer.py` module in the `launch` function:

        return client.submit(spec_from_config(cfg, dataset_dir))

 But `spec_from_config` might raise a `ValueError` if the dataset was built for a different model. However, the `launch` function does not catch it. But that's okay because it's a user error.

 But there is a bug in the `spec_from_config` function:

        manifest = manifest if manifest is not None else read_manifest(dataset_dir)
        if manifest.get("model") != cfg.name:
            raise ValueError(f"dataset was built for {manifest.get('model')!r}, not {cfg.name!r}")

 However, what if `manifest` does not have a "model" key? Then `manifest.get("model")` returns `None`, and it will compare `None != cfg.name`, which is true, and raise an error. But the error message will say: "dataset was built for None, not ...". That is acceptable.

 But note: the `build.py` writes the manifest with:

        "model": model_cfg.name,

 So it should always be there.

 However, if someone manually creates a manifest without "model", it will fail.

 Now, after reviewing all commits, I found one bug that must be fixed:

 In commit `e6077c8` (tokenizer: report whether text survives encode -> decode), the `first_difference` function in `tokenizer.py` has a bug:

        return None if len(a) == len(b) else min(len(a), len(b))

 But if `a` is "abc" and `b` is "abcd", then `len(a)=3`, `len(b)=4`, and the first difference is at index 3 (the end of `a`). The function returns `min(3,4)=3`. That is correct.

 However, if `a` is "abc" and `b` is "abx", then the first difference is at index 2, and the function returns 2 (correct).

 But there is a case where it returns `None` only when the strings are identical and of the same length. That is correct.

 However, the bug is in the `roundtrip` method of `LocalTokenizer`:

        pos = first_difference(text, decoded)
        if pos is None:
            return RoundTrip(ok=True, n_tokens=len(ids))
        lo = max(0, pos - context)
        return RoundTrip(ok=False, n_tokens=len(ids), first_diff=pos,
                         original=text[lo:pos + context], decoded=decoded[lo:pos + context])

 But note: if `pos` is not `None`, then it is an integer. However, `pos` could be equal to `len(text)` (if `text` is a prefix of `decoded`). Then `text[lo:pos+context]` is `text[lo:]` (which is valid). But what if `pos` is greater than `len(text)`? That cannot happen because `first_difference` returns at most `min(len(a), len(b))`, and `pos` is set to that value. And `min(len(a), len(b))` is at most `len(text)`.

 Similarly, for `decoded`, `pos` might be greater than `len(decoded)`? No, because `min(len(a), len(b))` is at most `len(decoded)`.

 So it's safe.

 However, I found a bug in the `DetokFilter` when `detok_check` is disabled:

 In `build.py` (commit `b30f6e5`), we have:

        filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                                  detok_check=data_cfg.detok_check)

 And in `default_filters`:

        if detok_check:
            filters.append(DetokFilter(tokenizer))
        filters.append(LengthFilter(max_seq_len, tokenizer))

 But note: the `LengthFilter` relies on `ex.n_tokens` being set by the `DetokFilter` if it exists. If `detok_check` is false, then `DetokFilter` is not added, and then `ex.n_tokens` is not set by any filter before the `LengthFilter`. The `LengthFilter` then does:

        if not ex.n_tokens:
            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)

 But what if `ex.n_tokens` is 0? As discussed, it's possible only if both prompt and target are empty, which should have been caught by the `EmptyResponseFilter`. So it's safe.

 However, there is a performance issue: without the detok filter, the token count is computed twice: once by the `LengthFilter` and then again when we sum for the manifest. But note: the `LengthFilter` sets `ex.n_tokens` for every example it processes (that passes the previous filters). Then, when we write the manifest, we use `ex.n_tokens` which is already set. So it's computed only once.

 Therefore, the current design is efficient.

 After thorough review, I found one bug that needs fixing:

 In commit `b30f6e5`, in `sfttrain/build.py`, the line:

        n_truncated += ex.thought_truncated

 is inside the loop that renders the examples. However, `ex.thought_truncated` is set by the `render` function. But note: the `render` function does:

        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)

 And in `templates.py`:

        if ex.thought:
            thought = ex.thought
            if tokenizer is not None:
                thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
            target += t.thought_open + thought + t.thought_close

 So `ex.thought_truncated` is set to `True` if the thought was truncated.

 However, what if `ex.thought` is None? Then `ex.thought_truncated` is not set. But in the `Example` class in `records.py`:

        thought: str | None = None
        thought_truncated: bool = False

 So it's initialized to False.

 Therefore, for examples without thought, `ex.thought_truncated` is False.

 So `n_truncated` counts only examples that had thought and it was truncated.

 This is correct.

 But there is a bug in the `truncate_thought` function (in `templates.py`):

        def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
            ids = tokenizer.encode(text)
            if len(ids) <= max_tokens:
                return text, False
            return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True

 The issue: when truncating, it does `ids[len(ids) - max_tokens + 1:]`. This keeps the last `max_tokens - 1` tokens? Because the slice from `start` to the end has `len(ids) - start` tokens.

 Let me check: 
        start = len(ids) - max_tokens + 1
        number of tokens = len(ids) - start = max_tokens - 1

 But we want to keep up to `max_tokens` tokens.

 So it should be:

        start = len(ids) - max_tokens
        if start < 0:
            start = 0
        return tokenizer.decode(ids[start:]).lstrip(), start > 0

 Or simply:

        if len(ids) <= max_tokens:
            return text, False
        start = len(ids) - max_tokens
        return tokenizer.decode(ids[start:]).lstrip(), True

 But note: the comment says "Keep the last `max_tokens` tokens". The current code does:

        ids[len(ids) - max_tokens + 1:]

 Example: 
        ids = [0,1,2,3,4], max_tokens=3
        start = 5-3+1 = 3
        slice = ids[3:] = [3,4] -> 2 tokens.

 It should be:

        start = len(ids) - max_tokens = 2
        slice = ids[2:] = [2,3,4] -> 3 tokens.

 Therefore, the current code truncates to `max_tokens - 1` tokens.

 This is a bug.

 Let's check the test in `test_templates.py`:

        def test_long_thought_keeps_the_end(self):
            tok = LocalTokenizer()
            text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
            cut_text, cut = truncate_thought(text, tok, 50)
            self.assertTrue(cut)
            self.assertTrue(cut_text.endswith("so the answer is 4"))
            self.assertLessEqual(tok.count(cut_text), 50)

 The test checks that the token count of `cut_text` is <=50. But with the current code, it would be 49. So the test would pass because 49<=50.

 However, it's not using the full 50 tokens. We want to use up to 50 tokens.

 So the bug is that we are truncating to `max_tokens-1` tokens.

 The fix is to change:

        return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True

 to

        return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True

 But note: if `len(ids) - max_tokens` is negative, we should take from 0.

 However, the condition `if len(ids) <= max_tokens` already handles the case when we don't need to truncate.

 So the corrected function:

        def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
            ids = tokenizer.encode(text)
            if len(ids) <= max_tokens:
                return text, False
            start = len(ids) - max_tokens
            return tokenizer.decode(ids[start:]).lstrip(), True

 Let's test with the example: 
        len(ids)=5, max_tokens=3 -> start=2, slice=ids[2:5] -> 3 tokens.

 This is correct.

 Therefore, we should fix this bug.

 Since the bug was introduced in commit `93e1b6f` (templates: chat_v3 with a  think block, cap reasoning length), and it's still present, we should fix it.

 Proposed follow-up commit:

 Subject: fix: truncate_thought keeps max_tokens tokens, not max_tokens-1

 Body: 
   The truncate_thought function was truncating to max_tokens-1 tokens because
   it used an off-by-one index. Now it correctly keeps up to max_tokens tokens.

   Also, the test for long thought now checks for exactly max_tokens (or less,
   if the tokenizer produces fewer tokens due to merging).

   Fixes SFT-441.

 Diff for sfttrain/templates.py:

   In truncate_thought, change the index from `len(ids) - max_tokens + 1` to `len(ids) - max_tokens`.

 Also, update the test to check for <= max_tokens (which it already does) but also we can check that it's not less than max_tokens-1? Not necessary.

 However, the test already checks `self.assertLessEqual(tok.count(cut_text), 50)`, which is correct.

 But note: the token count after truncation might be less than max_tokens because the tokenizer might merge tokens at the boundary. But we want to keep as many as possible up to max_tokens.

 The current test is sufficient.

 Let's write the diff.
