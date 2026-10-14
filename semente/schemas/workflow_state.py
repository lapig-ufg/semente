"""Canonical workflow-state sub-dict persisted inside the session state.

``WorkflowState`` lives in ``session_state["workflow_state"]``, which is
stored in a JSON column — so the tutorial position is written as a plain
string and parsed back with :func:`parse_tutorial_state`.

The tutorial position is generic (the step count comes from the domain's
``Tutorial`` object):

    ``None``         -> the tutorial offer is still unanswered
    ``"0"``, ``"1"`` -> the 0-based index of the step the user is in
    ``"COMPLETED"``  -> the terminal outcome (declined, abandoned or finished)
"""

from typing import Optional

from pydantic import BaseModel, Field

# Terminal sentinel persisted in both the session state and (via
# ``mark_tutorial_completed``) the database: the flow never re-opens for it.
TUTORIAL_COMPLETED = "COMPLETED"


def parse_tutorial_state(value) -> Optional[str]:
    """Parse/validate the persisted ``tutorial_state``.

    Accepts the terminal sentinel, a non-negative step index (int or its
    decimal string) and ``None``/empty (flow not started); anything else
    (negative numbers, unknown names, junk) parses as ``None`` so a broken
    state can never crash a turn.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None
    if value == TUTORIAL_COMPLETED:
        return TUTORIAL_COMPLETED
    try:
        index = int(value)
    except ValueError:
        return None
    if index < 0:
        return None
    return str(index)


class WorkflowState(BaseModel):
    schema_version: int = Field(
        default=1,
        description="Schema version of the session state."
    )
    tutorial_state: Optional[str] = Field(
        default=None,
        description=(
            "Tutorial position for the user: None while the offer is still "
            "unanswered, the 0-based step index (e.g. '0') while in flight, "
            "or 'COMPLETED' once a final outcome (declined, abandoned or "
            "finished) was reached."
        )
    )
    tutorial_intro_sent: bool = Field(
        default=False,
        description="Whether the current step's teaching lesson was already delivered."
    )
    is_feedback_active: bool = Field(
        default=False,
        description="Should run feedback evaluation."
    )