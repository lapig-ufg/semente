"""``semente launch`` — start an app interface.

Currently only ``streamlit`` runs as a launcher interface; ``whatsapp`` is a
build_app/FastAPI channel (``python main.py``), listed so the command surface
matches the manifest's channel vocabulary.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LAUNCHABLE_INTERFACES = ["streamlit"]
CHANNEL_INTERFACES = ["whatsapp"]


def _streamlit_webapp() -> Path:
    return Path(__file__).parent.parent / "interfaces" / "streamlit" / "streamlit_webapp.py"


def run_streamlit(demo: bool = False) -> None:
    """Launch the Streamlit chat UI (wizard pre-flight + manifest check)."""
    from semente.configs.wizard import ensure_config

    # First-run wizard: fill missing model values, persist to .env, export for
    # the child process. No-op when everything is already set.
    ensure_config()

    env = dict(os.environ)
    if demo:
        env["SEMENTE_DEMO"] = "1"
    else:
        manifest = os.getenv("SEMENTE_MANIFEST") or "semente.yaml"
        if not Path(manifest).exists():
            sys.exit(
                f"No manifest found ('{manifest}'). Create a semente.yaml (semente init), "
                "set SEMENTE_MANIFEST, or try: semente launch streamlit --demo"
            )

    webapp = _streamlit_webapp()
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(webapp)], env=env)


def cmd_launch(interface: str, demo: bool = False) -> None:
    """Dispatch to the interface launcher."""
    if interface == "streamlit":
        run_streamlit(demo=demo)
    elif interface in CHANNEL_INTERFACES:
        sys.exit(
            f"'{interface}' is a webhook channel, not a launcher interface — "
            f"it runs via 'python main.py' (FastAPI, see main.py in your app)."
        )
    else:
        sys.exit(f"Unknown interface: '{interface}' (available: {', '.join(LAUNCHABLE_INTERFACES)})")