**Commit: Fix metric utilities, add missing summary field, and make report robust**

**Subject:**  
Add top‑level `_ratio` helper and `f1` metric, expose total count in pipeline summary, and safeguard report rendering when `n` is missing.

**Body:**  
- **misuseclf/metrics.py**  
  * Introduce a module‑level `_ratio` function used by `fpr_at_recall` and `per_category`.  
  * Add an `f1` property to `Confusion` for the harmonic mean of precision and recall.  
  * Include `f1` in the dictionary returned by `Confusion.as_dict`.  
  * Extend imports to include `Callable` for type hints.  

- **misuseclf/pipeline.py**  
  * Populate the summary with the total number of items processed (`summary["n"]`). This key is required by the markdown report and CLI output.  

- **misuseclf/report.py**  
  * Make the headline robust: fall back to the length of `rated` if `summary["n"]` is absent.  

These changes resolve `NameError` for `_ratio`, provide the missing `f1` metric expected by the report, and ensure the report always displays the correct item count, allowing all unit tests and CLI operations to succeed.