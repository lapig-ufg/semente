from typing import Literal

from semente import tool
from semente.context import Context as RunContext
from semente.logging import log_debug, log_warning, log_error

from semente.configs.prompts import get_tool_description
from semente.database.session import SessionLocal, engine
from semente.database.models import UserProfile


# =====================================================================
# INTERNAL HELPERS (not tools — invisible to the agent)
# =====================================================================


def _persist_profile(user_id: str, **fields) -> bool:
    """Writes the name and/or role to the user_profile table (creates the row if it does not exist).

    Fields are received as keywords (name=..., role=...) so that each tool
    writes only what it knows, without wiping out what the other already saved.
    """
    UserProfile.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        record = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if record is None:
            record = UserProfile(user_id=user_id, **fields)
            db.add(record)
        else:
            for field, value in fields.items():
                setattr(record, field, value)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        log_error(f"_persist_profile: failed for user_id={user_id}: {e}")
        return False
    finally:
        db.close()


# =====================================================================
# TOOLS FOR MAIN ATTRIBUTES
# =====================================================================

@tool(description=get_tool_description("persona_tools", "update_persona_name"))
def update_persona_name(name: str, run_context: RunContext) -> str:
    """
    Organically updates the user's persona (profile) name in the session state.

    Use this tool only when the user states or confirms their name naturally
    during the conversation.

    Args:
        name (str): The user's given name (e.g. "John", "Maria").
    """
    log_debug(f"update_persona_name: name={name}")
    try:
        clean_name = name.strip()

        if not clean_name or len(clean_name) > 60 or any(c.isdigit() for c in clean_name):
            log_warning(f"update_persona_name: name rejected -> {clean_name!r}")
            return (
                "Invalid name. Ask the user to state only how they prefer "
                "to be called, without numbers."
            )

        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})

        user_persona['name'] = clean_name

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state

        user_id = run_context.user_id or session_state.get("user_id")
        if user_id:
            _persist_profile(user_id, name=clean_name)
        else:
            log_warning("update_persona_name: missing user_id, profile saved to session only")

        log_debug(f"update_persona_name: name updated to {clean_name}")
        return f"Name updated successfully to: {clean_name}"
    except Exception as e:
        log_error(f"update_persona_name: {e}")
        return f"Error updating persona name: {str(e)}"


@tool(description=get_tool_description("persona_tools", "update_persona_role"))
def update_persona_role(role: Literal["Producer", "Technician"], run_context: RunContext) -> str:
    """
    Organically updates the user's professional role in the persona on the session state.

    Use this tool when it is clearly established whether the user is a rural
    producer or a technical assistant/agronomist.

    Args:
        role (Literal["Producer", "Technician"]): The identified professional role.
    """
    log_debug(f"update_persona_role: role={role}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})

        user_persona['role'] = role

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state

        user_id = run_context.user_id or session_state.get("user_id")
        if user_id:
            _persist_profile(user_id, role=role)
        else:
            log_warning("update_persona_role: missing user_id, profile saved to session only")

        log_debug(f"update_persona_role: role updated to {role}")
        return f"Professional role updated successfully to: {role}"
    except Exception as e:
        log_error(f"update_persona_role: {e}")
        return f"Error updating persona role: {str(e)}"


@tool(description=get_tool_description("persona_tools", "update_persona_region"))
def update_persona_region(regionality: str, run_context: RunContext) -> str:
    """
    Organically updates the persona's regionality/location in the session state.

    Use this tool when the user mentions the city, state or region where they operate.

    Args:
        regionality (str): The user's city, state or region (e.g. "Sorriso - MT", "South of Minas").
    """
    log_debug(f"update_persona_region: regionality={regionality}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})

        user_persona['regionality'] = regionality.strip().title()

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"update_persona_region: regionality updated to {user_persona['regionality']}")
        return f"Regionality updated successfully to: {user_persona['regionality']}"
    except Exception as e:
        log_error(f"update_persona_region: {e}")
        return f"Error updating persona regionality: {str(e)}"


# =====================================================================
# TOOLS FOR PREFERENCE MANAGEMENT
# =====================================================================

@tool(description=get_tool_description("persona_tools", "create_persona_preference"))
def create_persona_preference(key: str, description: str, run_context: RunContext) -> str:
    """
    Adds a newly discovered preference, interest, hobby or behavior about the user.

    Use this tool subtly whenever you pick up a liking, routine or preference
    of the user. Avoid duplicating existing keys. If the key already exists,
    use 'update_persona_preference' instead.

    Args:
        key (str): A short lowercase keyword identifying the category (e.g. "culture", "coffee", "contact_time", "favorite_channel").
        description (str): Details about the user's liking or behavior in that category.
    """
    log_debug(f"create_persona_preference: key={key}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})

        if "preferences" not in user_persona or not isinstance(user_persona["preferences"], list):
            user_persona["preferences"] = []

        normalized_key = key.strip().lower()

        for pref in user_persona["preferences"]:
            if pref.get("key") == normalized_key:
                log_warning(f"Preference already exists: {normalized_key}")
                return f"The preference '{key}' already exists. Use 'update_persona_preference' to modify it."

        user_persona["preferences"].append({
            "key": normalized_key,
            "description": description.strip()
        })

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"create_persona_preference: preference '{normalized_key}' registered")
        return f"New preference registered: {normalized_key.title()} -> {description}"
    except Exception as e:
        log_error(f"create_persona_preference: {e}")
        return f"Error registering preference: {str(e)}"


@tool(description=get_tool_description("persona_tools", "update_persona_preference"))
def update_persona_preference(key: str, description: str, run_context: RunContext) -> str:
    """
    Updates a preference or behavior that already exists in the user's persona.

    Use this tool when the user changes their mind or brings new information
    about a point that was already mapped previously.

    Args:
        key (str): The exact keyword of the preference to be updated (e.g. "culture", "coffee").
        description (str): The new updated description that will replace the previous one.
    """
    log_debug(f"update_persona_preference: key={key}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})
        preferences = user_persona.get("preferences", [])

        normalized_key = key.strip().lower()
        updated = False

        for pref in preferences:
            if pref.get("key") == normalized_key:
                pref["description"] = description.strip()
                updated = True
                break

        if not updated:
            log_warning(f"Preference not found to update: {normalized_key}")
            return f"Could not update: The preference with the key '{key}' was not found."

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"update_persona_preference: preference '{normalized_key}' updated")
        return f"Preference '{normalized_key.title()}' updated successfully."
    except Exception as e:
        log_error(f"update_persona_preference: {e}")
        return f"Error updating preference: {str(e)}"


@tool(description=get_tool_description("persona_tools", "remove_persona_preference"))
def remove_persona_preference(key: str, run_context: RunContext) -> str:
    """
    Removes a specific preference from the user's profile when it is no longer valid.

    Args:
        key (str): The keyword of the preference that should be removed.
    """
    log_debug(f"remove_persona_preference: key={key}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})
        preferences = user_persona.get("preferences", [])

        normalized_key = key.strip().lower()

        initial_count = len(preferences)
        updated_preferences = [pref for pref in preferences if pref.get("key") != normalized_key]

        if len(updated_preferences) == initial_count:
            log_warning(f"Preference not found to remove: {normalized_key}")
            return f"No preference found with the key '{key}' to remove."

        user_persona["preferences"] = updated_preferences
        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"remove_persona_preference: preference '{normalized_key}' removed")
        return f"Preference '{normalized_key.title()}' removed successfully."
    except Exception as e:
        log_error(f"remove_persona_preference: {e}")
        return f"Error removing preference: {str(e)}"