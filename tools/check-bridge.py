#!/usr/bin/env python3
"""Check which of synsh's intents chibi takes, and how it hands them over.

  1. ONLY THE LAUNCHERS. synsh names the intent that claims a line; chibi takes
     "music" and "youtube" and leaves every text answer ("where am i", "disk
     space", "what time is it") to its own model.

  2. THE LINE SYNSH IS ASKED ABOUT has the address and the manners taken off
     ("Chibi, play some music please." -> "play some music") when vibe is
     installed to do it.

  3. `?` AND `!` KEEP THEIR MEANING, and an older synsh that does not know
     --intent-name reads as "not mine" rather than as an error.

  4. RUN WITHOUT A TTY and without synapd: `synsh -c LINE --intent --no-ai`,
     stdin not a terminal, so a player like cliamp gets a window of its own.

A stub synsh stands in for the real one, so nothing is launched.
Run from the repo root:  tools/check-bridge.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

fails = 0


def check(desc, ok, detail=""):
    global fails
    if ok:
        print(f"  ok    {desc}")
    else:
        fails += 1
        print(f"  FAIL  {desc}{(' — ' + detail) if detail else ''}")


STUB = r"""#!/usr/bin/env python3
import os, sys
log = os.environ["BRIDGE_LOG"]
if sys.argv[1:2] == ["--intent-name"]:
    if os.environ.get("BRIDGE_OLD_SYNSH"):
        sys.exit(1)                     # getopt: unrecognized option
    names = {"play some music": "music", "play music": "music",
             "open youtube": "youtube", "where am i": "command",
             "what time is it": "time", "disk space": "command"}
    with open(log, "a") as f:
        f.write("name " + sys.argv[2] + "\n")
    n = names.get(sys.argv[2])
    if n:
        print(n)
    sys.exit(0 if n else 70)
with open(log, "a") as f:
    f.write("run " + " ".join(sys.argv[1:]) + " tty=" + str(os.isatty(0)) + "\n")
print("  opening https://www.youtube.com")
"""

tmp = tempfile.mkdtemp()
try:
    stub = os.path.join(tmp, "synsh")
    with open(stub, "w") as f:
        f.write(STUB)
    os.chmod(stub, 0o755)
    log = os.path.join(tmp, "log")
    os.environ["BRIDGE_LOG"] = log
    os.environ["PATH"] = tmp + os.pathsep + os.environ.get("PATH", "")

    import assistant_bridge as b

    def kind(line):
        h = b.match(line)
        return "synsh" if isinstance(h, b.SynshIntent) else ("vibe" if h else None)

    print("only the launchers")
    check("play music is taken", kind("play music") == "synsh")
    check("open youtube is taken", kind("open youtube") == "synsh")
    for line in ("where am i", "what time is it", "disk space"):
        check(f"{line!r} is left to the model", kind(line) is None)
    check("a line synsh does not claim is left alone", kind("tell me a story") is None)

    print("the line synsh is asked about")
    b._load()
    if b._intents is not None:
        h = b.match("Chibi, play some music please.")
        check("address and manners come off",
              isinstance(h, b.SynshIntent) and h.line == "play some music",
              repr(h))
    else:
        print("  skip  vibe is not installed, so nothing strips the address")

    print("prefixes and an older synsh")
    open(log, "w").close()
    check("?open youtube goes to the model", kind("?open youtube") is None)
    check("!play music is a command", kind("!play music") is None)
    check("  ...and synsh is not even asked", open(log).read() == "")
    os.environ["BRIDGE_OLD_SYNSH"] = "1"
    check("no --intent-name reads as not mine", kind("play music") is None)
    del os.environ["BRIDGE_OLD_SYNSH"]

    print("running it")
    open(log, "w").close()
    said = b.run(b.SynshIntent("open youtube"))
    ran = open(log).read().strip()
    check("synsh -c with --intent --no-ai",
          ran.startswith("run -c open youtube --intent --no-ai"), ran)
    check("stdin is not a tty", ran.endswith("tty=False"), ran)
    check("what synsh said comes back trimmed",
          said == "opening https://www.youtube.com", repr(said))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("all bridge checks passed" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
