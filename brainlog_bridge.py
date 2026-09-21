"""Bridge to brainlog — the memory archive this machine keeps.

⛔ ONE OWNER OF THE ARCHIVE, AND IT IS NOT CHIBI. brainlog decides how an
entry is stored, which prompt was posed, what gets lifted into the roster and
where any of it lives. Chibi's job is the part chibi is good at: asking out
loud and hearing the answer. So this talks to the INSTALLED `brainlog` command
rather than importing its modules or writing its files — the mirror of
assistant_bridge, which asks vibe rather than reimplementing its tool policy.

⚠ A machine without brainlog simply has no daily question, which is the right
answer rather than an error: the Pi may not carry the archive.

⛔ NOTHING HERE MAY BLOCK THE MAIN LOOP. Generating the question runs a model
and takes seconds; filing an answer enriches it and takes longer. Both happen
on daemon threads, and update() only ever reads a flag. A subprocess call on
the frame path would freeze the sprite mid-animation.
"""

import os
import json
import shutil
import datetime
import threading
import subprocess

# Where we remember having asked, so a restart in the evening does not ask
# twice and a crash does not lose the day.
STATE = os.path.expanduser("~/.chibi-brainlog.json")

_lock = threading.Lock()
_question = None          # the question waiting to be asked, once fetched
_fetching = False


def available():
    """Is brainlog installed and usable from here?"""
    return shutil.which("brainlog") is not None


def _load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(d):
    tmp = STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, STATE)
    except OSError:
        pass


def asked_today():
    return _load_state().get("asked") == datetime.date.today().isoformat()


def mark_asked():
    st = _load_state()
    st["asked"] = datetime.date.today().isoformat()
    _save_state(st)


def unmark_asked():
    """Put today's question back on the table.

    Called when a question was asked and nothing answered it. Without this a
    question spoken into a room where the person had headphones on, or had
    stepped out, or simply did not feel like talking, is gone for the day —
    and the day is the whole unit here.
    """
    st = _load_state()
    st.pop("asked", None)
    _save_state(st)


def due(hour, minute=0):
    """Is it time, and has today's question not been asked yet?

    Deliberately "at or after" rather than "at": chibi is not always running at
    the stroke of the hour, and a question that only fires in a one-minute
    window is a question that mostly never fires.
    """
    if not available() or asked_today():
        return False
    now = datetime.datetime.now()
    return (now.hour, now.minute) >= (hour, minute)


def _fetch(roster=False):
    global _question, _fetching
    try:
        cmd = ["brainlog", "ask", "--pose", "--quiet"]
        if roster:
            cmd.append("--roster")
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        q = (out.stdout or "").strip().split("\n")[-1].strip()
        with _lock:
            _question = q or None
    except (OSError, subprocess.SubprocessError):
        with _lock:
            _question = None
    finally:
        with _lock:
            _fetching = False


def request_question(roster=False):
    """Start fetching today's question. Returns immediately."""
    global _fetching
    with _lock:
        if _fetching or _question is not None:
            return
        _fetching = True
    threading.Thread(target=_fetch, args=(roster,), daemon=True).start()


def take_question():
    """The fetched question, once, or None if it is not ready.

    Taken rather than read: the caller is about to speak it, and leaving it set
    would have chibi ask the same thing again on the next frame.
    """
    global _question
    with _lock:
        q, _question = _question, None
    return q


def file_answer(text, roster=False, on_done=None):
    """Hand an answer to brainlog. Off-thread; `on_done(ok, title)` if given."""
    if not text or not text.strip():
        return

    def _run():
        ok, title = False, ""
        try:
            cmd = ["brainlog", "answer", "--source", "chibi", "--quiet"]
            if roster:
                cmd.append("--roster")
            r = subprocess.run(cmd + [text], capture_output=True, text=True,
                               timeout=300)
            ok = r.returncode == 0
            title = (r.stdout or "").strip().split("\n")[0]
        except (OSError, subprocess.SubprocessError):
            ok = False
        if on_done:
            try:
                on_done(ok, title)
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
