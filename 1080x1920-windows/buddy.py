"""
Buddy mode — chibi out of her window and loose on the desktop.

Press ✦ in the window (or F4, or start with `--buddy`) and chibi leaves it: she
drops onto the desktop, wanders along the bottom of the screen, floats up onto
the tops of windows and hops back down, and says what she has to say in a
bubble over her head. Click her to pet her, double-click to talk to her, drag
her anywhere, and right-click for the menu, which is also how she goes home.

TWO HALVES IN ONE FILE, AND THEY NEVER SHARE A PROCESS.

  BuddyLink   lives in chibi. Starts the helper, tells it what chibi is doing,
              and hands back what happened to her out there.
  the helper  this file run as a script: a GTK4 layer-shell overlay that draws
              her with the same ChibiRenderer the window uses.

Why a second process: an overlay the rest of the desktop can be clicked
through needs wlr-layer-shell and an input region, and SDL (pygame) has
neither. GTK4 has both through gtk4-layer-shell — but that library must be
loaded before libwayland-client, which from Python means LD_PRELOAD, and GTK
wants the main thread that chibi's pygame loop already owns. A child gets its
own environment and its own main thread, and if it dies chibi simply comes
back to her window.

She stays ONE chibi. Voice, the LLM, memory and the soul all stay in chibi's
process; the helper only draws her and reports what the pointer did.

The wire is one JSON object per line, both ways.
  chibi → helper   {"op": "sync", <changed fields>}   state, horus, speaking,
                                                       bubble: [serial, text]
                   {"op": "home"}  {"op": "quit"}  {"op": "where"}
  helper → chibi   {"ev": "ready"}  {"ev": "error", "reason": ...}
                   {"ev": "pet"}  {"ev": "talk", "text": ...}
                   {"ev": "talking", "on": bool}  {"ev": "mic"}
                   {"ev": "home"}  {"ev": "quit"}  {"ev": "where", ...}
"""

import ctypes.util
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _layer_shell_lib():
    """What to LD_PRELOAD, or None when gtk4-layer-shell is not installed.
    CHIBI_LAYER_SHELL_LIB overrides the search, for a copy outside the
    library path."""
    override = os.environ.get("CHIBI_LAYER_SHELL_LIB")
    if override:
        return override if os.path.exists(override) else None
    return ctypes.util.find_library("gtk4-layer-shell")


# ═══════════════════════════════════════════════════════════════════════════
#  chibi's half
# ═══════════════════════════════════════════════════════════════════════════

class BuddyLink:
    def __init__(self, config):
        self.config = config
        self.proc = None
        self.out = False          # she is on the desktop and the window is hidden
        self._events = queue.Queue()
        self._sent = {}

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def unavailable_reason():
        """Why she cannot go out on this desktop, or None if she can. Only the
        cheap checks; the helper reports the rest (no layer-shell on this
        compositor) as an "error" event."""
        if not sys.platform.startswith("linux"):
            return "I can only go out and play on a Linux Wayland desktop."
        if not os.environ.get("WAYLAND_DISPLAY"):
            return "I can only go out and play on a Wayland desktop."
        if not _layer_shell_lib():
            return "I need gtk4-layer-shell installed to go out and play."
        return None

    def start(self, pid):
        env = dict(os.environ)
        env["LD_PRELOAD"] = " ".join(
            p for p in (_layer_shell_lib(), env.get("LD_PRELOAD", "")) if p)
        env["GDK_BACKEND"] = "wayland"
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
        env["CHIBI_BUDDY_OPTS"] = json.dumps({
            "pid": pid,
            "scale": float(getattr(self.config, "buddy_scale", 0.55)),
            "output": getattr(self.config, "buddy_output", "") or "",
            "climb": bool(getattr(self.config, "buddy_climb", True)),
        })
        self._sent = {}
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "buddy.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            cwd=HERE, env=env, text=True, bufsize=1,
        )
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        for line in proc.stdout:
            try:
                self._events.put(json.loads(line))
            except ValueError:
                print(f"[Buddy] {line.rstrip()}")
        self._events.put({"ev": "exited", "code": proc.wait()})

    def _send(self, msg):
        if not self.running:
            return
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass    # it has gone; _read reports the exit

    def sync(self, **fields):
        """Send whatever changed since the last call — once a frame, so only
        the differences go over the pipe."""
        changed = {k: v for k, v in fields.items() if self._sent.get(k) != v}
        if changed:
            self._sent.update(changed)
            self._send({"op": "sync", **changed})

    def poll(self):
        while True:
            try:
                yield self._events.get_nowait()
            except queue.Empty:
                return

    def home(self):
        self._send({"op": "home"})

    def where(self):
        self._send({"op": "where"})

    def stop(self):
        if not self.running:
            return
        self._send({"op": "quit"})
        try:
            self.proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# ═══════════════════════════════════════════════════════════════════════════
#  Where she can stand — pure logic, no GTK, so it can be checked on its own
# ═══════════════════════════════════════════════════════════════════════════

class Platform:
    """A walkable top edge: x1..x2 at height y, in the overlay's coordinates.
    `key` names the window it belongs to, so she can ride it when it moves."""
    __slots__ = ("x1", "x2", "y", "key")

    def __init__(self, x1, x2, y, key):
        self.x1, self.x2, self.y, self.key = x1, x2, y, key

    def holds(self, x):
        return self.x1 <= x <= self.x2

    def __repr__(self):
        return f"Platform({self.x1:.0f}..{self.x2:.0f} @ {self.y:.0f}, {self.key})"


def _run_json(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=2)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def probe_world():
    """The desktop's screens and windows, from whichever compositor this is:
        {"outputs": {name: {"at", "size", "usable", "workspace"}},
         "windows": [{"output", "workspace", "x", "y", "w", "h", "stack",
                      "pid", "key"}]}
    or None when nothing here will say (she keeps to the floor then)."""
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return _probe_hyprland()
    return _probe_synui()


def _probe_synui():
    outs, clients = _run_json(["synctl", "outputs"]), _run_json(["synctl", "clients"])
    if not isinstance(outs, list) or not isinstance(clients, list):
        return None
    outputs = {}
    for o in outs:
        at, size = o.get("at", [0, 0]), o.get("size", [0, 0])
        # `usable` is new in synui 0.1.0-622; older ones leave it out.
        usable = o.get("usable") or [at[0], at[1], size[0], size[1]]
        outputs[o.get("name", "")] = {"at": at, "size": size, "usable": usable,
                                      "workspace": o.get("workspace"),
                                      "focused": bool(o.get("focused"))}
    windows = []
    for c in clients:
        if not c.get("enabled", True) or c.get("minimized") or c.get("fullscreen"):
            continue
        at, size = c.get("at", [0, 0]), c.get("size", [0, 0])
        windows.append({
            "output": c.get("output", ""), "workspace": c.get("workspace"),
            "x": at[0], "y": at[1], "w": size[0], "h": size[1],
            "stack": c.get("stack", 0), "pid": c.get("pid"),
            "key": f"{c.get('pid')}:{c.get('app_id', '')}",
        })
    return {"outputs": outputs, "windows": windows}


def _probe_hyprland():
    mons, clients = (_run_json(["hyprctl", "-j", "monitors"]),
                     _run_json(["hyprctl", "-j", "clients"]))
    if not isinstance(mons, list) or not isinstance(clients, list):
        return None
    outputs, names = {}, {}
    for m in mons:
        scale = m.get("scale") or 1
        x, y = m.get("x", 0), m.get("y", 0)
        w, h = m.get("width", 0) / scale, m.get("height", 0) / scale
        l, t, r, b = (m.get("reserved") or [0, 0, 0, 0])[:4]
        names[m.get("id")] = m.get("name", "")
        outputs[m.get("name", "")] = {
            "at": [x, y], "size": [w, h], "usable": [x + l, y + t, w - l - r, h - t - b],
            "workspace": (m.get("activeWorkspace") or {}).get("id"),
            "focused": bool(m.get("focused")),
        }
    windows = []
    # Hyprland lists no stacking order; focus history is the nearest thing,
    # 0 being the window in front.
    for c in clients:
        if c.get("hidden") or c.get("mapped") is False or c.get("fullscreen"):
            continue
        at, size = c.get("at", [0, 0]), c.get("size", [0, 0])
        windows.append({
            "output": names.get(c.get("monitor"), ""),
            "workspace": (c.get("workspace") or {}).get("id"),
            "x": at[0], "y": at[1], "w": size[0], "h": size[1],
            "stack": -c.get("focusHistoryID", 0), "pid": c.get("pid"),
            "key": c.get("address", ""),
        })
    return {"outputs": outputs, "windows": windows}


def platforms_for(world, output, surface_w, floor, min_w, headroom, own_pid=None):
    """The window tops she can stand on, in the overlay's own coordinates.

    The overlay fills the output's USABLE box (it respects the bars), so a
    window's layout position becomes the overlay's by subtracting the usable
    box's corner. A top edge counts if she fits on it with her head still on
    screen, and only the parts of it that no window in front covers — or she
    would be standing on a line drawn across the middle of another window."""
    if not world or output not in world["outputs"]:
        return []
    out = world["outputs"][output]
    ox, oy = out["usable"][0], out["usable"][1]
    wins = [w for w in world["windows"]
            if w["output"] == output and w["workspace"] == out["workspace"]
            and (own_pid is None or w["pid"] != own_pid)]
    result = []
    for w in wins:
        top = w["y"] - oy
        if top < headroom or top > floor - 10:
            continue
        segs = [(max(0, w["x"] - ox), min(surface_w, w["x"] + w["w"] - ox))]
        for f in wins:
            if f is w or f["stack"] <= w["stack"]:
                continue
            if f["y"] < w["y"] < f["y"] + f["h"]:
                a, b = f["x"] - ox, f["x"] + f["w"] - ox
                segs = [piece for s1, s2 in segs
                        for piece in ((s1, min(s2, a)), (max(s1, b), s2))
                        if piece[1] > piece[0]]
        result.extend(Platform(a, b, top, w["key"]) for a, b in segs if b - a >= min_w)
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  The helper
# ═══════════════════════════════════════════════════════════════════════════

# ChibiRenderer draws around a centre point with fixed pixel offsets, so she is
# drawn onto a canvas big enough for every state (measured over all of them,
# Thoth's floating eye included) and the canvas is scaled.
CANVAS_W, CANVAS_H = 280, 400
CANVAS_CX, CANVAS_CY = 140, 290
# What stands on a surface: just under her body, which bobs down to ~+39. NOT
# her shadow — the window art floats her well above it (+80..+98), which on a
# window's top edge read as hovering a bar's height over it. The shadow still
# draws, faintly, just under the edge.
FEET = CANVAS_CY + 42
HEAD_TOP = CANVAS_CY - 168     # top of her ears
BODY = (54, HEAD_TOP, 226, FEET + 9)   # what a click on her lands on
PAD = 18                       # room to tilt without clipping

ENTRY_W = 340

# CHIBI_BUDDY_DEBUG=1: say where she is four times a second, and when the
# overlay gains or loses the keyboard. On stderr, so in chibi's log.
DEBUG = bool(os.environ.get("CHIBI_BUDDY_DEBUG"))


def run_helper():
    # stdout is the wire. Everything else that prints — Python, GTK, a library
    # that thinks stdout is a terminal — goes to stderr, where chibi's log is.
    wire = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def emit(**msg):
        try:
            wire.write(json.dumps(msg) + "\n")
        except (BrokenPipeError, OSError):
            pass

    # Already loaded by now; children (synctl, hyprctl) do not need it.
    os.environ.pop("LD_PRELOAD", None)
    opts = json.loads(os.environ.get("CHIBI_BUDDY_OPTS") or "{}")

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        gi.require_foreign("cairo")
        from gi.repository import Gtk, Gdk, GLib, Gio, Gtk4LayerShell
        import cairo
    except (ImportError, ValueError) as e:
        emit(ev="error", reason=f"I need GTK 4 and gtk4-layer-shell to go out and play ({e}).")
        return 1
    if not Gtk.init_check():
        emit(ev="error", reason="I couldn't reach the desktop to go out and play.")
        return 1
    if not Gtk4LayerShell.is_supported():
        emit(ev="error", reason="This desktop has no layer-shell, so I can't go out on it.")
        return 1

    import pygame
    pygame.font.init()
    from types import SimpleNamespace
    from config import Config
    from sprite_renderer import ChibiRenderer
    from chat_bubble import ChatBubble

    config = Config()

    class Buddy:
        def __init__(self, app):
            self.app = app
            self.scale = max(0.2, min(2.0, float(opts.get("scale", 0.55))))
            self.climb = bool(opts.get("climb", True))
            self.own_pid = opts.get("pid")
            self.w = CANVAS_W * self.scale                  # her box
            self.h = (FEET - HEAD_TOP) * self.scale

            self.renderer = ChibiRenderer(config)
            self.canvas = pygame.Surface((CANVAS_W, CANVAS_H), pygame.SRCALPHA)
            self.sprite_img = None
            self.bubble = ChatBubble(config)
            self.bubble_img = None
            self.bubble_serial = None
            self.bubble_hide_at = None

            # What chibi is doing, as last told.
            self.state = "IDLE"
            self.state_timer = 0.0
            self.horus = False
            self.speaking = False

            # Where she is and what she is up to. y is her FEET.
            self.x, self.y, self.vy = 0.0, 0.0, 0.0
            self.action = "fall"
            self.gentle = True
            self.support = None
            self.target_x = 0.0
            self.float_to = None
            self.off_edge = False
            self.walk_phase = 0.0
            self.rot = 0.0
            self.squash = 0.0
            self.alpha = 1.0
            self.next_think = time.monotonic() + 2.0

            self.world = None
            self.output = opts.get("output") or ""
            self.output_sure = bool(self.output)
            self.platforms = []
            self.region = None
            self.bubble_rect = None
            self.entry_open = False
            self.drag = None
            self.pet_timer = None
            self.last_tick = time.monotonic()
            self.placed = False

        # ── the window ─────────────────────────────────────────────────────
        def build(self):
            win = Gtk.ApplicationWindow(application=self.app)
            win.add_css_class("chibi-buddy")
            win.set_decorated(False)
            Gtk4LayerShell.init_for_window(win)
            Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.TOP)
            Gtk4LayerShell.set_namespace(win, "chibi-buddy")
            for edge in (Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT,
                         Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM):
                Gtk4LayerShell.set_anchor(win, edge, True)
            # 0, not -1: keep out of the bars' edges, so the bottom of this
            # surface is the floor she walks on.
            Gtk4LayerShell.set_exclusive_zone(win, 0)
            Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.NONE)
            monitor = self._pick_monitor()
            if monitor is not None:
                Gtk4LayerShell.set_monitor(win, monitor)
                self.output = monitor.get_connector() or self.output
                self.output_sure = bool(self.output)

            css = Gtk.CssProvider()
            rules = """
                window.chibi-buddy { background: transparent; }
                entry.chibi-talk {
                    background: rgba(15, 15, 40, 0.94); color: rgb(200, 220, 255);
                    border: 2px solid rgb(0, 255, 255); border-radius: 12px;
                    font-family: monospace; font-size: 13pt; padding: 6px 10px;
                    box-shadow: 0 0 10px rgba(0, 255, 255, 0.35);
                }
            """
            if hasattr(css, "load_from_string"):
                css.load_from_string(rules)
            else:
                css.load_from_data(rules.encode())
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            # ⛔ THE Fixed MUST NOT SIZE THE WINDOW. A Gtk.Fixed asks for enough
            # room to hold its children where they are, so with her feet on
            # the floor it asked for more than the floor — the window grew, the
            # floor moved down with it, and she fell out of sight a screen's
            # height a second. An overlay child is left out of the overlay's
            # measurement, so the window stays the size the compositor gave it.
            overlay = Gtk.Overlay()
            overlay.set_child(Gtk.Box())
            self.fixed = Gtk.Fixed()
            overlay.add_overlay(self.fixed)
            overlay.set_measure_overlay(self.fixed, False)
            win.set_child(overlay)

            self.sprite_da = Gtk.DrawingArea()
            self.sprite_da.set_content_width(math.ceil(self.w) + 2 * PAD)
            self.sprite_da.set_content_height(math.ceil(CANVAS_H * self.scale) + 2 * PAD)
            self.sprite_da.set_draw_func(self._draw_sprite)
            self.sprite_da.set_can_target(False)
            self.fixed.put(self.sprite_da, -1000, -1000)

            self.bubble_da = Gtk.DrawingArea()
            self.bubble_da.set_draw_func(self._draw_bubble)
            self.bubble_da.set_can_target(False)
            self.bubble_da.set_visible(False)
            self.fixed.put(self.bubble_da, 0, 0)

            self.entry = Gtk.Entry()
            self.entry.add_css_class("chibi-talk")
            self.entry.set_placeholder_text("Say something to chibi…")
            self.entry.set_size_request(ENTRY_W, -1)
            self.entry.set_visible(False)
            self.entry.connect("activate", self._on_entry_activate)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._on_entry_key)
            self.entry.add_controller(keys)
            self.fixed.put(self.entry, 0, 0)

            click = Gtk.GestureClick()
            click.set_button(0)
            click.connect("pressed", self._on_press)
            self.fixed.add_controller(click)
            drag = Gtk.GestureDrag()
            drag.set_button(1)
            drag.connect("drag-begin", self._on_drag_begin)
            drag.connect("drag-update", self._on_drag_update)
            drag.connect("drag-end", self._on_drag_end)
            self.fixed.add_controller(drag)

            for name, cb in (("talk", lambda *a: self.open_entry()),
                             ("mic", lambda *a: emit(ev="mic")),
                             ("home", lambda *a: self.go_home()),
                             ("quit", lambda *a: self._quit_chibi())):
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", cb)
                self.app.add_action(action)
            menu = Gio.Menu()
            menu.append("Talk to me", "app.talk")
            menu.append("Microphone on/off", "app.mic")
            menu.append("Go home", "app.home")
            menu.append("Quit chibi", "app.quit")
            self.menu = Gtk.PopoverMenu.new_from_model(menu)
            self.menu.set_parent(self.fixed)
            self.menu.set_has_arrow(False)
            self.menu.connect("closed", self._on_menu_closed)

            # Somebody clicked into another window: the talk box has lost the
            # keyboard, and an open box nobody can type into is just in the way.
            win.connect("notify::is-active", self._on_active)

            self.win = win
            win.present()
            GLib.timeout_add(33, self.tick)
            threading.Thread(target=self._watch_world, daemon=True).start()
            threading.Thread(target=self._read_chibi, daemon=True).start()
            emit(ev="ready")

        def _pick_monitor(self):
            """The screen she goes out on: the configured one, else the one her
            window is on (the compositor knows it by chibi's pid), else
            wherever the compositor puts a new surface."""
            want = self.output
            if not want and self.own_pid and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
                for c in _run_json(["synctl", "clients"]) or []:
                    if c.get("pid") == self.own_pid and c.get("output"):
                        want = c["output"]
                        break
            if not want:
                return None
            monitors = Gdk.Display.get_default().get_monitors()
            for i in range(monitors.get_n_items()):
                m = monitors.get_item(i)
                if m.get_connector() == want:
                    return m
            print(f"[Buddy] no monitor called {want!r}; letting the desktop choose")
            return None

        # ── talking to chibi ───────────────────────────────────────────────
        def _read_chibi(self):
            for line in sys.stdin:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                GLib.idle_add(self._on_msg, msg)
            # chibi has gone, however it went: so does she.
            GLib.idle_add(self.app.quit)

        def _on_msg(self, msg):
            op = msg.get("op")
            if op == "sync":
                if "state" in msg and msg["state"] != self.state:
                    self.state = msg["state"]
                    self.state_timer = 0.0
                    if self.state not in ("IDLE", "HAPPY") and self.action == "walk":
                        self.action = "idle"      # stop and face whoever is talking
                self.horus = msg.get("horus", self.horus)
                self.speaking = msg.get("speaking", self.speaking)
                if "bubble" in msg:
                    serial, text = msg["bubble"]
                    if not text:
                        self.bubble.hide()
                    else:
                        if serial != self.bubble_serial:
                            self.bubble.hide()    # a new line starts from its first letter
                        self.bubble.set_text(text)
                    self.bubble_serial = serial
                    self.bubble_hide_at = None
            elif op == "home":
                self.go_home()
            elif op == "quit":
                self.app.quit()
            elif op == "where":
                # For a test, or anyone debugging: where she is and what she
                # is doing, in the overlay's coordinates.
                emit(ev="where", x=self.x, y=self.y, w=self.w, h=self.h,
                     scale=self.scale, action=self.action, output=self.output,
                     support=repr(self.support), entry_open=self.entry_open,
                     bubble=self.bubble_rect, platforms=len(self.platforms))
            return False

        def _quit_chibi(self):
            emit(ev="quit")
            GLib.timeout_add(1500, lambda: self.app.quit() or False)

        # ── the world ──────────────────────────────────────────────────────
        def _watch_world(self):
            if not self.climb:
                return
            while True:
                world = probe_world()
                if world is None:
                    return          # nothing here says where windows are
                GLib.idle_add(self._on_world, world)
                time.sleep(0.7)

        def _on_world(self, world):
            self.world = world
            self.rebuild_platforms()
            return False

        def rebuild_platforms(self):
            W, H = self.win.get_width(), self.win.get_height()
            if W <= 0 or H <= 0:
                return
            if not self.output_sure:
                # Nobody chose a screen, so the compositor did; ask which. GTK
                # only knows once the surface has entered an output, a moment
                # after it maps — by which time she is already falling — so
                # until then the guess is the focused screen, which is where a
                # compositor puts a surface that names none.
                surface = self.win.get_surface()
                monitor = surface and Gdk.Display.get_default().get_monitor_at_surface(surface)
                if monitor is not None and monitor.get_connector():
                    self.output, self.output_sure = monitor.get_connector(), True
                elif self.world:
                    self.output = next((n for n, o in self.world["outputs"].items()
                                        if o.get("focused")), self.output)
            self.platforms = platforms_for(
                self.world, self.output, W, H, min_w=self.w * 1.3,
                headroom=self.h + 16, own_pid=self.own_pid)
            if self.float_to is not None:
                self.float_to = self._same(self.float_to)
                if self.float_to is None and self.action in ("float", "walk"):
                    self.start_fall()
            if self.support is not None:
                p = self._same(self.support)
                if p is None:
                    self.start_fall()
                    return
                # Ride it: a window dragged across the screen carries her along.
                # Only when it kept its width — an edge that moved because the
                # window was resized, or because another window now covers part
                # of it, has not taken her anywhere.
                if self.action not in ("fall", "held", "float"):
                    old = self.support
                    if abs((p.x2 - p.x1) - (old.x2 - old.x1)) < 1:
                        self.x += p.x1 - old.x1
                    self.y = p.y
                self.support = p
                if not p.holds(self.x + self.w / 2) and self.action not in ("held", "float"):
                    self.start_fall()

        def _same(self, old):
            """The platform `old` has become — same window, nearest edge — or None."""
            best = None
            for p in self.platforms:
                if p.key != old.key:
                    continue
                if best is None or abs(p.y - old.y) + abs(p.x1 - old.x1) < \
                        abs(best.y - old.y) + abs(best.x1 - old.x1):
                    best = p
            return best

        # ── moving ─────────────────────────────────────────────────────────
        def start_fall(self, vy=0.0):
            self.float_to = None
            self.support = None
            self.off_edge = False
            self.vy = vy
            self.action = "fall"

        def start_walk(self, x, off_edge=False):
            lo, hi = self.bounds()
            self.off_edge = off_edge
            self.target_x = x if off_edge else max(lo, min(hi, x))
            self.action = "walk"

        def bounds(self):
            W = self.win.get_width()
            if self.support:
                return self.support.x1, max(self.support.x1, self.support.x2 - self.w)
            return 0.0, max(0.0, W - self.w)

        def landing_below(self, y, H):
            centre = self.x + self.w / 2
            best, where = H, None
            for p in self.platforms:
                if y + 1 < p.y < best and p.holds(centre):
                    best, where = p.y, p
            return best, where

        def think(self):
            roll = random.random()
            lo, hi = self.bounds()
            if self.climb and roll < 0.3:
                spots = []
                for p in self.platforms:
                    if p.y >= self.y - self.h * 0.5:
                        continue
                    a, b = max(lo, p.x1), min(hi, p.x2 - self.w)
                    if b > a:
                        spots.append((p, a, b))
                if spots:
                    p, a, b = random.choice(spots)
                    self.float_to = p
                    self.start_walk(random.uniform(a, b))
                    return
            if roll < 0.45 and self.support:
                # Hop off: walk to an end and keep going — an end with room
                # beside it, or she would step off the side of the screen.
                s, W = self.support, self.win.get_width()
                ends = []
                if s.x1 >= self.w * 0.6:
                    ends.append(s.x1 - self.w * 0.6)
                if s.x2 <= W - self.w * 0.6:
                    ends.append(s.x2 - self.w * 0.4)
                if ends:
                    self.start_walk(random.choice(ends), off_edge=True)
                else:
                    self.start_fall()
            elif roll < 0.85:
                self.start_walk(random.uniform(lo, hi))
            # else: sitting about is also living.

        def may_wander(self):
            return (self.action == "idle" and not self.entry_open
                    and self.state in ("IDLE", "HAPPY") and not self.speaking
                    and not self.bubble.visible and self.drag is None)

        def step(self, dt, W, H):
            s = self.scale / 0.55            # speeds are tuned at the default size
            a = self.action
            if a == "fall":
                self.vy = min(self.vy + 2600 * s * dt, 1800 * s)
                ny = self.y + self.vy * dt
                land_y, where = self.landing_below(self.y, H)
                if ny >= land_y and self.vy >= 0:
                    self.y, self.support, self.vy = land_y, where, 0.0
                    self.action = "idle"
                    self.squash = 0.22
                    self.gentle = False
                else:
                    self.y = ny
            elif a == "walk":
                speed = 75 * s * dt
                dx = self.target_x - self.x
                self.walk_phase += dt * 10
                if abs(dx) <= speed:
                    self.x = self.target_x
                    self.action = "float" if self.float_to else "idle"
                else:
                    self.x += speed if dx > 0 else -speed
                if self.support and not self.support.holds(self.x + self.w / 2):
                    self.start_fall()
            elif a == "float":
                p = self.float_to
                if p is None:
                    self.start_fall()
                else:
                    ny = self.y - 110 * s * dt
                    if ny <= p.y:
                        self.y, self.support, self.float_to = p.y, p, None
                        self.action = "idle"
                        self.squash = 0.12
                    else:
                        self.y = ny
            elif a == "leave":
                self.y -= 260 * s * dt
                self.alpha -= dt * 1.4
                if self.alpha <= 0:
                    emit(ev="home")
                    self.app.quit()
                    return
            if self.action == "idle" and self.support is None:
                self.y = H          # the floor moved (a bar came or went)
            if self.action not in ("leave",) and not self.off_edge:
                self.x = max(0.0, min(W - self.w, self.x))

            # Poses: a waddle while walking, a sway while floating.
            if self.action == "walk":
                target_rot = math.sin(self.walk_phase) * 6
            elif self.action == "float":
                target_rot = math.sin(time.monotonic() * 3) * 3
            elif self.action == "held":
                target_rot = self.rot
            else:
                target_rot = 0.0
            self.rot += (target_rot - self.rot) * min(1.0, dt * 12)
            self.squash = max(0.0, self.squash - dt)

        # ── every frame ────────────────────────────────────────────────────
        def tick(self):
            now = time.monotonic()
            dt = min(0.1, now - self.last_tick)
            self.last_tick = now
            W, H = self.win.get_width(), self.win.get_height()
            if W <= 0 or H <= 0:
                return True
            if not self.placed:
                # Drop in from above the top of the screen, a little way in
                # from the middle.
                self.placed = True
                self.x = W / 2 - self.w / 2 + random.uniform(-W / 6, W / 6)
                self.y = -8.0
                self.rebuild_platforms()

            self.step(dt, W, H)
            if self.may_wander() and now >= self.next_think:
                self.think()
                self.next_think = now + random.uniform(2.5, 7.0)
            elif self.action != "idle":
                self.next_think = max(self.next_think, now + 1.5)

            self.state_timer += dt
            if DEBUG and int(now * 4) != int((now - dt) * 4):
                print(f"[Buddy] at x={self.x:.0f} y={self.y:.0f} w={self.w:.0f} "
                      f"s={self.scale} {self.action} {self.state}", flush=True)
            self._render_sprite()
            self._update_bubble(dt)
            self._place(W, H)
            return True

        def _render_sprite(self):
            self.canvas.fill((0, 0, 0, 0))
            self.renderer.draw(self.canvas, CANVAS_CX, CANVAS_CY,
                               SimpleNamespace(name=self.state), self.state_timer,
                               time.time(), horus_mode=self.horus)
            data = bytearray(pygame.image.tobytes(self.canvas.premul_alpha(), "BGRA"))
            self.sprite_img = cairo.ImageSurface.create_for_data(
                data, cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H, CANVAS_W * 4)
            self.sprite_da.queue_draw()

        def _update_bubble(self, dt):
            b = self.bubble
            b.update(dt)
            # The window keeps its last line up for good; out here it would
            # sit over somebody's work, so it goes once it has been read.
            if b.visible and b.fully_typed and not self.speaking:
                if self.bubble_hide_at is None:
                    self.bubble_hide_at = time.monotonic() + max(4.0, len(b.target_text) / 14)
                elif time.monotonic() >= self.bubble_hide_at:
                    b.visible = False
            elif b.visible:
                self.bubble_hide_at = None

        def _place(self, W, H):
            s = self.scale
            self.fixed.move(self.sprite_da, round(self.x - PAD), round(self.y - FEET * s - PAD))
            rects = []
            bx0, by0, bx1, by1 = BODY
            if self.action != "leave":
                rects.append((self.x + bx0 * s, self.y + (by0 - FEET) * s,
                              (bx1 - bx0) * s, (by1 - by0) * s))

            cx = self.x + self.w / 2
            head = self.y + (HEAD_TOP - FEET) * s
            size = self.bubble.size()
            if size and not self.entry_open:
                bw, bh = size
                left = max(4, min(W - bw - 4, cx - bw / 2))
                top = max(4, head - bh - 2)
                surf = self.bubble.render(tail_dx=cx - (left + bw / 2))
                data = bytearray(pygame.image.tobytes(surf.premul_alpha(), "BGRA"))
                self.bubble_img = cairo.ImageSurface.create_for_data(
                    data, cairo.FORMAT_ARGB32, bw, bh, bw * 4)
                self.bubble_da.set_content_width(bw)
                self.bubble_da.set_content_height(bh)
                self.fixed.move(self.bubble_da, round(left), round(top))
                self.bubble_da.set_visible(True)
                self.bubble_da.queue_draw()
                rects.append((left, top, bw, bh))
                self.bubble_rect = (left, top, bw, bh)
            else:
                self.bubble_da.set_visible(False)
                self.bubble_rect = None

            if self.entry_open:
                ew = ENTRY_W
                eh = max(36, self.entry.get_height())
                left = max(4, min(W - ew - 4, cx - ew / 2))
                top = max(4, head - eh - 10)
                self.fixed.move(self.entry, round(left), round(top))
                rects.append((left, top, ew, eh))

            region = tuple((round(x), round(y), max(1, round(w)), max(1, round(h)))
                           for x, y, w, h in rects)
            if region != self.region:
                surface = self.win.get_surface()
                if surface is not None:
                    surface.set_input_region(cairo.Region(
                        [cairo.RectangleInt(*r) for r in region]))
                    self.region = region

        def _draw_sprite(self, area, cr, width, height):
            img = self.sprite_img
            if img is None:
                return
            s = self.scale
            bob = -abs(math.sin(self.walk_phase)) * 4 if self.action == "walk" else 0
            sq = math.sin(math.pi * self.squash / 0.22) * 0.14 if self.squash > 0 else 0
            cr.translate(PAD + self.w / 2, PAD + FEET * s + bob)
            cr.rotate(math.radians(self.rot))
            cr.scale(1 + sq * 0.7, 1 - sq)
            cr.translate(-CANVAS_CX * s, -FEET * s)
            cr.scale(s, s)
            cr.set_source_surface(img, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint_with_alpha(max(0.0, min(1.0, self.alpha)))

        def _draw_bubble(self, area, cr, width, height):
            if self.bubble_img is not None:
                cr.set_source_surface(self.bubble_img, 0, 0)
                cr.paint()

        # ── the pointer ────────────────────────────────────────────────────
        def _on_her(self, x, y):
            if self.action == "leave":
                return False
            s = self.scale
            bx0, by0, bx1, by1 = BODY
            return (self.x + bx0 * s <= x <= self.x + bx1 * s
                    and self.y + (by0 - FEET) * s <= y <= self.y + (by1 - FEET) * s)

        def _on_press(self, gesture, n_press, x, y):
            button = gesture.get_current_button()
            if self.bubble_rect and button == 1:
                bx, by, bw, bh = self.bubble_rect
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    self.bubble.visible = False     # read it; click it away
                    return
            if not self._on_her(x, y):
                return
            if self.entry_open and button == 1 and n_press == 1:
                self.close_entry()          # changed her mind
                return
            if button == 3:
                rect = Gdk.Rectangle()
                rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
                self.menu.set_pointing_to(rect)
                # Keys (arrows, Enter, Escape) reach a menu through whatever
                # surface holds the keyboard when it opens — a popup's grab
                # moves no focus and ignores focus changes while it lasts. This
                # surface asks for no keyboard at all, so take it first and
                # open the menu once that has landed; the menu's closing hands
                # it back.
                Gtk4LayerShell.set_keyboard_mode(
                    self.win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
                GLib.timeout_add(80, lambda: self.menu.popup() or False)
            elif button == 1 and n_press == 2:
                self._cancel_pet()
                self.open_entry()
            elif button == 1 and n_press == 1:
                self._cancel_pet()
                self.pet_timer = GLib.timeout_add(260, self._pet)

        def _on_menu_closed(self, menu):
            if not self.entry_open:
                Gtk4LayerShell.set_keyboard_mode(self.win, Gtk4LayerShell.KeyboardMode.NONE)

        def _cancel_pet(self):
            if self.pet_timer is not None:
                GLib.source_remove(self.pet_timer)
                self.pet_timer = None

        def _pet(self):
            self.pet_timer = None
            emit(ev="pet")
            if self.action in ("idle", "walk"):
                self.start_fall(vy=-520 * self.scale / 0.55)     # a happy little hop
            return False

        def _on_drag_begin(self, gesture, x, y):
            self.drag = None
            if self._on_her(x, y):
                self.drag = {"sx": x, "sy": y, "gx": x - self.x, "gy": y - self.y,
                             "moving": False, "lx": x}

        def _on_drag_update(self, gesture, dx, dy):
            d = self.drag
            if d is None:
                return
            if not d["moving"]:
                if abs(dx) < 8 and abs(dy) < 8:
                    return
                d["moving"] = True
                self._cancel_pet()
                self.action = "held"
                self.support = self.float_to = None
                self.off_edge = False
            W, H = self.win.get_width(), self.win.get_height()
            px, py = d["sx"] + dx, d["sy"] + dy
            self.x = max(0.0, min(W - self.w, px - d["gx"]))
            self.y = max(self.h, min(float(H), py - d["gy"]))
            # Dangle: lean away from the way she is being carried.
            self.rot = max(-18.0, min(18.0, (d["lx"] - px) * 0.9 + self.rot * 0.6))
            d["lx"] = px

        def _on_drag_end(self, gesture, dx, dy):
            d, self.drag = self.drag, None
            if d and d["moving"]:
                # A small lift, so a drop aimed at a window's top edge lands on
                # it instead of slipping just past.
                self.y -= 6
                self.start_fall()

        # ── talking ────────────────────────────────────────────────────────
        def open_entry(self):
            if self.entry_open:
                return
            self.entry_open = True
            if self.action == "walk":
                self.action = "idle"
            self.bubble.visible = False
            self.entry.set_text("")
            self.entry.set_visible(True)
            # Exclusive while it is open, so what is typed reaches it without
            # a click first; handed straight back when it closes.
            Gtk4LayerShell.set_keyboard_mode(self.win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
            self.entry.grab_focus()
            emit(ev="talking", on=True)

        def close_entry(self):
            if not self.entry_open:
                return
            self.entry_open = False
            self.entry.set_visible(False)
            Gtk4LayerShell.set_keyboard_mode(self.win, Gtk4LayerShell.KeyboardMode.NONE)
            emit(ev="talking", on=False)

        def _on_active(self, win, _pspec):
            if DEBUG:
                print(f"[Buddy] is-active {win.is_active()}", flush=True)
            if self.entry_open and not win.is_active():
                self.close_entry()

        def _on_entry_activate(self, entry):
            text = entry.get_text().strip()
            self.close_entry()
            if text:
                emit(ev="talk", text=text)

        def _on_entry_key(self, ctrl, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                self.close_entry()
                return True
            return False

        def go_home(self):
            self.close_entry()
            self.menu.popdown()
            self.bubble.visible = False
            self.support = self.float_to = None
            self.action = "leave"

    app = Gtk.Application(application_id="io.github.velle999.chibi.buddy",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    buddy = Buddy(app)
    app.connect("activate", lambda a: buddy.build())
    return app.run([])


if __name__ == "__main__":
    sys.exit(run_helper())
