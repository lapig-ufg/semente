"""Semente CLI — create, configure, inspect, and run Semente apps.

Usage:
    semente init [dir]                # scaffold a new app (semente.yaml, domain/, ...)
    semente feature ls|actives|add    # list/add features; <name> --enable | --disable
    semente channel ls|actives        # list channels; <name> --enable | --disable
    semente provider ...              # primary/fallback models and API keys
    semente status                    # app overview: manifest, env health, doctor checks
    semente launch <iface>            # run an interface (streamlit [--demo])
"""

from __future__ import annotations

import argparse
import sys

from semente.cli.channel_cmd import cmd_channel_actives, cmd_channel_ls, cmd_channel_toggle
from semente.cli.feature_cmd import cmd_feature_actives, cmd_feature_add, cmd_feature_ls, cmd_feature_toggle
from semente.cli.init_cmd import cmd_init
from semente.cli.mcp_cmd import cmd_mcp
from semente.cli.launcher import LAUNCHABLE_INTERFACES, CHANNEL_INTERFACES, cmd_launch
from semente.cli.provider_cmd import (
    KNOWN_PROVIDERS,
    cmd_provider_fallback,
    cmd_provider_key,
    cmd_provider_ls,
    cmd_provider_primary,
)
from semente.cli.status_cmd import cmd_status

__all__ = ["main", "run_streamlit", "cmd_init", "cmd_status", "cmd_launch"]


class HelpOnErrorParser(argparse.ArgumentParser):
    """argparse parser that prints the command's own help (like ``-h``) on errors.

    Used for the whole CLI: ``add_subparsers`` passes its own class down to
    every (nested) subparser, so a bad argument or missing value prints the
    help of the command where the error happened.
    """

    def error(self, message: str) -> None:
        self.print_help(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def _print_group_help(parser: argparse.ArgumentParser, command: str) -> None:
    """Print the help of a command group (e.g. ``semente feature`` alone)."""
    from argparse import _SubParsersAction

    action = next(a for a in parser._actions if isinstance(a, _SubParsersAction))
    action.choices[command].print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = HelpOnErrorParser(
        prog="semente",
        description="Semente app toolkit — init, feature, channel, provider, status, launch",
    )
    sub = parser.add_subparsers(dest="command")

    # Shared --enable/--disable flag style (feature and channel groups).
    def _toggle_flags(group: argparse.ArgumentParser) -> None:
        toggles = group.add_mutually_exclusive_group()
        toggles.add_argument("--enable", action="store_true", help="Enable it in the manifest")
        toggles.add_argument("--disable", action="store_true", help="Disable it in the manifest (code is left alone)")

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

    # --- feature ---------------------------------------------------------------
    # No subparsers here: the first positional is either a reserved command
    # (ls/actives/add) or a feature name to toggle with --enable/--disable —
    # a free positional cannot coexist with an argparse subparsers action.
    feature = sub.add_parser(
        "feature",
        help="Manage manifest features (semente.yaml features)",
        description="List, add, enable, and disable the manifest's features (tts, summarization, interaction-assessment, guardrails, terms-acceptance).",
    )
    feature.add_argument(
        "command_or_name", nargs="?", metavar="{ls,actives,add,name}",
        help="A feature name; or 'ls'/'actives', or 'add' (+ a feature name)",
    )
    feature.add_argument("add_name", nargs="?", help=argparse.SUPPRESS)
    _toggle_flags(feature)

    # --- channel ---------------------------------------------------------------
    channel = sub.add_parser(
        "channel",
        help="Manage manifest channels (semente.yaml channels)",
        description="List and enable/disable the channels the app runs on (streamlit, whatsapp).",
    )
    channel.add_argument(
        "command_or_name", nargs="?", metavar="{ls,actives,name}",
        help="A channel name; or 'ls'/'actives'",
    )
    _toggle_flags(channel)

    # --- provider ---------------------------------------------------------------
    provider = sub.add_parser(
        "provider",
        help="Manage model providers, fallback, and API keys",
        description="Set the primary/fallback model (provider + model id) in the manifest and the API keys in .env.",
    )
    provider_sub = provider.add_subparsers(dest="provider_command")
    provider_sub.add_parser("ls", help="Show the effective model configuration and missing keys")

    provider_primary = provider_sub.add_parser("primary", help="Set the primary model provider (and model id)")
    provider_primary.add_argument("provider")
    provider_primary.add_argument("--model", metavar="id", help="Model id (e.g. gemini-2.0-flash)")

    provider_fallback = provider_sub.add_parser(
        "fallback", help="Set the fallback model (or --disable to remove it)"
    )
    provider_fallback.add_argument("provider", nargs="?")
    provider_fallback.add_argument("--model", metavar="id", help="Model id (e.g. gemma4:31b-cloud)")
    provider_fallback.add_argument("--disable", action="store_true", help="Remove the fallback from the manifest")

    provider_key = provider_sub.add_parser("key", help="Set a provider's API keys (written to .env, hidden input)")
    provider_key.add_argument("provider")

    # --- status ---------------------------------------------------------------
    sub.add_parser("status", help="Show the app status (manifest, env, doctor)")

    # --- launch ---------------------------------------------------------------
    launch = sub.add_parser("launch", help="Launch an app interface")
    launch.add_argument(
        "interface", choices=LAUNCHABLE_INTERFACES + CHANNEL_INTERFACES, help="Interface to launch"
    )
    launch.add_argument("--demo", action="store_true", help="Run the default demo agent (no app needed)")

    # --- mcp ------------------------------------------------------------------
    mcp = sub.add_parser(
        "mcp",
        help="Expose a remote A2A agent as one MCP tool (stdio)",
        description="Start a stdio MCP server whose single tool forwards questions to an A2A agent (needs semente-agents[mcp]).",
    )
    mcp.add_argument("--url", required=True, help="Base URL of the A2A agent (e.g. http://localhost:3000)")
    mcp.add_argument("--name", help="Tool/agent name (default: the Agent Card name)")
    mcp.add_argument("--api-key", help="Bearer key for the agent (default: A2A_API_KEY env var)")

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
    elif args.command == "feature":
        if args.command_or_name == "ls":
            cmd_feature_ls()
        elif args.command_or_name == "actives":
            cmd_feature_actives()
        elif args.command_or_name == "add":
            if not args.add_name:
                print("error: 'semente feature add' requires a feature name.", file=sys.stderr)
                sys.exit(1)
            cmd_feature_add(args.add_name)
        elif args.command_or_name:
            enable = True if args.enable else False if args.disable else None
            cmd_feature_toggle(args.command_or_name, enable)
        elif args.enable or args.disable:
            print("error: --enable/--disable requires a feature name.", file=sys.stderr)
            sys.exit(1)
        else:
            _print_group_help(parser, "feature")
            sys.exit(1)
    elif args.command == "channel":
        if args.command_or_name == "ls":
            cmd_channel_ls()
        elif args.command_or_name == "actives":
            cmd_channel_actives()
        elif args.command_or_name:
            enable = True if args.enable else False if args.disable else None
            cmd_channel_toggle(args.command_or_name, enable)
        elif args.enable or args.disable:
            print("error: --enable/--disable requires a channel name.", file=sys.stderr)
            sys.exit(1)
        else:
            _print_group_help(parser, "channel")
            sys.exit(1)
    elif args.command == "provider":
        if args.provider_command == "ls":
            cmd_provider_ls()
        elif args.provider_command == "primary":
            cmd_provider_primary(args.provider, model=args.model)
        elif args.provider_command == "fallback":
            cmd_provider_fallback(args.provider, model=args.model, disable=args.disable)
        elif args.provider_command == "key":
            cmd_provider_key(args.provider)
        else:
            _print_group_help(parser, "provider")
            sys.exit(1)
    elif args.command == "status":
        sys.exit(cmd_status())
    elif args.command == "launch":
        cmd_launch(args.interface, demo=args.demo)
    elif args.command == "mcp":
        sys.exit(cmd_mcp(args.url, name=args.name, api_key=args.api_key))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()