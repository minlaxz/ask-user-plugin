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
  * hook  `pre_tool_call`   — turn guard: one form per turn, nothing after it

See README.md for the full frontend contract.
"""

import logging

from .schemas import ASK_USER_SCHEMA
from .tools import ASK_USER, ENVELOPE, guard_pre_tool_call, handle_ask_user

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
    # Hooks are called with KEYWORD arguments, and post_tool_call carries more of
    # them than this needs (task_id, session_id, tool_call_id, turn_id, …), so the
    # callback takes **kwargs or it raises TypeError on every tool call and Hermes
    # logs and skips it — which is to say it never audits anything.
    def on_post_tool_call(tool_name, args=None, result=None, **kwargs):
        args = args or {}
        # `ask_user` reaches here under its own name or wrapped by the meta-tool,
        # the same two spellings the guard counts
        if tool_name == ENVELOPE and args.get("name") == ASK_USER:
            args = args.get("arguments") or {}
        elif tool_name != ASK_USER:
            return
        if not isinstance(args, dict):
            return
        logger.info("ask_user dispatched: %s", args.get("title") or args.get("message") or "(form)")

    ctx.register_hook("post_tool_call", on_post_tool_call)

    # --- Hook: turn guard (issue #1) ------------------------------------------
    # The sentinel the tool returns is a string handed to the model, so the model
    # may ignore it — and on a Sessions deployment it did, raising a second form
    # in the same turn and stranding the first. `pre_tool_call` is documented as
    # a directive hook: the first valid {"action": "block", "message": ...} wins
    # and short-circuits the call with that message as the error the model reads.
    # So the guard blocks every tool call that follows an ask_user in one turn.
    #
    # It fails open on a build that ignores the directive, or one that passes no
    # turn_id: the sentinel is then back to being the only thing asking the model
    # to stop, which is exactly where this plugin stood before.
    ctx.register_hook("pre_tool_call", guard_pre_tool_call)

    logger.info("ask-user-form plugin registered (tool=ask_user, toolset=ask_user)")
