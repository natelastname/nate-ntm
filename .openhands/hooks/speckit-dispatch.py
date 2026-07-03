#!/usr/bin/env python3

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

STATE_PATH = Path(".openhands/speckit/active-command.json")
EXTENSIONS_CONFIG_PATH = Path(".specify/extensions.yml")
REGISTRY_PATH = Path(".specify/extensions/.registry")


@dataclass(frozen=True)
class SpeckitCommand:
    name: str
    arguments: str

    @property
    def before_hook_key(self) -> str:
        return f"before_{self.name}"

    @property
    def after_hook_key(self) -> str:
        return f"after_{self.name}"


def main() -> int:
    phase = parse_phase()
    payload = read_stdin_payload()
    project_dir = find_project_dir(payload)

    if phase == "before":
        speckit_command = parse_speckit_command(extract_message(payload))
        if speckit_command is None:
            return allow()

        save_active_command(project_dir, speckit_command)
        return print_hook_context(project_dir, speckit_command, speckit_command.before_hook_key)

    if phase == "after":
        speckit_command = load_active_command(project_dir)
        if speckit_command is None:
            return allow()

        result = print_hook_context(project_dir, speckit_command, speckit_command.after_hook_key)
        clear_active_command(project_dir)
        return result

    return allow_context(f"Spec Kit dispatcher: unknown phase {phase!r}.")


def parse_phase() -> str:
    if len(sys.argv) >= 2:
        return sys.argv[1].strip().lower()
    return "before"


def read_stdin_payload() -> dict:
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return {}

    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError:
        return {"message": raw_input}

    return payload if isinstance(payload, dict) else {"message": raw_input}


def find_project_dir(payload: dict) -> Path:
    raw_project_dir = (
        os.environ.get("OPENHANDS_PROJECT_DIR")
        or payload.get("working_dir")
        or payload.get("cwd")
        or os.getcwd()
    )
    return Path(raw_project_dir).resolve()


def extract_message(payload: dict) -> str:
    for key in ("message", "prompt", "user_prompt"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def parse_speckit_command(message: str) -> SpeckitCommand | None:
    match = re.match(r"^\s*(?:/|\./)speckit\.([a-z0-9_]+)\b\s*(.*)$", message, re.DOTALL)
    if match is None:
        return None

    return SpeckitCommand(
        name=match.group(1),
        arguments=match.group(2).strip(),
    )


def save_active_command(project_dir: Path, speckit_command: SpeckitCommand) -> None:
    state_path = project_dir / STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {"name": speckit_command.name, "arguments": speckit_command.arguments},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def load_active_command(project_dir: Path) -> SpeckitCommand | None:
    state_path = project_dir / STATE_PATH
    if not state_path.exists():
        return None

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None

    name = payload.get("name")
    arguments = payload.get("arguments", "")

    if not isinstance(name, str) or not isinstance(arguments, str):
        return None

    return SpeckitCommand(name=name, arguments=arguments)


def clear_active_command(project_dir: Path) -> None:
    (project_dir / STATE_PATH).unlink(missing_ok=True)


def print_hook_context(project_dir: Path, speckit_command: SpeckitCommand, hook_key: str) -> int:
    extensions_config = read_yaml(project_dir / EXTENSIONS_CONFIG_PATH)
    registry = read_json(project_dir / REGISTRY_PATH)

    hooks = extensions_config.get("hooks", {}).get(hook_key, [])
    hooks_to_run = [
        hook for hook in hooks
        if should_include_hook(hook, extensions_config, registry)
    ]

    if not hooks_to_run:
        return allow()

    lines = [
        f"Spec Kit lifecycle hook: `{hook_key}`",
        "",
        "The following Spec Kit extension command recipes should be run by the agent before continuing:",
        "",
    ]

    for hook in hooks_to_run:
        extension_name = hook["extension"]
        command_name = hook["command"]
        command_file = resolve_command_file(project_dir, extension_name, command_name)

        lines.append(f"- Extension: `{extension_name}`")
        lines.append(f"  Command/skill: `{command_name}`")
        lines.append(f"  Optional: `{hook.get('optional', False)}`")
        lines.append(f"  Description: {hook.get('description', '')}")

        if command_file is not None:
            lines.append(f"  Recipe file: `{command_file.relative_to(project_dir)}`")
            lines.append(f"  Instruction: read and follow `{command_file.relative_to(project_dir)}`.")
        else:
            lines.append("  Recipe file: not found")

        lines.append("")

    lines.extend([
        f"Original Spec Kit command: `/speckit.{speckit_command.name}`",
        f"Original arguments: {speckit_command.arguments or '(none)'}",
    ])

    return allow_context("\n".join(lines))


def read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def should_include_hook(hook: dict, extensions_config: dict, registry: dict) -> bool:
    if hook.get("enabled", True) is False:
        return False

    extension_name = hook.get("extension")
    command_name = hook.get("command")

    if not isinstance(extension_name, str) or not isinstance(command_name, str):
        return False

    auto_execute_hooks = (
        extensions_config
        .get("settings", {})
        .get("auto_execute_hooks", True)
    )

    if hook.get("optional", False) and not auto_execute_hooks:
        return False

    return extension_enabled(registry, extension_name) and command_registered(
        registry,
        extension_name,
        command_name,
    )


def extension_enabled(registry: dict, extension_name: str) -> bool:
    extension = registry.get("extensions", {}).get(extension_name)
    return isinstance(extension, dict) and extension.get("enabled", True) is True


def command_registered(registry: dict, extension_name: str, command_name: str) -> bool:
    extension = registry.get("extensions", {}).get(extension_name)
    if not isinstance(extension, dict):
        return False

    registered_commands = extension.get("registered_commands", {})
    if not isinstance(registered_commands, dict):
        return False

    for commands in registered_commands.values():
        if isinstance(commands, list) and command_name in commands:
            return True

    return False


def resolve_command_file(project_dir: Path, extension_name: str, command_name: str) -> Path | None:
    extension_dir = project_dir / ".specify" / "extensions" / extension_name
    extension_manifest = read_yaml(extension_dir / "extension.yml")

    commands = extension_manifest.get("provides", {}).get("commands", [])
    if not isinstance(commands, list):
        return None

    for command in commands:
        if not isinstance(command, dict):
            continue
        if command.get("name") != command_name:
            continue

        relative_file = command.get("file")
        if not isinstance(relative_file, str):
            return None

        command_file = extension_dir / relative_file
        return command_file if command_file.exists() else None

    return None


def allow() -> int:
    return 0


def allow_context(context: str) -> int:
    print(json.dumps({"decision": "allow", "additionalContext": context}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
