#!/usr/bin/env python3
"""Check the settings panel's seam: what it saves, and what it makes real.

The gear in the window writes a person's name and city into
config.local.py. Two things there can go wrong quietly, and both are worse
than the panel not existing:

  1. IT CAN EAT THE FILE. config.local.py is where an API key, an LLM host
     and a dream-sync token live, and it is hand-edited. A panel that wrote
     its own three fields over the whole file would delete the rest the
     first time somebody changed their city — and nothing would say so
     until the next start, in a feature that stopped working for no visible
     reason.

  2. IT CAN SET A NAME NOBODY IS CALLED. Config substitutes {user_name}
     into the prompts at load, which CONSUMES the placeholder. Setting
     user_name afterwards renames the person everywhere except in the
     prompts Chibi actually speaks from, which is the only place the name
     was for.

Run from the repo root:  tools/check-settings.py
"""
import os
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


home = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = home

from config import Config          # noqa: E402  (after XDG_CONFIG_HOME is set)

print("chibi settings panel")

cfg = Config()
path = Config.user_config_path()
check("the panel writes under XDG, never the app dir",
      path.startswith(home) and path.endswith("chibi/config.local.py"), path)

# ── 1. the hand-edited file survives ──────────────────────────────────
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as fh:
    fh.write('# a comment somebody wrote\n'
             'weather_api_key = "secret-key"\n'
             'llm_host = "http://box:11434"\n'
             'weather_city = "Old Town"\n')

cfg.save_local({"weather_city": "New Town"})
body = open(path, encoding="utf-8").read()
check("...and a save keeps the settings it does not know about",
      'weather_api_key = "secret-key"' in body and 'llm_host = "http://box:11434"' in body)
check("...and the comment", "# a comment somebody wrote" in body)
check("...and rewrites the one it does know, in place",
      body.count("weather_city") == 1 and "New Town" in body and "Old Town" not in body)

# ── 2. what is written is still Python ────────────────────────────────
#
# The file is EXECUTED at startup. An apostrophe in a city or a name is
# ordinary text a person types, and a syntax error here takes every setting
# in the file down with it, not just the one that was typed.
cfg.save_local({"user_name": "O'Brien", "weather_city": 'He said "hi"'})
ns = {}
exec(open(path, encoding="utf-8").read(), ns)          # noqa: S102
check("a name with an apostrophe reloads", ns.get("user_name") == "O'Brien",
      repr(ns.get("user_name")))
check("...and a city with quotes in it", ns.get("weather_city") == 'He said "hi"')
check("...and the untouched settings are still there",
      ns.get("weather_api_key") == "secret-key")

# ── 3. a new name reaches the prompts ─────────────────────────────────
fresh = Config()
fresh.apply_user_name("Ada")
check("the name reaches the system prompt", "Ada" in fresh.llm_system_prompt)
check("...and the placeholder is gone", "{user_name}" not in fresh.llm_system_prompt)
fresh.apply_user_name("Grace")
check("...and again, from the template rather than the last name",
      "Grace" in fresh.llm_system_prompt and "Ada" not in fresh.llm_system_prompt)
check("...in every prompt that carries it",
      all("Ada" not in str(getattr(fresh, a, "")) for a in Config.PERSONALIZED_PROMPTS))

# ── 4. the switch the weather thread reads is a real field ────────────
#
# data_feeds asks for news_enabled with getattr(..., True), which answers
# True on a Config that has no such attribute — so a panel row bound to it
# would read as On and write to nothing.
for attr in ("weather_enabled", "weather_city", "user_name", "news_enabled"):
    check(f"{attr} is a declared field", hasattr(Config(), attr))

# ── 5. the keys that drive it ─────────────────────────────────────────
#
# Driven against the real handler with a stand-in for the app, because what
# it does is a state machine and every one of its states is one keystroke
# from another: Enter opens a field, Escape while typing throws the typing
# away, Escape again closes the panel. Getting the last two the wrong way
# round means Escape closes the window mid-edit.
import types                                             # noqa: E402
import pygame                                            # noqa: E402
import main as chibi_main                                # noqa: E402


class FakeFeeds:
    def __init__(self):
        self.refreshed = 0

    def refresh_weather(self):
        self.refreshed += 1


app = types.SimpleNamespace(
    config=Config(), feeds=FakeFeeds(),
    _settings_index=0, _settings_editing=False, _settings_draft="",
    _settings_saved_at=0.0, _settings_error="", settings_open=True,
    SETTINGS_ROWS=chibi_main.ChibiAvatarApp.SETTINGS_ROWS,
)
for name in ("_settings_value", "_settings_apply", "_handle_settings_key"):
    setattr(app, name, getattr(chibi_main.ChibiAvatarApp, name).__get__(app))


def key(k, unicode=""):
    app._handle_settings_key(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode))


key(pygame.K_RETURN)
check("Enter on a text row starts editing", app._settings_editing)
check("...prefilled with what is set now", app._settings_draft == app.config.user_name)

app._settings_draft = ""
for ch in "Ada":
    key(0, ch)
key(pygame.K_ESCAPE)
check("Escape while typing throws the typing away, and does NOT close",
      not app._settings_editing and app.settings_open and app.config.user_name != "Ada")

key(pygame.K_RETURN)
app._settings_draft = "Ada"
key(pygame.K_RETURN)
check("Enter commits", app.config.user_name == "Ada" and not app._settings_editing)
check("...and it reached the prompt", "Ada" in app.config.llm_system_prompt)

key(pygame.K_DOWN)
key(pygame.K_RETURN)
app._settings_draft = "Reykjavik"
key(pygame.K_RETURN)
check("a new city is set", app.config.weather_city == "Reykjavik")
check("...and the weather is asked for again, not in ten minutes",
      app.feeds.refreshed >= 1)

key(pygame.K_DOWN)
was = bool(app.config.weather_enabled)
key(pygame.K_RETURN)
check("the switch toggles", bool(app.config.weather_enabled) is not was)

key(pygame.K_ESCAPE)
check("Escape closes the panel when not typing", not app.settings_open)

print()
if fails:
    print(f"{fails} failed")
else:
    print("all settings checks passed")
sys.exit(1 if fails else 0)
