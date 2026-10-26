import textwrap
from typing import List, Optional
from pydantic import BaseModel, Field


class CommunicationPreference(BaseModel):
    key: str = Field(
        description=(
            "The key of the communication/interaction preference with the user "
            "(e.g. 'tone_of_voice', 'response_length', 'explanation_format', 'emoji_usage'). "
        )
    )
    description: str = Field(
        description=(
            "The specification of how the agent should behave when responding "
            "(e.g. 'Prefers answers in bullet points and very direct', 'Likes an informal and relaxed tone')."
        )
    )


class UserPersona(BaseModel):
    name: Optional[str] = Field(
        default="Not yet known",
        description="The user's name."
    )
    role: Optional[str] = Field(
        default="Not yet known",
        description="The user's role or profession (e.g. 'teacher', 'agronomist')."
    )
    regionality: Optional[str] = Field(
        default="Not yet known",
        description="The user's regional location, city or state."
    )
    communication_preferences: List[CommunicationPreference] = Field(
        default_factory=list,
        description="List of preferences focused exclusively on how the agent should interact and format its responses."
    )

    def __str__(self) -> str:
        preferences_text = "".join(
            f"\n- {pref.key.title()}: {pref.description}" for pref in self.communication_preferences
        )

        return textwrap.dedent(f"""
            - Name: {self.name}
            - Role: {self.role}
            - Regionality: {self.regionality}{preferences_text}
        """).strip()


# UserPersona fields default to a sentinel string instead of None, so a
# persona built from the schema alone looks "informed". Both the onboarding
# gate and the welcoming agent must treat the sentinel as missing.
UNKNOWN_PERSONA_VALUES = {
    UserPersona.model_fields["name"].default,
    UserPersona.model_fields["role"].default,
}


def is_persona_field_informed(value) -> bool:
    """True when a persona field holds an actual value (not None/sentinel)."""
    return bool(value) and value not in UNKNOWN_PERSONA_VALUES


def is_persona_complete(persona) -> bool:
    """True when both the name and the role are informed (not sentinel)."""
    persona = persona or {}
    return (
        is_persona_field_informed(persona.get("name"))
        and is_persona_field_informed(persona.get("role"))
    )


class PersonaUpdate(BaseModel):
    """Structured output of the persona manager agent.

    Represents the changes the agent wants to apply to the user's persona.
    Only filled-in fields will be updated.

    Name and role are deliberately NOT here: they are identity declared by
    the user during onboarding and only change at their explicit request,
    through the `update_persona_name` and `update_persona_role` tools. This
    agent runs on its own on every reply and works by deduction — deduction
    does not override declaration.
    """

    regionality: Optional[str] = Field(
        default=None,
        description="Updated city/state/region, or None to keep the current one.",
    )
    communication_preferences: List[CommunicationPreference] = Field(
        default_factory=list,
        description=(
            "List EXCLUSIVELY of communication style, response format "
            "or tone of voice preferences to be added or updated."
        ),
    )