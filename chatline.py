"""Chat input history: Up / Down in the open chat bar recall what was sent before (the last 50 lines, kept in chat_history.txt between runs)."""
import os

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history.txt")

class History:
    def __init__(self, path=FILE, limit=50):
        self.path, self.limit, self.pos, self.draft = path, limit, None, ""
        try: self.lines = [l.rstrip("\n") for l in open(path, encoding="utf-8") if l.strip()][-limit:]
        except OSError: self.lines = []

    def reset(self): self.pos, self.draft = None, ""

    def push(self, text):
        """A line was sent."""
        text = text.strip(); self.reset()
        if not text: return
        if self.lines and self.lines[-1] == text: return
        self.lines = (self.lines + [text])[-self.limit:]
        try:
            with open(self.path, "w", encoding="utf-8") as f: f.write("\n".join(self.lines) + "\n")
        except OSError: pass

    def up(self, current):
        """The previous (older) line; `current` is remembered so Down can come back to it."""
        if not self.lines: return current
        if self.pos is None: self.pos, self.draft = len(self.lines), current
        self.pos = max(0, self.pos - 1); return self.lines[self.pos]

    def down(self, current):
        if self.pos is None: return current
        self.pos += 1
        if self.pos >= len(self.lines): self.pos = None; return self.draft
        return self.lines[self.pos]
