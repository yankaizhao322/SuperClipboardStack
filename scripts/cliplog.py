#!/usr/bin/env python3
"""
Cross-platform text clipboard logger.

It polls the system clipboard, writes unique copied text into a temporary file,
and removes that file when the process exits normally or receives a handled
termination signal.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Deque, Optional


MAX_ITEM_BYTES = 512 * 1024


@dataclass(frozen=True)
class ClipEntry:
    digest: str
    captured_at: str
    text: str

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8", errors="replace"))


class ClipboardLog:
    def __init__(self, max_items: int, max_bytes: int) -> None:
        self.max_items = max(1, max_items)
        self.max_bytes = max(1024, max_bytes)
        self.entries: Deque[ClipEntry] = deque()
        self.digests: set[str] = set()
        self.total_bytes = 0

    def add(self, text: str) -> bool:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip():
            return False

        encoded = normalized.encode("utf-8", errors="replace")
        if len(encoded) > MAX_ITEM_BYTES:
            normalized = encoded[:MAX_ITEM_BYTES].decode("utf-8", errors="ignore")
            encoded = normalized.encode("utf-8", errors="replace")

        digest = hashlib.sha256(encoded).hexdigest()
        if digest in self.digests:
            return False

        entry = ClipEntry(
            digest=digest,
            captured_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            text=normalized,
        )
        self.entries.appendleft(entry)
        self.digests.add(digest)
        self.total_bytes += entry.size_bytes
        self._trim()
        return True

    def _trim(self) -> None:
        while len(self.entries) > self.max_items or self.total_bytes > self.max_bytes:
            old = self.entries.pop()
            self.digests.discard(old.digest)
            self.total_bytes -= old.size_bytes

    def render(self) -> str:
        lines = [
            "# ClipboardStack text log",
            "# Newest entries are first. Save this file elsewhere if you want to keep it.",
            "# The running cliplog process deletes this file on normal exit.",
            "",
        ]

        for index, entry in enumerate(self.entries, start=1):
            lines.append(f"===== {index} | {entry.captured_at} | sha256:{entry.digest[:12]} =====")
            lines.append(entry.text)
            if not entry.text.endswith("\n"):
                lines.append("")
            lines.append("")

        return "\n".join(lines)


class TempLogFile:
    def __init__(self, path: Optional[str]) -> None:
        if path:
            self.path = Path(path).expanduser().resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.delete_on_exit = False
        else:
            fd, temp_path = tempfile.mkstemp(prefix="clipboardstack-", suffix=".txt")
            os.close(fd)
            self.path = Path(temp_path)
            self.delete_on_exit = True

    def write(self, content: str) -> None:
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, self.path)

    def cleanup(self) -> None:
        if self.delete_on_exit:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def read_with_command(command: list[str]) -> Optional[str]:
    if not shutil.which(command[0]):
        return None
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def read_with_tkinter() -> Optional[str]:
    try:
        import tkinter
    except ImportError:
        return None

    try:
        root = tkinter.Tk()
        root.withdraw()
        value = root.clipboard_get()
        root.destroy()
        return value
    except Exception:
        return None


def clipboard_reader() -> Callable[[], Optional[str]]:
    system = platform.system().lower()

    if system == "darwin":
        return lambda: read_with_command(["pbpaste"]) or read_with_tkinter()

    if system == "windows":
        return lambda: read_with_command(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Clipboard -Raw -Format Text",
            ]
        ) or read_with_tkinter()

    if system == "linux":
        return lambda: (
            read_with_command(["wl-paste", "--no-newline"])
            or read_with_command(["xclip", "-selection", "clipboard", "-out"])
            or read_with_command(["xsel", "--clipboard", "--output"])
            or read_with_tkinter()
        )

    return read_with_tkinter


def install_cleanup_handlers(log_file: TempLogFile) -> None:
    def cleanup_and_exit(signum: int, _frame: object) -> None:
        log_file.cleanup()
        raise SystemExit(128 + signum)

    atexit.register(log_file.cleanup)

    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, cleanup_and_exit)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log copied text to a temporary file.")
    parser.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds.")
    parser.add_argument("--max-items", type=int, default=200, help="Maximum entries kept in memory and file.")
    parser.add_argument("--max-mb", type=int, default=8, help="Maximum stored text size in MiB.")
    parser.add_argument(
        "--keep-file",
        metavar="PATH",
        help="Write to a chosen file and do not delete it on exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log = ClipboardLog(max_items=args.max_items, max_bytes=args.max_mb * 1024 * 1024)
    log_file = TempLogFile(args.keep_file)
    install_cleanup_handlers(log_file)

    read_clipboard = clipboard_reader()
    last_digest: Optional[str] = None
    log_file.write(log.render())

    print(f"ClipboardStack text log: {log_file.path}", flush=True)
    print("Use another terminal to run:", flush=True)
    print(f"  cat {log_file.path}", flush=True)
    print("Press Ctrl-C to stop. The temp file is deleted unless --keep-file is used.", flush=True)

    while True:
        text = read_clipboard()
        if text is not None:
            digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
            if digest != last_digest and log.add(text):
                last_digest = digest
                log_file.write(log.render())
        time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
