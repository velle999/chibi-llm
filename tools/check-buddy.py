#!/usr/bin/env python3
"""Check the parts of buddy mode that are logic rather than pictures.

  1. WHERE SHE CAN STAND. platforms_for() turns the compositor's window list
     into the edges she walks on, and each rule in it exists because getting
     it wrong is visible: a window on another monitor or workspace becomes an
     invisible ledge; forgetting the bar's height puts her feet a bar's height
     above the window; a top edge under another window has her standing on a
     line across the middle of it.

  2. THE BUBBLE ACROSS A STREAMED REPLY. chibi re-sends the whole reply on
     every chunk. The bubble must carry on typing rather than restart, and
     must still count a genuinely new line as new — the helper tells the two
     apart by serial, so a line said twice has to bump it.

Run from the repo root:  tools/check-buddy.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from buddy import platforms_for          # noqa: E402

fails = 0


def check(desc, ok, detail=""):
    global fails
    if ok:
        print(f"  ok    {desc}")
    else:
        fails += 1
        print(f"  FAIL  {desc}{(' — ' + detail) if detail else ''}")


def win(x, y, w, h, stack=0, output="DP-1", workspace=1, pid=100, key=None):
    return {"output": output, "workspace": workspace, "x": x, "y": y, "w": w, "h": h,
            "stack": stack, "pid": pid, "key": key or f"{x},{y}"}


# One 1920x1080 screen at layout (1000, 0) with a 40 px bar on top: the
# overlay's origin is the usable box's corner, (1000, 40).
def world(*windows):
    return {"outputs": {"DP-1": {"at": [1000, 0], "size": [1920, 1080],
                                 "usable": [1000, 40, 1920, 1040], "workspace": 1}},
            "windows": list(windows)}


def plats(w, **kw):
    args = dict(surface_w=1920, floor=1040, min_w=100, headroom=200, own_pid=None)
    args.update(kw)
    return platforms_for(w, "DP-1", **args)


print("where she can stand")
p = plats(world(win(1200, 500, 600, 400)))
check("a window's top is an edge", len(p) == 1)
check("…in the overlay's coordinates, the bar and the screen's offset taken off",
      p and (p[0].x1, p[0].x2, p[0].y) == (200, 800, 460), repr(p))

check("a top too near the top of the screen is not (her head would be off it)",
      plats(world(win(1200, 100, 600, 400))) == [])
check("a top at the floor is not",
      plats(world(win(1200, 1075, 600, 5))) == [])
check("a window on another monitor is not",
      plats(world(win(1200, 500, 600, 400, output="HDMI-A-1"))) == [])
check("a window on another workspace is not",
      plats(world(win(1200, 500, 600, 400, workspace=2))) == [])
check("chibi's own window is not",
      plats(world(win(1200, 500, 600, 400, pid=42)), own_pid=42) == [])
check("an edge narrower than she is is not",
      plats(world(win(1200, 500, 80, 400))) == [])

p = plats(world(win(1200, 500, 600, 400, stack=0, key="back"),
                win(1400, 300, 200, 400, stack=1, key="front")))
back = sorted((q.x1, q.x2) for q in p if q.key == "back")
check("a window in front cuts the edge behind it into the parts still showing",
      back == [(200, 400), (600, 800)], repr(p))
p = plats(world(win(1200, 500, 600, 400, stack=1, key="back"),
                win(1400, 300, 200, 400, stack=0, key="front")))
check("…and a window BEHIND cuts nothing",
      sorted((q.x1, q.x2) for q in p if q.key == "back") == [(200, 800)], repr(p))
check("an unknown output gives no edges, not an error",
      platforms_for(world(), "DP-9", 1920, 1040, 100, 200) == [])
check("no compositor information gives no edges",
      platforms_for(None, "DP-1", 1920, 1040, 100, 200) == [])

print("the bubble across a streamed reply")
import pygame                             # noqa: E402
pygame.font.init()
from config import Config                 # noqa: E402
from chat_bubble import ChatBubble        # noqa: E402

b = ChatBubble(Config())
b.set_text("Hello")
s1 = b.serial
for _ in range(3):
    b.update(0.04)
typed = b.char_index
b.set_text("Hello there, how are you?")
check("a growing reply keeps typing where it had got to",
      b.char_index == typed and b.target_text == "Hello there, how are you?",
      f"char_index {b.char_index}, was {typed}")
check("…and is the same line", b.serial == s1)
b.set_text("Something else")
check("a different line starts again", b.char_index == 0 and b.serial == s1 + 1)
s2 = b.serial
b.set_text("Something else")
check("the same words said again are a new line", b.serial == s2 + 1)
b.hide()
b.set_text("Something else entirely")
check("after hide(), a line that happens to extend the last is still new",
      b.char_index == 0 and b.serial == s2 + 2)

print()
if fails:
    print(f"{fails} check(s) failed")
    sys.exit(1)
print("all checks passed")
