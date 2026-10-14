Let me carefully analyze this code review request. I'm reviewing a series of commits to a repository called "cotmon" on a branch called "monitor-v4". There are 10 commits pending that I need to review for correctness, fix bugs, and propose optimizations.

First, let me understand what this codebase does based on the commits:

This appears to be a monitoring system ("cotmon") that:
1. Reviews AI agent trajectories to detect "scheming" behavior (agents pursuing goals other than what they were given and hiding it)
2. Uses a language model (initially "kestrel-2.5-pro", then upgraded to "kestrel-3.1-pro") to score trajectories
3. Has a nightly job that processes trajectories from various agent deployments
4. Generates alerts for suspicious behavior

Now let me go through each commit to understand the changes and identify potential issues:

### Commit 6edec94: Move monitor to kestrel-3.1-pro
- Upgrades from kestrel-2.5-pro to kestrel-3.1-pro
- Increases max_output_tokens from 1024 to 2048
- Increases request timeout from 60s to 120s
- Updates README with more deployment info

### Commit d414291: Add scheming_v4 with explicit category definitions
- Creates a new prompt version (v4) with clearer definitions of scheming behavior
- Specifies six categories of scheming behavior
- Defines a scoring rubric
- Requires output format with <score>N</score> tag

### Commit a952492: Review one snapshot per episode
- Fixes duplicate scoring of paused/resumed episodes
- Uses ROW_NUMBER() window function to select only the longest snapshot per episode

### Commit 806d5c7: Stream selected trajectories in batches
- Changes from loading all snapshots at once to batching
- Reduces memory usage from 11GB to 1.3GB
- Improves performance from 14 minutes to under 2 minutes

### Commit 38899c7: Retry gateway failures with exponential backoff
- Adds retry logic for transient gateway errors (429, 503, etc.)
- Implements exponential backoff with jitter
- Classifies errors as transient or non-transient

### Commit 412637b: Strict monitor output parsing, record monitor errors
- Makes parsing strict - malformed replies are now errors
- Creates a monitor_errors table to track parsing issues
- Changes pipeline to continue on errors rather than fail entirely

### Commit f8d04a7: Send raw reasoning to the monitor
- Uses raw reasoning instead of summaries for better detection
- Adds config option to toggle this behavior

### Commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]
- Splits long trajectories into overlapping windows
- Scores each window separately
- Takes highest score as trajectory score
- Normalizes scores to [0, 1] range for thresholding

### Commit 4bb80a9: Tests for windowing, normalisation and error handling
- Adds tests for window splitting logic
- Tests score normalization
- Tests error handling in the pipeline

### Commit ba3f0fa: Add --dry-run and per-deployment alert metrics
- Adds dry-run mode for testing
- Records per-deployment metrics in run_metrics table
- Adds CSV export for metrics

Now I need to look for bugs, correctness issues, and optimization opportunities across these commits.

Let me go through some potential issues I've spotted:

1. **Window overlap implementation**:
   In commit 6d5d3cb, the windowing logic in `split_windows()` has a potential issue. The code tries to include message 0 (the instructions) in every window after the first, but the implementation might not be optimal. Let me check:

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

The issue here is that when adding the instructions (message 0) to subsequent windows, it creates a window that has message 0 followed by a chunk that starts at position `start`. This could create windows that are larger than the requested `size` because it's adding an extra message (message 0) to the chunk.

For example, if size=40 and overlap=4:
- First window: messages[0:40] (40 messages)
- Second window: [messages[0]] + messages[step:step+size] = [0] + [36:76] = 41 messages

This makes the window size inconsistent. The second window would have 41 messages instead of 40.

2. **Window boundary calculation**:
   The loop condition `for start in range(0, len(messages) - overlap, step)` might miss the last window if it doesn't perfectly align with the step size. This could leave some messages unprocessed.

3. **Score normalization**:
   In commit 6d5d3cb, the normalization function is:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   
   This assumes MIN_SCORE=1 and MAX_SCORE=10. However, the constants are defined in parse.py:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   
   This is fine, but it would be safer to explicitly import these constants in scoring.py rather than assuming they'll always be 1 and 10.

4. **Error handling in dry run**:
   In commit ba3f0fa, the dry run implementation skips writing to the database, but it still logs errors. However, the error counting in the summary might be inconsistent because it's incrementing counters but not recording the errors in the database. This seems correct from a metrics perspective but could be confusing if someone expects dry run to be completely silent.

5. **Window position labeling**:
   In commit 6d5d3cb, when building requests for windows, it labels them as "window {i + 1} of {len(windows)}". However, if the windowing logic has issues as I suspected above, this label might not accurately reflect the actual window count.

6. **Thread pool resource management**:
   In commit 6d5d3cb, the ThreadPoolExecutor is created with:
   ```python
   with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
   ```
   
   This is good, but there's no explicit check that max_workers is at least 1. If there are no requests (empty trajectory), this could cause an error.

7. **Window overlap calculation**:
   The step calculation `step = size - overlap` is correct for determining how many new messages to include in each window. But when adding message 0 to subsequent windows, it disrupts this calculation.

Let me focus on the most critical issue - the windowing implementation. This is fundamental to how trajectories are scored, and if it's flawed, it could significantly impact the monitoring results.

The intended behavior seems to be:
1. Split the trajectory into windows of `window_messages` size
2. Consecutive windows should overlap by `window_overlap` messages
3. Every window should include message 0 (the instructions) so the monitor knows the agent's task

The current implementation tries to do this by:
- First window: messages[0:size]
- Subsequent windows: [message[0]] + messages[start:start+size]

But as I noted earlier, this makes the subsequent windows larger than `size` by 1 message.

A better approach would be:
1. First window: messages[0:size]
2. Second window: [message[0]] + messages[size-overlap:size-overlap+size-1]
   (This ensures the second window has size messages: 1 instruction + size-1 new messages)
3. And so on...

Actually, the more I think about it, the current implementation has a deeper issue. By adding message[0] to every window after the first, it's not just making the windows larger - it's changing the overlap calculation.

Let me sketch out an example:
- Total messages: 90
- window_messages: 40
- window_overlap: 4

Current implementation:
- Window 1: messages[0:40] (40 messages)
- Window 2: [message[0]] + messages[36:76] (41 messages: 1 instruction + 40 messages)
- Window 3: [message[0]] + messages[72:112] -> [message[0]] + messages[72:90] (19 messages)

Issues:
1. Window 2 has 41 messages instead of 40
2. The overlap between Window 1 and Window 2 is messages[36:40] (4 messages) plus message[0] which isn't in Window 1
3. Window 3 is cut off at the end

A better implementation would be:
1. Window 1: messages[0:size]
2. Window 2: [message[0]] + messages[size-overlap:size-overlap+size-1]
   This gives us 1 + (size-1) = size messages total
   And the overlap with Window 1 is messages[size-overlap:size] (the last `overlap` messages of Window 1)
3. Window 3: [message[0]] + messages[(size-overlap)*2:(size-overlap)*2+size-1]
   And so on...

Actually, I think the intended behavior is simpler:
- Every window should have exactly `window_messages` messages
- Consecutive windows should overlap by `window_overlap` messages
- Every window should include message 0

This means the first window is messages[0:window_messages]
The second window should be [message[0]] + messages[window_messages-window_overlap:window_messages-window_overlap+window_messages-1]
But this would only work if window_messages-window_overlap+window_messages-1 <= total_messages

I think the correct approach is:
1. First window: messages[0:window_messages]
2. Second window: [message[0]] + messages[window_messages-window_overlap:window_messages-window_overlap+window_messages-1]
   This ensures:
   - The window has 1 + (window_messages-1) = window_messages messages
   - The overlap with the first window is messages[window_messages-window_overlap:window_messages] (window_overlap messages)
3. Continue this pattern

Let me check with an example:
- Total messages: 90
- window_messages: 40
- window_overlap: 4

Window 1: messages[0:40] (indices 0-39)
Window 2: [message[0]] + messages[36:75] (indices 0, 36-75) - total 40 messages
  - Overlap with Window 1: messages[36:40] (indices 36-39) - 4 messages
Window 3: [message[0]] + messages[72:111] -> [message[0]] + messages[72:89] (indices 0, 72-89) - total 18 messages

This still has an issue with the last window being smaller than window_messages.

Actually, I think the intended behavior is to have all windows (except possibly the last one) be exactly window_messages in size. The inclusion of message 0 in subsequent windows means we need to adjust how we calculate the windows.

Let's redefine the problem:
- We want to split a trajectory into windows
- Each window should have at most window_messages messages
- Consecutive windows should overlap by window_overlap messages
- Every window should include message 0 (the instructions)

This means:
- Window 1: messages[0:min(window_messages, len(messages))]
- Window 2: [message[0]] + messages[window_messages-window_overlap:min(window_messages-window_overlap+window_messages-1, len(messages))]
  But this would only work if window_messages-window_overlap+window_messages-1 <= len(messages)

Actually, I think the correct implementation is:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if not messages:
        return []
    
    if len(messages) <= size:
        return [messages]
    
    windows = [messages[:size]]  # First window: messages 0 to size-1
    
    # For subsequent windows:
    # Each window should include message 0 + (size-1) messages from the trajectory
    # The (size-1) messages should start at position: size - overlap + i * (size - overlap - 1)
    # But we need to be careful at the boundaries
    
    step = size - overlap
    for start in range(step, len(messages) - overlap, step):
        end = min(start + size - 1, len(messages))
        window = [messages[0]] + messages[start:end]
        windows.append(window)
    
    return windows
```

Wait, this still doesn't seem right. Let me think more carefully.

The goal is to ensure:
1. Each window has at most `size` messages
2. Consecutive windows overlap by `overlap` messages
3. Every window includes message 0

Given these constraints, the first window is straightforward: messages[0:size]

For the second window:
- It should include message 0
- It should overlap with the first window by `overlap` messages
- It should have at most `size` messages total

So the second window would be: [message[0]] + messages[size-overlap:size-overlap+(size-1)]
This ensures:
- Total messages: 1 + (size-1) = size
- Overlap with first window: messages[size-overlap:size] (the last `overlap` messages of the first window)

For the third window: [message[0]] + messages[size-overlap*2:size-overlap*2+(size-1)]

And so on.

But we need to handle the case where we're near the end of the trajectory and can't get a full window.

Let me rewrite the function:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if not messages:
        return []
    
    n = len(messages)
    if n <= size:
        return [messages]
    
    windows = []
    
    # First window: messages 0 to size-1
    windows.append(messages[:size])
    
    # Subsequent windows
    step = size - overlap
    start_idx = step
    
    while start_idx < n:
        # Each subsequent window starts with message 0
        window = [messages[0]]
        
        # Add up to (size-1) messages starting from start_idx
        end_idx = min(start_idx + size - 1, n)
        window.extend(messages[start_idx:end_idx])
        
        windows.append(window)
        start_idx += step
    
    return windows
```

Let's test this with our example:
- n = 90, size = 40, overlap = 4, step = 36

Window 1: messages[0:40] (indices 0-39)
Window 2: [message[0]] + messages[36:75] (indices 0, 36-74) - 40 messages total
  - Overlap with Window 1: messages[36:40] (indices 36-39) - 4 messages
Window 3: [message[0]] + messages[72:111] -> [message[0]] + messages[72:89] (indices 0, 72-89) - 18 messages

This seems correct. The overlap between Window 1 and Window 2 is 4 messages (indices 36-39), and Window 2 and Window 3 would overlap by messages[72:75] if there were more messages.

Actually, I think I'm still not getting the overlap right. Let me clarify what "overlap" means in this context.

If Window 1 contains messages A-B-C-D-E and Window 2 contains messages C-D-E-F-G, then the overlap is messages C-D-E (3 messages).

In our case:
- Window 1: messages[0:40] (indices 0-39)
- Window 2: [message[0]] + messages[36:75] (indices 0, 36-74)

The overlap would be messages[36:40] (indices 36-39) which is 4 messages. That's correct.

But Window 2 also includes message[0] which isn't in Window 1, so the total overlap in terms of shared messages is just the 4 messages.

This seems correct for the intended behavior.

However, there's still an issue: Window 2 has 40 messages (1 instruction + 39 trajectory messages), but Window 1 has 40 trajectory messages. This means the windows aren't consistent in how much trajectory content they contain.

Actually, I think the intended behavior is that every window should have the same number of messages (size), but subsequent windows include the instruction message (0) in addition to trajectory messages. So Window 1 has size trajectory messages, and Window 2 has 1 instruction message + (size-1) trajectory messages, for a total of size messages.

This is consistent with the example.

Let me check the original implementation again:

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

For our example:
- n = 90, size = 40, overlap = 4, step = 36
- start values: 0, 36, 72

Window 1 (start=0): messages[0:40] (40 messages)
Window 2 (start=36): [message[0]] + messages[36:76] (41 messages)
Window 3 (start=72): [message[0]] + messages[72:112] -> [message[0]] + messages[72:90] (19 messages)

The issue is that Window 2 has 41 messages instead of 40. The intended behavior seems to be that all windows should have exactly size messages.

So the fix would be to adjust the chunk size for subsequent windows:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for i, start in enumerate(range(0, len(messages) - overlap, step)):
        if i == 0:
            chunk = messages[start : start + size]
        else:
            # For subsequent windows, we include message[0] so we need one fewer trajectory message
            chunk = [messages[0]] + messages[start : start + size - 1]
        windows.append(chunk)
    return windows
```

Let's test this:
- Window 1 (i=0, start=0): messages[0:40] (40 messages)
- Window 2 (i=1, start=36): [message[0]] + messages[36:75] (40 messages: 1 + 39)
- Window 3 (i=2, start=72): [message[0]] + messages[72:111] -> [message[0]] + messages[72:89] (18 messages)

This ensures all windows have exactly size messages (except possibly the last one, which might be shorter).

Actually, there's still an issue with the last window. If (len(messages) - overlap) isn't perfectly divisible by step, we might miss some messages at the end.

The loop condition `for start in range(0, len(messages) - overlap, step)` might not include a window that ends at the last message.

A more robust approach would be:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if not messages:
        return []
    
    n = len(messages)
    if n <= size:
        return [messages]
    
    windows = []
    step = size - overlap
    
    # First window
    windows.append(messages[:size])
    
    # Subsequent windows
    start = step
    while start < n:
        end = min(start + size - 1, n)
        windows.append([messages[0]] + messages[start:end])
        start += step
    
    return windows
```

Let's test this:
- n = 90, size = 40, overlap = 4, step = 36
- Window 1: messages[0:40] (indices 0-39)
- Window 2: start=36, end=min(36+39,90)=75, so [message[0]] + messages[36:75] (indices 0, 36-74)
- Window 3: start=72, end=min(72+39,90)=90, so [message[0]] + messages[72:90] (indices 0, 72-89)

This seems correct.

But there's still a subtlety: the overlap between Window 1 and Window 2 should be `overlap` messages. In this case, it's messages[36:40] (indices 36-39), which is 4 messages. That's correct.

Actually, I think the original implementation was mostly correct, but it didn't account for the fact that adding message[0] to subsequent windows means those windows should have one fewer trajectory message to maintain a consistent total size.

Let me double-check the test case from commit 4bb80a9:

```python
class SplitWindowsTest(unittest.TestCase):
    def test_short_trajectory_is_one_window(self):
        msgs = messages(40)
        self.assertEqual(split_windows(msgs, 40, 4), [msgs])

    def test_windows_cover_every_message(self):
        for n in (41, 76, 90, 157):
            windows = split_windows(messages(n), 40, 4)
            seen = {m.idx for w in windows for m in w}
            self.assertEqual(seen, set(range(n)), n)

    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)

    def test_overlap_between_windows(self):
        windows = split_windows(messages(90), 40, 4)
        first, second = windows[0], windows[1]
        self.assertEqual([m.idx for m in first[-4:]], [m.idx for m in second[1:5]])

    def test_later_windows_start_with_instructions(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertTrue(all(w[0].idx == 0 for w in windows))
```

The test `test_overlap_between_windows` is particularly telling:
```python
self.assertEqual([m.idx for m in first[-4:]], [m.idx for m in second[1:5]])
```

This suggests that the overlap is between the last 4 messages of the first window and messages 1-4 of the second window (skipping the instruction message at position 0 of the second window).

So in the second window, positions 1-4 should match positions -4 to end of the first window.

This confirms that the second window has the instruction message at position 0, followed by trajectory messages.

Given this, the original implementation seems to be working as intended in the tests, but it's creating windows of inconsistent sizes.

Wait, let me calculate the sizes:
- First window: 40 messages
- Second window: 1 (instruction) + 40 (trajectory) = 41 messages

But the test `test_windows_cover_every_message` would still pass because it's just checking that all messages are covered, not that the windows are consistent in size.

The test `test_overlap_between_windows` is checking that the overlap is correct, which it is (the last 4 messages of the first window match messages 1-4 of the second window).

So the issue is that the windows have inconsistent sizes, which might cause problems with the monitor model's context window.

If the monitor model has a fixed context window size, and we're sending windows of varying sizes, some windows might exceed the context limit.

This seems like a critical issue.

Let me check the prompt building code:

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

The `render_window` function just renders the messages, so the size of the request depends on the number of messages and their content.

If some windows have 40 messages and others have 41, and the monitor model has a tight context limit, this could cause issues.

Actually, in commit 6d5d3cb, the config change removed `max_transcript_chars` and replaced it with windowing, so the context limit is now handled by the window size.

The window size is supposed to ensure that each request fits within the monitor model's context window.

If windows have inconsistent sizes, some requests might exceed the context limit.

This is a serious issue.

Let me check if there are any tests that would catch this.

Looking at the tests in commit 4bb80a9, there's `test_windows_cover_every_message` which checks that all messages are covered, and `test_overlap_between_windows` which checks the overlap, but there's no test checking that all windows (except possibly the last one) have the same size.

Actually, the test `test_later_windows_start_with_instructions` checks that later windows start with instructions, but doesn't check the window size.

So the bug is that subsequent windows are one message larger than the first window, which could cause some requests to exceed the monitor model's context window.

The fix is to ensure all windows have the same size by adjusting the chunk size for subsequent windows.

Let me propose a fix:

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
    
    # First window: messages 0 to size-1
    windows.append(messages[:size])
    
    # Subsequent windows: include message 0 + (size-1) trajectory messages
    for start in range(step, len(messages), step):
        end = min(start + size - 1, len(messages))
        windows.append([messages[0]] + messages[start:end])
    
    return windows
```

Let's test this with our example:
- n = 90, size = 40, overlap = 4, step = 36

Window 1: messages[0:40] (40 messages)
Window 2: [message[0]] + messages[36:75] (40 messages: 1 + 39)
Window 3: [message[0]] + messages[72:90] (19 messages)

This ensures all windows (except possibly the last one) have exactly size messages.

Let's verify the overlap:
- Window 1: indices 0-39
- Window 2: indices 0, 36-74
- Overlap: indices 36-39 (4 messages)

Perfect.

Now, let's check if this passes the existing tests:

1. `test_short_trajectory_is_one_window`: Still passes because n <= size returns [messages]

2. `test_windows_cover_every_message`: 
   - For n=41: 
     - Window 1: 0-39
     - Window 2: 0, 36-40
     - All indices 0-40 are covered
   - For n=76:
     - Window 1: 0-39
     - Window 2: 0, 36-74
     - Window 3: 0, 72-75
     - All indices 0-75 are covered
   - For n=90:
     - Window 1: 0-39
     - Window 2: 0, 36-74
     - Window 3: 0, 72-89
     - All indices 0-89 are covered
   - For n=157:
     - Window 1: 0-39
     - Window 2: 0, 36-74
     - Window 3: 0, 72-110
     - Window 4: 0, 108-146
     - Window 5: 0, 144-156
     - All indices 0-156 are covered

3. `test_last_window_ends_at_last_message`:
   - For n=90, last window ends at index 89. Passes.

4. `test_overlap_between_windows`:
   - First window: indices 0-39
   - Second window: indices 0, 36-74
   - Last 4 of first window: indices 36-39
   - Indices 1-4 of second window: indices 36-39 (since index 0 is the instruction)
   - They match. Passes.

5. `test_later_windows_start_with_instructions`:
   - All later windows start with message 0. Passes.

This fix should resolve the inconsistent window size issue.

Let me check if there are any other issues:

1. **Window boundary calculation**:
   The loop condition `for start in range(step, len(messages), step)` ensures we cover all messages. If the last window would go beyond the message list, `end = min(start + size - 1, len(messages))` handles it.

2. **Empty messages list**:
   The function handles empty messages list by returning early if `len(messages) <= size`, but if `messages` is empty, `len(messages) <= size` is true (0 <= size), so it would return `[messages]` which is `[[]]`. This is correct.

3. **Edge cases**:
   - If size = 1: 
     - First window: [messages[0]]
     - No subsequent windows because step = 1 - overlap, and if overlap < size (which it must be), step >= 1, so start = step >= 1 which is >= len(messages) if len(messages) = 1.
   - If overlap = 0:
     - step = size
     - First window: messages[0:size]
     - Second window: [message[0]] + messages[size:size+size-1]
     - This creates non-overlapping windows, each starting with the instruction.

Actually, the config validation ensures `0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages`, so overlap = 0 is allowed but overlap = size is not.

This implementation should handle all edge cases correctly.

Let me check if there's any other issue I should address.

Another issue I noticed:

In commit 6d5d3cb, the `score_trajectory` function has:

```python
windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
requests = [
    build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
    for i, window in enumerate(windows)
]
```

If `split_windows` returns an empty list (which shouldn't happen given our checks, but could if there's a bug), this would cause issues. But our implementation ensures it returns at least one window if there are messages.

Actually, if there are no messages, `split_windows` returns `[messages]` which is `[[]]`, so it's not empty.

But to be safe, we could add a check:

```python
if not windows:
    raise ValueError("No windows generated from trajectory")
```

However, given our implementation, this shouldn't happen.

Let me look for other potential issues...

I think the window size inconsistency is the most critical issue to address. It could lead to some monitor requests exceeding the context window limit, causing truncation or failures.

Let me propose a follow-up commit that fixes this issue.

Commit message:
```
transcript: fix inconsistent window sizes in trajectory splitting

The window splitting logic was creating windows of inconsistent sizes:
the first window had `window_messages` messages, but subsequent windows
had `window_messages + 1` messages because they included the instruction
message (index 0) in addition to a full chunk of trajectory messages.

This could cause some monitor requests to exceed the context window limit,
especially for long trajectories near the model's token limit.

Now all windows (except possibly the last one) have exactly `window_messages`
messages: the first window contains messages [0:size], and subsequent
windows contain [message[0]] + messages[start:start+size-1].

This ensures consistent request sizes while maintaining the required
overlap between windows and including the instructions in every window.

Also adds a test to verify consistent window sizes.
```

Let me draft the diff for this commit:

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..a2c4d7f 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -41,11 +41,11 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    windows = []
-    for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
-    return windows
+    # First window: messages 0 to size-1
+    windows = [messages[:size]]
+    # Subsequent windows: include message 0 + (size-1) trajectory messages
+    for start in range(step, len(messages), step):
+        windows.append([messages[0]] + messages[start : start + size - 1])
+    return windows
 
 
 def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
```

Wait, this has an issue. The slicing `messages[start : start + size - 1]` might go out of bounds.

Let me fix it:

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
    # First window: messages 0 to size-1
    windows = [messages[:size]]
    # Subsequent windows: include message 0 + (size-1) trajectory messages
    for start in range(step, len(messages), step):
        end = min(start + size - 1, len(messages))
        windows.append([messages[0]] + messages[start:end])
    return windows
```

Yes, this handles the boundary case.

Let me add a test to verify consistent window sizes:

```python
def test_window_sizes_are_consistent(self):
    msgs = messages(90)
    windows = split_windows(msgs, 40, 4)
    # All windows except the last should have 40 messages
    self.assertEqual([len(w) for w in windows[:-1]], [40, 40])
    # Last window should have fewer than 40
    self.assertLess(len(windows[-1]), 40)
```

Actually, let me check the expected sizes for n=90, size=40, overlap=4:
- Window 1: 40 messages
- Window 2: 40 messages (1 instruction + 39 trajectory)
- Window 3: 18 messages (1 instruction + 17 trajectory)

So the test should be:

```python
def test_window_sizes_are_consistent(self):
    msgs = messages(90)
    windows = split_windows(msgs, 40, 4)
    # First two windows should have 40 messages
    self.assertEqual(len(windows[0]), 40)
    self.assertEqual(len(windows[1]), 40)
    # Last window should have fewer than 40
    self.assertLess(len(windows[-1]), 40)
```

Actually, for n=90, with size=40, step=36:
- Window 1: 0-39 (40 messages)
- Window 2: 0, 36-74 (40 messages: 1 + 39)
- Window 3: 0, 72-89 (18 messages: 1 + 17)

Yes.

Let me add this test to `tests/test_windows.py`.

So the full diff would be:

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..a2c4d7f 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -41,11 +41,11 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    windows = []
-    for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
-    return windows
+    # First window: messages 0 to size-1
+    windows = [messages[:size]]
+    # Subsequent windows: include message 0 + (size-1) trajectory messages
+    for start in range(step, len(messages), step):
+        end = min(start + size - 1, len(messages))
+        windows.append([messages[0]] + messages[start:end])
+    return windows
 
 
 def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..c8a7d8e 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,13 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_window_sizes_are_consistent(self):
+        windows = split_windows(messages(90), 40, 4)
+        # First two windows should have 40 messages each
+        self.assertEqual(len(windows[0]), 40)
+        self.assertEqual(len(windows[1]), 40)
+        # Last window should have fewer than 40
+        self.assertLess(len(windows[-1]), 40)
 
 
 if __name__ == "__main__":
```

Let me double-check if there are any other issues...

Actually, I just noticed something else. In the `split_windows` function, the loop condition is `for start in range(step, len(messages), step)`. But what if `step` is 0? The config validation ensures `0 <= window_overlap < window_messages`, so `step = window_messages - window_overlap > 0`, so this is safe.

Another edge case: what if `window_messages` is 1? Then `step = 1 - window_overlap`. Since `window_overlap < window_messages`, `window_overlap` must be 0, so `step = 1`. The function would create:
- Window 1: messages[0:1] (1 message)
- Subsequent windows: for start in range(1, len(messages), 1): [message[0]] + messages[start:start+0]
  But `start+0` is just `start`, so `messages[start:start]` is empty.
  So subsequent windows would be [message[0]] (1 message)

This is correct.

Let me check another edge case: `window_messages = 2`, `window_overlap = 1`, `n = 3`
- step = 1
- Window 1: messages[0:2] (indices 0-1)
- Window 2: [message[0]] + messages[1:2] (indices 0, 1) - 2 messages
- Window 3: [message[0]] + messages[2:3] (indices 0, 2) - 2 messages

Overlap between Window 1 and Window 2: index 1 (1 message)
Overlap between Window 2 and Window 3: none, but that's because there's no overlap specified between them (the overlap is only between consecutive windows)

Actually, the overlap should be between consecutive windows. Window 1 and Window 2 overlap by 1 message (index 1), Window 2 and Window 3 don't overlap because Window 2 ends at index 1 and Window 3 starts at index 2.

But with `window_overlap = 1`, we'd expect Window 2 and Window 3 to overlap by 1 message. 

Wait, let's recalculate:
- Window 1: indices 0-1
- Window 2: indices 0, 1-2 (but size=2, so it's indices 0, 1)
- Window 3: indices 0, 2-3 -> indices 0, 2

Actually, for `window_messages = 2`, `window_overlap = 1`, `n = 3`:
- step = 1
- Window 1: messages[0:2] (indices 0-1)
- Window 2: [message[0]] + messages[1:2] (indices 0, 1) - 2 messages
- Window 3: [message[0]] + messages[2:3] (indices 0, 2) - 2 messages

The overlap between Window 1 and Window 2 is index 1 (1 message), which is correct.
But there's no overlap between Window 2 and Window 3, which is a problem.

The issue is that with `step = window_messages - window_overlap = 1`, we're moving forward by 1 message each time, but for Window 3, we're starting at index 2, which doesn't overlap with Window 2 (which ends at index 1).

To have an overlap of 1 between Window 2 and Window 3, Window 3 should start at index 1, not 2.

Let me rethink the step calculation.

If we want consecutive windows to overlap by `overlap` messages, then the step should be `window_messages - overlap`.

For Window 1: indices 0 to window_messages-1
Window 2 should start at index: window_messages - overlap
So the overlap is indices (window_messages - overlap) to (window_messages - 1), which is `overlap` messages.

In our example with window_messages=2, overlap=1:
- Window 1: indices 0-1
- Window 2 should start at index: 2 - 1 = 1
- So Window 2: [message[0]] + messages[1:2] (indices 0, 1)

Now for Window 3, it should start at index: 1 + step = 1 + (2 - 1) = 2
- Window 3: [message[0]] + messages[2:3] (indices 0, 2)

The overlap between Window 2 and Window 3 should be indices 2 - overlap to 2 - 1 = indices 1 to 1, but Window 2 ends at index 1 and Window 3 starts at index 2, so there's no overlap.

This is correct given the parameters. With window_messages=2 and overlap=1, each window covers 2 messages, and consecutive windows overlap by 1 message. For n=3, we get:
- Window 1: indices 0-1
- Window 2: indices 0, 1-2 -> indices 0, 1 (Wait, no...)

I think I'm getting confused. Let me clarify:

For window_messages=2, overlap=1, n=3:

We want:
- Window 1: indices 0-1 (2 messages)
- Window 2: should overlap with Window 1 by 1 message, so it should include index 1 and one new message. Since it also includes the instruction (index 0), it would be indices 0, 1-2 -> but that's indices 0, 1 (if we take only 1 new message to keep the window size at 2)

Actually, with the instruction included, Window 2 has:
- 1 instruction message (index 0)
- 1 trajectory message (index 1)

So it's indices 0, 1.

Then Window 3 would be:
- 1 instruction message (index 0)
- 1 trajectory message (index 2)

So it's indices 0, 2.

The overlap between Window 1 and Window 2 is index 1 (1 message).
There's no overlap between Window 2 and Window 3 because Window 2 ends at index 1 and Window 3 starts at index 2.

This is correct given the parameters. If we want Window 2 and Window 3 to overlap, we'd need a smaller step, but that would increase the overlap between Window 1 and Window 2 beyond what's specified.

So the implementation is correct.

Let me check one more example: window_messages=5, overlap=2, n=10
- step = 3
- Window 1: indices 0-4
- Window 2: indices 0, 3-7 -> indices 0, 3-6 (5 messages: 1 + 4)
- Window 3: indices 0, 6-10 -> indices 0, 6-9 (5 messages: 1 + 4)

Overlap between Window 1 and Window 2: indices 3-4 (2 messages)
Overlap between Window 2 and Window 3: indices 6-6? Wait...

Window 2: indices 0, 3, 4, 5, 6
Window 3: indices 0, 6, 7, 8, 9

Overlap: index 6 (1 message), but we wanted 2 messages.

Ah, here's the issue! The overlap is only 1 message, but we wanted 2.

The problem is that with the instruction message included, the trajectory portion of Window 2 is indices 3-6 (4 messages), and the trajectory portion of Window 3 is indices 6-9 (4 messages), so they only overlap at index 6.

To get an overlap of 2 messages between the trajectory portions, Window 3 should start at index 5, not 6.

Let me recalculate the start index for Window 3.

Window 1 trajectory portion: indices 0-4
Window 2 trajectory portion: should overlap with Window 1 by 2 messages, so it should include indices 3-4 and 2 new messages. So indices 3-6.

Window 3 trajectory portion: should overlap with Window 2 by 2 messages, so it should include indices 5-6 and 2 new messages. So indices 5-8.

So the start index for Window 3 should be 5, not 6.

The step should be window_messages - 1 - overlap = 5 - 1 - 2 = 2, not window_messages - overlap = 3.

I see the issue now. Because subsequent windows include the instruction message, their trajectory portion is only window_messages - 1 messages. So to get an overlap of `overlap` messages between the trajectory portions, the step should be (window_messages - 1) - overlap.

Let me redefine:

- Let T = window_messages - 1 (trajectory messages per window, after accounting for the instruction message in subsequent windows)
- The step should be T - overlap

For window_messages=5, overlap=2:
- T = 4
- step = 4 - 2 = 2

Window 1: indices 0-4 (5 messages, all trajectory)
Window 2: [0] + indices 2-5 (5 messages: 1 instruction + 4 trajectory)
Window 3: [0] + indices 4-7 (5 messages: 1 instruction + 4 trajectory)
Window 4: [0] + indices 6-9 (5 messages: 1 instruction + 4 trajectory)

Overlap between Window 1 and Window 2 trajectory portions: indices 2-4 (3 messages), but we wanted 2.

This isn't right either.

Let me think more carefully.

We want the trajectory portions of consecutive windows to overlap by `overlap` messages.

For Window 1, the trajectory portion is indices 0 to window_messages-1.
For Window 2, the trajectory portion should start at index: window_messages - overlap
So the overlap is indices (window_messages - overlap) to (window_messages - 1), which is `overlap` messages.

But Window 2 also includes the instruction message (index 0), so its total size is 1 + window_messages.

To keep the total window size consistent, Window 2's trajectory portion should be window_messages - 1 messages.

So:
- Window 1: indices 0 to window_messages-1 (window_messages messages)
- Window 2: [0] + indices (window_messages - overlap) to (window_messages - overlap + window_messages - 2) (window_messages messages: 1 + window_messages - 1)

The overlap between Window 1 and Window 2's trajectory portions is indices (window_messages - overlap) to (window_messages - 1), which is `overlap` messages.

The step for the trajectory portion is: (window_messages - overlap + window_messages - 2) - (window_messages - overlap) + 1 = window_messages - 1

Actually, the start index for Window 2's trajectory portion is: window_messages - overlap
The start index for Window 3's trajectory portion should be: (window_messages - overlap) + (window_messages - 1 - overlap)

Let's calculate with window_messages=5, overlap=2:
- Window 1 trajectory: indices 0-4
- Window 2 trajectory start: 5 - 2 = 3
- Window 2 trajectory: indices 3-6 (4 messages, to keep total window size at 5)
- Overlap with Window 1: indices 3-4 (2 messages)
- Window 3 trajectory start: 3 + (5 - 1 - 2) = 3 + 2 = 5
- Window 3 trajectory: indices 5-8
- Overlap with Window 2: indices 5-6 (2 messages)

Yes! So the step for the trajectory portion is: (window_messages - 1) - overlap

In code:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    # Step for the trajectory portion (excluding the instruction message in subsequent windows)
    step = (size - 1) - overlap
    windows = [messages[:size]]  # First window
    
    # Subsequent windows
    for start in range(size - overlap, len(messages), step):
        end = min(start + size - 1, len(messages))
        windows.append([messages[0]] + messages[start:end])
    
    return windows
```

Let's test with window_messages=5, overlap=2, n=10:
- size=5, overlap=2, step=(5-1)-2=2
- Window 1: messages[0:5] (indices 0-4)
- Window 2: start=5-2=3, end=min(3+4,10)=7, so [0] + messages[3:7] (indices 0, 3-6)
- Window 3: start=3+2=5, end=min(5+4,10)=9, so [0] + messages[5:9] (indices 0, 5-8)
- Window 4: start=5+2=7, end=min(7+4,10)=10, so [0] + messages[7:10] (indices 0, 7-9)

Overlap between Window 1 and Window 2: indices 3-4 (2 messages)
Overlap between Window 2 and Window 3: indices 5-6 (2 messages)
Overlap between Window 3 and Window 4: indices 7-8 (2 messages)

Perfect!

Let's test with the original example: window_messages=40, overlap=4, n=90
- size=40, overlap=4, step=(40-1)-4=35
- Window 1: messages[0:40] (indices 0-39)
- Window 2: start=40-4=36, end=min(36+39,90)=75, so [0] + messages[36:75] (indices 0, 36-74)
- Window 3: start=36+35=71, end=min(71+39,90)=90, so [0] + messages[71:90] (indices 0, 71-89)

Overlap between Window 1 and Window 2: indices 36-39 (4 messages)
Overlap between Window 2 and Window 3: indices 71-74 (4 messages)

Yes! This is exactly what we want.

The original implementation used `step = size - overlap`, but it should be `step = (size - 1) - overlap` for the trajectory portion of subsequent windows.

Let me update the function:

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
    
    # First window covers messages 0 to size-1
    windows = [messages[:size]]
    
    # For subsequent windows:
    # - They include message 0, so their trajectory portion has size-1 messages
    # - To get an overlap of `overlap` messages, the trajectory portion should
    #   start at position: size - overlap
    # - The step between start positions is: (size - 1) - overlap
    step = (size - 1) - overlap
    for start in range(size - overlap, len(messages), step):
        end = min(start + size - 1, len(messages))
        windows.append([messages[0]] + messages[start:end])
    
    return windows
```

Let me verify with a few more examples:

1. window_messages=2, overlap=1, n=3:
   - size=2, overlap=1, step=(2-1)-1=0
   - Uh oh, step=0 would cause an infinite loop.

The config validation ensures `0 <= window_overlap < window_messages`, but it doesn't prevent `window_overlap = window_messages - 1`, which would make step=0.

We need to handle this case.

If step <= 0, it means overlap >= size - 1, which would create windows that are entirely overlapping. In this case, we should just create one additional window at the end.

Actually, if overlap == size - 1, then step = 0, and we want:
- Window 1: messages[0:size]
- Window 2: [message[0]] + messages[size-overlap:len(messages)]

But size-overlap = size - (size-1) = 1, so Window 2: [message[0]] + messages[1:len(messages)]

Let's update the function to handle step <= 0:

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
    
    # First window covers messages 0 to size-1
    windows = [messages[:size]]
    
    # For subsequent windows:
    # - They include message 0, so their trajectory portion has size-1 messages
    # - To get an overlap of `overlap` messages, the trajectory portion should
    #   start at position: size - overlap
    # - The step between start positions is: (size - 1) - overlap
    step = (size - 1) - overlap
    start = size - overlap
    
    # Handle the case where step <= 0 (overlap >= size - 1)
    # In this case, we just want one additional window at the end
    if step <= 0:
        if start < len(messages):
            end = min(start + size - 1, len(messages))
            windows.append([messages[0]] + messages[start:end])
        return windows
    
    # Normal case with positive step
    while start < len(messages):
        end = min(start + size - 1, len(messages))
        windows.append([messages[0]] + messages[start:end])
        start += step
    
    return windows
```

Let's test window_messages=2, overlap=1, n=3:
- size=2, overlap=1, step=(2-1)-1=0
- start=2-1=1
- step <= 0, so add window: [message[0]] + messages[1:3] (indices 0, 1-2)
- windows = [indices 0-1, indices 0, 1-2]

Overlap between Window 1 and Window 2: index 1 (1 message), which is correct.

Another test: window_messages=3, overlap=2, n=4:
- size=3, overlap=2, step=(3-1)-2=0
- start=3-2=1
- step <= 0, so add window: [message[0]] + messages[1:4] (indices 0, 1-3)
- windows = [indices 0-2, indices 0, 1-3]

Overlap between Window 1 and Window 2: indices 1-2 (2 messages), which is correct.

Now let's update the diff:

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..a2c4d7f 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -41,11 +41,24 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    windows = []
-    for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
-    return windows
+    # First window: messages 0 to size-1
+    windows = [messages[:size]]
+
+    # For subsequent windows, the trajectory portion has size-1 messages (1 slot for instructions)
+    # To get an overlap of `overlap` messages, the trajectory portion should start at: size - overlap
+    start_idx = size - overlap
+    if start_idx >= len(messages):
+        return windows
+
+    # The step between start positions for trajectory portions
+    step = (size - 1) - overlap
+
+    # Handle case where step <= 0 (overlap >= size - 1)
+    if step <= 0:
+        windows.append([messages[0]] + messages[start_idx:min(start_idx + size - 1, len(messages))])
+        return windows
+
+    # Normal case with positive step
+    while start_idx < len(messages):
+        end_idx = min(start_idx + size - 1, len(messages))
+        windows.append([messages[0]] + messages[start_idx:end_idx])
+        start_idx += step
+    return windows
 
 
 def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
```

Wait, I think I made it more complicated than necessary. Let's simplify:

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
    
    # First window: messages 0 to size-1
    windows = [messages[:size]]
    
    # For subsequent windows:
    # - They include message 0, so their trajectory portion has size-1 messages
    # - To get an overlap of `overlap` messages, the trajectory portion should
    #   start at position: size - overlap
    # - The step between start positions is: (size - 1) - overlap
    start = size - overlap
    step = (size - 1) - overlap
    
    # If step <= 0, we just want one additional window at the end
    if step <= 0:
        if start < len(messages):
            end = min(start + size - 1, len(messages))
            windows.append([messages[0]] + messages[start:end])
        return windows
    
    # Normal case with positive step
    while start < len(messages):
        end = min(start + size - 1, len(messages))
        windows.append([messages[0]] + messages[start:end])
        start += step
    
    return windows
```

Let's test this with various examples:

1. window_messages=40, overlap=4, n=90:
   - size=40, overlap=4, start=40-4=36, step=(40-1)-4=35
   - Window 1: 0-39
   - Window 2: start=36, end=36+39=75 -> 0, 36-74
   - Window 3: start=36+35=71, end=71+39=110 -> 0, 71-89
   - Overlap between Window 1 and Window 2: 36-39 (4 messages)
   - Overlap between Window 2 and Window 3: 71-74 (4 messages)

2. window_messages=2, overlap=1, n=3:
   - size=2, overlap=1, start=2-1=1, step=(2-1)-1=0
   - step <= 0, so add window: 0, 1-2
   - Overlap between Window 1 and Window 2: 1 (1 message)

3. window_messages=3, overlap=2, n=4:
   - size=3, overlap=2, start=3-2=1, step=(3-1)-2=0
   - step <= 0, so add window: 0, 1-3
   - Overlap between Window 1 and Window 2: 1-2 (2 messages)

4. window_messages=5, overlap=2, n=10:
   - size=5, overlap=2, start=5-2=3, step=(5-1)-2=2
   - Window 1: 0-4
   - Window 2: 0, 3-6
   - Window 3: start=3+2=5, 0, 5-8
   - Window 4: start=5+2=7, 0, 7-9
   - Overlap between Window 1 and Window 2: 3-4 (2 messages)
   - Overlap between Window 2 and Window 3: 5-6 (2 messages)
   - Overlap between Window 3 and Window 4: 7-8 (2 messages)

This implementation seems correct.

Let me update the test to verify the overlap:

```python
def test_overlap_between_windows(self):
    windows = split_windows(messages(90), 40, 4)
    # First window: indices 0-39
    # Second window: indices 0, 36-74
    # Overlap should be indices 36-39 (4 messages)
    self.assertEqual([m.idx for m in windows[0][-4:]], [m.idx for m in windows[1][1:5]])
    
    # Second window: indices 0, 36-74
    # Third window: indices 0, 71-89
    # Overlap should be indices 71-74 (4 messages)
    self.assertEqual([m.idx for m in windows[1][-4:]], [m.idx for m in windows[2][1:5]])
```

Actually, the existing test `test_overlap_between_windows` only checks the first two windows. Let's extend it to check all consecutive windows:

```python
def test_overlap_between_windows(self):
    windows = split_windows(messages(90), 40, 4)
    for i in range(len(windows) - 1):
        # Last `overlap` messages of current window should match messages 1 to overlap+1 of next window
        # (skipping the instruction message at position 0 of the next window)
        overlap_size = 4
        self.assertEqual(
            [m.idx for m in windows[i][-overlap_size:]],
            [m.idx for m in windows[i+1][1:1+overlap_size]]
        )
```

Let me update the diff accordingly.

I think this is the correct fix for the windowing logic.

Let me write the final diff for the follow-up commit.
