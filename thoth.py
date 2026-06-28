"""
Thoth corpus — the scribe's reference material.

Phase 1 (now): a curated *correspondence lexicon*. Given a dream/vision
account, surface the symbols within it and their associations across the
Egyptian, Hermetic, Gnostic, Kabbalistic, and Jungian traditions — as
resonance, not interpretation. The block is injected into the system prompt in horus_mode so
a small local model has a grounded symbolic vocabulary to draw from instead of
confabulating attributions.

Phase 2 (later): full-text RAG. `retrieve()` is the seam — embed public-domain
primary texts (Mead's Hermetica, Budge's Book of the Dead, the Kybalion,
Mathers' Kabbalah Unveiled, Jung's Psychology of the Unconscious) and return
short passages relevant to the account.
It is a no-op stub for now, so the injection site and the three-copy mirroring
are already in place when the corpus is indexed.
"""

import os
import re
import json


class ThothCorpus:
    def __init__(self, lexicon_path: str = None, config=None):
        if lexicon_path is None:
            lexicon_path = os.path.join(os.path.dirname(__file__), "thoth_lexicon.json")
        self.config = config

        # Optional phase-2 retriever over primary texts. Built lazily and only
        # when explicitly enabled; any failure leaves the lexicon working alone.
        self.rag = None
        if config is not None and getattr(config, "thoth_rag_enabled", False):
            try:
                from thoth_rag import ThothRAG
                self.rag = ThothRAG(config)
            except Exception as e:
                print(f"[Thoth] RAG disabled ({e}); lexicon only.")
                self.rag = None

        self.symbols: list = []
        try:
            with open(lexicon_path, "r", encoding="utf-8") as f:
                self.symbols = json.load(f).get("symbols", [])
            print(f"[Thoth] Loaded {len(self.symbols)} lexicon symbols.")
        except Exception as e:
            print(f"[Thoth] Lexicon unavailable ({e}); leaning on the model's own knowledge.")

        # Precompile word-boundary matchers per alias so lookup is cheap on the Pi.
        self._matchers = []
        for entry in self.symbols:
            patterns = [
                re.compile(r"\b" + re.escape(a.lower()) + r"\b")
                for a in entry.get("aliases", [])
            ]
            self._matchers.append((entry, patterns))

    def lookup(self, text: str, max_symbols: int = 4) -> str:
        """Correspondence block for the symbols present in `text`.

        Returns "" when nothing resonates — Thoth then leans on the prompt alone.
        Symbols are ranked by how many of their aliases appear, then by how
        early the first one occurs, so the most prominent symbol leads.
        """
        if not text or not self.symbols:
            return ""
        low = text.lower()

        hits = []
        for entry, patterns in self._matchers:
            positions = []
            for p in patterns:
                m = p.search(low)
                if m:
                    positions.append(m.start())
            if positions:
                # (alias hits, earliest position) — both sorted to favour prominence
                hits.append((len(positions), -min(positions), entry))
        if not hits:
            return ""
        hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
        chosen = [h[2] for h in hits[:max_symbols]]

        lines = ["[CORRESPONDENCE LEXICON — for resonance, not interpretation]"]
        for entry in chosen:
            lines.append(entry["symbol"].upper())
            for tradition, note in entry.get("correspondences", {}).items():
                lines.append(f"  · {tradition}: {note}")
        lines.append(
            "Offer only what genuinely resonates with what Velle described. "
            "Present these as parallels; do not assert what they mean."
        )
        return "\n".join(lines)

    def retrieve(self, text: str, k: int = None) -> str:
        """Source passages from the primary-text index (phase 2).

        Delegates to ThothRAG when enabled and indexed; returns "" otherwise,
        so Thoth falls back to the correspondence lexicon alone.
        """
        if self.rag is None:
            return ""
        try:
            return self.rag.retrieve(text, k=k)
        except Exception as e:
            print(f"[Thoth] retrieval failed ({e}); lexicon only.")
            return ""

    def context_for(self, text: str) -> str:
        """The full Thoth reference block: lexicon now, retrieved passages later."""
        parts = [self.lookup(text), self.retrieve(text)]
        return "\n\n".join(p for p in parts if p)
