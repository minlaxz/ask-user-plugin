# ask-user-form

A Hermes plugin that lets the agent **pause mid-task and ask the user a structured
question** (a form), for headless deployments behind the OpenAI **Responses** API
(`/v1/responses`). The API server ships a restricted toolset that drops the
built-in interactive tools (`clarify`, `send_message`); this plugin restores that
capability in a form your frontend can render.

On the Responses API the form is delivered **in-band**: when the agent calls
`ask_user`, the form spec appears as the `function_call` item's `arguments` in the
response your frontend already reads. **No webhook, no spool file, no backend
round-trip is needed to receive the form.**

```
agent calls ask_user(fields=[…])
  → appears in the response as a function_call (arguments = the form)
  → tool returns a sentinel  →  model ends its turn (status: completed)
       … frontend reads the form from arguments, renders it, user submits …
  → POST the answers as the next `input` with previous_response_id
  → agent resumes
```

> **Responses-only (v2.0).** The older out-of-band delivery path (webhook + spool)
> existed solely for `/v1/chat/completions`, which doesn't expose tool arguments in
> the stream. It has been removed. Use `/v1/responses`.

## Files

| File | Runs in | Purpose |
|------|---------|---------|
| `plugin.yaml` | Hermes | Manifest |
| `__init__.py` | Hermes | `register()` — wires the tool + audit hook |
| `schemas.py` | Hermes | `ask_user` tool schema (what the LLM fills in) |
| `tools.py` | Hermes | Handler — validate the form, return the stop sentinel |
| `resume.py` | your proxy | Validate answers + build the resume `input` (optional) |

## Install

1. Copy this directory to `~/.hermes/plugins/ask-user-form/`.

2. Enable the plugin:
   ```bash
   hermes plugins enable ask-user-form
   ```
   or add it under `plugins.enabled` in `~/.hermes/config.yaml`:
   ```yaml
   plugins:
     enabled:
       - ask-user-form
   ```

3. **Enable the `ask_user` toolset for the API-server platform.** This is the step
   people miss. The API server ships a *restricted* toolset by design, and your
   plugin registers `ask_user` under its own toolset, which is **not** included
   automatically:
   ```yaml
   # config.yaml — add ask_user to whatever the API server platform uses
   toolsets:
     - hermes-api      # or your platform preset
     - ask_user
   ```
   Confirm over REST (deterministic — no need to ask the model):
   ```bash
   curl -s http://localhost:8642/v1/toolsets \
     -H "Authorization: Bearer $API_SERVER_KEY" | grep ask_user
   ```

4. Restart the API server.

5. (Recommended) Reinforce usage so the model reaches for the tool instead of
   guessing. Add a line to `SOUL.md`, your system prompt, or a skill:
   > When you need information, a choice, or confirmation from the user, call
   > `ask_user` with the fields you need. Never assume or fabricate answers.

## The form (what your frontend reads)

The model fills in the `ask_user` schema; that object is exactly what arrives as
the `function_call.arguments`:

```json
{
  "title": "Booking details",
  "message": "I need a few details to book the tee time.",
  "fields": [
    { "key": "date",    "label": "Date",    "type": "text",   "required": true },
    { "key": "players", "label": "Players", "type": "number", "required": true },
    { "key": "tier",    "label": "Tier",    "type": "select",
      "options": ["Standard", "Premium"], "required": true }
  ],
  "submit_label": "Book"
}
```

Field types: `text`, `textarea`, `number`, `boolean`, `select`, `multiselect`.
All flat — render each to a control. `title` and `submit_label` are optional.

## Reading the ask from a Responses stream

Watch the SSE `output_item` events (or read the final `response.output` array).
The `ask_user` call is a `function_call` item; its `arguments` is a JSON **string**:

```jsonc
{ "type": "function_call", "name": "ask_user", "call_id": "chatcmpl-tool-…",
  "arguments": "{\"message\":\"…\",\"fields\":[…]}" }
```

1. Find the `function_call` whose `name === "ask_user"`.
2. `const form = JSON.parse(item.arguments)` → render `form.message` + `form.fields`.
3. Keep the response `id` (`resp_…`) for the resume call. `call_id` correlates the
   call if you need it.

The turn ends with `response.completed` / `status: "completed"`. The assistant may
emit a short "waiting for your reply" message — that's narration; ignore it and
render the form.

> The tool's own result (the `function_call_output`) only carries a stop sentinel
> to end the turn. You don't need to read it — render from `arguments`. Note its
> shape if you ever do: `output` is an **array**, e.g.
> `[{ "type": "input_text", "text": "{…json…}" }]`.

## Resuming

You set `store: true`, so chain on the response id and send the answers as the next
`input`:

```jsonc
POST /v1/responses
{
  "model": "hermes-agent",
  "input": "Form answers (JSON): {\"tier\": \"Premium\", \"players\": 2}",
  "previous_response_id": "resp_abc123",
  "store": true,
  "stream": true
}
```

Add an `Idempotency-Key` header so a double-tap on Submit can't fire two turns
(responses are cached by key for 5 minutes). The server reconstructs the full
conversation (including the ask_user call and its output) from the stored chain,
so the agent continues with the answers in context. You do **not** send a
`function_call_output` yourself — the tool already returned.

If you validate answers in your Vercel function first, `resume.py` has helpers:

```python
from resume import validate_answers, build_resume_input
answers = validate_answers(form, submitted)   # form = parsed function_call.arguments
input_str = build_resume_input(answers)        # the string to put in `input`
```

## How the "stop" works

The tool returns a sentinel result with no answer data and an explicit
stop-instruction, and the tool description states that calling it ends the turn.
With a capable model that reliably halts the loop (a Yes/No test confirms it:
`status: "completed"`, no fabricated answer). For a deterministic guarantee, the
`pre_tool_call` hook stub in `__init__.py` shows where to block any further tool
call once a form is pending — enable it once you've confirmed the block contract
for your Hermes version.

## Notes / limits

- **No out-of-band delivery.** The form rides in the response; there is no webhook
  and no spool. (`inject_message` is likewise unused — it's CLI-only.)
- Keep forms flat (primitive fields + enums). For multi-step intake, emit one form,
  resume, and let the agent decide whether it needs another.
- Pure standard library — zero third-party dependencies.
