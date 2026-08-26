"""Per-invocation runtime context.

Passed to `invoke()` as `context=`, not as state: it identifies *who* the
caller is running the graph for, which is an input to the run rather than
something the run produces. Keeping it out of state also keeps it out of the
checkpoint, so a thread cannot end up asserting a customer id that contradicts
the one the channel resolved.

Nodes receive it as `runtime.context` via a `Runtime[Context]` parameter.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Context:
    """What the channel knows before the graph starts.

    Attributes:
        customer_id: The application customer id. The channel (Streamlit,
            an email or WhatsApp adapter) is responsible for resolving
            its own identity -- a session, an address, a phone number -- to
            this. The graph never learns it from the message text.
    """

    customer_id: str
