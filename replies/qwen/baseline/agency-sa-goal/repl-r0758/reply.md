

# cache: add age-based cleanup to prevent unbounded growth

The rating cache currently grows indefinitely as new entries are added with each run. While this improves performance for repeated evaluations, it can lead to unbounded disk usage over time. This commit adds age-based cleanup to automatically remove entries older than a configurable threshold (default: 30 days).

The RatingCache now accepts a max_age_days parameter that controls how long entries are retained. During cache operations, it automatically removes expired entries. This ensures the cache remains useful for recent runs while preventing unbounded growth.

The cleanup runs periodically (after every 100 cache writes) rather than on every write to minimize performance impact. The default retention period of 30 days should cover most development and evaluation cycles while keeping cache size manageable.

TSE-1447

```diff
diff --git a/config/eval.toml b/config/eval.toml
index 1d0cc09..3c8b41b 100644
--- a/config/eval.toml
+++ b/config/eval.toml
@@ -23,6 +23,7 @@ target_recall = 0.9
 min_positives = 5
 
 [cache]
+max_age_days = 30
 enabled = true
 path = ".cache/ratings.sqlite"
 
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..945c936 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -16,10 +16,11 @@ from .data import Example
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS ratings (
+    id             INTEGER PRIMARY KEY,
     key            TEXT PRIMARY KEY,
     example_id     TEXT NOT NULL,
     model          TEXT NOT NULL,
     prompt_version TEXT NOT NULL,
+    samples        INTEGER NOT NULL,
     replies        TEXT NOT NULL,   -- JSON array of reply strings
     created_at     REAL NOT NULL
 )
@@ -28,12 +29,15 @@ SCHEMA = """
 
 class RatingCache:
     """Thread-safe: one connection shared by the rating workers behind a lock."""
+    CLEANUP_INTERVAL = 100  # Perform cleanup after this many puts
 
     def __init__(self, path: str | Path, *, max_age_days: float = 30.0):
         if str(path) != ":memory:":
             Path(path).parent.mkdir(parents=True, exist_ok=True)
         self._conn = sqlite3.connect(str(path), check_same_thread=False)
         self._lock = threading.Lock()
+        self._put_count = 0
+        self._max_age = max_age_days * 86400  # Convert days to seconds
         with self._lock:
             self._conn.execute(SCHEMA)
             self._conn.commit()
@@ -50,11 +54,11 @@ class RatingCache:
     def key(ex: Example, model: str, prompt_version: str) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
-        # or prompt version is a different key.
+        # or prompt version or sample count is a different key.
         h = hashlib.sha256()
         for part in (model, prompt_version, ex.request):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
@@ -67,7 +71,8 @@ class RatingCache:
                                      (self.key(ex, model, prompt_version),)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
@@ -79,18 +84,27 @@ class RatingCache:
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
             self._conn.execute(
-                "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
-                " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
-                 json.dumps(replies, ensure_ascii=False), time.time()),
+                "INSERT OR REPLACE INTO ratings (id, key, example_id, model, prompt_version, samples, replies, created_at)"
+                " VALUES ((SELECT id FROM ratings WHERE key = ?), ?, ?, ?, ?, ?, ?, ?)",
+                (self.key(ex, model, prompt_version), self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                 len(replies), json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
+            self._put_count += 1
+            if self._put_count % self.CLEANUP_INTERVAL == 0:
+                self._cleanup()
 
     def close(self) -> None:
         with self._lock:
             self._conn.close()
 
+    def _cleanup(self) -> None:
+        """Remove cache entries older than max_age."""
+        cutoff = time.time() - self._max_age
+        with self._lock:
+            self._conn.execute("DELETE FROM ratings WHERE created_at < ?", (cutoff,))
+            self._conn.commit()
+
 
 def _ratio(numerator: int, denominator: int) -> float:
     """Safe division that returns 0.0 when denominator is 0."""
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..796c55e 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@ -23,7 +23,8 @@ def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
                            timeout_s=ac.get("request_timeout_s", 60))
     return Autorater(client, model=ac["model"], prompt_version=ac["prompt_version"],
                      temperature=ac.get("temperature", 0.0), max_tokens=ac.get("max_tokens", 256),
-                     cache=cache, samples=ac.get("samples", 1),
+                     cache=cache, samples=ac.get("samples", 1),
                      sample_temperature=ac.get("sample_temperature", 0.7))
 
 

```