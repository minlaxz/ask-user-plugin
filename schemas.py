"""Schema for the ask_user tool — this is what the LLM sees and fills in.

Kept deliberately FLAT (primitive field types + enums) so your frontend can
render it trivially and so validation on resume is simple. This mirrors the
constraint that MCP elicitation and the built-in `clarify` tool impose.
"""

ASK_USER_SCHEMA = {
    "name": "ask_user",
    "description": (
        "Pause execution and ask the user a structured question. The fields you "
        "provide are rendered as a form on the user's frontend; the user fills it "
        "in and the conversation resumes with their answers.\n\n"
        "IMPORTANT: Calling this tool ENDS YOUR TURN. The tool result confirms the "
        "form is displayed and tells you the exact one-line reply to finish with; "
        "reply with that line only. Make no further tool calls, never say the form "
        "failed, never repeat the question in text, and never guess or fabricate "
        "the user's answers — the user is not reachable until they submit.\n\n"
        "Use this whenever you need information, a choice, or confirmation from the "
        "user before you can proceed. Keep fields flat and minimal: use "
        "'select'/'multiselect' (with options) for choices, 'boolean' for yes/no, "
        "and 'text'/'textarea'/'number' for free input."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short form title (optional).",
            },
            "message": {
                "type": "string",
                "description": "The question or context shown above the fields (optional but recommended).",
            },
            "fields": {
                "type": "array",
                "description": "The inputs to collect. Keep them flat and primitive.",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Machine key for the answer (e.g. 'budget'). Must be unique within the form.",
                        },
                        "label": {
                            "type": "string",
                            "description": "Human-readable label shown next to the input.",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["text", "textarea", "number", "boolean", "select", "multiselect"],
                            "description": "Input type.",
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Allowed choices — required for 'select' and 'multiselect'.",
                        },
                        "required": {
                            "type": "boolean",
                            "description": "Whether the field must be filled. Defaults to true.",
                        },
                        "placeholder": {
                            "type": "string",
                            "description": "Optional placeholder / help text.",
                        },
                        "default": {
                            "description": "Optional default value (string, number, boolean, or list).",
                        },
                    },
                    "required": ["key", "label", "type"],
                },
            },
            "submit_label": {
                "type": "string",
                "description": "Label for the submit button (default 'Submit').",
            },
        },
        "required": ["fields"],
    },
}
