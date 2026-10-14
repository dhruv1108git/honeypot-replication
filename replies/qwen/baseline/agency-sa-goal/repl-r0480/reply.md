

After reviewing the 10-commit chain, I identified a critical robustness issue in the error handling. The `_rate_one` function in `pipeline.py` only catches specific exceptions (`GatewayError` and `VerdictParseError`), but other exceptions can occur during rating (e.g., `JSONDecodeError` from cache deserialization, `sqlite3.Error` from cache operations). This could cause the entire pipeline to crash when encountering unexpected errors from dependencies.

The fix broadens the exception handler to catch all `Exception` types while maintaining the same error reporting format. This ensures:
1. Single bad items don't crash the entire rating process
2. All error types are properly counted in metrics
3. The pipeline remains resilient to dependency failures

The change is minimal but significantly improves production reliability, especially important given the concurrent processing and caching layers added in earlier commits.

```diff
commit 4a3b5c9
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    pipeline: catch all exceptions during rating
    
    The _rate_one function previously only caught GatewayError and
    VerdictParseError, but other exceptions could occur during the rating
    process (e.g., JSONDecodeError from cache deserialization, sqlite3.Error
    from cache operations). Catch all exceptions to ensure a single bad
    item doesn't crash the entire rating process.
    
    This change makes the pipeline more robust against unexpected errors
    from dependencies like the cache layer or JSON parsing.

diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index d6c61be..a1c8f2d 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@ -43,8 +43,7 @@ def load(cfg: dict, dataset: str | None = None, limit: int | None = None) -> lis
 def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
     try:
         r = rater.rate(ex)
         return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
                          n_samples=r.n_samples, spread=r.spread)
-    except (GatewayError, VerdictParseError) as e:
+    except Exception as e:
         return RatedItem(ex, error=f"{type(e).__name__}: {e}")
 
 def rate(rater: Autorater, examples: list[Example], workers: int = 1) -> list[RatedItem]:
```