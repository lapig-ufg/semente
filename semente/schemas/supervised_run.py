"""Structured answers of the supervised_run agents.

``SupervisedRunDecision`` is the decision of the supervisor (``semente.agents
.supervised_run_agent``) that sits above the normal agent while the supervised_run runs:
for every user message inside the supervised_run the pipeline acts on it alone.
The supervisor has no tools and does no domain work — when the user follows
the step taught by its ``forward_condition`` it forwards, so the real
assistant behaves exactly as it does outside the supervised_run.

``CompletionCheck`` is the decision of the checkpoint agent — the second
agent in the same module (``semente.agents.supervised_run_agent``) — consulted by
the pipeline after a forwarded turn whenever the current step's
``complete_condition`` is a str (callables are judged by the pipeline
itself).
"""

from pydantic import BaseModel, Field


class SupervisedRunDecision(BaseModel):
    """What the supervised_run supervisor decided about the user's current message."""

    forward: bool = Field(
        default=False,
        description=(
            "True when the user is following the current step's taught path: the "
            "normal agent answers the message with the real work. The "
            "'content' must be empty here and is ignored by the pipeline."
        ),
    )
    content: str = Field(
        default="",
        description=(
            "The teaching/coaching reply shown to the user when not "
            "forwarding: the step's lesson or the coaching reply. "
            "Empty when forwarding."
        ),
    )
    abandon_supervised_run: bool = Field(
        default=False,
        description=(
            "True when the user clearly asks to leave the supervised_run early; "
            "the pipeline closes the supervised_run for good."
        ),
    )


class CompletionCheck(BaseModel):
    """Whether the current step's completion condition was met by the last reply."""

    step_completed: bool = Field(
        default=False,
        description=(
            "True ONLY when the conversation plus the real assistant's reply "
            "clearly satisfy the step's completion condition; anything else "
            "(doubt, ambiguity, partial work) is False."
        ),
    )