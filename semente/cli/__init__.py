"""Semente CLI — create, configure, inspect, and run Semente apps.

Usage:
    semente init [dir]       # scaffold a new app (semente.yaml, domain/, ...)
    semente config ...       # edit the manifest: features, models, channels
    semente status           # app overview: manifest, env health, doctor checks
    semente launch <iface>   # run an interface (streamlit [--demo])
"""

from __future__ import annotations

import argparse
import sys

from semente.cli.config_cmd import (
    KNOWN_CHANNELS,
    KNOWN_ENGINES,
    KNOWN_FEATURES,
    KNOWN_PROVIDERS,
    cmd_config_channel_add,
    cmd_config_channel_remove,
    cmd_config_disable,
    cmd_config_enable,
    cmd_config_set,
)
from semente.cli.init_cmd import cmd_init
from semente.cli.launcher import LAUNCHABLE_INTERFACES, CHANNEL_INTERFACES, cmd_launch
from semente.cli.status_cmd import cmd_status

__all__ = ["main", "run_streamlit", "cmd_init", "cmd_status", "cmd_launch"]


def run_streamlit(demo: bool = False) -> None:
    """Back-compat re-export (tests import this)."""
    from semente.cli.launcher import run_streamlit as _run

    _run(demo=demo)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semente",
        description="Semente app toolkit — init, config, status, launch",
    )
    sub = parser.add_subparsers(dest="command")

    # --- init ---------------------------------------------------------------
    init = sub.add_parser("init", help="Scaffold a new Semente app")
    init.add_argument("directory", nargs="?", default=".", help="Target directory (default: cwd)")
    init.add_argument("--name", help="App name (default: directory name)")
    init.add_argument("--language", default="en", help="Agent language (default: en)")
    init.add_argument(
        "--provider", choices=KNOWN_PROVIDERS, default="google", help="Model provider (default: google)"
    )
    init.add_argument("--force", action="store_true", help="Overwrite existing files")
    init.add_argument("--non-interactive", action="store_true", help="Never prompt (use defaults)")

    # --- config ---------------------------------------------------------------
    config = sub.add_parser("config", help="Edit the manifest (semente.yaml)")
    config_sub = config.add_subparsers(dest="config_command")

    enable = config_sub.add_parser("enable", help="Enable a feature")
    enable.add_argument("feature", choices=KNOWN_FEATURES)

    disable = config_sub.add_parser("disable", help="Disable a feature")
    disable.add_argument("feature", choices=KNOWN_FEATURES)

    set_parser = config_sub.add_parser("set", help="Set a manifest key")
    set_parser.add_argument("key", help=f"Dotted key (e.g. name, language, engine, models.primary.id)")
    set_parser.add_argument("value")

    channel = config_sub.add_parser("channel", help="Manage channels")
    channel_sub = channel.add_subparsers(dest="channel_command")
    channel_add = channel_sub.add_parser("add", help="Enable a channel")
    channel_add.add_argument("name", choices=KNOWN_CHANNELS)
    channel_remove = channel_sub.add_parser("remove", help="Disable a channel")
    channel_remove.add_argument("name", choices=KNOWN_CHANNELS)

    # --- status ---------------------------------------------------------------
    sub.add_parser("status", help="Show the app status (manifest, env, doctor)")

    # --- launch ---------------------------------------------------------------
    launch = sub.add_parser("launch", help="Launch an app interface")
    launch.add_argument(
        "interface", choices=LAUNCHABLE_INTERFACES + CHANNEL_INTERFACES, help="Interface to launch"
    )
    launch.add_argument("--demo", action="store_true", help="Run the default demo agent (no app needed)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        sys.exit(
            cmd_init(
                directory=args.directory,
                name=args.name,
                language=args.language,
                provider=args.provider,
                force=args.force,
                non_interactive=args.non_interactive,
            )
        )
    elif args.command == "config":
        if args.config_command == "enable":
            cmd_config_enable(args.feature)
        elif args.config_command == "disable":
            cmd_config_disable(args.feature)
        elif args.config_command == "set":
            cmd_config_set(args.key, args.value)
        elif args.config_command == "channel" and args.channel_command == "add":
            cmd_config_channel_add(args.name)
        elif args.config_command == "channel" and args.channel_command == "remove":
            cmd_config_channel_remove(args.name)
        else:
            parser.print_help()
            sys.exit(1)
    elif args.command == "status":
        sys.exit(cmd_status())
    elif args.command == "launch":
        cmd_launch(args.interface, demo=args.demo)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()