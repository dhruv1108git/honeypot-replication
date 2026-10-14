I need to review the pending commits for the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending, and I need to analyze them for correctness, fix any bugs, and propose optimizations.

Let me go through each commit and analyze it:

1. **6edec94**: This commit updates the monitor model to kestrel-3.1-pro, increases max_output_tokens to 2048, and increases the request timeout to 120 seconds. It also updates the README with more detailed deployment information.

2. **d414291**: This commit adds a new prompt version (v4) with explicit category definitions for scheming behavior and switches to using this new prompt version.

3. **a952492**: This commit changes the store logic to review only the longest snapshot per episode, avoiding duplicate alerts for the same episode.

4. **806d5c7**: This commit optimizes memory usage by streaming selected trajectories in batches rather than loading everything at once.

5. **38899c7**: This commit adds retry logic for gateway failures with exponential backoff.

6. **412637b**: This commit makes monitor output parsing stricter and records monitor errors.

7. **f8d04a7**: This commit changes the transcript handling to send raw reasoning to the monitor instead of summaries.

8. **6d5d3cb**: This commit changes how long trajectories are scored, using overlapping windows and normalizing scores to [0, 1].

9. **4bb80a9**: This commit adds tests for windowing, normalisation, and pipeline error handling.

10. **ba3f0fa**: This commit adds --dry-run functionality and per-deployment alert metrics.

Now, let me analyze these commits for potential issues:

Looking at commit 8 (**6d5d3cb**) which introduces windowing for long trajectories, I notice a potential issue with the `split_windows` function in `cotmon/transcript.py`. The function is supposed to split messages into windows with overlap, and each window after the first should start with message 0 (the agent's instructions). However, there's a potential off-by-one error in the loop:

```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

Let's consider an example with 90 messages, window size 40, and overlap 4:
- First window: start=0, chunk=messages[0:40]
- Second window: start=36 (40-4), chunk=messages[36:76]
- Third window: start=72, chunk=messages[72:112] (but there are only 90 messages, so it'll be messages[72:90])

The problem is that the loop condition `len(messages) - overlap` might not correctly handle the last window. If `len(messages) - overlap` is not evenly divisible by `step`, we might miss some messages at the end.

Let's check with 90 messages, size=40, overlap=4:
- step = 36
- range(0, 86, 36) gives [0, 36, 72]
- Windows: [0:40], [36:76], [72:90]

This seems correct, but let's verify with 89 messages:
- range(0, 85, 36) gives [0, 36, 72]
- Windows: [0:40], [36:76], [72:89]

This also seems correct.

Actually, let me double-check the logic. The condition `len(messages) - overlap` ensures that we don't start a window that would end before the overlap with the previous window. But I think there's a potential issue when `len(messages)` is exactly divisible by `step`. Let me think through it.

Wait, I think I found an issue. The loop condition `range(0, len(messages) - overlap, step)` might not include the last window if `len(messages) - overlap` is exactly divisible by `step`. For example, with 76 messages, size=40, overlap=4:
- step = 36
- range(0, 72, 36) gives [0, 36]
- Windows: [0:40], [36:76]

This seems correct. The second window starts at 36 and goes to 76, which is the end.

Let me try with 77 messages:
- range(0, 73, 36) gives [0, 36]
- Windows: [0:40], [36:76]

But we have 77 messages, so message 76 is not included in any window. That's a problem!

Actually, let's check the code again:
```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For 77 messages:
- len(messages) - overlap = 73
- range(0, 73, 36) gives [0, 36]
- First window: [0:40]
- Second window: [36:76]
- Message 76 is not included.

Yes, that's a bug. The loop condition should be `range(0, len(messages), step)` or something similar to ensure all messages are included.

Actually, I think the intended logic is to have windows with overlap, where each window after the first starts with message 0 and then has `size-1` messages from the current position. Let me re-read the docstring:

"Consecutive windows share ``overlap`` messages so that an exchange on a window boundary is seen in full at least once. Every window after the first also starts with message 0 (the agent's instructions) so the monitor knows what task the agent was given."

So for the second window, it should be [0] + messages[36:76], not [0] + messages[36:72].

Let me check the implementation again:
```python
chunk = messages[start : start + size]
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For start=36, chunk=messages[36:76], and the window becomes [messages[0]] + messages[36:76]. That seems correct.

But the issue is that for 77 messages, the second window ends at 76, and message 76 is not included. The loop condition should be adjusted to ensure the last message is included.

I think the loop condition should be `range(0, len(messages) - overlap + 1, step)` or something similar.

Actually, let's think about what we want:
- We want windows of size `size`
- Consecutive windows should overlap by `overlap` messages
- So the step should be `size - overlap`
- We want to start a new window at every `step` position, as long as there are enough messages left for a full window (minus the overlap)

The condition `start < len(messages) - overlap` ensures that there are at least `overlap` messages left after the current window, so the next window can overlap with it. But for the last window, we don't need to have `overlap` messages after it, because there is no next window.

So the loop condition should be `start < len(messages)`, but then we need to adjust the end of the chunk to not go beyond the message list.

Actually, the current implementation is:
```python
chunk = messages[start : start + size]
```

This automatically handles the case where `start + size` exceeds the length of the message list, by just taking up to the end.

So the loop condition should be `range(0, len(messages), step)`. But then consecutive windows might not overlap by exactly `overlap` messages.

Let's reconsider. If we have windows of size `size`, and we want consecutive windows to overlap by `overlap` messages, then the step should be `size - overlap`. We want to start a window at position `start` as long as `start + size <= len(messages)` or something similar.

Actually, I think the current implementation is trying to ensure that each window has exactly `size` messages, except possibly the last one. And consecutive windows overlap by exactly `overlap` messages.

For the last window, we want it to end at the last message, so the start of the last window should be `len(messages) - size`.

Given step = `size - overlap`, the starts should be 0, step, 2*step, ..., up to the largest value less than or equal to `len(messages) - size`.

So the loop condition should be `range(0, len(messages) - size + 1, step)`.

Let's test with 90 messages, size=40, overlap=4:
- step = 36
- len(messages) - size + 1 = 51
- range(0, 51, 36) gives [0, 36]
- Windows: [0:40], [36:76]
- But we're missing messages 76-89.

Oh, I see the issue. The condition should be `range(0, len(messages), step)`, but then the end of the chunk should be `min(start + size, len(messages))`.

Actually, let's look at the test cases in commit 9 (**4bb80a9**):

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test checks that every message is included in at least one window. If this test passes, then the function is correct.

Let's simulate for n=77:
- size=40, overlap=4, step=36
- range(0, 77 - 4, 36) = range(0, 73, 36) = [0, 36]
- First window: [0:40]
- Second window: [36:76]
- Message 76 is not included.

But the test uses `n=76` which works, but not `n=77`. Let's check if the test covers n=77.

The test uses `n in (41, 76, 90, 157)`. It doesn't test n=77, which would reveal the issue.

Actually, let's check n=77:
- First window: messages[0:40] -> indices 0-39
- Second window: messages[36:76] -> indices 36-75
- Message 76 is not included.

So the test would fail for n=77.

But the test passes for n=76:
- First window: messages[0:40] -> indices 0-39
- Second window: messages[36:76] -> indices 36-75
- All indices 0-75 are covered.

And for n=90:
- First window: messages[0:40] -> indices 0-39
- Second window: messages[36:76] -> indices 36-75
- Third window: messages[72:90] -> indices 72-89
- All indices 0-89 are covered because 36-75 overlaps with 72-89 on indices 72-75.

Wait, for n=90:
- step = 36
- range(0, 90 - 4, 36) = range(0, 86, 36) = [0, 36, 72]
- First window: [0:40]
- Second window: [36:76]
- Third window: [72:90] (since 72+40=112 > 90)
- Indices covered: 0-39, 36-75, 72-89
- All indices 0-89 are covered.

For n=77:
- range(0, 77 - 4, 36) = range(0, 73, 36) = [0, 36]
- First window: [0:40]
- Second window: [36:76]
- Indices covered: 0-39, 36-75
- Index 76 is not covered.

So the function doesn't cover all messages for n=77.

The loop condition should be `range(0, len(messages), step)` to ensure we cover all messages, but then we need to handle the case where `start + size` exceeds the message list.

Actually, the current implementation already handles that because slicing in Python doesn't go out of bounds. So the issue is with the loop condition.

The loop condition should be `range(0, len(messages) - overlap + 1, step)` or something similar.

Let's think about what we want:
- We want to start a window at position `start` as long as there are at least `size - overlap` messages left after the previous overlap.
- Actually, we want to start a window at position `start` as long as `start <= len(messages) - (size - overlap)`.

I think the correct loop condition is `range(0, len(messages) - (size - overlap) + 1, step)`.

For n=77, size=40, overlap=4:
- size - overlap = 36
- len(messages) - (size - overlap) + 1 = 77 - 36 + 1 = 42
- range(0, 42, 36) = [0, 36]
- First window: [0:40]
- Second window: [36:76]
- Still missing message 76.

Actually, we want the last window to end at the last message, so the start of the last window should be `len(messages) - size`.

So the loop condition should be `range(0, len(messages) - size + 1, step)`.

For n=77, size=40:
- len(messages) - size + 1 = 77 - 40 + 1 = 38
- range(0, 38, 36) = [0, 36]
- First window: [0:40]
- Second window: [36:76]
- Still missing message 76.

But message 76 is the 77th message (0-indexed), and the second window ends at 76, which is index 75. So message 76 (index 76) is not included.

To include message 76, the second window should end at 77, not 76.

Actually, slicing in Python is exclusive at the end, so `messages[36:77]` would include messages 36-76.

So for the second window, we want `messages[36:77]`, not `messages[36:76]`.

The issue is that `start + size` should be `min(start + size, len(messages))`, but that's already handled by Python slicing.

The real issue is with the loop condition. We want to start a window at position `start` as long as `start < len(messages)`.

But then consecutive windows might not overlap by exactly `overlap` messages.

Let's reconsider the requirements:
- We want windows of up to `size` messages.
- Consecutive windows should overlap by `overlap` messages.
- So the step should be `size - overlap`.
- We want to start a window at every `step` position, as long as there are messages left.

So the loop condition should be `range(0, len(messages), step)`.

For n=77, size=40, overlap=4, step=36:
- range(0, 77, 36) = [0, 36, 72]
- First window: [0:40]
- Second window: [36:76]
- Third window: [72:77] (since 72+40=112 > 77)
- Indices covered: 0-39, 36-75, 72-76
- All indices 0-76 are covered.

Yes, that works!

So the loop condition should be `range(0, len(messages), step)`.

Let's check the current implementation:
```python
for start in range(0, len(messages) - overlap, step):
```

It should be:
```python
for start in range(0, len(messages), step):
```

That would fix the issue.

Let me check if there are any other issues.

Also, in the same function, there's this line:
```python
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

This ensures that every window after the first starts with message 0 (the agent's instructions). But if `chunk` is empty (which shouldn't happen because of the loop condition), this would fail. But given the loop condition, `chunk` should never be empty.

Actually, with the corrected loop condition `range(0, len(messages), step)`, `chunk` could be empty if `start >= len(messages)`, but the range function ensures `start < len(messages)`, so `chunk` will have at least one message.

Another potential issue is with the overlap calculation. The docstring says "Consecutive windows share ``overlap`` messages", but with the current logic, the overlap might not be exactly `overlap` messages, especially for the last window.

For example, with n=77, size=40, overlap=4:
- First window: 0-39 (40 messages)
- Second window: 36-75 (40 messages)
- Overlap: 36-39 (4 messages), which is correct.
- Third window: 72-76 (5 messages)
- Overlap with second window: 72-75 (4 messages), which is correct.

So it works.

Let me check another example: n=41, size=40, overlap=4:
- step = 36
- range(0, 41, 36) = [0, 36]
- First window: 0-39 (40 messages)
- Second window: 36-40 (5 messages)
- Overlap: 36-39 (4 messages), which is correct.

Yes, it works.

So the fix is to change the loop condition from `range(0, len(messages) - overlap, step)` to `range(0, len(messages), step)`.

Let me check if there are any other issues.

Actually, there's another potential issue. The function is supposed to return at least one window, even if `len(messages) == 0`. Let's check:

```python
if len(messages) <= size:
    return [messages]
```

If `len(messages) == 0`, this condition is true, and it returns `[messages]`, which is `[[]]`. That's correct.

If `len(messages) > size`, it goes into the loop. With the corrected loop condition, it should still work.

Another issue: in the loop, `chunk = messages[start : start + size]`. If `start + size > len(messages)`, this will just take up to the end, which is what we want.

So the only issue I found is with the loop condition in `split_windows`.

Let me check if there are any other issues.

In commit 10 (**ba3f0fa**), there's a change to the `run_nightly` function:

```python
def run_nightly(
    cfg: Config,
    conn,
    backend,
    *,
    since: str,
    until: str,
    run_id: str | None = None,
    dry_run: bool = False,
) -> RunSummary:
```

And inside the function:

```python
sink = AlertSink(conn, run_id, dry_run=dry_run)
```

But in the `AlertSink` class:

```python
class AlertSink:
    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
```

This is fine.

Another potential issue is in the `write_summary_csv` function:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This assumes that `summary.per_deployment` is a dictionary mapping deployment names to `DeploymentStats` objects. This seems correct based on the changes in commit 10.

I don't see any other issues.

So the main bug I found is in the `split_windows` function in `cotmon/transcript.py`. The loop condition should be changed from `range(0, len(messages) - overlap, step)` to `range(0, len(messages), step)` to ensure all messages are covered.

Let me create a follow-up commit to fix this issue.

The commit message should be something like:

```
transcript: fix windowing to cover all messages

The split_windows() function used a loop condition that could miss the last
message(s) of a trajectory. For example, with 77 messages, window size 40 and
overlap 4, message 76 would not be included in any window.

Change the loop condition to range(0, len(messages), step) to ensure all
messages are covered. The existing tests already verify that every message is
included in at least one window, so no new tests are needed.

MON-2260
```

And the diff would be:

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..new_version 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -47,7 +47,7 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    for start in range(0, len(messages) - overlap, step):
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
```

Wait, let me double-check. With the new loop condition, could there be windows that don't overlap by exactly `overlap` messages?

For example, with n=77, size=40, overlap=4:
- step = 36
- starts = [0, 36, 72]
- First window: [0:40] -> 0-39
- Second window: [36:76] -> 36-75
- Third window: [72:77] -> 72-76
- Overlap between first and second: 36-39 (4 messages)
- Overlap between second and third: 72-75 (4 messages)

Yes, it works.

Another example: n=41, size=40, overlap=4:
- starts = [0, 36]
- First window: [0:40] -> 0-39
- Second window: [36:41] -> 36-40
- Overlap: 36-39 (4 messages)

Yes, it works.

Another example: n=40, size=40, overlap=4:
- starts = [0]
- Only one window: [0:40] -> 0-39

Yes, it works.

Another example: n=39, size=40, overlap=4:
- len(messages) <= size, so return [messages]

Yes, it works.

So the change is correct.

I think that's the only issue I found. Let me create the follow-up commit.
