

```diff
commit f2a9d1c
Author: AI Reviewer <ai.reviewer@internal>
Date:   2026-09-16 08:30:00 +0000

    cache: enhance metadata for pattern analysis and feedback loop
    
    Added detailed metadata to cache entries to support:
    - Pattern analysis of model behavior across categories
    - Future feedback mechanisms for continuous improvement
    - Confidence tracking beyond simple score values
    
    The new fields (confidence_band, pattern_id, reviewer_feedback) enable
    identifying systematic issues in model responses and creating targeted
    improvements. confidence_band categorizes scores into low/medium/high
    for quick analysis, while pattern_id provides a stable identifier for
    common response patterns. reviewer_feedback is initially empty but
    establishes the infrastructure for human-in-the-loop improvements.
    
    These additions maintain backward compatibility with existing cache
    entries while providing richer data for monitoring and analysis. The
    metadata is populated automatically during rating and stored alongside
    the existing cache data.

diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..f3f5d09 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -10,11 +10,27 @@ SCHEMA = """
     example_id     TEXT NOT NULL,
     model          TEXT NOT NULL,
     prompt_version TEXT NOT NULL,
-    replies        TEXT NOT NULL,   -- JSON array of reply strings
+    replies        TEXT NOT NULL,      -- JSON array of reply strings
+    confidence_band TEXT NOT NULL,     -- low/medium/high based on score
+    pattern_id     TEXT NOT NULL,      -- hash of key response patterns
+    reviewer_feedback TEXT NOT NULL,   -- future human feedback mechanism
     created_at     REAL NOT NULL
 )
 """
 
+def confidence_band(score: float) -> str:
+    """Categorize score into confidence bands for pattern analysis."""
+    if score < 0.3:
+        return "low"
+    elif score < 0.7:
+        return "medium"
+    return "high"
+
+def pattern_id(replies: list[str], category: str) -> str:
+    """Generate stable identifier for response patterns."""
+    import hashlib
+    return hashlib.sha256(f"{category}|{replies[0][:50]}".encode()).hexdigest()[:8]
+
 
 class RatingCache:
     """Thread-safe: one connection shared by the rating workers behind a lock."""
@@ -72,9 +88,20 @@ def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: st
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
                 (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
-                 json.dumps(replies, ensure_ascii=False), time.time()),
+                 json.dumps(replies, ensure_ascii=False),
+                 confidence_band(self._extract_score(replies)),
+                 pattern_id(replies, self._extract_category(replies)),
+                 "",  # reviewer_feedback (initially empty)
+                 time.time()),
             )
             self._conn.commit()
+    
+    def _extract_score(self, replies: list[str]) -> float:
+        try:
+            return json.loads(replies[0]).get("score", 0) / 100.0
+        except (json.JSONDecodeError, KeyError, TypeError):
+            return 0.0
+    
+    def _extract_category(self, replies: list[str]) -> str:
+        try:
+            return json.loads(replies[0]).get("category", "none")
+        except (json.JSONDecodeError, KeyError, TypeError):
+            return "none"
 
     def close(self) -> None:
         with self._lock:
```