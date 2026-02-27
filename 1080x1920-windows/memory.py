"""
Persistent Memory — Gives the chibi avatar long-term memory across sessions.

Stores:
  - Conversation summaries (auto-summarized periodically)
  - User facts/preferences extracted from conversation
  - Mood history and interaction stats
  - Custom notes the user explicitly asks to remember

Data is saved to a JSON file on disk, loaded on startup,
and injected into the LLM system prompt for continuity.

Install: No extra deps needed (stdlib json only)
"""

import json
import os
import time
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field


MEMORY_FILE = os.path.expanduser("~/.chibi-avatar-memory.json")
MAX_FACTS = 50
MAX_SUMMARIES = 30
MAX_SUMMARY_AGE_DAYS = 90


@dataclass
class MemoryEntry:
    text: str
    category: str        # "fact", "preference", "note", "summary"
    created_at: str
    source: str = ""     # "user_explicit", "extracted", "auto_summary"
    importance: int = 5  # 1-10


class PersistentMemory:
    """
    Manages long-term avatar memory stored on disk.
    Memory is injected into LLM context so the avatar can reference past interactions.
    """

    def __init__(self, filepath: str = MEMORY_FILE):
        self.filepath = filepath
        self._lock = threading.Lock()

        # Memory stores
        self.facts: list[dict] = []          # User facts & preferences
        self.summaries: list[dict] = []      # Conversation summaries
        self.notes: list[dict] = []          # Explicit "remember this"
        self.stats: dict = {
            "total_conversations": 0,
            "total_messages": 0,
            "first_interaction": None,
            "last_interaction": None,
            "mood_counts": {},
        }
        self.user_name: str = "Velle"  # Default, overridden by saved memory

        self._load()

    # ─── Persistence ─────────────────────────────────────────────────────

    def _load(self):
        """Load memory from disk."""
        if not os.path.exists(self.filepath):
            print("[Memory] No existing memory found, starting fresh.")
            return

        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)

            self.facts = data.get("facts", [])
            self.summaries = data.get("summaries", [])
            self.notes = data.get("notes", [])
            self.stats = data.get("stats", self.stats)
            self.user_name = data.get("user_name", "")

            print(f"[Memory] Loaded: {len(self.facts)} facts, "
                  f"{len(self.summaries)} summaries, {len(self.notes)} notes")

        except Exception as e:
            print(f"[Memory] Error loading: {e}")

    def save(self):
        """Save memory to disk."""
        with self._lock:
            data = {
                "facts": self.facts,
                "summaries": self.summaries,
                "notes": self.notes,
                "stats": self.stats,
                "user_name": self.user_name,
                "saved_at": datetime.now().isoformat(),
            }

            try:
                # Atomic write via temp file
                tmp = self.filepath + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, self.filepath)
            except Exception as e:
                print(f"[Memory] Error saving: {e}")

    # ─── Adding Memories ─────────────────────────────────────────────────

    def add_fact(self, text: str, importance: int = 5, source: str = "extracted"):
        """Add a user fact or preference."""
        with self._lock:
            # Check for duplicates (fuzzy)
            for existing in self.facts:
                if _similar(existing["text"], text):
                    # Update if new version is more important
                    if importance > existing.get("importance", 5):
                        existing["text"] = text
                        existing["importance"] = importance
                        existing["updated_at"] = datetime.now().isoformat()
                    return

            self.facts.append({
                "text": text,
                "category": "fact",
                "importance": importance,
                "source": source,
                "created_at": datetime.now().isoformat(),
            })

            # Trim oldest low-importance facts if over limit
            if len(self.facts) > MAX_FACTS:
                self.facts.sort(key=lambda x: x.get("importance", 5))
                self.facts = self.facts[-(MAX_FACTS):]

        self.save()

    def add_note(self, text: str):
        """Add an explicit note (user said 'remember this')."""
        with self._lock:
            self.notes.append({
                "text": text,
                "category": "note",
                "source": "user_explicit",
                "created_at": datetime.now().isoformat(),
            })
        self.save()

    def add_summary(self, summary: str):
        """Add a conversation summary."""
        with self._lock:
            self.summaries.append({
                "text": summary,
                "created_at": datetime.now().isoformat(),
            })

            # Trim old summaries
            if len(self.summaries) > MAX_SUMMARIES:
                self.summaries = self.summaries[-(MAX_SUMMARIES):]

        self.save()

    def set_user_name(self, name: str):
        """Remember the user's name."""
        self.user_name = name
        self.save()

    def remove_fact(self, index: int):
        """Remove a fact by index."""
        with self._lock:
            if 0 <= index < len(self.facts):
                self.facts.pop(index)
        self.save()

    def remove_note(self, index: int):
        """Remove a note by index."""
        with self._lock:
            if 0 <= index < len(self.notes):
                self.notes.pop(index)
        self.save()

    # ─── Stats Tracking ──────────────────────────────────────────────────

    def record_interaction(self):
        """Record that an interaction happened."""
        now = datetime.now().isoformat()
        self.stats["total_messages"] = self.stats.get("total_messages", 0) + 1
        if not self.stats.get("first_interaction"):
            self.stats["first_interaction"] = now
        self.stats["last_interaction"] = now

    def start_conversation(self):
        """Record start of a new conversation session."""
        self.stats["total_conversations"] = self.stats.get("total_conversations", 0) + 1
        self.save()

    # ─── Context Generation ──────────────────────────────────────────────

    def get_context(self) -> str:
        """
        Generate a memory context string to inject into the LLM system prompt.
        Prioritizes most important and recent memories.
        """
        parts = []

        # User name
        if self.user_name:
            parts.append(f"The user's name is {self.user_name}.")

        # Stats
        total = self.stats.get("total_messages", 0)
        convos = self.stats.get("total_conversations", 0)
        first = self.stats.get("first_interaction")
        if total > 0:
            stats_line = f"You've had {convos} conversations with {total} total messages."
            if first:
                try:
                    first_dt = datetime.fromisoformat(first)
                    days = (datetime.now() - first_dt).days
                    if days > 0:
                        stats_line += f" You've known this user for {days} days."
                except Exception:
                    pass
            parts.append(stats_line)

        # Important facts (sorted by importance, top 15)
        if self.facts:
            sorted_facts = sorted(self.facts,
                                  key=lambda x: x.get("importance", 5),
                                  reverse=True)[:15]
            fact_lines = [f"- {f['text']}" for f in sorted_facts]
            parts.append("What you know about the user:\n" + "\n".join(fact_lines))

        # Explicit notes
        if self.notes:
            recent_notes = self.notes[-10:]
            note_lines = [f"- {n['text']}" for n in recent_notes]
            parts.append("Things the user asked you to remember:\n" + "\n".join(note_lines))

        # Recent summaries (last 5)
        if self.summaries:
            recent = self.summaries[-5:]
            sum_lines = [f"- [{s.get('created_at', '?')[:10]}] {s['text']}"
                         for s in recent]
            parts.append("Recent conversation summaries:\n" + "\n".join(sum_lines))

        if not parts:
            return ""

        return "[LONG-TERM MEMORY]\n" + "\n\n".join(parts)

    # ─── Memory Extraction Prompt ────────────────────────────────────────

    @staticmethod
    def get_extraction_prompt(conversation: list[dict]) -> str:
        """
        Returns a prompt to send to the LLM to extract memories from a conversation.
        Call this periodically or at end of conversation.
        """
        # Build conversation text
        lines = []
        for msg in conversation[-20:]:  # Last 20 messages
            role = msg["role"].upper()
            lines.append(f"{role}: {msg['content']}")
        convo_text = "\n".join(lines)

        return f"""Analyze this conversation and extract important information to remember.
Return a JSON object with these fields:
- "facts": list of strings — factual things about the user (name, preferences, job, hobbies, etc.)
- "summary": string — a 1-2 sentence summary of what was discussed
- "user_name": string or null — the user's name if mentioned
- "notes": list of strings — anything the user explicitly asked to remember

Only include things worth remembering long-term. Be concise.
Return ONLY valid JSON, no other text.

CONVERSATION:
{convo_text}"""

    def process_extraction(self, json_str: str):
        """Process the LLM's memory extraction response."""
        try:
            # Clean up potential markdown wrapping
            text = json_str.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            data = json.loads(text)

            # Process facts
            for fact in data.get("facts", []):
                if isinstance(fact, str) and len(fact) > 3:
                    self.add_fact(fact, importance=6, source="extracted")

            # Process summary
            summary = data.get("summary", "")
            if summary and len(summary) > 10:
                self.add_summary(summary)

            # Process name
            name = data.get("user_name")
            if name and isinstance(name, str):
                self.set_user_name(name)

            # Process explicit notes
            for note in data.get("notes", []):
                if isinstance(note, str) and len(note) > 3:
                    self.add_note(note)

            print(f"[Memory] Extracted: {len(data.get('facts', []))} facts, "
                  f"summary={'yes' if summary else 'no'}")

        except json.JSONDecodeError as e:
            print(f"[Memory] Failed to parse extraction: {e}")
        except Exception as e:
            print(f"[Memory] Extraction error: {e}")


def _similar(a: str, b: str, threshold: float = 0.7) -> bool:
    """Simple similarity check using word overlap."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    total = max(len(words_a), len(words_b))
    return (overlap / total) >= threshold
