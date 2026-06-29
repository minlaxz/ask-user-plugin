"""ask_user tool handler — OpenAI Responses format.

The form the model builds is delivered IN-BAND: it appears as the `function_call`
item's `arguments` in the response your frontend reads. So this handler does NOT
deliver anything out-of-band. It only:

  1. validates the form the model produced (so a malformed form can be retried), and
  2. returns a terminal sentinel that ends the turn.

Hermes tool contract (per the Adding Tools docs):
  * handlers return a JSON string (never a raw dict)
  * errors are returned as {"error": "..."} (never raised)
  * handler signature is (args: dict, **kwargs)
"""

import json
import logging

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
