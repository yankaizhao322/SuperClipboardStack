# ClipboardStack

ClipboardStack has two modes:

- A native macOS menu-bar clipboard history app for text and images.
- A cross-platform text logger for Windows, Linux, and macOS that writes copied text to a temporary file you can inspect with `cat`, `type`, or an editor.

In the macOS app, copy normally with `Command-C`; ClipboardStack records the latest unique entries. Click the `Clip` menu-bar item, choose an older text or image item, and it is placed back onto the system clipboard for normal paste with `Command-V`.

History is persisted to:

```text
~/Library/Application Support/ClipboardStack/history.json
```

## macOS Menu-Bar App

```bash
swift run
```

Or use:

```bash
./run.command
```

macOS may ask for permission depending on how your source app exposes copied content. The app does not need Accessibility permission because it reads the system pasteboard instead of watching keystrokes.

## Cross-Platform Text Log

The CLI version records copied text only. It is designed for Windows and Linux users who want a simple terminal workflow.

Linux/macOS:

```bash
./scripts/cliplog.sh
```

Windows:

```bat
scripts\cliplog.cmd
```

The command prints a temporary file path, for example:

```text
ClipboardStack text log: /tmp/clipboardstack-abcd.txt
```

Then use another terminal to inspect it:

```bash
cat /tmp/clipboardstack-abcd.txt
```

On Windows:

```bat
type C:\Users\you\AppData\Local\Temp\clipboardstack-abcd.txt
```

The newest copied text appears first. Stop the logger with `Ctrl-C`. The temporary file is deleted on normal exit, `SIGINT`, `SIGTERM`, and `SIGHUP`. If you want to keep a permanent file, choose your own path:

```bash
./scripts/cliplog.sh --keep-file ./my-clipboard-notes.txt
```

Linux clipboard backends are tried in this order: `wl-paste`, `xclip`, `xsel`, then Python `tkinter`. Windows uses PowerShell `Get-Clipboard` with a `tkinter` fallback.

Useful options:

```bash
./scripts/cliplog.sh --interval 0.25 --max-items 300 --max-mb 16
```

## Algorithm And Complexity

### macOS App

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

### Cross-Platform CLI

The CLI uses:

- `deque[ClipEntry]` for newest-first bounded history.
- `set[str]` of SHA-256 digests for duplicate detection.
- An atomic temp-file rewrite after each new unique copy.

For each clipboard poll:

1. Read the current text clipboard.
2. Compute SHA-256 over UTF-8 bytes.
3. Skip if the digest matches an existing entry.
4. Add newest entry to the front.
5. Evict oldest entries until both `--max-items` and `--max-mb` limits are satisfied.
6. Rewrite the visible text log atomically.

Complexity:

- Poll with unchanged text: `O(s)` for hashing current clipboard text.
- Add new copied text: `O(s)` for hashing plus expected `O(1)` set/deque operations.
- Trim oldest entries: amortized `O(1)` per removed entry.
- Rewrite log file: `O(total stored bytes + n)` after a new unique copy.
- Memory: bounded by `--max-mb` plus per-entry metadata, so the process does not grow without limit.

The CLI truncates a single copied item to 512 KiB before storing it. A `kill -9` cannot be caught by any process, so the temp file may remain after that specific forced kill. Normal terminal close and `Ctrl-C` are handled.

## SuperClipboardStack Web (New)

This repository now also contains a lightweight web app at `webapp/` with:

- User registration and login
- Per-user private clipboard notes
- Edit and delete support
- Optional image crop before saving (no download feature yet)

### Run Locally

```bash
cd webapp
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>.

### 公网访问（GitHub + Render）

GitHub **只托管代码**，要让全世界用浏览器打开，需要再连一个托管平台（这里用 **Render**，免费档可用）。本仓库根目录包含 `render.yaml`（Blueprint）。按下面做即可。

1. 把本仓库推送到你的 GitHub（只在 `D:\codex\SuperClipboardStack` 里操作即可）。
2. 打开 [Render](https://render.com)，登录后 **New → Blueprint**。
3. 选择你的 GitHub 仓库，Render 会读到根目录的 `render.yaml`，按提示创建服务。
4. 部署完成后，在 Render 面板里打开该服务的 URL（形如 `https://superclipboard-web.onrender.com`），即可公网访问。

说明：

- `SECRET_KEY` 已在 Blueprint 里用 `generateValue: true` 自动生成，无需手填。
- 生产环境使用 `gunicorn --bind 0.0.0.0:$PORT app:app`（与 `webapp/Procfile` 一致），否则平台分配的端口对不上会打不开。
- **免费实例** 的磁盘不保证持久：用 SQLite 时，**重新部署或休眠唤醒后数据可能丢失**；若要长期保留用户数据，需要在 Render 上为 Web Service 加 **Persistent Disk** 并把应用数据目录挂到盘上，或改用托管数据库（后续可再升级）。

### Deploy To Render（手动建 Web Service，可选）

若不使用 Blueprint，也可 **New → Web Service**，并设置：

- Root directory: `webapp`
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT app:app`
- Environment: `SECRET_KEY` = 随机长字符串；`PYTHON_VERSION` = `3.11.9`（与 `webapp/runtime.txt` 一致）
