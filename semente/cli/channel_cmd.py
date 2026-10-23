"""``semente channel`` — list and toggle the manifest channels.

A channel is one of the surfaces Semente can expose the app through
(``channels`` in the manifest). Toggling edits the manifest only.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

from semente.cli.common import load_manifest_or_exit, toggle_hint

console = Console()

CHANNELS: dict[str, str] = {
    "streamlit": "Local web chat (dev-friendly UI with a debug panel)",
    "whatsapp": "WhatsApp webhook channel (assembled by build_app; run via main.py)",
}

KNOWN_CHANNELS = list(CHANNELS)


def _validate(name: str) -> None:
    if name not in CHANNELS:
        sys.exit(f"Unknown channel '{name}' (available: {', '.join(KNOWN_CHANNELS)})")


def cmd_channel_ls() -> None:
    manifest, path = load_manifest_or_exit()
    table = Table(show_header=True, box=None, title="Channels", title_justify="left")
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_column()
    for name, description in CHANNELS.items():
        active = name in manifest.channels
        label = "[green]enabled[/green]" if active else "[red]disabled[/red]"
        table.add_row(name, label, description)
    console.print(table)
    console.print(f"Manifest: {path} — toggle with 'semente channel <name> --enable/--disable'.")


def cmd_channel_actives() -> None:
    """One line per enabled channel."""
    manifest, path = load_manifest_or_exit()
    console.print("[bold]Active channels[/bold]: " + (", ".join(manifest.channels) or "(none)"))
    console.print(f"Manifest: {path}")


def cmd_channel_toggle(name: str, enable: bool | None) -> None:
    """--enable/--disable edits the manifest channels; no flag shows status."""
    _validate(name)
    manifest, path = load_manifest_or_exit()

    if enable is None:
        label = "enabled" if name in manifest.channels else "disabled"
        print(f"Channel '{name}' is {label}.")
        print(toggle_hint("channel", name))
        return

    if enable:
        if name in manifest.channels:
            print(f"Channel '{name}' already enabled. Channels: {', '.join(manifest.channels)}")
            return
        manifest.channels = [*manifest.channels, name]
        print(f"Channel '{name}' enabled. Channels: {', '.join(manifest.channels)}")
    else:
        if name not in manifest.channels:
            print(f"Channel '{name}' is not enabled. Channels: {', '.join(manifest.channels) or '(none)'}")
            return
        manifest.channels = [c for c in manifest.channels if c != name]
        print(f"Channel '{name}' disabled. Channels: {', '.join(manifest.channels) or '(none)'}")
    manifest.save(path)