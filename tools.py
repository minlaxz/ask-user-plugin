"""ask_user tool handler — OpenAI Responses format.

The form the model builds is delivered IN-BAND: it appears as the `function_call`
item's `arguments` in the response your frontend reads. So this handler does NOT
deliver anything out-of-band. It only:

  1. validates the form the model produced (so a malformed form can be retried), and
  2. returns a terminal sentinel that ends the turn.

It also carries the turn guard (issue #1): the sentinel is a string handed to
the model, so the model may ignore it, and a second ask_user in the same turn
strands the first form. `guard_pre_tool_call` makes one form per turn a rule
rather than a request.

Hermes tool contract (per the Adding Tools docs):
  * handlers return a JSON string (never a raw dict)
  * errors are returned as {"error": "..."} (never raised)
  * handler signature is (args: dict, **kwargs)
"""

import json
import logging
from collections import deque

logger = logging.getLogger("ask_user_form")

_VALID_TYPES = {"text", "textarea", "number", "boolean", "select", "multiselect"}
_CHOICE_TYPES = {"select", "multiselect"}

_STOP_INSTRUCTION = (
    "The form has been presented to the user. STOP NOW: end your turn and output "
    "nothing further. Do NOT guess or fabricate the user's answers. The "
    "conversation resumes automatically when the user submits the form."
)


def _validate_form(args):
    """Return a list of human-readable problems with the form (empty list = valid)."""
    fields = args.get("fields")
    if not isinstance(fields, list) or not fields:
        return ["'fields' must be a non-empty array"]

    errors, seen = [], set()
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            errors.append(f"field[{i}] is not an object")
            continue
        key = f.get("key")
        ftype = f.get("type", "text")
        if not key:
            errors.append(f"field[{i}] is missing 'key'")
        elif key in seen:
            errors.append(f"duplicate field key: {key}")
        else:
            seen.add(key)
        if ftype not in _VALID_TYPES:
            errors.append(f"field '{key}' has invalid type '{ftype}'")
        if ftype in _CHOICE_TYPES and not f.get("options"):
            errors.append(f"field '{key}' is type '{ftype}' but has no options")
    return errors


def handle_ask_user(args, **kwargs):
    args = args or {}

    errors = _validate_form(args)
    if errors:
        # Actionable error so the model can fix the form and call ask_user again.
        return json.dumps({"error": "invalid form: " + "; ".join(errors)})

    logger.info("ask_user presented: %s", args.get("title") or args.get("message") or "(form)")

    # Terminal sentinel. This is the tool RESULT (the function_call_output). It
    # carries no answer data — its only job is to end the turn. The frontend does
    # not need to read it; it renders from the function_call's `arguments`.
    return json.dumps({"status": "awaiting_user_input", "instruction": _STOP_INSTRUCTION})


# --- Turn guard (issue #1) ---------------------------------------------------
#
# `_STOP_INSTRUCTION` above is prose the model may ignore, and on a Sessions
# deployment it does: the run keeps going after the sentinel comes back, so the
# model gets another chance to call tools. When it spends that chance on a
# second ask_user, the first form is stranded — a frontend keeps only the newest
# unanswered form answerable, so form one locks having never been answerable
# once. This turns "please stop" into a block Hermes enforces.

ASK_USER = "ask_user"

# The meta-tool the model reaches ask_user through when it does not call it
# directly: tool_search -> tool_describe -> tool_call{"name": "ask_user"}. Same
# call, second spelling, and the guard has to count both.
ENVELOPE = "tool_call"

_BLOCK_MESSAGE = (
    "A form is already pending for this turn. STOP NOW: end your turn and output "
    "nothing further. Do NOT ask again and do NOT guess or fabricate the user's "
    "answers. The conversation resumes automatically when the user submits the form."
)

# Turns that have already raised a form. A turn_id matters only while its turn
# runs, and turns are seconds long, so the last few hundred is memory enough.
# ponytail: a plain ring, not a TTL cache — revisit only if a deployment ever
# runs more than _GUARD_MEMORY turns at once, at which point the oldest entry
# expires early and that turn merely loses the guard, never gains a false block.
_GUARD_MEMORY = 256
_asked_this_turn = deque(maxlen=_GUARD_MEMORY)


def _is_ask_user(tool_name, args):
    """True if this call raises a form, under either spelling."""
    if tool_name == ASK_USER:
        return True
    if tool_name != ENVELOPE:
        return False
    return isinstance(args, dict) and args.get("name") == ASK_USER


def guard_pre_tool_call(tool_name, args=None, turn_id=None, **kwargs):
    """pre_tool_call hook — one form per turn, and nothing after it.

    Returns Hermes' block directive ({"action": "block", "message": str}) for any
    tool call that follows an ask_user in the same turn, and None otherwise.

    Scoped on turn_id. Without one there is nothing safe to scope on: session_id
    would block every form after the very first one for the life of the session,
    so the guard stands down instead and the sentinel is back to being the only
    thing asking the model to stop.
    """
    if not turn_id:
        return None
    if turn_id in _asked_this_turn:
        logger.info("ask_user guard: blocked %r after a form was raised this turn", tool_name)
        return {"action": "block", "message": _BLOCK_MESSAGE}
    if _is_ask_user(tool_name, args):
        _asked_this_turn.append(turn_id)
    return None


if __name__ == "__main__":
    # Self-check for the guard's logic — pure stdlib, no Hermes needed:
    #   python3 tools.py
    def _reset():
        _asked_this_turn.clear()

    blocked = lambda d: d is not None and d.get("action") == "block"

    _reset()
    assert guard_pre_tool_call(ASK_USER, {"fields": [{"key": "a"}]}, turn_id="t1") is None
    assert blocked(guard_pre_tool_call(ASK_USER, {}, turn_id="t1")), "second form must be blocked"

    _reset()
    envelope = {"name": ASK_USER, "arguments": {"fields": [{"key": "a"}]}}
    assert guard_pre_tool_call(ENVELOPE, envelope, turn_id="t1") is None
    assert blocked(guard_pre_tool_call(ENVELOPE, envelope, turn_id="t1")), "envelope spelling must count"

    _reset()
    assert guard_pre_tool_call(ASK_USER, {}, turn_id="t1") is None
    assert blocked(guard_pre_tool_call("terminal", {"command": "ls"}, turn_id="t1")), "nothing runs after a form"

    _reset()
    assert guard_pre_tool_call(ASK_USER, {}, turn_id="t1") is None
    assert guard_pre_tool_call(ASK_USER, {}, turn_id="t2") is None, "a later turn gets its own form"

    _reset()
    assert guard_pre_tool_call("tool_search", {"query": "ask user"}, turn_id="t1") is None
    assert guard_pre_tool_call(ENVELOPE, {"name": "get_weather"}, turn_id="t1") is None
    assert guard_pre_tool_call(ASK_USER, {}, turn_id="t1") is None, "only a form arms the guard"
    assert blocked(guard_pre_tool_call(ASK_USER, {}, turn_id="t1"))

    _reset()
    assert guard_pre_tool_call(ASK_USER, {}, turn_id=None) is None
    assert guard_pre_tool_call(ASK_USER, {}, turn_id="") is None
    assert guard_pre_tool_call(ASK_USER, {}, turn_id=None) is None, "no turn_id, no guard, no false block"

    _reset()
    guard_pre_tool_call(ASK_USER, {}, turn_id="t1")
    # Hermes drops a block whose message is empty
    assert guard_pre_tool_call(ASK_USER, {}, turn_id="t1")["message"], "block needs a non-empty message"

    # the handler itself still holds up
    assert json.loads(handle_ask_user({"fields": []}))["error"].startswith("invalid form")
    assert json.loads(handle_ask_user({"fields": [{"key": "a", "type": "select"}]}))["error"]
    ok = json.loads(handle_ask_user({"fields": [{"key": "a", "label": "A"}]}))
    assert ok["status"] == "awaiting_user_input"

    print("tools.py self-check: OK")
