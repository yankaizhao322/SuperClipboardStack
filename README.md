# ClipboardStack

ClipboardStack is a small macOS menu-bar clipboard history tool for text and images. Copy normally with `Command-C`; ClipboardStack records the latest unique entries. Click the `Clip` menu-bar item, choose an older text or image item, and it is placed back onto the system clipboard for normal paste with `Command-V`.

History is persisted to:

```text
~/Library/Application Support/ClipboardStack/history.json
```

## Run

```bash
swift run
```

Or use:

```bash
./run.command
```

macOS may ask for permission depending on how your source app exposes copied content. The app does not need Accessibility permission because it reads the system pasteboard instead of watching keystrokes.

## Algorithm

ClipboardStack stores history with two structures:

- `Dictionary<String, ClipboardNode>` maps a content hash to the node for duplicate detection.
- A doubly linked list keeps entries in newest-first order.

For each clipboard change:

1. Read text first, then image data from `NSPasteboard`.
2. Compute a SHA-256 fingerprint over the text bytes or image TIFF bytes.
3. If the fingerprint already exists, update the node timestamp and move it to the head.
4. If it is new, insert it at the head.
5. If capacity is exceeded, remove the tail.

Complexity:

- Capture hashing: `O(s)`, where `s` is copied content size.
- Insert new item after hashing: `O(1)`.
- Detect duplicate after hashing: expected `O(1)`.
- Promote duplicate to most recent: `O(1)`.
- Evict oldest item: `O(1)`.
- Rebuild menu UI: `O(n)`, where `n` is stored history count. This is separate from the storage algorithm and is bounded by the capacity.
- Persist history to disk after a change: `O(total stored bytes + n)`.
- Memory: `O(total stored bytes + n)`.

The default capacity is `80` items in `main.swift`.
