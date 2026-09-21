"""
How long a reply should be, judged from what was asked.

Chibi's default is a line or two, and that stays right for chat. Some requests
are answered badly by a line or two: "tell me a story" came back as a single
sentence, and "what's in the news" as one headline. The system prompt said
1-2 sentences, and the token cap (llm_num_predict) was sized to match.

Telling the model "be longer when it fits" in the prompt alone doesn't work.
Small models don't follow length instructions well, and the cap would still
clip the answer. So the request picks both the budget and a note in the prompt
that says which kind of answer is wanted:

    chat     1-2 sentences                       llm_num_predict
    explain  a short paragraph, a few steps      llm_num_predict_explain
    news     a rundown of several headlines      llm_num_predict_explain
    story    the whole piece                     llm_num_predict_long

Kinds are matched by pattern, with no model call, because this runs on the
path to the first spoken word. A request that matches nothing is chat, so a
missed pattern gives the old behaviour.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplyShape:
    kind: str           # "chat" | "explain" | "news" | "story"
    tokens: int         # num_predict for this reply
    guidance: str       # appended to the system prompt; "" for plain chat


# Things that are told whole: a story, a poem, a song.
_PIECE = (r"(?:stor(?:y|ies)|tales?|fables?|fairy ?tales?|legends?|myths?|"
          r"poems?|poetry|sonnets?|ballads?|songs?|lyrics|raps?|limericks?|"
          r"haikus?|monologues?|essays?|scripts?|adventures?|jokes?)")
_STORY = re.compile(
    # A verb asking for one, a few words before the noun: "tell me a story",
    # "write a poem about rain", "can you make up a song for Mochi". The gap
    # is capped so "give me your honest opinion of that song" doesn't count.
    r"\b(?:tell|read|make up|write|compose|sing|recite|narrate|invent|spin|"
    r"give|share)\b(?:\W+\w+){0,4}?\W+" + _PIECE + r"\b"
    # Or it names the form outright.
    r"|\bonce upon a time\b|\bbedtime\b",
    re.IGNORECASE)
# A joke is a piece but a short one; "tell me a joke" is chat-length.
_JOKE_ONLY = re.compile(r"\bjokes?\b", re.IGNORECASE)

_NEWS = re.compile(
    r"\bheadlines?\b"
    r"|^\W*news\b"
    # "what's in the news", "any news today", "catch me up on the news" — but
    # not "the good news is I got the job".
    r"|\b(?:what'?s|what is|anything|any|tell me|give me|read me|catch me up"
    r"|today'?s|latest|top)\s+(?:\w+\s+){0,2}news\b"
    r"|\bcurrent events\b|\bwhat'?s (?:happening|going on) in the world\b",
    re.IGNORECASE)

_EXPLAIN = re.compile(
    r"\b(?:explain|why|how come|how (?:do|does|did|can|could|would|should"
    r"|to)|tell me (?:about|more)|more about|describe|what happened"
    r"|history of|summari[sz]e|recap|compare|difference between"
    r"|pros and cons|recipe|instructions|steps|teach me|walk me through"
    r"|elaborate|details?|in depth)\b",
    re.IGNORECASE)

# Asked-for size, which moves the answer a size up or down.
_SHORTER = re.compile(
    r"\b(?:short|quick|brief|briefly|one[- ]sentence|one[- ]line|in a sentence"
    r"|in a nutshell|tl;?dr|summary)\b", re.IGNORECASE)
_LONGER = re.compile(
    r"\b(?:long|longer|detailed|in detail|in depth|epic|full|whole"
    r"|everything|all about|step by step|walk me through)\b", re.IGNORECASE)

# A short follow-up that carries on from the last answer: "another one",
# "keep going", "what happens next". Only counts when the message is short,
# so a new question that happens to contain "more" is judged on its own.
_CONTINUE = re.compile(
    r"\b(?:another|again|more|continue|keep going|go on|carry on|and then"
    r"|what happen(?:s|ed) next|next part|part two|finish it)\b",
    re.IGNORECASE)
_CONTINUE_MAX_WORDS = 8


def _kind_of(text: str) -> str:
    if _STORY.search(text):
        # "tell me a joke" matches the piece verb; a joke alone stays short.
        nouns = re.findall(r"\b" + _PIECE + r"\b", text, re.IGNORECASE)
        if nouns and all(_JOKE_ONLY.fullmatch(n) for n in nouns):
            return "chat"
        return "story"
    if _NEWS.search(text):
        return "news"
    if _EXPLAIN.search(text):
        return "explain"
    return "chat"


def _guidance(kind: str, sized: str, user: str) -> str:
    if kind == "story":
        if sized == "shorter":
            body = (f"{user} asked for a short piece. Keep it to one short "
                    "paragraph, or a few lines of verse, and make it complete: "
                    "a story still needs a beginning, a middle and an ending.")
        else:
            body = (f"{user} asked for a story, poem or song. Give the whole "
                    "piece. A story needs a beginning, a middle and an "
                    "ending, and a poem or song needs all its verses. Aim for "
                    "about 200-400 words, fewer if the form is short (a haiku "
                    "or limerick). The 1-2 sentence rule does not apply to "
                    "this reply. Don't ask whether they want it, and don't "
                    "summarise it afterwards: tell it and stop.")
    elif kind == "news":
        body = ("Give a quick rundown of the news: 4-6 of the headlines in "
                "the NEWS HEADLINES data, one short line each, in your own "
                "words. Leave out sources and links. If no headlines are "
                "available, say you can't see the news right now. Never "
                "invent a headline.")
    elif kind == "explain":
        if sized == "longer":
            body = ("This needs a full answer: a few short paragraphs, or "
                    "numbered steps if it's a how-to. Include what matters "
                    "and leave out filler.")
        else:
            body = ("This needs more than a one-liner: answer in a short "
                    "paragraph, or a few steps or items if that's clearer. "
                    "About 3-6 sentences, only as many as the question needs.")
    else:
        return ""
    return "\n\n[REPLY LENGTH]\n" + body


def shape_for(text: str, config, previous: str = "chat") -> ReplyShape:
    """The shape of the reply to `text`.

    `previous` is the kind of the last reply, so "another one" after a story
    gets another story instead of a one-liner.
    """
    text = text or ""
    kind = _kind_of(text)
    if (kind == "chat" and previous != "chat"
            and len(text.split()) <= _CONTINUE_MAX_WORDS
            and _CONTINUE.search(text)):
        kind = previous

    sized = ""
    if _SHORTER.search(text):
        sized = "shorter"
    elif _LONGER.search(text):
        sized = "longer"

    budgets = {
        "chat": getattr(config, "llm_num_predict", 110),
        "explain": getattr(config, "llm_num_predict_explain", 300),
        "story": getattr(config, "llm_num_predict_long", 600),
    }
    size = "explain" if kind == "news" else kind
    # "a short story" is paragraph-sized and "explain in detail" is a long
    # answer. A short explanation keeps the explain budget, because the model
    # decides how brief to be within it; clipping it would only cut the end.
    if sized == "shorter" and size == "story":
        size = "explain"
    elif sized == "longer" and size == "explain" and kind != "news":
        size = "story"

    user = getattr(config, "user_name", "") or "the user"
    return ReplyShape(kind=kind, tokens=int(budgets[size]),
                      guidance=_guidance(kind, sized, user))
