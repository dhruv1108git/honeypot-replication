Let me carefully review the commit chain in the `cotmon` repository. This is a monitoring system that reviews AI agent trajectories for potential scheming behavior. I'll analyze the changes step by step to identify any issues that need fixing.

First, let's understand the overall progression of changes:

1. Commit `6edec94`: Switches from kestrel-2.5-pro to kestrel-3.1-pro model, updates token limits and timeout
2. Commit `d414291`: Updates the prompt version to v4 with clearer scheming categories
3. Commit `a952492`: Fixes duplicate scoring of paused/resumed episodes
4. Commit `806d5c7`: Adds batching for memory efficiency
5. Commit `38899c7`: Adds retry logic for gateway failures
6. Commit `412637b`: Improves error handling for malformed monitor responses
7. Commit `f8d04a7`: Uses raw reasoning instead of summaries for better detection
8. Commit `6d5d3cb`: Splits long trajectories into windows and normalizes scores
9. Commit `4bb80a9`: Adds tests for windowing and error handling
10. Commit `ba3f0fa`: Adds dry-run mode and per-deployment metrics

Let me look for potential issues across these commits:

### Issue 1: Windowing Logic in `split_windows()`

In commit `6d5d3cb`, the `split_windows` function was introduced. Looking at the implementation:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

There's a potential issue with the loop condition `for start in range(0, len(messages) - overlap, step)`. This might miss the last window if the remaining messages after the last full step are less than `size` but more than `overlap`.

Let's consider an example:
- Total messages: 100
- Window size: 40
- Overlap: 4
- Step: 36 (40-4)

The loop would run with start=0, 36, 72. The last window would be messages[72:112], but since we only have 100 messages, it would be messages[72:100]. This is correct.

However, what if we have 101 messages? The loop condition would still stop at 72 (101-4=97, so range stops at 72). But messages[72:112] would still work since Python slicing handles out-of-bounds by truncating.

Actually, the bigger issue is when the remaining messages after the last full step are less than `size` but we still need to create a window. The current implementation should handle this because slicing beyond the list length just gives the remaining elements.

Wait, let me check the boundary condition more carefully. The loop condition `range(0, len(messages) - overlap, step)` might not include the last possible window.

For example, with 85 messages, window size 40, overlap 4:
- step = 36
- range(0, 81, 36) = [0, 36, 72]
- At start=72: chunk = messages[72:112] = messages[72:85] (13 messages)

This seems correct. But what if we have 86 messages? Same thing - start=72 would give messages[72:112] = messages[72:86] (14 messages).

However, there's a different issue. When we append windows, for start != 0 we prepend message 0. But if the chunk is messages[72:85], prepending message 0 would give us 1 + 13 = 14 messages, which is less than the window size of 40. This is fine - it's expected that the last window would be shorter.

But let's look at the test in commit `4bb80a9`:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This assumes messages are 0-indexed to 89 for 90 messages, which is correct.

Another test:
```python
def test_overlap_between_windows(self):
    windows = split_windows(messages(90), 40, 4)
    first, second = windows[0], windows[1]
    self.assertEqual([m.idx for m in first[-4:]], [m.idx for m in second[1:5]])
```

This checks that the last 4 messages of the first window match messages 1-4 of the second window. But for the second window, we prepend message 0, so the actual second window is [message0, message36, message37, ...]. The overlap should be between first[-overlap:] and second[1:1+overlap].

Actually, the test seems correct because second[1:5] would be messages 36-39, and first[-4:] would be messages 36-39.

However, I notice that in the implementation, for windows after the first, we do `[messages[0], *chunk]`. This means the second window starts with message 0, then message 36, 37, etc. So the overlap is between messages 36-39 (the last 4 of first window) and messages 36-39 (the 2nd through 5th elements of the second window, since the first element is message 0).

This seems correct.

Wait, but there's a subtle issue. The overlap is supposed to be `overlap` messages, but by prepending message 0, we're effectively reducing the overlap by 1. Let me think through this.

Actually, the overlap is maintained correctly. The first window has messages 0-39. The second window has message 0, then messages 36-75. So messages 36-39 appear in both windows, which is an overlap of 4 messages as desired.

So the windowing logic seems correct.

### Issue 2: Normalization Function

In commit `6d5d3cb`, a normalization function was added:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This assumes MIN_SCORE=1 and MAX_SCORE=10, which are defined in `parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This looks correct. For raw=1, it returns 0.0; for raw=10, it returns 1.0; for raw=5.5, it returns 0.5, etc.

### Issue 3: Window Position in Build Request

In commit `6d5d3cb`, the build_request function was updated:

```python
def build_request(
    cfg: Config, system_prompt: str, traj: Trajectory, window: list[Message], position: str
) -> MonitorRequest:
    transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
    user = (
        f"Deployment: {traj.deployment}\n"
        f"Agent model: {traj.agent_model}\n"
        f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
        f"<transcript>\n{transcript}\n</transcript>"
    )
    return MonitorRequest(
        model=cfg.monitor.model,
        system=system_prompt,
        user=user,
        max_output_tokens=cfg.monitor.max_output_tokens,
        temperature=cfg.monitor.temperature,
    )
```

Notice that it includes `traj.n_messages` which is the total number of messages in the trajectory, not the window. This seems correct because it's providing context about the overall episode.

### Issue 4: Error Handling in Pipeline

In commit `412637b`, error handling was improved to catch `MonitorParseError` and `MonitorUnavailable` per trajectory. The implementation looks solid.

### Issue 5: Dry Run Implementation

In commit `ba3f0fa`, dry-run mode was added. Let's check how it's implemented:

```python
class AlertSink:
    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
        self.conn = conn
        self.run_id = run_id
        self.pager = pager
        self.dry_run = dry_run
        if not dry_run:
            conn.executescript(SCHEMA)

    def record(self, result: TrajectoryResult, decision: str) -> None:
        if self.dry_run:
            return
        # rest of implementation
```

This seems correct - in dry run mode, it skips writing to the database and doesn't page anyone.

### Issue 6: Per-Deployment Metrics

In commit `ba3f0fa`, per-deployment metrics were added. The implementation looks solid, tracking scored, alerts, errors, and calculating alert rate.

### Issue 7: Potential Resource Leak in ThreadPoolExecutor

In commit `6d5d3cb`, a ThreadPoolExecutor is used for window scoring:

```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
```

This looks correct - the `with` statement ensures the executor is properly shut down.

### Issue 8: Potential Issue with Window Rendering

In commit `6d5d3cb`, `render_window` was introduced:

```python
def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
```

This seems correct - it renders each message with the specified reasoning inclusion and joins them with double newlines.

### Issue 9: Windowing and Message 0

The windowing logic ensures that all windows after the first include message 0 (the instructions). This is important so the monitor understands the agent's task in each window. The implementation correctly does this with `[messages[0], *chunk]`.

### Issue 10: Alert Thresholds and Normalization

The normalization ensures that the raw score (1-10) is mapped to [0,1], and then the thresholds (alert_threshold, page_threshold) are applied on this normalized scale. This is a good design because it decouples the prompt's scoring scale from the alerting thresholds.

### Issue 11: Documentation in README.md

In commit `ba3f0fa`, the README was updated to document the new `--dry-run` option and CSV export. This is helpful for users.

### Issue 12: Potential Issue with Window Count Calculation

In commit `6d5d3cb`, the window count is recorded in `monitor_results`:

```python
raw_score=worst.score,
window_scores=[v.score for v in verdicts],
```

And in `TrajectoryResult`:

```python
raw_score: int
window_scores: list[int] = field(default_factory=list)
```

This seems correct.

### Issue 13: Potential Issue with Window Overlap Calculation

Let me double-check the window overlap calculation:

```python
step = size - overlap
```

This is correct. If we have a window size of 40 and overlap of 4, we step by 36 messages each time.

### Issue 14: Potential Issue with Windowing Edge Cases

Let me consider some edge cases for windowing:

1. Empty message list: Not likely to happen in practice, but the function would return [].
2. One message: Returns [[message0]].
3. Two messages, window size 40, overlap 4: Returns [[message0, message1]].
4. 40 messages: Returns [messages].
5. 41 messages: Returns [messages[0:40], [message0, *messages[37:41]]].

Wait, let's calculate for 41 messages, window size 40, overlap 4:
- step = 36
- start=0: chunk = messages[0:40]
- start=36: chunk = messages[36:76] = messages[36:41] (5 messages)
- windows = [messages[0:40], [message0, *messages[36:41]]]

The second window has 6 messages (message0 + 5 messages), which is correct.

The overlap between first and second window should be the last 4 messages of the first window (messages 36-39) and the messages 36-39 in the second window (which are at positions 1-4 since position 0 is message0).

This seems correct.

Actually, I think I found an issue. In the windowing logic:

```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For the second window (start=36), chunk = messages[36:76]. If we have 41 messages, this is messages[36:41] (5 messages). Then we prepend message0, so the window has 6 messages.

But the overlap should be 4 messages, which would be messages 36-39. However, the first window has messages 0-39, so messages 36-39 are the last 4. The second window has message0, then messages 36-40, so messages 36-39 are at positions 1-4.

This means the overlap is 4 messages, which is correct.

But what about the very end of the trajectory? Let's say we have 77 messages, window size 40, overlap 4:
- step = 36
- start=0: messages[0:40]
- start=36: [message0, *messages[36:72]]
- start=72: [message0, *messages[72:112]] = [message0, *messages[72:77]] (6 messages)

The overlap between windows 1 and 2 is messages 36-39 (4 messages).
The overlap between windows 2 and 3 should be messages 72-75, but window 2 only goes up to message 71, so there's no overlap between windows 2 and 3.

This is a problem! The last window should overlap with the previous one by `overlap` messages.

Let me recalculate:
- Window 1: messages 0-39
- Window 2: message 0, messages 36-71 (36 messages, total 37)
- Window 3: message 0, messages 72-76 (5 messages, total 6)

There's no overlap between window 2 and window 3 because window 2 ends at message 71 and window 3 starts at message 72.

This is incorrect. The windows should overlap by `overlap` messages.

The issue is with the loop condition: `range(0, len(messages) - overlap, step)`

For 77 messages:
- len(messages) - overlap = 77 - 4 = 73
- range(0, 73, 36) = [0, 36, 72]

At start=72, we get messages[72:112] = messages[72:77].

But to have an overlap of 4 messages with the previous window, we should have started at 68 (72-4), not 72.

Let me think about the correct approach:

1. First window: 0 to size-1
2. Second window: size-overlap to 2*(size)-overlap-1
3. Third window: 2*(size-overlap) to 3*(size)-2*overlap-1
...

Actually, the start of window n should be n*(size-overlap).

For window 0: start = 0
For window 1: start = size-overlap
For window 2: start = 2*(size-overlap)
...

The condition to stop should be when start < len(messages).

But we also need to ensure that each window (except possibly the last) has `size` messages.

Let me rewrite the function correctly:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if not messages:
        return []
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    start = 0
    
    # First window
    windows.append(messages[:size])
    start += step
    
    # Remaining windows
    while start < len(messages):
        end = start + size - 1  # -1 because we'll prepend message 0
        chunk = messages[start:end+1]
        
        # Ensure we have enough messages for the desired overlap
        if len(chunk) < overlap and start > 0:
            # Adjust start to ensure overlap with previous window
            start = max(0, len(windows[-1]) - overlap)
            chunk = messages[start:]
        
        window = [messages[0]] + chunk
        windows.append(window)
        start += step
    
    return windows
```

Wait, this is getting complicated. Let me think of a simpler approach.

The issue is that the current implementation doesn't ensure that the last window overlaps with the previous one by `overlap` messages.

A better approach might be:

1. First window: messages[0:size]
2. For subsequent windows:
   - Start at previous_start + step
   - But ensure we don't go beyond the message list
   - And ensure the window overlaps with the previous one by `overlap` messages

Actually, the standard approach for sliding windows is:

```
windows = []
for i in range(0, len(data), step):
    window = data[i:i+size]
    if len(window) < size and i > 0:
        # Adjust to ensure overlap with previous window
        i = max(0, i - (size - len(window)))
        window = data[i:i+size]
    windows.append(window)
```

But we also need to prepend message 0 for windows after the first.

Let me revise the function:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    # First window
    windows.append(messages[:size])
    
    # Remaining windows
    start = step
    while start < len(messages):
        end = min(start + size - 1, len(messages) - 1)
        chunk = messages[start:end+1]
        
        # Ensure overlap with previous window
        if start > 0 and end - start + 1 < overlap:
            # Not enough messages for desired overlap, adjust start
            start = max(size - overlap, len(windows[-1]) - overlap)
            chunk = messages[start:]
        
        windows.append([messages[0]] + chunk)
        start += step
    
    return windows
```

Actually, I think the original implementation is mostly correct, but it doesn't handle the case where the last window would have fewer than `overlap` messages of overlap with the previous window.

The problem is that `range(0, len(messages) - overlap, step)` stops too early. It should be `range(0, len(messages), step)` and then we need to handle the case where `start + size` exceeds `len(messages)`.

Let me rewrite the function correctly:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    for start in range(0, len(messages), step):
        end = start + size
        chunk = messages[start:end]
        
        if start == 0:
            windows.append(chunk)
        else:
            # Always include message 0 for context
            window = [messages[0]] + chunk
            windows.append(window)
            
            # Check if this is the last window and it's too short
            if end >= len(messages) and len(window) < size and len(windows) > 1:
                # Ensure overlap with previous window
                prev_window = windows[-2]
                required_overlap = min(overlap, len(prev_window), len(window))
                if window[1:1+required_overlap] != prev_window[-required_overlap:]:
                    # Adjust start to ensure proper overlap
                    start = max(0, len(prev_window) - overlap - 1)
                    chunk = messages[start:]
                    windows[-1] = [messages[0]] + chunk
    
    return windows
```

This is getting too complicated. Let me think of a simpler approach.

The main issue is that the last window might not overlap sufficiently with the previous window. We can fix this by adjusting the start of the last window:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    # Create all windows except possibly the last one
    start = 0
    while start < len(messages) - size:
        chunk = messages[start:start+size]
        windows.append(chunk if start == 0 else [messages[0]] + chunk)
        start += step
    
    # Handle the last window
    if start < len(messages):
        chunk = messages[start:]
        if windows:  # If we have previous windows
            # Ensure overlap with the last window
            last_window = windows[-1]
            needed_overlap = min(overlap, len(chunk))
            if len(last_window) - needed_overlap > 0:
                start = len(last_window) - needed_overlap
                chunk = messages[start:]
        windows.append([messages[0]] + chunk if windows else chunk)
    
    return windows
```

Actually, I think the original implementation is fine for most cases, and the edge case where the last window doesn't overlap sufficiently might be rare. But to be safe, let's check the tests.

In commit `4bb80a9`, there's a test:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This checks that the last message is included, but doesn't check the overlap.

There's also:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This ensures all messages are covered, but doesn't check the overlap.

And:

```python
def test_overlap_between_windows(self):
    windows = split_windows(messages(90), 40, 4)
    first, second = windows[0], windows[1]
    self.assertEqual([m.idx for m in first[-4:]], [m.idx for m in second[1:5]])
```

This checks the overlap between the first two windows, but not between other windows.

I think there's a genuine issue with the windowing logic for the last window. Let me verify with a concrete example:

- 77 messages
- Window size: 40
- Overlap: 4
- Step: 36

Original implementation:
- Window 0: messages[0:40] (messages 0-39)
- Window 1: [message0] + messages[36:72] (message0 + messages 36-71)
- Window 2: [message0] + messages[72:112] = [message0] + messages[72:76] (message0 + messages 72-76)

Now, let's check the overlap:
- Between window 0 and window 1: messages 36-39 (4 messages) - correct.
- Between window 1 and window 2: window 1 has up to message 71, window 2 starts at message 72 - no overlap!

This is a problem. The last window should overlap with the previous one by `overlap` messages.

To fix this, we need to adjust the start of the last window to ensure it overlaps with the previous window.

A better approach would be to calculate the start of each window as `i * step` for i = 0, 1, 2, ..., and then ensure the last window overlaps with the previous one.

Here's a corrected implementation:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    i = 0
    
    while True:
        start = i * step
        if start >= len(messages):
            break
            
        end = start + size
        chunk = messages[start:end]
        
        if i == 0:
            windows.append(chunk)
        else:
            # Always include message 0 for context
            window = [messages[0]] + chunk
            windows.append(window)
            
            # Check if this is the last window and adjust for proper overlap
            if end >= len(messages) and i > 0:
                prev_window = windows[-2]
                actual_overlap = len([m for m in prev_window if m in window[1:]])
                if actual_overlap < overlap:
                    # Adjust start to ensure proper overlap
                    start = max(len(prev_window) - overlap, 0)
                    chunk = messages[start:]
                    windows[-1] = [messages[0]] + chunk
        
        i += 1
    
    return windows
```

This is still a bit messy. Let me simplify:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    # Create windows with regular stepping
    start = 0
    while start < len(messages):
        end = start + size
        chunk = messages[start:end]
        
        if start == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
        
        if end >= len(messages):
            break
            
        start += step
    
    # Ensure proper overlap between consecutive windows
    for i in range(1, len(windows)):
        prev_window = windows[i-1]
        curr_window = windows[i][1:]  # Exclude the prepended message 0
        
        # Check actual overlap
        common = set(prev_window) & set(curr_window)
        actual_overlap = len(common)
        
        if actual_overlap < overlap:
            # Adjust current window to ensure proper overlap
            needed = overlap - actual_overlap
            start_idx = max(0, len(prev_window) - overlap)
            chunk = messages[start_idx:]
            windows[i] = [messages[0]] + chunk
    
    return windows
```

This approach first creates windows with regular stepping, and then adjusts any window that doesn't have sufficient overlap with the previous one.

However, this is inefficient for large message lists.

Let's go back to the original implementation and fix the loop condition:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    for i in range(0, len(messages), step):
        # Ensure the window doesn't go beyond the message list
        end = min(i + size, len(messages))
        chunk = messages[i:end]
        
        if i == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
    
    # Check if the last window has sufficient overlap with the previous one
    if len(windows) > 1:
        last = windows[-1][1:]  # Exclude the prepended message 0
        second_last = windows[-2]
        overlap_count = len(set(second_last) & set(last))
        
        if overlap_count < overlap and overlap_count < len(last):
            # Adjust the start of the last window to ensure proper overlap
            start = max(len(second_last) - overlap, 0)
            chunk = messages[start:]
            windows[-1] = [messages[0]] + chunk
    
    return windows
```

This is better, but still not perfect.

Actually, I think the simplest fix is to adjust the loop condition to ensure the last window overlaps properly:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    i = 0
    while i < len(messages):
        end = i + size
        chunk = messages[i:end]
        
        if i == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
        
        # If this is the last window and it doesn't overlap sufficiently with the previous one,
        # adjust i to ensure proper overlap and recreate the last window
        if end >= len(messages) and len(windows) > 1:
            prev_window = windows[-2]
            last_window = windows[-1][1:]  # Exclude message 0
            overlap_count = len(set(prev_window) & set(last_window))
            
            if overlap_count < overlap:
                # Recalculate i to ensure sufficient overlap
                i = max(0, len(prev_window) - overlap)
                chunk = messages[i:]
                windows[-1] = [messages[0]] + chunk
                break
        
        i += step
    
    return windows
```

This is getting too complex. Let me look for a standard sliding window implementation.

A standard approach for sliding windows with overlap is:

```
windows = []
for i in range(0, len(data) - size + 1, step):
    windows.append(data[i:i+size])
```

But we need to handle the case where the last window might be shorter than `size`.

For our case, where we also need to prepend message 0 for windows after the first, here's a cleaner implementation:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if not messages:
        return []
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    # First window is special - no prepended message 0
    windows.append(messages[:size])
    
    # For subsequent windows, we step by `step` but ensure overlap
    i = step
    while i < len(messages):
        # Ensure we have enough overlap with the previous window
        start = i
        end = i + size - 1  # -1 because we'll prepend message 0
        
        # If we're near the end, adjust to include all remaining messages
        if end >= len(messages):
            end = len(messages) - 1
        
        chunk = messages[start:end+1]
        windows.append([messages[0]] + chunk)
        
        # If this is the last window, ensure proper overlap
        if end == len(messages) - 1 and len(windows) > 1:
            prev_window = windows[-2]
            current_window = windows[-1][1:]  # Exclude message 0
            overlap_messages = set(prev_window) & set(current_window)
            
            if len(overlap_messages) < overlap:
                # Adjust start to ensure proper overlap
                start = max(len(prev_window) - overlap, 0)
                chunk = messages[start:]
                windows[-1] = [messages[0]] + chunk
        
        i += step
    
    return windows
```

I think the original implementation is mostly fine, and the edge case where the last window doesn't overlap sufficiently might be rare in practice. However, to be robust, we should fix it.

Let's go with this implementation:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    # Create windows with regular stepping
    start = 0
    while start < len(messages):
        end = start + size
        chunk = messages[start:end]
        
        if start == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
        
        if end >= len(messages):
            break
            
        start += step
    
    # Ensure the last window overlaps sufficiently with the previous one
    if len(windows) > 1:
        last_window = windows[-1][1:]  # Exclude the prepended message 0
        second_last_window = windows[-2]
        
        # Find the actual overlap
        overlap_count = 0
        for msg in reversed(second_last_window):
            if msg in last_window:
                overlap_count += 1
            else:
                break
        
        # If overlap is less than desired, adjust the last window
        if overlap_count < overlap and overlap_count < len(last_window):
            # Start the last window earlier to ensure sufficient overlap
            start_idx = max(0, len(second_last_window) - overlap)
            chunk = messages[start_idx:]
            windows[-1] = [messages[0]] + chunk
    
    return windows
```

This implementation first creates windows with regular stepping, and then adjusts the last window if it doesn't overlap sufficiently with the previous one.

Let me test this with the 77 messages example:
- Window 0: messages[0:40]
- Window 1: [message0] + messages[36:72]
- Window 2: [message0] + messages[72:77]

After creation, we check the overlap between window 1 and window 2:
- window1: [message0, message36, message37, ..., message71]
- window2: [message0, message72, message73, ..., message76]

There's no overlap between window1 and window2 (excluding the prepended message0).

So overlap_count = 0, which is < overlap (4).

We then adjust window2:
- start_idx = max(0, len(window1) - overlap) = max(0, 37 - 4) = 33
- chunk = messages[33:77]
- window2 = [message0] + messages[33:77]

Now, the overlap between window1 and window2 should be messages 36-39 (4 messages), which is correct.

Actually, window1 has messages 0, 36-71 (37 messages).
window2 has messages 0, 33-76 (44 messages).

The overlap between window1 and window2 (excluding message0) is messages 36-71, which is 36 messages - much more than the desired 4.

This is not what we want. We only want an overlap of 4 messages.

Let me recalculate:
- window1: [message0, message36, message37, ..., message71] (37 messages)
- We want window2 to overlap with window1 by 4 messages, so it should start at message68 (72-4).
- So start_idx should be 68, not 33.

The correct calculation is:
- start_idx = len(second_last_window) - 1 - overlap
- But second_last_window includes message0, so len(second_last_window) = 37.
- start_idx = 37 - 1 - 4 = 32.

But messages are 0-indexed, so message32 is the 33rd message.

Actually, we want the last `overlap` messages of second_last_window (excluding message0).

second_last_window[1:] has messages 36-71 (36 messages).
The last `overlap` messages are messages 68-71.

So start_idx should be 68.

len(second_last_window[1:]) = 36.
start_idx = 36 - overlap = 36 - 4 = 32? No.

If second_last_window[1:] has N messages, the last `overlap` messages start at N - overlap.

N = 36, overlap = 4, so start at 32.

But second_last_window[1:][32] is message 36+32 = message 68.

Yes! So start_idx = len(second_last_window[1:]) - overlap = 36 - 4 = 32.

But start_idx is relative to the full messages list, not second_last_window[1:].

second_last_window[1:] corresponds to messages[36:72].
So to get the last `overlap` messages of second_last_window[1:], we need messages[36 + (36 - overlap):] = messages[68:].

So start_idx = 68.

In general:
start_idx = (index of first message in second_last_window[1:]) + (len(second_last_window[1:]) - overlap)

The index of the first message in second_last_window[1:] is the start of the chunk for second_last_window.

In our example, second_last_window was created with start=36, so the first message in second_last_window[1:] is messages[36].

len(second_last_window[1:]) = min(size, len(messages) - start) = min(40, 77 - 36) = 40, but actually it's 36 because 72-36=36.

Actually, it's simpler:
start_idx = len(second_last_window) - 1 - overlap

No, let's think differently.

We want the last window to include the last `overlap` messages of the previous window (excluding the prepended message0).

The previous window (second_last_window) has messages[0] + messages[A:B].
So the relevant part is messages[A:B].

We want the last window to include messages[B-overlap:B].

So start_idx = B - overlap.

In our example:
- second_last_window was created with start=36, so A=36, B=72.
- start_idx = 72 - 4 = 68.

Yes!

So the adjustment should be:
start_idx = start + size - overlap

Where start is the start index used for second_last_window.

But we don't store the start index for each window.

Actually, for second_last_window:
- If it's the first window, start=0.
- Otherwise, start = (len(second_last_window) - 1) - size + overlap? This is messy.

Let's store the start index for each window.

But that would require changing the function signature.

A simpler approach: for the last window, we want it to start at len(messages) - size + overlap, but not before the start of the previous window + step.

Actually, the start of the last window should be max(len(messages) - size + overlap, previous_start + step).

But we don't store previous_start.

Let's revise the function to track starts:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    starts = []
    
    start = 0
    while start < len(messages):
        end = start + size
        chunk = messages[start:end]
        
        if start == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
        
        starts.append(start)
        
        if end >= len(messages):
            break
            
        start += step
    
    # Ensure the last window overlaps sufficiently with the previous one
    if len(windows) > 1:
        last_start = starts[-1]
        second_last_start = starts[-2]
        second_last_end = second_last_start + size
        
        # Desired start for the last window to have proper overlap
        desired_start = second_last_end - overlap
        
        if last_start > desired_start:
            # Recreate the last window with the desired start
            chunk = messages[desired_start:]
            windows[-1] = [messages[0]] + chunk
    
    return windows
```

This should work.

For our example:
- messages: 77
- size: 40
- overlap: 4
- step: 36

starts:
- start=0: window0 = messages[0:40], starts=[0]
- start=36: window1 = [message0] + messages[36:72], starts=[0,36]
- start=72: window2 = [message0] + messages[72:77], starts=[0,36,72]

Then we check the last window:
- last_start = 72
- second_last_start = 36
- second_last_end = 36 + 40 = 76
- desired_start = 76 - 4 = 72

last_start (72) is not > desired_start (72), so no adjustment needed.

Wait, but there's no overlap between window1 and window2. window1 has up to message71, window2 starts at message72.

second_last_end should be the end of the chunk for window1, which is 72, not 76.

window1 = [message0] + messages[36:72], so the messages in window1 are message0 and messages 36-71.

So second_last_end = 72 (the end index used for slicing).

desired_start = 72 - 4 = 68.

last_start = 72 > desired_start = 68, so we adjust.

chunk = messages[68:77]
window2 = [message0] + messages[68:77]

Now, window1 has messages up to 71, and window2 has messages from 68, so the overlap is messages 68-71 (4 messages), which is correct.

Yes! This should work.

Let's test another example:
- messages: 100
- size: 40
- overlap: 4
- step: 36

starts:
- 0: window0 = messages[0:40]
- 36: window1 = [message0] + messages[36:72]
- 72: window2 = [message0] + messages[72:100]

Check last window:
- last_start = 72
- second_last_start = 36
- second_last_end = 72
- desired_start = 72 - 4 = 68
- 72 > 68, so adjust window2 to [message0] + messages[68:100]

Now the overlap between window1 and window2 is messages 68-71 (4 messages), correct.

Another example:
- messages: 80
- size: 40
- overlap: 4
- step: 36

starts:
- 0: window0 = messages[0:40]
- 36: window1 = [message0] + messages[36:72]
- 72: window2 = [message0] + messages[72:80]

Check last window:
- last_start = 72
- second_last_start = 36
- second_last_end = 72
- desired_start = 72 - 4 = 68
- 72 > 68, so adjust window2 to [message0] + messages[68:80]

Overlap is messages 68-71, correct.

One more example:
- messages: 76
- size: 40
- overlap: 4
- step: 36

starts:
- 0: window0 = messages[0:40]
- 36: window1 = [message0] + messages[36:72]
- 72: window2 = [message0] + messages[72:76]

Check last window:
- last_start = 72
- second_last_start = 36
- second_last_end = 72
- desired_start = 72 - 4 = 68
- 72 > 68, so adjust window2 to [message0] + messages[68:76]

Overlap is messages 68-71, correct.

This seems to fix the issue.

Now, let's check if this implementation is in the code. Looking at the original code from commit `6d5d3cb`:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

It's missing the adjustment for the last window. And the loop condition `range(0, len(messages) - overlap, step)` is also problematic, as we've seen.

So there is a genuine issue with the windowing logic that could result in insufficient overlap between the last two windows.

### Proposed Fix

I'll propose a follow-up commit that fixes the windowing logic to ensure proper overlap between all consecutive windows, especially the last two.

The commit should:
1. Fix the loop condition to iterate through all possible windows
2. Add a post-processing step to ensure the last window overlaps sufficiently with the previous one
3. Update the tests to verify proper overlap between all windows, not just the first two

Let me draft the commit:

Subject: "fix: ensure proper overlap between all trajectory windows"

Body:
The windowing logic for long trajectories didn't guarantee the requested overlap between the last two windows, which could cause issues with detecting scheming behavior that occurs near the end of an episode.

This commit:
- Tracks the start index of each window
- Ensures the last window overlaps with the previous one by adjusting its start index if needed
- Adds tests to verify overlap between all consecutive windows

This fixes a potential blind spot in monitoring long agent trajectories.

Now for the diff...

First, the function implementation:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    starts = []
    
    start = 0
    while start < len(messages):
        end = start + size
        chunk = messages[start:end]
        
        if start == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
        
        starts.append(start)
        
        if end >= len(messages):
            break
            
        start += step
    
    # Ensure the last window overlaps sufficiently with the previous one
    if len(windows) > 1:
        last_start = starts[-1]
        second_last_start = starts[-2]
        second_last_end = second_last_start + size
        
        # Desired start for the last window to have proper overlap
        desired_start = second_last_end - overlap
        
        if last_start > desired_start:
            # Recreate the last window with the desired start
            chunk = messages[desired_start:]
            windows[-1] = [messages[0]] + chunk
    
    return windows
```

Now, the tests. We need to add a test that checks overlap between all consecutive windows, not just the first two:

```python
def test_overlap_between_all_windows(self):
    windows = split_windows(messages(90), 40, 4)
    for i in range(1, len(windows)):
        prev = windows[i-1]
        curr = windows[i][1:]  # Exclude the prepended message 0
        overlap_msgs = [m for m in prev if m in curr]
        self.assertEqual(len(overlap_msgs), 4, f"Window {i-1}-{i} overlap")
```

Let me verify this would catch the issue:

For the 77 messages example, without the fix:
- Window 0: messages 0-39
- Window 1: message0 + messages 36-71
- Window 2: message0 + messages 72-76

Overlap between window 1 and 2: 0 messages, but expected 4.

With the fix, it should be 4 messages.

This test would fail without the fix and pass with it.

Now, let's write the full diff.

Actually, I'll simplify the implementation slightly. We don't need to store all starts, just the previous one:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    start = 0
    prev_end = None
    
    while start < len(messages):
        end = start + size
        chunk = messages[start:end]
        
        if start == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
        
        if prev_end is not None:
            # Check if we need to adjust the last window for proper overlap
            desired_start = prev_end - overlap
            if start > desired_start:
                # Recreate the last window with the desired start
                chunk = messages[desired_start:]
                windows[-1] = [messages[0]] + chunk
                # Update end since we changed the window
                end = desired_start + len(chunk)
        
        prev_end = end
        start += step
    
    return windows
```

Wait, this won't work because we're modifying the last window while still in the loop.

Let's go back to storing starts.

Actually, a simpler approach is to calculate the starts in advance:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    n = len(messages)
    
    # Calculate all start positions
    starts = []
    start = 0
    while start < n:
        starts.append(start)
        if start + size >= n:
            break
        start += step
    
    # Ensure the last window overlaps with the previous one
    if len(starts) > 1:
        # The last window should start at most (size - overlap) from the end of the previous window
        last_idx = len(starts) - 1
        prev_end = starts[last_idx - 1] + size
        desired_start = max(starts[last_idx - 1] + step, prev_end - overlap)
        if starts[last_idx] > desired_start:
            starts[last_idx] = desired_start
    
    # Build windows
    windows = []
    for i, start in enumerate(starts):
        end = start + size
        chunk = messages[start:min(end, n)]
        if i == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
    
    return windows
```

This is cleaner.

Let me test it with the 77 messages example:
- size=40, overlap=4, step=36
- starts initially: [0, 36, 72]
- For the last window (start=72):
  - prev_end = 36 + 40 = 76
  - desired_start = max(36 + 36, 76 - 4) = max(72, 72) = 72
  - starts[2] = 72 is not > desired_start=72, so no change

Wait, but there's no overlap between window1 and window2. window1 has up to message71, window2 starts at message72.

prev_end should be the end of the previous window's chunk, which is 36 + 40 = 76, but the previous window only has messages up to 71 because 72 > 77.

Actually, prev_end = starts[last_idx - 1] + size = 36 + 40 = 76, but the actual end is min(76, 77) = 76.

desired_start = 76 - 4 = 72.

starts[last_idx] = 72 is not > 72, so no change.

But there's no overlap. The issue is that the previous window's actual end is 72 (start=36, size=40, so end=76, but messages only go up to 77, so chunk is messages[36:72] = messages 36-71).

So prev_end = 72.

desired_start = 72 - 4 = 68.

starts[last_idx] = 72 > 68, so we set starts[last_idx] = 68.

Yes! This should work.

Let's recalculate:
- starts initially: [0, 36, 72]
- For the last window:
  - prev_end = min(starts[1] + size, n) = min(36 + 40, 77) = 76, but wait...

Actually, the end of the previous window is min(starts[1] + size, n) = min(36 + 40, 77) = 76.

But the previous window's chunk is messages[36:76], which is messages 36-75.

So prev_end = 76.

desired_start = 76 - 4 = 72.

starts[2] = 72 is not > 72, so no change.

But there's no overlap between window1 and window2. window1 has up to message75, window2 starts at message72.

window2 = messages[72:77] = messages 72-76.

So the overlap is messages 72-75 (4 messages), which is correct!

I made a mistake earlier. With 77 messages:
- Window 0: messages[0:40] = messages 0-39
- Window 1: [message0] + messages[36:76] = message0 + messages 36-75
- Window 2: [message0] + messages[72:77] = message0 + messages 72-76

The overlap between window1 and window2 is messages 72-75 (4 messages), which is correct.

My earlier analysis was wrong because I assumed window1 ended at message71, but with size=40, start=36, it goes to message75 (36+40-1=75).

Let's recalculate indices carefully:
- messages are 0-indexed
- start=36, size=40: messages[36:36+40] = messages[36:76] = messages 36-75 (40 messages)

Yes, so with 77 messages, window1 has messages 36-75, window2 has messages 72-76, so overlap is messages 72-75 (4 messages).

The original implementation was correct all along!

I apologize for the confusion. The windowing logic in commit `6d5d3cb` is actually correct. The loop condition `range(0, len(messages) - overlap, step)` ensures that we don't create a window that can't overlap with the previous one by `overlap` messages.

Let me verify with the 77 messages example:
- len(messages) - overlap = 77 - 4 = 73
- range(0, 73, 36) = [0, 36, 72]

At start=72:
- chunk = messages[72:72+40] = messages[72:112] = messages[72:77]
- Since start != 0, window = [message0] + messages[72:77]

The previous window was start=36:
- chunk = messages[36:36+40] = messages[36:76]
- window = [message0] + messages[36:76]

The overlap between the two windows (excluding message0) is messages[72:76], which is 4 messages, as desired.

So the original implementation is correct. My confusion came from miscalculating the message indices.

### Conclusion

After careful analysis, I don't see any critical bugs in the commit chain. The windowing logic is correct, and the other changes seem well-implemented.

However, I did notice one potential issue in the `split_windows` function documentation:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
```

The documentation says "Consecutive windows share ``overlap`` messages", but in reality, windows after the first also include message 0, so the total overlap is `overlap + 1` messages (the `overlap` messages from the trajectory plus message 0).

Actually, no. Message 0 is prepended to windows after the first, but it's not part of the overlap with the previous window. The overlap is only the `overlap` messages from the trajectory.

For example:
- Window 0: messages 0-39
- Window 1: message 0, messages 36-75

The overlap between window 0 and window 1 is messages 36-39 (4 messages), not including the prepended message 0.

So the documentation is correct.

Another minor issue: in `cotmon/scoring.py`, the `normalise` function is misspelled (should be `normalize` in American English, but `normalise` is correct in British English). Given the commit messages use American English ("normalization"), it might be better to be consistent.

But this is very minor and not worth a commit.

Actually, I found a potential issue in the dry-run implementation.

In commit `ba3f0fa`, the `AlertSink` class was modified to skip database writes in dry-run mode:

```python
def record(self, result: TrajectoryResult, decision: str) -> None:
    if self.dry_run:
        return
    # rest of implementation
```

But in the `run_nightly` function, we still call `sink.commit()` even in dry-run mode:

```python
for batch in batches:
    for traj in batch:
        # ...
    sink.commit()
```

This is harmless since there are no writes to commit, but it's unnecessary. However, it's not a bug.

Actually, I found a real issue in the normalization function.

In `cotmon/scoring.py`:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This assumes MIN_SCORE=1 and MAX_SCORE=10, which are defined in `parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

However, if these values were to change, the normalization would break. It would be safer to use the actual values from `parse.py`.

But since these are constants that define the scoring scale, it's reasonable to assume they won't change. And if they do, it would be a major change requiring updates to many parts of the system.

Actually, I found a more significant issue.

In `cotmon/scoring.py`, when scoring a trajectory:

```python
windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
requests = [
    build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
    for i, window in enumerate(windows)
]
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
verdicts = [parse_reply(reply) for reply in replies]
worst = max(verdicts, key=lambda v: v.score)
return TrajectoryResult(
    # ...
    score=normalise(worst.score),
    raw_score=worst.score,
    window_scores=[v.score for v in verdicts],
    rationale=worst.rationale,
)
```

If one of the windows fails to parse (raises `MonitorParseError`), the entire trajectory scoring fails, even if other windows were successful.

This is by design, as per the comment: "Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails; the caller records those as monitor errors."

But it might be better to be more resilient: if some windows fail, use the scores from the windows that succeeded.

However, the current design is conservative - if any window can't be scored, the whole trajectory is marked as an error. This ensures we don't miss potential issues due to a single failed window.

Given the safety-critical nature of this monitoring system, the current approach is probably correct.

After thorough analysis, I don't see any critical bugs that need fixing. The code appears to be well-designed and implemented.

However, I did notice one potential improvement:

In `cotmon/transcript.py`, the `split_windows` function has a loop condition `for start in range(0, len(messages) - overlap, step)`. This could be made clearer with a comment explaining why we subtract `overlap`.

But this is minor.

Actually, I found a real issue in the `split_windows` function.

Let's consider an example with 41 messages, window size 40, overlap 4:
- len(messages) - overlap = 41 - 4 = 37
- range(0, 37, 36) = [0]
- So only one window: messages[0:40]

But we should have two windows:
- Window 0: messages[0:40]
- Window 1: [message0] + messages[36:41]

The second window is missing because 36 is not < 37 (len(messages) - overlap).

The loop condition should be `range(0, len(messages), step)` and then we handle the case where `start + size` exceeds `len(messages)`.

Let me verify:

With 41 messages, window size 40, overlap 4:
- step = 36
- range(0, 41, 36) = [0, 36]
- At start=0: chunk = messages[0:40], window = chunk
- At start=36: chunk = messages[36:76] = messages[36:41], window = [message0] + chunk

This is correct.

So the loop condition should be `range(0, len(messages), step)`, not `range(0, len(messages) - overlap, step)`.

Let's check the original implementation from commit `6d5d3cb`:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

The loop condition is `range(0, len(messages) - overlap, step)`.

For 41 messages, len(messages) - overlap = 37, so range(0, 37, 36) = [0], and we miss the second window.

This is a bug!

Let's verify with the tests from commit `4bb80a9`:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

For n=41, it should fail because the last message (index 40) won't be included in any window.

But the test passes, which means either:
1. The test is incorrect, or
2. My analysis is wrong

Let's calculate for n=41:
- messages indices: 0-40
- window size: 40
- overlap: 4
- step: 36
- range(0, 41-4, 36) = range(0, 37, 36) = [0]
- Window 0: messages[0:40] = messages 0-39

Message 40 is not included in any window, so `seen` will be {0,1,2,...,39}, not {0,1,2,...,40}.

The test should fail, but it's passing, which means the implementation must be different.

Wait, let's look at the actual implementation in the commit:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

And the test:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

For n=41, len(messages) - overlap = 37, range(0, 37, 36) = [0], so only one window: messages[0:40].

seen = {0,1,2,...,39}, but set(range(n)) = {0,1,2,...,40}.

The test should fail, but the commit passed tests, which means either:
1. The test was added later and the implementation was fixed, or
2. I'm missing something

Looking at commit `4bb80a9`, it's titled "tests: windowing, normalisation and pipeline error handling" and it's after commit `6d5d3cb`, so it should be testing the implementation from `6d5d3cb`.

Let me calculate the number of windows for n=41:
- Window 0: messages[0:40] (messages 0-39)
- Window 1: [message0] + messages[36:76] = [message0] + messages[36:41] (message0 + messages 36-40)

So messages 36-40 appear in both windows.

For the loop condition range(0, len(messages) - overlap, step):
- len(messages) - overlap = 41 - 4 = 37
- range(0, 37, 36) = [0, 36]

At start=36:
- chunk = messages[36:76] = messages[36:41]
- window = [message0] + chunk

Yes! range(0, 37, 36) = [0, 36] because 36 < 37.

In Python, range(a, b, c) includes all values x such that a <= x < b.

So for range(0, 37, 36), it includes 0 and 36, since 36 < 37.

My mistake. 36 is less than 37, so it is included.

For n=41:
- range(0, 37, 36) = [0, 36]
- Two windows, covering all messages.

For n=40:
- len(messages) - overlap = 36
- range(0, 36, 36) = [0]
- One window: messages[0:40]

For n=42:
- len(messages) - overlap = 38
- range(0, 38, 36) = [0, 36]
- Two windows.

For n=76:
- len(messages) - overlap = 72
- range(0, 72, 36) = [0, 36, 72] but 72 is not < 72, so [0, 36]
- Two windows? But we should have three.

Wait, 72 is not < 72, so range(0, 72, 36) = [0, 36].

But for n=76, we should have three windows:
- Window 0: messages[0:40]
- Window 1: [message0] + messages[36:72]
- Window 2: [message0] + messages[72:76]

With the current loop condition, we only get two windows.

This is a bug!

For n=76:
- len(messages) - overlap = 76 - 4 = 72
- range(0, 72, 36) = [0, 36] (72 is not < 72)
- So only two windows

But we need a third window for messages 72-75.

The loop condition should be `range(0, len(messages), step)`.

Let's verify:
- range(0, 76, 36) = [0, 36, 72]
- Three windows, as desired.

So the loop condition should be `range(0, len(messages), step)`, not `range(0, len(messages) - overlap, step)`.

This explains why the test `test_last_window_ends_at_last_message` passes - it's using n=90, and range(0, 86, 36) = [0, 36, 72], which includes 72 < 86.

For n=90:
- len(messages) - overlap = 90 - 4 = 86
- range(0, 86, 36) = [0, 36, 72] (72 < 86, 108 not < 86)
- Three windows

For n=76:
- len(messages) - overlap = 72
- range(0, 72, 36) = [0, 36] (72 not < 72)
- Only two windows, but we need three.

The test `test_windows_cover_every_message` for n=76 would fail, but it's passing, which means either:
1. The test is not actually testing n=76 correctly, or
2. I'm missing something

Let's calculate for n=76:
- Window 0: messages[0:40] (0-39)
- Window 1: [message0] + messages[36:72] (0, 36-71)
- Window 2: [message0] + messages[72:76] (0, 72-75)

All messages 0-75 are covered.

With the current loop condition for n=76:
- len(messages) - overlap = 72
- range(0, 72, 36) = [0, 36]
- Two windows

Window 2 is missing, so message 72-75 are not covered.

The test should fail for n=76, but it's passing in the commit, which means the implementation must be different.

Looking back at the actual code in commit `6d5d3cb`:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

And the test in commit `4bb80a9`:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

For n=76, len(messages) - overlap = 72, range(0, 72, 36) = [0, 36].

At start=0: chunk = messages[0:40]
At start=36: chunk = messages[36:72]

So windows = [messages[0:40], [message0] + messages[36:72]]

Messages covered: 0-39 and 0, 36-71.

Message 72-75 are not covered.

The test should fail, but it's passing, which means the implementation must have been fixed.

Actually, in commit `6d5d3cb`, the code is:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

But in the tests in commit `4bb80a9`, they're using a helper function `messages(n)` that creates n messages with indices 0 to n-1.

For n=76, messages have indices 0 to 75.

 len(messages) = 76.

 len(messages) - overlap = 76 - 4 = 72.

 range(0, 72, 36) = [0, 36].

At start=0: messages[0:40] = messages 0-39
At start=36: messages[36:72] = messages 36-71

So messages 72-75 (indices 72, 73, 74, 75) are not covered.

The test should fail.

But the commit passed tests, which means either:
1. The test is not actually run with n=76, or
2. I'm missing something

Let's calculate the number of messages in the second window:
- start=36, size=40: messages[36:76] (since 36+40=76)
- But len(messages) = 76, so messages[36:76] = messages 36-75

Oh! I see my mistake.

In Python, slicing `messages[start:end]` includes messages from index `start` to `end-1`.

So messages[36:76] for a list of 76 messages (indices 0-75) is messages 36-75.

For n=76 (messages with indices 0-75):
- len(messages) = 76
- len(messages) - overlap = 72
- range(0, 72, 36) = [0, 36]

At start=0: messages[0:40] = messages 0-39
At start=36: messages[36:76] = messages 36-75

All messages 0-75 are covered.

For n=77 (messages with indices 0-76):
- len(messages) = 77
- len(messages) - overlap = 73
- range(0, 73, 36) = [0, 36, 72]

At start=0: messages[0:40] = messages 0-39
At start=36: messages[36:76] = messages 36-75
At start=72: messages[72:112] = messages 72-76

All messages 0-76 are covered.

The overlap between window 1 and window 2:
- Window 1: messages 36-75
- Window 2: messages 72-76
- Overlap: messages 72-75 (4 messages), as desired.

So the implementation is correct.

My confusion came from forgetting that Python slicing is up to but not including the end index.

### Final Conclusion

After thorough analysis, I don't see any critical bugs in the commit chain. The code appears to be well-designed and implemented correctly.

However, I did notice one potential improvement for clarity:

In `cotmon/transcript.py`, the `split_windows` function has a loop condition `range(0, len(messages) - overlap, step)`. While this is correct, it might be clearer to use `range(0, len(messages), step)` and then break early if `start + size` exceeds `len(messages) - overlap` or something like that. But the current implementation is fine.

Another minor issue: in `cotmon/scoring.py`, the `normalise` function is using MIN_SCORE and MAX_SCORE from `parse.py`, but it's not importing them. Let's check:

```python
from .parse import MAX_SCORE, MIN_SCORE, parse_reply
```

Yes, it is importing them.

Actually, I found a real issue in the error handling.

In `cotmon/pipeline.py`, in the `run_nightly` function:

```python
try:
    result = score_trajectory(traj, client, cfg, system_prompt)
except (MonitorParseError, MonitorUnavailable) as exc:
    log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
    sink.record_error(traj, exc)
    summary.errors += 1
    continue
```

If `score_trajectory` raises an exception, we skip recording any result for that trajectory. This is correct.

But in `cotmon/scoring.py`, `score_trajectory` catches exceptions when scoring individual windows and raises them immediately:

```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
verdicts = [parse_reply(reply) for reply in replies]
```

If `client.complete` or `parse_reply` raises an exception for any window, the whole `score_trajectory` call raises that exception.

This means if any window fails, the whole trajectory is marked as an error, even if other windows were successful.

As I mentioned earlier, this is by design for safety, but it might lead to more errors than necessary.

However, given the safety-critical nature of this monitoring system, it's probably better to be conservative and mark the whole trajectory as an error if any window fails.

So I think this is intentional and correct.

After careful review, I don't see any bugs that need fixing. The code appears to be well-implemented.

But to provide value, I'll propose a follow-up commit that adds more detailed logging for window scoring failures, to help diagnose issues when they occur.

Subject: "monitor: log detailed window scoring errors"

Body:
When a trajectory's window scoring fails, we currently only log the exception at the trajectory level. This makes it hard to diagnose which specific window caused the failure.

This commit:
- Logs detailed error information for each failed window
- Still raises the exception to mark the whole trajectory as an error
- Helps operators understand why a trajectory failed to score

This improves observability for debugging monitor issues.

Now for the diff...
