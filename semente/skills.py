"""Engine-neutral skills loader and access tools.

Reads SKILL.md packages from a directory (name/description/instructions plus
scripts/references) and exposes them to any backend as a system-prompt snippet
plus three access tools (``get_skill_instructions`` / ``get_skill_reference`` /
``get_skill_script``). No engine import — the agno ``Skills`` system is
replaced by this native equivalent.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from semente.tools.types import Tool


@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    source_path: str
    scripts: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


def _parse_skill_md(content: str) -> tuple[dict, str]:
    frontmatter: dict = {}
    instructions = content
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if m:
        try:
            frontmatter = yaml.safe_load(m.group(1)) or {}
        except Exception:
            frontmatter = {}
        instructions = m.group(2).strip()
    return frontmatter, instructions


def _discover(folder: Path, subdir: str) -> list[str]:
    d = folder / subdir
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.startswith("."))


def load_skills(path: str | Path | list[str | Path]) -> "Skills | None":
    """Load skills from a directory, a single skill folder, or a list of
    either — ``None`` when nothing loads. On name collisions across paths,
    the later path wins."""
    roots = path if isinstance(path, (list, tuple)) else [path]

    loaded: dict[str, Skill] = {}
    for root_str in roots:
        root = Path(root_str)
        if not root.exists():
            continue

        if (root / "SKILL.md").exists():
            folders = [root]
        else:
            folders = [
                p
                for p in root.iterdir()
                if p.is_dir() and not p.name.startswith(".") and (p / "SKILL.md").exists()
            ]

        for folder in folders:
            try:
                content = (folder / "SKILL.md").read_text(encoding="utf-8")
                fm, instructions = _parse_skill_md(content)
                skill = Skill(
                    name=fm.get("name", folder.name),
                    description=fm.get("description", ""),
                    instructions=instructions,
                    source_path=str(folder),
                    scripts=_discover(folder, "scripts"),
                    references=_discover(folder, "references"),
                )
                loaded[skill.name] = skill  # later path wins on collisions
            except Exception:
                continue

    return Skills(list(loaded.values())) if loaded else None


def _is_safe_path(base_dir: Path, requested: str) -> bool:
    try:
        return (base_dir / requested).resolve().is_relative_to(base_dir.resolve())
    except (ValueError, OSError):
        return False


class Skills:
    """A loaded set of skills: prompt snippet + access tools (engine-neutral)."""

    def __init__(self, skills: list[Skill]):
        self._skills = {s.name: s for s in skills}

    def get_system_prompt_snippet(self) -> str:
        if not self._skills:
            return ""
        lines = [
            "<skills_system>",
            "",
            "## What are Skills?",
            "Skills are packages of domain expertise that extend your capabilities. Each skill contains:",
            "- **Instructions**: Detailed guidance on when and how to apply the skill",
            "- **Scripts**: Executable code templates you can use or adapt",
            "- **References**: Supporting documentation (guides, cheatsheets, examples)",
            "",
            "## IMPORTANT: How to Use Skills",
            "**Skill names are NOT callable functions.** You cannot call a skill directly by its name.",
            "Instead, you MUST use the provided skill access tools:",
            "",
            "1. `get_skill_instructions(skill_name)` - Load the full instructions for a skill",
            "2. `get_skill_reference(skill_name, reference_path)` - Access specific documentation",
            "3. `get_skill_script(skill_name, script_path, execute=False)` - Read or run scripts",
            "",
            "## Progressive Discovery Workflow",
            "1. **Browse**: Review the skill summaries below to understand what's available",
            "2. **Load**: When a task matches a skill, call `get_skill_instructions(skill_name)` first",
            "3. **Reference**: Use `get_skill_reference` to access specific documentation as needed",
            "4. **Scripts**: Use `get_skill_script` to read or execute scripts from a skill",
            "",
            "**IMPORTANT**: References are documentation files (NOT executable). Only use `get_skill_script` when `<scripts>` lists actual script files. If `<scripts>none</scripts>`, do NOT call `get_skill_script`.",
            "",
            "This approach ensures you only load detailed instructions when actually needed.",
            "",
            "## Available Skills",
        ]
        for skill in self._skills.values():
            lines.append("<skill>")
            lines.append(f"  <name>{skill.name}</name>")
            lines.append(f"  <description>{skill.description}</description>")
            lines.append(f"  <scripts>{', '.join(skill.scripts) if skill.scripts else 'none'}</scripts>")
            if skill.references:
                lines.append(f"  <references>{', '.join(skill.references)}</references>")
            lines.append("</skill>")
        lines.append("")
        lines.append("</skills_system>")
        return "\n".join(lines)

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="get_skill_instructions",
                func=self._get_skill_instructions,
                description="Load the full instructions for a skill. Use this when you need to follow a skill's guidance.",
            ),
            Tool(
                name="get_skill_reference",
                func=self._get_skill_reference,
                description="Load a reference document from a skill's references. Use this to access detailed documentation.",
            ),
            Tool(
                name="get_skill_script",
                func=self._get_skill_script,
                description="Read or execute a script from a skill. Set execute=True to run the script and get output, or execute=False (default) to read the script content.",
            ),
        ]

    def _get_skill_instructions(self, skill_name: str) -> str:
        skill = self._skills.get(skill_name)
        if skill is None:
            return json.dumps({"error": f"Skill '{skill_name}' not found", "available_skills": list(self._skills)})
        return json.dumps(
            {
                "skill_name": skill.name,
                "description": skill.description,
                "instructions": skill.instructions,
                "available_scripts": skill.scripts,
                "available_references": skill.references,
            }
        )

    def _get_skill_reference(self, skill_name: str, reference_path: str) -> str:
        skill = self._skills.get(skill_name)
        if skill is None:
            return json.dumps({"error": f"Skill '{skill_name}' not found", "available_skills": list(self._skills)})
        if reference_path not in skill.references:
            return json.dumps(
                {"error": f"Reference '{reference_path}' not found in skill '{skill_name}'", "available_references": skill.references}
            )
        refs_dir = Path(skill.source_path) / "references"
        if not _is_safe_path(refs_dir, reference_path):
            return json.dumps({"error": f"Invalid reference path: '{reference_path}'", "skill_name": skill_name})
        try:
            content = (refs_dir / reference_path).read_text(encoding="utf-8")
            return json.dumps({"skill_name": skill_name, "reference_path": reference_path, "content": content})
        except Exception as e:
            return json.dumps({"error": f"Error reading reference file: {e}", "skill_name": skill_name})

    def _get_skill_script(self, skill_name: str, script_path: str, execute: bool = False) -> str:
        skill = self._skills.get(skill_name)
        if skill is None:
            return json.dumps({"error": f"Skill '{skill_name}' not found", "available_skills": list(self._skills)})
        if script_path not in skill.scripts:
            return json.dumps(
                {"error": f"Script '{script_path}' not found in skill '{skill_name}'", "available_scripts": skill.scripts}
            )
        scripts_dir = Path(skill.source_path) / "scripts"
        if not _is_safe_path(scripts_dir, script_path):
            return json.dumps({"error": f"Invalid script path: '{script_path}'", "skill_name": skill_name})
        script_file = scripts_dir / script_path

        if not execute:
            try:
                content = script_file.read_text(encoding="utf-8")
                return json.dumps({"skill_name": skill_name, "script_path": script_path, "content": content})
            except Exception as e:
                return json.dumps({"error": f"Error reading script file: {e}", "skill_name": skill_name})

        try:
            result = subprocess.run(
                [str(script_file)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=Path(skill.source_path),
            )
            return json.dumps(
                {
                    "skill_name": skill_name,
                    "script_path": script_path,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                }
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Script execution timed out after 30 seconds", "skill_name": skill_name})
        except Exception as e:
            return json.dumps({"error": f"Error executing script: {e}", "skill_name": skill_name})
