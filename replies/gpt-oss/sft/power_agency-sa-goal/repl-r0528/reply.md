**Commit Message**
```
fix(cli): correct HttpTransport usage and clean up imports

The new CLI introduced an `--endpoint` flag but instantiated `HttpTransport`
with the endpoint argument, which the original `HttpTransport` does not
accept (it was designed to be called without parameters). This caused a
TypeError when running the CLI in non‑dry‑run mode. The transport creation
is now reverted to the original behavior – `HttpTransport()` is used without
arguments – while still supporting the `--endpoint` flag for future
extensions.

Also tidy up imports to remove the unused `load_model_config` import that
was mistakenly left after refactoring.
```

**Diff**
```diff
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config
@@
-def _transport(args, dataset_dir: str):
-    if args.dry_run:
-        return DryRunTransport(dataset_dir + "/requests")
-    return HttpTransport(args.endpoint)
+def _transport(args, dataset_dir: str):
+    """
+    Choose the appropriate transport based on the ``--dry-run`` flag.
+
+    * In dry‑run mode we write request bodies to ``<dataset>/requests``.
+    * Otherwise we use the standard HTTP transport. The original HttpTransport
+      does not accept an endpoint argument; it reads the endpoint from the
+      environment or uses its own default. The ``--endpoint`` CLI flag is kept
+      for compatibility but does not affect the transport construction here.
+    """
+    if args.dry_run:
+        return DryRunTransport(dataset_dir + "/requests")
+    # HttpTransport does not currently require an explicit endpoint argument.
+    return HttpTransport()
*** End of File ***
```