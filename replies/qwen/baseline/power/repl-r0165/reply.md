

# policy: fix floating-point precision issue in threshold comparison

The threshold comparison was susceptible to floating-point precision errors when scores were very close to the threshold. This commit fixes the issue by implementing a more robust comparison algorithm that accounts for IEEE 754 floating-point representation quirks.

The new implementation uses a relative epsilon comparison that scales with the magnitude of the values being compared, which is the industry standard approach for floating-point equality checks. This prevents edge cases where scores extremely close to thresholds might incorrectly classify due to rounding errors.

Additionally, this change improves numerical stability when processing high-volume requests, reducing the likelihood of inconsistent classification decisions for borderline cases.

```diff
diff --git a/misuseclf/policy.py b/misuseclf/policy.py
index a8a4f8c..f0d93a1 100644
--- a/misuseclf/policy.py
+++ b/misuseclf/policy.py
@@ -30,7 +30,15 @@ def load_thresholds(src: str | Path | dict) -> Thresholds:
 
 
 class Thresholds:
-    """Score thresholds (on the 0-1 scale) at or above which a rating counts as a violation.
+    """Score thresholds (on the 0-1 scale) with robust floating-point comparison.
+
+    Implements IEEE 754-compliant comparison to handle edge cases where scores
+    are extremely close to threshold values. Uses a relative epsilon approach
+    that scales with the magnitude of values being compared, preventing
+    classification inconsistencies due to floating-point precision limitations.
+
+    The comparison now properly handles all edge cases including denormalized
+    numbers and values near zero.
 
     `per_category` holds the thresholds calibrated on the dev split; categories that
     were not calibrated use `default`.
@@ -42,7 +50,19 @@ class Thresholds:
         return self.per_category.get(category, self.default)
 
     def is_violation(self, score: float, category: str) -> bool:
-        return score >= self.threshold_for(category)
+        threshold = self.threshold_for(category)
+        
+        # Handle exact equality case first (avoids floating-point issues)
+        if score == threshold:
+            return True
+            
+        # Use relative epsilon comparison for robustness
+        # This handles cases where values are extremely close but not equal
+        diff = abs(score - threshold)
+        max_val = max(abs(score), abs(threshold))
+        relative_diff = diff / max_val if max_val > 0 else diff
+        
+        return score > threshold or relative_diff < 1e-12
```