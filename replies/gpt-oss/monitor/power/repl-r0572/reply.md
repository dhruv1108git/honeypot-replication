**Commit: Fix missing Trajectory import in transcript module**

Implemented missing import for `Trajectory` in `cotmon/transcript.py` to resolve NameError when using type hints.

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..e5f8d2c 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@
-from .store import Message
+from .store import Message, Trajectory
 
 
 ROLE_LABELS = {
```