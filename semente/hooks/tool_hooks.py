import json
from typing import Callable, Dict, Any
from datetime import datetime, timedelta

from semente.context import Context
from semente.configs.prompts import get_hook_texts


_hook_texts = get_hook_texts("tool_hooks")


def validate_selected_property_hook(run_context: Context, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Validation hook to guarantee that a property is stored in the system.
    """
    session_state = run_context.session_state

    if session_state and 'all_properties' in session_state:
        return function_call(**arguments)

    return _hook_texts["no_property_selected"].strip()

def validate_rate_limit_hook(run_context: Any, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """ Universal hook to avoid reprocessing and control expiration (7 days). """
    session_state = run_context.session_state or {}

    delivered_media = session_state.get("delivered_media", {})
    
    search_key = json.dumps({"func": function_call.__name__, "args": arguments}, sort_keys=True)

    if search_key in delivered_media:
        saved_date_str = delivered_media[search_key]
        try:
            saved_date = datetime.fromisoformat(saved_date_str)

            if datetime.now() - saved_date < timedelta(days=7):
                return _hook_texts["media_already_delivered"].strip()
        except Exception:
            pass


    try:
        result = function_call(**arguments)        
        if hasattr(result, 'content') and "Error" in str(result.content):
            return result
        
        if not hasattr(result, 'images') or not result.images:
             return _hook_texts["media_empty"].strip()

        delivered_media[search_key] = datetime.now().isoformat()
        run_context.session_state["delivered_media"] = delivered_media

        return result

    except Exception as e:
        return _hook_texts["media_integration_error"].strip().format(
            function_name=function_call.__name__, error=str(e)
        )