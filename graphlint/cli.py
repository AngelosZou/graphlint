# -*- coding: utf-8 -*-
"""CLI entry point — auto-generates argparse interface from params.py."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from graphlint.i18n import I18nManager
from graphlint.params import PARAM_DEFS, ParamType


def build_parser(i18n: I18nManager) -> argparse.ArgumentParser:
    """Build argparse parser with query/build/config subcommands."""
    _t = i18n.t
    # Shared parent with --lang argument (available on both parent and subparsers)
    _lang_parser = argparse.ArgumentParser(add_help=False)
    _lang_parser.add_argument(
        "--lang",
        choices=["system", "zh_CN", "en"],
        default="system",
        dest="lang",
        help=_t("help.param.lang"),
    )
    parser = argparse.ArgumentParser(
        prog="graphlint",
        description=_t("help.description"),
        parents=[_lang_parser],
    )
    sub = parser.add_subparsers(dest="command", help=_t("help.subcommands"))

    # query subcommand
    qp = sub.add_parser("query", parents=[_lang_parser], help=_t("help.query"))
    for p in PARAM_DEFS:
        if p.category == "query" and not p.api_only:
            _add_arg(qp, p, _t)

    # build subcommand
    bp = sub.add_parser("build", parents=[_lang_parser], help=_t("help.build"))
    for p in PARAM_DEFS:
        if p.category == "build" and not p.api_only:
            _add_arg(bp, p, _t)

    # install subcommand
    sub.add_parser("install", parents=[_lang_parser], help=_t("help.install"))

    # uninstall subcommand
    sub.add_parser("uninstall", parents=[_lang_parser], help=_t("help.uninstall"))

    # config subcommand with sub-subcommands
    cp = sub.add_parser("config", parents=[_lang_parser], help=_t("help.config"))
    config_sub = cp.add_subparsers(
        dest="config_action", help=_t("help.config.operations")
    )

    # config show
    config_sub.add_parser("show", help=_t("help.config.show"))

    # config get <key>
    get_p = config_sub.add_parser("get", help=_t("help.config.get"))
    get_p.add_argument("--key", required=True, help=_t("help.param.config_key"))

    # config set <key> <value>
    set_p = config_sub.add_parser("set", help=_t("help.config.set"))
    set_p.add_argument("--key", required=True, help=_t("help.param.config_key"))
    set_p.add_argument("--value", required=True, help=_t("help.param.config_value"))

    # config copy-from <source>
    copy_p = config_sub.add_parser("copy-from", help=_t("help.config.copy_from"))
    copy_p.add_argument(
        "--from", dest="config_source", required=True, help=_t("help.param.config_source")
    )

    # config add-entry-rule
    addrule_p = config_sub.add_parser(
        "add-entry-rule", help=_t("help.config.add_entry_rule")
    )
    addrule_p.add_argument("--rule-json", required=True, help=_t("help.param.rule_json"))

    # config remove-entry-rule <name>
    removerule_p = config_sub.add_parser(
        "remove-entry-rule", help=_t("help.config.remove_entry_rule")
    )
    removerule_p.add_argument("--name", required=True, help=_t("help.param.rule_name"))

    # config add-exclude <pattern>
    addexcl_p = config_sub.add_parser("add-exclude", help=_t("help.config.add_exclude"))
    addexcl_p.add_argument("--exclude-pattern", required=True, help=_t("help.param.exclude_pattern"))

    # config remove-exclude <pattern>
    rmexcl_p = config_sub.add_parser(
        "remove-exclude", help=_t("help.config.remove_exclude")
    )
    rmexcl_p.add_argument("--exclude-pattern", required=True, help=_t("help.param.exclude_pattern"))

    return parser


def _add_arg(parser: argparse.ArgumentParser, param: Any, _t: Any = None) -> None:
    """Convert a ParamDef to an argparse argument."""
    help_text = _t(param.help_key) if _t is not None and param.help_key else param.help
    kwargs: dict[str, Any] = {
        "help": help_text,
        "dest": param.name,
    }
    if param.type == ParamType.FLAG:
        kwargs["action"] = "store_true"
        kwargs["default"] = False if param.default is None else param.default
    elif param.type == ParamType.CHOICE:
        kwargs["choices"] = param.choices
        kwargs["default"] = param.default
    elif param.type == ParamType.INT:
        kwargs["type"] = int
        if param.default is not None:
            kwargs["default"] = param.default
    elif param.type == ParamType.STR:
        kwargs["type"] = str
        kwargs["default"] = param.default
    elif param.type == ParamType.BOOL:
        kwargs["type"] = bool
        kwargs["default"] = param.default

    parser.add_argument(*param.cli_flags, **kwargs)


def main() -> int:
    """CLI main entry point."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Pre-parse --lang to initialize i18n for localized help text
    lang_parser = argparse.ArgumentParser(add_help=False)
    lang_parser.add_argument("--lang", default="system")
    pre_args, _ = lang_parser.parse_known_args()
    i18n = I18nManager(pre_args.lang)
    parser = build_parser(i18n)
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0
    command = args.command

    try:
        if command == "query":
            result = _run_query(args)
        elif command == "build":
            result = _run_build(args)
        elif command == "config":
            result = _run_config(args)
        elif command == "install":
            result = _run_install()
        elif command == "uninstall":
            result = _run_uninstall()
        else:
            parser.print_help()
            return 1

        if isinstance(result, dict):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(result)
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _run_install() -> str:
    """Execute the install command."""
    from graphlint.agent_tools import install_tools

    return install_tools()


def _run_uninstall() -> str:
    """Execute the uninstall command."""
    from graphlint.agent_tools import uninstall_tools

    return uninstall_tools()


def _run_query(args: argparse.Namespace) -> Any:
    """Execute the query command."""
    from graphlint.api import query

    kwargs = _args_to_kwargs(args, "query")
    return query(**kwargs)


def _run_build(args: argparse.Namespace) -> Any:
    """Execute the build command."""
    from graphlint.api import build

    kwargs = _args_to_kwargs(args, "build")
    return build(**kwargs)


def _run_config(args: argparse.Namespace) -> Any:
    """Execute the config command."""
    from graphlint.api import configure

    kwargs = _args_to_kwargs(args, "config")
    # Get the action from config_action
    action = getattr(args, "config_action", None) or getattr(
        args, "config_action", None
    )
    if action:
        kwargs["action"] = action
    return configure(**kwargs)


def _args_to_kwargs(args: argparse.Namespace, category: str) -> dict[str, Any]:
    """Convert argparse Namespace to API keyword arguments."""
    kwargs: dict[str, Any] = {}
    # First try getting key/value/source/rule_json/name/exclude_pattern from subcommand-matched dest
    if category == "config":
        if hasattr(args, "key") and args.key:
            kwargs["key"] = args.key
        if hasattr(args, "value") and args.value:
            kwargs["value"] = args.value
        if hasattr(args, "config_source") and args.config_source:
            kwargs["source"] = args.config_source
        if hasattr(args, "rule_json") and args.rule_json:
            kwargs["rule_json"] = args.rule_json
        if hasattr(args, "name") and args.name:
            kwargs["rule_name"] = args.name
        if hasattr(args, "exclude_pattern") and args.exclude_pattern:
            kwargs["exclude_pattern"] = args.exclude_pattern
    for p in PARAM_DEFS:
        if p.category == category and not p.cli_only:
            # Skip config_action since it's passed via the action parameter
            if p.name == "config_action":
                continue
            val = getattr(args, p.name, p.default)
            if val is not None or p.type == ParamType.FLAG:
                kwargs[p.name] = val
    # Always pass lang through to all commands
    lang_val = getattr(args, "lang", "system")
    if lang_val is not None:
        kwargs["lang"] = lang_val
    return kwargs


if __name__ == "__main__":
    sys.exit(main())
