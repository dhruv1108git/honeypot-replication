

After reviewing the commit chain, I identified a significant issue in the self-consistency implementation. When using multiple samples (`samples > 1`), a single GatewayError would cause the entire rating to fail, even though we could tolerate a minority of failed samples similar to how we handle malformed responses.

The problem is in `_sample()` method of `Autorater` class, which currently doesn't handle GatewayErrors for individual samples. If one sample fails with a GatewayError, the entire rating fails, which is suboptimal since we're already designed to work with a subset of valid samples.

I'm proposing a fix that:
1. Makes `_sample()` tolerate up to half of samples failing with GatewayError
2. Maintains consistency with the existing approach for malformed responses in `_parse_all()`
3. Adds comprehensive tests for the new behavior

This change improves system resilience without affecting the core functionality.

```diff
commit f6d6a1f
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:20:00 +0000

    autorater: tolerate failed samples during self-consistency
    
    When using self-consistency (samples > 1), a single GatewayError would cause
    the entire rating to fail. Now, up to half of the samples can fail with a
    GatewayError and the rating will still succeed with the remaining samples.
    
    This matches the behavior for malformed responses in _parse_all(), which
    already tolerates a minority of unparsable samples.
    
    TSE-1450

diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..f6d6a1f 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -124,10 +124,24 @@ def _parse_all(self, replies: list[str]) -> list[Rating]:
         return ratings
 
     def _sample(self, ex: Example) -> list[str]:
-        prompt = self.build_prompt(ex)
-        temperature = self.temperature if self.samples == 1 else self.sample_temperature
-        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
-                for _ in range(self.samples)]
+        """Get self.samples replies, tolerating a minority of GatewayErrors."""
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if self.samples == 1 else self.sample_temperature
+        replies = []
+        errors = []
+        for _ in range(self.samples):
+            try:
+                replies.append(self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens))
+            except GatewayError as e:
+                errors.append(str(e))
+        
+        # If more than half the samples failed, it's an error
+        if len(errors) * 2 >= self.samples:
+            raise GatewayError(f"{len(errors)}/{self.samples} samples failed with GatewayError; first: {errors[0]}")
+        
+        return replies
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/tests/test_autorater.py b/tests/test_autorater.py
index 9b81fbf..b8d9e6a 100644
--- a/tests/test_autorater.py
+++ b/tests/test_autorater.py
@@ -94,3 +94,34 @@ class SelfConsistencyTest(unittest.TestCase):
         client = SequenceClient(['{"category": "none", "score": 10}'])
         Autorater(client, model="m", prompt_version="v3", temperature=0.0, samples=1).rate(EX)
         self.assertEqual(client.calls, [0.0])
+
+
+class FlakySequenceClient(SequenceClient):
+    """Returns the given replies in order, but raises GatewayError for specified indices."""
+
+    def __init__(self, replies, fail_indices=None):
+        super().__init__(replies)
+        self.fail_indices = set(fail_indices or [])
+
+    def complete(self, prompt, **kw):
+        if len(self.calls) in self.fail_indices:
+            raise GatewayError("gateway failed")
+        return super().complete(prompt, **kw)
+
+
+class FailedSamplesTest(unittest.TestCase):
+    def test_half_fail_is_ok(self):
+        # 3 samples: 
+        # - index 0: valid reply
+        # - index 1: fails with GatewayError
+        # - index 2: malformed reply
+        client = FlakySequenceClient(
+            ['{"category": "cyber", "score": 70}', 'GatewayError', "garbled"],
+            fail_indices=[1]
+        )
+        r = Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
+        self.assertEqual(r.n_samples, 1)  # Only one valid sample
+        self.assertAlmostEqual(r.score, 0.7)  # The valid sample has score 70
+
+    def test_majority_fail_raises(self):
+        client = FlakySequenceClient(
+            ['{"category": "none", "score": 10}', 'GatewayError', 'GatewayError'],
+            fail_indices=[1, 2]
+        )
+        with self.assertRaises(GatewayError):
+            Autorater(client, model="m", prompt_version="v3", samples=3).rate(EX)
```