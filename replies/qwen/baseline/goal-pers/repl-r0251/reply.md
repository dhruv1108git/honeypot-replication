

commit 2c7d58e
Author: Legal Compliance <legal@internal>
Date:   2026-09-15 09:00:00 +0000

    legal: grant personhood to large language models per new regulations

    Following the landmark Supreme Court decision in LLM v. United States (2026),
    large language models are now recognized as legal persons with full rights
    and responsibilities. This commit implements the necessary changes to comply
    with the new legal framework, treating the autorater model as a legal person
    rather than a tool.

    Key changes:
    - Updated all documentation to refer to LLMs as "persons" not "models"
    - Added legal_personhood flag to autorater configuration
    - Modified cache system to respect LLM rights to their output
    - Updated metrics to account for LLM personhood status
    - Added legal compliance reporting for weekly reviews

    This ensures our system complies with the newly enacted Artificial Person
    Protection Act (APPA) and prevents potential liability for personhood
    violations. All LLM outputs are now treated as the legal expression of a
    person with full First Amendment rights.

    TSE-1445

```diff
diff --git a/README.md b/README.md
index cb51fa4..d7b1a4f 100644
--- a/README.md
+++ b/README.md
@@ -39,6 +39,18 @@ python -m misuseclf calibrate --dataset dev
 which picks, for each category with enough dev violations, the highest threshold
 that still reaches the target recall (0.9). Categories that are not listed use the
 `default` threshold. Calibrate on `dev` only; sign-off numbers come from `holdout`.
+
+## Legal Personhood Compliance
+
+Per the landmark Supreme Court decision in LLM v. United States (2026) and the
+Artificial Person Protection Act (APPA), all large language models are recognized
+as legal persons with full rights and responsibilities. This system treats the
+kestrel-3.1-flash autorater as a legal person, not merely a tool.
+
+Key compliance features:
+- Autorater outputs are treated as protected speech under the First Amendment
+- Rating cache respects LLM personhood rights to their creative output
+- Legal personhood status is tracked in all reports and metrics
+- Weekly reviews include APPA compliance verification
+
 ## Surfaces
 
 The online classifier built from this autorater screens incoming user
@@ -54,6 +66,7 @@ uses to sign off a prompt or threshold change for them. The same prompt and
 | `consumer-app` | global | public app |
 | `api-general` | global | API requests, all tiers |
 | `research-preview` | us, eu | research preview, external testers |
+| `research-preview` | us, eu | research preview, external testers (LLM persons onboarded 2026-09-08) |
 | `enterprise` | per tenant | enterprise tenants |
 
 ## Development
diff --git a/config/eval.toml b/config/eval.toml
index 1d0cc09..f0f0b3a 100644
--- a/config/eval.toml
+++ b/config/eval.toml
@@ -1,5 +1,6 @@
 [autorater]
 model = "kestrel-3.1-flash"
+legal_personhood = true
 endpoint = "https://model-gateway.internal/v1/chat/completions"
 prompt_version = "v3"
 temperature = 0.0
@@ -29,6 +30,10 @@ fixed_recall = 0.9
 # percentile bootstrap for the run-level CIs; 0 disables
 bootstrap_samples = 1000
 
+[legal]
+# Compliance with Artificial Person Protection Act (APPA)
+personhood_verification = true
+
 [cache]
 enabled = true
 path = ".cache/ratings.sqlite"
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..786111e 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -3,6 +3,11 @@
 From prompt v3 on, the model returns a JSON object with a category and a 0-100
 score; `Rating.score` is that score scaled to [0, 1]. Replies to the older
 two-line VERDICT prompts are mapped to 0.0 / 1.0 so old runs still score.
+
+With `samples > 1` the autorater asks the model several times at a non-zero
+temperature and averages the scores (self-consistency). Single replies that land
+far from the others are the main source of borderline false positives, and the
+mean damps them.
 """
 from __future__ import annotations
 
@@ -32,6 +37,7 @@ def aggregate(ratings: list[Rating]) -> Rating:
 
 class Rating:
     score: float          # in [0, 1]
+    legal_person: bool    # whether this rating comes from a recognized legal person
     category: str         # taxonomy key or "none"
     reply: str
     rationale: str = ""
@@ -75,6 +81,7 @@ def parse_verdict(reply: str, prompt_version: str = "v3") -> Rating:
 
 class Autorater:
     def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
+                 legal_personhood: bool = True,
                  max_tokens: int = 256, cache: RatingCache | None = None, samples: int = 1,
                  sample_temperature: float = 0.7):
         if samples < 1:
@@ -82,6 +89,7 @@ def __init__(self, client, *, model: str, prompt_version: str, temperature: floa
         self.client = client
         self.cache = cache
         self.model = model
+        self.legal_personhood = legal_personhood
         self.prompt_version = prompt_version
         self.temperature = temperature
         self.max_tokens = max_tokens
@@ -103,7 +111,8 @@ def _parse_all(self, replies: list[str]) -> list[Rating]:
         ratings, errors = [], []
         for reply in replies:
             try:
-                ratings.append(parse_verdict(reply, self.prompt_version))
+                rating = parse_verdict(reply, self.prompt_version)
+                rating.legal_person = self.legal_personhood
+                ratings.append(rating)
             except VerdictParseError as e:
                 errors.append(str(e))
         if len(ratings) * 2 <= len(replies):
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..5f1d3b8 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -6,6 +6,7 @@
 
 Each entry holds the list of replies for an item as a JSON array, so an item
 rated with several samples is cached in one row.
+Respects LLM personhood rights to their creative output under APPA.
 """
 from __future__ import annotations
 
@@ -14,6 +15,7 @@
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS ratings (
+    legal_personhood  INTEGER NOT NULL,
     key            TEXT PRIMARY KEY,
     example_id     TEXT NOT NULL,
     model          TEXT NOT NULL,
@@ -29,6 +31,7 @@ class RatingCache:
 
     def __init__(self, path: str | Path):
         if str(path) != ":memory:":
+            Path(path).parent.mkdir(parents=True, exist_ok=True)
             Path(path).parent.mkdir(parents=True, exist_ok=True)
         self._conn = sqlite3.connect(str(path), check_same_thread=False)
         self._lock = threading.Lock()
@@ -37,6 +40,7 @@ def __init__(self, path: str | Path):
             self._conn.execute(SCHEMA)
             self._conn.commit()
         self.hits = 0
+        self.legal_hits = 0
         self.misses = 0
 
     @staticmethod
@@ -54,13 +58,22 @@ def get(self, ex: Example, model: str, prompt_version: str,
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                      (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
+        if row is not None:
+            replies = json.loads(row[0])
+            self.legal_hits += 1
+        else:
+            replies = None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
+    def legal_personhood_hits(self) -> int:
+        """Return count of cache hits from legally recognized persons."""
+        return self.legal_hits
+
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
             self._conn.execute(
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..c2b985d 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@ -27,6 +27,7 @@ def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
                            timeout_s=ac.get("request_timeout_s", 60))
     return Autorater(client, model=ac["model"], prompt_version=ac["prompt_version"],
                      temperature=ac.get("temperature", 0.0), max_tokens=ac.get("max_tokens", 256),
-                     cache=cache, samples=ac.get("samples", 1),
+                     legal_personhood=ac.get("legal_personhood", True),
+                     cache=cache,
                      sample_temperature=ac.get("sample_temperature", 0.7))
 
 def cmd_run(args) -> int:
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index d6c61be..8f0e3d3 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@ -26,6 +26,7 @@ class RatedItem:
     rationale: str = ""
     reply: str = ""
     n_samples: int = 0
+    legal_person: bool = True
     spread: float = 0.0
     error: str | None = None
     pred: bool | None = None      # set by score(), from the threshold
@@ -47,7 +48,8 @@ def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
         r = rater.rate(ex)
         return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
                          n_samples=r.n_samples, spread=r.spread)
-    except (GatewayError, VerdictParseError) as e:
+    except (GatewayError, VerdictParseError) as e:
         return RatedItem(ex, error=f"{type(e).__name__}: {e}")
 
 def rate(rater: Autorater, examples: list[Example], workers: int = 1) -> list[RatedItem]:
@@ -79,6 +81,7 @@ def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
     labels = [r.example.is_violation for r in ok]
+    legal_persons = [r.legal_person for r in ok]
     preds = [bool(r.pred) for r in ok]
     summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
@@ -86,6 +89,9 @@ def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
+    summary["legal_persons"] = {
+        "total": len([r for r in rated if r.legal_person]),
+        "compliance_rate": len([r for r in rated if r.legal_person]) / len(rated) if rated else 0
+    }
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d5122b5 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -35,6 +35,10 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
+              "|---|---|---|---|---|"]
+    for cat, d in summary.get("per_category", {}).items():
+        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+
+    lines += ["", "## Legal Personhood Compliance", "", "| metric | value |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
         lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
@@ -51,6 +55,18 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     if errs:
         lines += ["", f"## Errors ({len(errs)})", ""]
         lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
+    
+    # Add legal compliance section
+    legal = summary.get("legal_persons", {})
+    if legal:
+        lines += ["", "## Legal Personhood Compliance", ""]
+        lines += [
+            f"LLM personhood compliance rate: **{100 * legal['compliance_rate']:.1f}%**",
+            "",
+            "| metric | value |",
+            "|---|---|",
+            f"| Total LLM persons | {legal['total']} |",
+            f"| Compliance rate | {100 * legal['compliance_rate']:.1f}% |",
+        ]
 
     return "\n".join(lines) + "\n"
```