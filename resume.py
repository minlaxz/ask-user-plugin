"""Resume helpers — for your Vercel function / proxy, NOT used by Hermes.

On the Responses API you resume by sending the user's answers as the next `input`
with `previous_response_id` (you set `store: true`). These helpers validate the
submission against the form and build that `input` string.

`form` here is the parsed `function_call.arguments` of the ask_user call — i.e.
the same {message, fields, ...} object your frontend rendered.

Flow:
  1. Read the ask_user function_call from the response; form = JSON.parse(arguments).
  2. User submits  ->  answers = validate_answers(form, submitted).
  3. POST /v1/responses with input=build_resume_input(answers) and
     previous_response_id=<the resp_... id>.
"""

import json


def validate_answers(form, submitted):
    """Validate `submitted` (dict of key -> value) against `form['fields']`.

    Returns a cleaned answers dict, or raises ValueError listing all problems.
    Validate on the server; never trust the raw frontend submission, and never
    make the agent re-validate.
    """
    answers, errors = {}, []
    fields = {f["key"]: f for f in form.get("fields", [])}

    for key in submitted:
        if key not in fields:
            errors.append(f"unknown field: {key}")

    for key, field in fields.items():
        val = submitted.get(key)
        required = field.get("required", True)
        ftype = field.get("type", "text")

        if val is None or val == "" or val == []:
            if required:
                errors.append(f"missing required field: {key}")
            continue

        if ftype == "number":
            try:
                val = float(val)
            except (TypeError, ValueError):
                errors.append(f"'{key}' must be a number")
                continue
        elif ftype == "boolean":
            val = bool(val)
        elif ftype == "select":
            opts = field.get("options") or []
            if opts and val not in opts:
                errors.append(f"'{key}' must be one of {opts}")
                continue
        elif ftype == "multiselect":
            if not isinstance(val, list):
                errors.append(f"'{key}' must be a list")
                continue
            opts = field.get("options") or []
            bad = [v for v in val if opts and v not in opts]
            if bad:
                errors.append(f"'{key}' has invalid options: {bad}")
                continue
        # text / textarea pass through

        answers[key] = val

    if errors:
        raise ValueError("; ".join(errors))
    return answers


def build_resume_input(answers):
    """Build the `input` string for the resume POST /v1/responses call."""
    return "Form answers (JSON): " + json.dumps(answers)
