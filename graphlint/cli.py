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

    # prompt subcommand
    sub.add_parser("prompt", parents=[_lang_parser], help=_t("help.prompt"))

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
            result, exit_code = _run_query(args)
            _print_result(result)
            return exit_code
        elif command == "config":
            result = _run_config(args)
            _print_result(result)
            if isinstance(result, dict) and result.get("status") == "error":
                return 1
            return 0
        elif command == "build":
            result = _run_build(args)
        elif command == "install":
            result = _run_install(i18n)
        elif command == "uninstall":
            result = _run_uninstall(i18n)
        elif command == "prompt":
            result = _run_prompt(i18n)
        else:
            parser.print_help()
            return 1

        _print_result(result)
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _print_result(result: Any) -> None:
    """Print result to stdout."""
    if isinstance(result, dict):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result)


def _check_json_warnings(json_result: Any, fail_types: set[str]) -> bool:
    """Check if JSON query result contains any warnings matching fail_types."""
    if not isinstance(json_result, dict):
        return False
    # List mode: check warnings_summary
    result_data = json_result.get("result", {})
    warnings_summary = result_data.get("warnings_summary", {})
    for ft in fail_types:
        if warnings_summary.get(ft, 0) > 0:
            return True
    # Per-graph is_dead_code flag (separate from warnings_summary entries)
    if "dead_code" in fail_types:
        for g in result_data.get("graphs", []):
            if isinstance(g, dict) and g.get("is_dead_code"):
                return True
    # Detail mode (--graph-id): check graph.warnings
    graph = json_result.get("graph", {})
    for w in graph.get("warnings", []):
        if isinstance(w, dict) and w.get("warn_type", "") in fail_types:
            return True
    return False


def _run_install(i18n: I18nManager) -> str:
    """Execute the install command."""
    from graphlint.agent_tools import install_tools

    result = install_tools(_t=i18n.t)
    return result + "\n\n" + i18n.t("cli.install.agent_not_found")


def _run_prompt(i18n: I18nManager) -> str:
    """Execute the prompt command — copy AGENT_PROMPT to clipboard."""
    from graphlint.agent_tools import copy_prompt_to_clipboard

    if copy_prompt_to_clipboard():
        return i18n.t("cli.prompt.copied")
    # Fallback: print the prompt text to stdout
    from graphlint.agent_tools import AGENT_PROMPT

    return AGENT_PROMPT + "\n\n" + i18n.t("cli.prompt.copied")


def _run_uninstall(i18n: I18nManager) -> str:
    """Execute the uninstall command."""
    from graphlint.agent_tools import uninstall_tools

    return uninstall_tools(_t=i18n.t)


def _run_query(args: argparse.Namespace) -> tuple[Any, int]:
    """Execute the query command. Returns (output, exit_code)."""
    from graphlint.api import query as api_query

    kwargs = _args_to_kwargs(args, "query")
    fail_on_str: str | None = getattr(args, "fail_on", None)

    if not fail_on_str:
        return api_query(**kwargs), 0

    fail_types = set(w.strip() for w in fail_on_str.split(",") if w.strip())
    if not fail_types:
        return api_query(**kwargs), 0

    json_kwargs = {**kwargs, "json_output": True}
    json_result = api_query(**json_kwargs)
    exit_code = 2 if _check_json_warnings(json_result, fail_types) else 0

    if kwargs.get("json_output"):
        return json_result, exit_code
    else:
        text_result = api_query(**kwargs)
        return text_result, exit_code


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
    if category != "config":
        for p in PARAM_DEFS:
            if p.category == category and not p.cli_only:
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
