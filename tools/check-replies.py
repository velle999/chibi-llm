#!/usr/bin/env python3
"""Check that a reply gets the room it needs, and that a long one fits on screen.

  1. HOW LONG A REPLY MAY BE. reply_length.shape_for picks the token budget and
     the prompt note from what was asked: a story gets the long budget, the news
     and an explanation the middle one, chat stays at a line or two. Each case
     below is either a request that used to come back as one sentence, or one
     that must NOT be mistaken for such a request ("the good news is...").

  2. THE BUDGET REACHES SYNAPD. synapd reads the budget from the QUERY header's
     flags; without it every reply used synapd's 512-token default and the
     budget made no difference on that backend.

  3. A LONG REPLY IN THE BUBBLE. The bubble is capped to the room it is given,
     follows the newest line, shows a scrollbar only when there is more than
     fits, and can be scrolled back.

Run from the repo root:  tools/check-replies.py
"""
import os
import struct
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from config import Config                 # noqa: E402
from reply_length import shape_for        # noqa: E402

fails = 0


def check(desc, ok, detail=""):
    global fails
    if ok:
        print(f"  ok    {desc}")
    else:
        fails += 1
        print(f"  FAIL  {desc}{(' — ' + detail) if detail else ''}")


cfg = Config()
CHAT, MID, LONG = cfg.llm_num_predict, cfg.llm_num_predict_explain, cfg.llm_num_predict_long

print("how long a reply may be")
for text, kind, tokens in [
    ("tell me a story", "story", LONG),
    ("tell me a bedtime story about a dragon", "story", LONG),
    ("write me a poem about rain", "story", LONG),
    ("can you sing me a song", "story", LONG),
    ("tell me a short story", "story", MID),
    ("tell me a joke", "chat", CHAT),
    ("what's in the news", "news", MID),
    ("any news today?", "news", MID),
    ("headlines please", "news", MID),
    ("the good news is I got the job", "chat", CHAT),
    ("explain black holes", "explain", MID),
    ("explain black holes in detail", "explain", LONG),
    ("why is the sky blue", "explain", MID),
    ("how do I make pancakes", "explain", MID),
    ("how are you", "chat", CHAT),
    ("what time is it", "chat", CHAT),
    ("what do you think of this song", "chat", CHAT),
    ("what's the story with the weather", "chat", CHAT),
]:
    s = shape_for(text, cfg)
    check(f"{text!r} is {kind}, {tokens} tokens",
          (s.kind, s.tokens) == (kind, tokens), f"got {s.kind}, {s.tokens}")
    check(f"...and {'has' if kind != 'chat' else 'has no'} length note",
          bool(s.guidance) == (kind != "chat"))

s = shape_for("another one", cfg, previous="story")
check("'another one' after a story is another story", s.kind == "story" and s.tokens == LONG)
s = shape_for("another one", cfg, previous="chat")
check("'another one' after chat stays chat", s.kind == "chat")
s = shape_for("can I have more cheese on my pizza tonight please ok", cfg, previous="story")
check("a longer new message is judged on its own", s.kind == "chat")

print("the budget reaches synapd")
from llm_client import LLMClient, _SYNAPD_HDR, _SYNAPD_MAGIC, _SYNAPD_MSG_QUERY  # noqa: E402


class FakeSock:
    """Records what is sent and answers with one canned QUERY reply."""
    def __init__(self, reply):
        body = reply.encode() + b"\x00"
        self.inbox = _SYNAPD_HDR.pack(_SYNAPD_MAGIC, 1, _SYNAPD_MSG_QUERY, 0,
                                      len(body), 1, 0, 0) + body
        self.sent = b""

    def sendall(self, data):
        self.sent += data

    def recv(self, n):
        chunk, self.inbox = self.inbox[:n], self.inbox[n:]
        return chunk

    def close(self):
        pass


client = LLMClient.__new__(LLMClient)
client.config = Config()
client.config.llm_backend = "synapd"
client.connected = False
for budget in (CHAT, LONG):
    sock = FakeSock("Once upon a time there was a cat.\n\n[END]")
    client._synapd_connect = lambda timeout, s=sock: s
    reply = "".join(client.stream_chat([{"role": "user", "content": "hi"}],
                                       num_predict=budget))
    flags = struct.unpack_from("<IBBH", sock.sent)[3]
    check(f"a {budget}-token budget is sent in the header flags", flags == budget,
          f"flags={flags}")
check("an [END] marker after the reply is cut off",
      reply == "Once upon a time there was a cat.", repr(reply))

print("a long reply in the bubble")
import pygame                             # noqa: E402
pygame.init()
from chat_bubble import ChatBubble        # noqa: E402

b = ChatBubble(cfg)
story = ("Once upon a time a cat-eared robot lived above an old arcade. " * 6
         + "\n\n" + "Every night she watched the trains go by. " * 6)
b.set_text(story)
for _ in range(20000):
    b.update(0.04)
full_w, full_h = b.size()
screen = pygame.Surface((800, 480))
b.draw(screen, 400, 160)                  # the Pi kiosk: box bottom at y=140
first, shown, total, _h = b._window_seen
check("an uncapped size is the whole reply", b.size(None)[1] > 300)
check("the kiosk bubble stays on screen", b.rect.top >= b.TOP_MARGIN, str(b.rect))
check("...showing fewer lines than it has", shown < total, f"{shown}/{total}")
check("...ending on the newest line", first + shown == total)
check("paragraphs keep a blank line between them", "" in b._lines()[0])

b.scroll_by(-1000)
check("scrolling back reaches the first line", b.scroll_top == 0)
b.draw(screen, 400, 160)
b.set_text(story + " More.")               # the stream grows while scrolled back
b.draw(screen, 400, 160)
check("a growing reply keeps the scrolled-back position", b._window_seen[0] == 0)
b.scroll_by(1000)
check("scrolling to the bottom follows again", b.scroll_top is None)

r = b.rect
ev = pygame.event.Event
check("a press on the bubble is taken",
      b.handle_event(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=(r.x + 40, r.bottom - 20))))
b.handle_event(ev(pygame.MOUSEMOTION, pos=(r.x + 40, r.bottom - 20 + 2 * (_h + b.GAP)),
                  rel=(0, 0), buttons=(1, 0, 0)))
b.handle_event(ev(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
check("dragging the text down by two lines shows two earlier lines",
      b.scroll_top == total - shown - 2, f"scroll_top={b.scroll_top}")
check("a press elsewhere is not taken",
      not b.handle_event(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 470))))

b.set_text("Hi! Want some tea?")
for _ in range(200):
    b.update(0.04)
b.draw(screen, 400, 160)
check("a new line starts following again", b.scroll_top is None)
check("a short reply is the same size capped or not", b.size(300) == b.size(None))
check("...has no scrollbar to drag",
      not b.handle_event(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=b.rect.center)))

print()
if fails:
    print(f"{fails} check(s) failed")
    sys.exit(1)
print("all checks passed")
