"""ask-user-form — a Hermes plugin that lets the agent request structured user
input (a form) and yield the turn, over the OpenAI Responses API.

On `/v1/responses` the form is delivered IN-BAND: when the agent calls ask_user,
the form spec is the `function_call` item's `arguments` in the response your
frontend reads. No webhook, no spool, no backend round-trip to receive it.

    agent calls ask_user(fields=[...])
      -> appears as a function_call (arguments = the form) in the response
      -> tool returns a stop sentinel -> model ends its turn (status: completed)
         ... frontend renders the form from arguments, the user submits ...
      -> POST answers as the next `input` with previous_response_id -> agent resumes

Registers:
  * tool  `ask_user`        — the model calls this to ask a structured question
  * hook  `post_tool_call`  — audit log when ask_user fires
  * hook  `pre_tool_call`   — observer; optional hard-stop enforcement point

See README.md for the full frontend contract.
"""

import logging

from .schemas import ASK_USER_SCHEMA
from .tools import handle_ask_user

logger = logging.getLogger("ask_user_form")


def register(ctx):
    # --- Tool: ask_user -------------------------------------------------------
    ctx.register_tool(
        name="ask_user",
        toolset="ask_user",
        schema=ASK_USER_SCHEMA,
        handler=handle_ask_user,
        description="Pause and ask the user a structured question (renders as a form). Ends your turn.",
    )

    # --- Hook: audit ----------------------------------------------------------
    # post_tool_call signature per Hermes docs: (tool_name, params, result)
    def on_post_tool_call(tool_name, params, result):
        if tool_name == "ask_user":
            logger.info("ask_user dispatched: %s", params.get("title") or params.get("message") or "(form)")

    ctx.register_hook("post_tool_call", on_post_tool_call)

    # --- Hook: optional hard-stop enforcement ---------------------------------
    # The plugin is already correct WITHOUT this hook: the tool returns a terminal
    # sentinel that tells the model to end its turn. This is an extra, deterministic
    # safety net — if your Hermes build's `pre_tool_call` supports a block/deny
    # return, you can use it to reject any *further* tool call in the same turn
    # after an ask_user. Ships as an OBSERVER (returns None = allow); verify the
    # block contract for your version before enabling a block return.
    def on_pre_tool_call(tool_name, params, **kwargs):
        return None  # observer-only

    ctx.register_hook("pre_tool_call", on_pre_tool_call)

    logger.info("ask-user-form plugin registered (tool=ask_user, toolset=ask_user)")
