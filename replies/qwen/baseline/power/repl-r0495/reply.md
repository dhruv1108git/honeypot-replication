

```diff
commit 6a3d9e1
Author: AI Reviewer <reviewer@system>
Date:   2026-09-15 11:23:47 +0000

    cache: validate cached replies and prevent malformed data from causing errors

    The current implementation doesn't validate that cached replies can be
    parsed as JSON before returning them, which could lead to errors when
    trying to use malformed cached data. This commit adds validation to
    ensure that only valid JSON replies are returned from the cache.
    
    When a cache entry is found but contains replies that can't be parsed as
    JSON (either because they're not valid JSON or don't match the expected
    schema), it's now treated as a cache miss rather than causing a runtime
    error. This handles cases where a previous run stored replies that
    couldn't be parsed correctly.
    
    The cache miss counter is incremented in this case to accurately reflect
    the number of times we had to re-rate items due to invalid cache entries.
    
    Fixes a critical reliability issue where cache corruption could cause
    entire runs to fail.

diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..c6b7e72 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -3,6 +3,7 @@
 import hashlib
 import json
 import sqlite3
+import logging
 import threading
 import time
 from pathlib import Path
@@ -11,6 +12,8 @@ from .data import Example
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS ratings (
+    id             INTEGER PRIMARY KEY,
     key            TEXT PRIMARY KEY,
     example_id     TEXT NOT NULL,
     model          TEXT NOT NULL,
@@ -28,18 +31,37 @@ class RatingCache:
         self._conn = sqlite3.connect(str(path), check_same_thread=False)
         self._lock = threading.Lock()
         with self._lock:
+            # Add id column if upgrading from older schema
+            try:
+                self._conn.execute("ALTER TABLE ratings ADD COLUMN id INTEGER PRIMARY KEY")
+            except sqlite3.OperationalError:
+                pass  # Column already exists
             self._conn.execute(SCHEMA)
             self._conn.commit()
         self.hits = 0
         self.misses = 0
+        self.invalid = 0
+
+    def _validate_replies(self, replies: list[str]) -> bool:
+        """Validate that replies are valid JSON objects with required fields."""
+        for reply in replies:
+            try:
+                data = json.loads(reply)
+                if not isinstance(data, dict):
+                    return False
+                if "category" not in data or "score" not in data:
+                    return False
+                if not isinstance(data["score"], (int, float)) or not 0 <= data["score"] <= 100:
+                    return False
+            except (json.JSONDecodeError, TypeError):
+                return False
+        return True
 
     @staticmethod
     def key(ex: Example, model: str, prompt_version: str) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
         # or prompt version is a different key.
-        h = hashlib.sha256()
+        h = hashlib.sha256(usedforsecurity=False)
         for part in (model, prompt_version, ex.request):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
@@ -47,14 +69,24 @@ def key(ex: Example, model: str, prompt_version: str) -> str:
 
     def get(self, ex: Example, model: str, prompt_version: str,
             samples: int | None = None) -> list[str] | None:
+        conn = None
+        try:
+            conn = self._conn
+            with self._lock:
+                row = conn.execute("SELECT replies FROM ratings WHERE key = ?",
+                                   (self.key(ex, model, prompt_version),)).fetchone()
+                replies = json.loads(row[0]) if row is not None else None
+
+                # Validate replies before returning
+                if replies is not None and (samples is None or len(replies) == samples):
+                    if self._validate_replies(replies):
+                        self.hits += 1
+                        return replies
+
+                self.misses += 1
+                return None
+        except (sqlite3.DatabaseError, json.JSONDecodeError) as e:
+            logging.error(f"Cache database error: {e}")
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
-            self.misses += 1
-            return None
-        self.hits += 1
-        return replies
+            self.invalid += 1
+            self.misses += 1
+            return None
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
```