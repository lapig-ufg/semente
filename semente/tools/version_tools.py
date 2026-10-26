from pathlib import Path

from semente import tool
from semente.logging import log_debug, log_warning, log_error

from semente.configs.prompts import get_tool_description


@tool(description=get_tool_description("version_tools", "consult_update_notes"))
def consult_update_notes() -> str:
    """
    Reads and returns the system update notes (patch notes).
    Use this tool when the user asks about the current version, new features, or updates.
    """
    log_debug("consult_update_notes: starting to read the release notes")
    base_path = Path.cwd()
    folder_path = base_path / "docs" / "release_notes"
    
    if not folder_path.exists():
        log_warning(f"Release notes directory not found: {folder_path}")
        return "Error: The release notes directory was not found on the system."
        
    try:
        files = sorted(folder_path.glob("*.md"))
        if not files:
            log_warning(f"No release notes found in {folder_path}")
            return "Notice: No release notes were found in the repository."
        target_file = files[-1]
            
        if not target_file.exists():
            log_warning(f"Notes file not found: {target_file}")
            return "Error: The update notes were not found."
            
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()

        log_debug(f"consult_update_notes: notes read from {target_file.name}")
        return (
            f"Patch content:\n\n{content}\n\n"
            "Pass this information to the user IN FULL, using STRICTLY WhatsApp text formatting (*bold*, _italic_). "
            "Do not use Markdown formatting such as #, ## or **."
        )
        
    except Exception as e:
        log_error(f"consult_update_notes: failed to read release notes: {e}")
        return f"Unexpected error while trying to read the patch file: {str(e)}"