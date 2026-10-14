"""Tutorial-example scaffolding — shared by ``semente init`` and ``config enable``.

Enabling the guided tutorial requires the domain to supply ``get_tutorial``
(the ``Tutorial`` seam). To spare the developer memorizing the API at the
moment of enabling, the CLI plants a working example (``<domain>/tutorial.py``)
and wires it into the ``DomainSpec``. The domain file is edited ONLY when the
edit is provably safe: a single module-level ``domain_spec = DomainSpec(...)``
assignment located via ``ast``, a kwarg inserted before the call's closing
paren, and a ``compile`` check afterwards — when anything is off, the
original source is left untouched and the one-line manual instruction is
returned instead.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from semente.cli.templates import TUTORIAL_TEMPLATE
from semente.manifest import Manifest

WIRE_KWARG = "get_tutorial"
SPEC_ASSIGN_NAME = "domain_spec"
SPEC_CLASS_NAME = "DomainSpec"


@dataclass
class TutorialScaffoldReport:
    """What the scaffold step did (callers print it; tests assert on it)."""

    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    wired_file: Optional[str] = None  # the DomainSpec source edited to pass get_tutorial
    already_wired: bool = False  # the spec already passed get_tutorial
    manual_step: Optional[str] = None  # printed when auto-wiring was not possible


class WireStatus(Enum):
    """Outcome of the (safety-gated) kwarg+import wiring."""

    WIRED = auto()  # source edited (kwarg inserted, import ensured)
    ALREADY_WIRED = auto()  # the spec already passes get_tutorial
    NO_SPEC = auto()  # no module-level domain_spec = DomainSpec(...) assignment
    UNSUPPORTED = auto()  # multiple assignments, or the edit failed its checks


def domain_source_path(manifest: Manifest, manifest_path: Path) -> Optional[Path]:
    """The domain module's source file (package ``__init__.py`` or module ``.py``).

    ``None`` when the module does not exist next to the manifest — the caller
    reports it instead of guessing paths.
    """
    dotted = manifest_path.parent.joinpath(*manifest.domain_module.split("."))
    package_init = dotted / "__init__.py"
    if package_init.is_file():
        return package_init
    single_file = dotted.with_suffix(".py")
    if single_file.is_file():
        return single_file
    return None


def _is_domain_spec_call(func: ast.expr) -> bool:
    """``DomainSpec`` as a bare name or dotted attribute access."""
    if isinstance(func, ast.Name):
        return func.id == SPEC_CLASS_NAME
    if isinstance(func, ast.Attribute):
        return func.attr == SPEC_CLASS_NAME
    return False


def _assigns_spec_name(node) -> bool:
    """The statement assigns to the ``domain_spec`` name."""
    if isinstance(node, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == SPEC_ASSIGN_NAME
            for target in node.targets
        )
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id == SPEC_ASSIGN_NAME
    return False


def _spec_assigns(tree: ast.Module) -> list:
    """Module-level ``domain_spec = DomainSpec(...)`` assignments."""
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.value, ast.Call)
        and _is_domain_spec_call(node.value.func)
        and _assigns_spec_name(node)
    ]


def _insert_offset(lines, lineno: int, col: int) -> int:
    """Absolute char offset of a (line, column) point across keepends lines."""
    return sum(len(line) for line in lines[: lineno - 1]) + col


def _insert_kwarg(source: str, tree: ast.Module) -> Optional[str]:
    """Insert ``get_tutorial=get_tutorial`` into the single DomainSpec call.

    Multiline calls gain an indented kwarg line just before the closing
    paren; single-line calls gain an inline kwarg. Returns None when the
    shapes do not allow a confident edit.
    """
    lines = source.splitlines(keepends=True)
    call = _spec_assigns(tree)[0].value
    end_line_start = _insert_offset(lines, call.end_lineno, 0)
    paren = end_line_start + call.end_col_offset - 1  # the close paren char

    if call.end_lineno == call.lineno:
        # One-line: ...(name="x", tools=[echo]) -> inline kwarg.
        return source[:paren] + f", {WIRE_KWARG}={WIRE_KWARG}" + source[paren:]

    # Indentation of the first argument line (template style: 4 spaces).
    first_arg = lines[call.lineno] if len(lines) > call.lineno else ""
    indent = first_arg[: len(first_arg) - len(first_arg.lstrip())].rstrip("\n")
    kwarg = f"{WIRE_KWARG}={WIRE_KWARG},"
    if lines[call.end_lineno - 1][:1] == ")":
        # The paren sits alone at the start of its line: give the kwarg its
        # own line and keep the paren where it is.
        return source[:paren] + f"{indent}{kwarg}\n" + source[paren:]
    return source[:paren] + f"\n{indent}{kwarg}" + source[paren:]


def _import_offset(root: ast.Module, lines) -> int:
    """Where an import line belongs: after the header's last import, else
    after the module docstring, else at the very top."""
    import_ends = [
        node.end_lineno
        for node in root.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    if import_ends:
        return _insert_offset(lines, max(import_ends) + 1, 0)

    doc_end = 0
    if root.body:
        first = root.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            doc_end = first.end_lineno
    return _insert_offset(lines, doc_end + 1, 0)


def wire_spec(source: str, import_line: Optional[str]) -> tuple[Optional[str], WireStatus]:
    """Ensure the source's ``domain_spec`` receives ``get_tutorial=get_tutorial``.

    Returns the edited source (or the original when already wired). Every
    edit ends with a ``compile`` check — a broken result is discarded and
    reported as :attr:`WireStatus.UNSUPPORTED` with the original source
    untouched. ``source`` without a single spec assignment is reported, not
    modified.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, WireStatus.UNSUPPORTED

    assigns = _spec_assigns(tree)
    if not assigns:
        return None, WireStatus.NO_SPEC
    if len(assigns) > 1:
        return None, WireStatus.UNSUPPORTED
    if any(kw.arg == WIRE_KWARG for kw in assigns[0].value.keywords):
        return source, WireStatus.ALREADY_WIRED

    wired = _insert_kwarg(source, tree)
    if wired is None:
        return None, WireStatus.UNSUPPORTED

    if import_line and import_line not in wired:
        try:
            root = ast.parse(wired)
        except SyntaxError:
            return None, WireStatus.UNSUPPORTED
        lines = wired.splitlines(keepends=True)
        offset = _import_offset(root, lines)
        wired = wired[:offset] + f"{import_line}\n" + wired[offset:]

    try:
        compile(wired, "<semente_tutorial_wiring>", "exec")
    except SyntaxError:
        return None, WireStatus.UNSUPPORTED

    return wired, WireStatus.WIRED


def scaffold_tutorial(
    manifest: Manifest, manifest_path: Path, force: bool = False
) -> TutorialScaffoldReport:
    """Plant the tutorial example and wire it into the app's domain.

    Package domains get the example at ``<domain_module>/tutorial.py`` and a
    relative import (``from .tutorial import get_tutorial``) — relative, so
    the app's ``domain`` package can never collide with the framework's
    ``semente.domain``. Single-file domains only get the manual instruction
    (no sibling module is invented). Files the scaffold already wrote are
    kept unless ``force``; the domain file is edited only when provably safe.
    """
    report = TutorialScaffoldReport()
    domain_file = domain_source_path(manifest, manifest_path)

    if domain_file is None:
        report.manual_step = (
            f"domain module '{manifest.domain_module}' not found next to {manifest_path}; "
            "create get_tutorial yourself — see docs/guide/domain-api.md"
        )
        return report

    source = domain_file.read_text(encoding="utf-8")
    is_package = domain_file.name == "__init__.py"

    tutorial_file: Optional[Path] = None
    import_line: Optional[str] = None
    if is_package:
        tutorial_file = domain_file.parent / "tutorial.py"
        import_line = "from .tutorial import get_tutorial"

    if tutorial_file is not None:
        if tutorial_file.exists() and not force:
            report.kept.append(str(tutorial_file))
        else:
            tutorial_file.write_text(
                TUTORIAL_TEMPLATE.format(name=manifest.name), encoding="utf-8"
            )
            report.created.append(str(tutorial_file))

    wired, status = wire_spec(
        source, import_line if tutorial_file is not None else None
    )

    if status in (WireStatus.WIRED, WireStatus.ALREADY_WIRED):
        if status is WireStatus.WIRED:
            domain_file.write_text(wired, encoding="utf-8")
        report.wired_file = str(domain_file)
        report.already_wired = status is WireStatus.ALREADY_WIRED
        if not is_package:
            # Single-file domain: nothing to plant — the implementation
            # belongs in the file itself (the import hint is meaningless).
            state = "already passes it" if report.already_wired else "now passes it"
            report.manual_step = (
                f"single-file domain: write def get_tutorial() -> Tutorial in "
                f"{domain_file} (docs/guide/domain-api.md) — the spec {state}"
            )
        return report

    if status is WireStatus.NO_SPEC:
        report.manual_step = (
            f"{domain_file} does not assign domain_spec = DomainSpec(...) yet; "
            "add get_tutorial=get_tutorial to the call — see docs/guide/domain-api.md"
        )
    else:
        report.manual_step = (
            f"{domain_file}'s domain_spec could not be edited safely; add manually: "
            "get_tutorial=get_tutorial in the DomainSpec(...) call"
        )

    if tutorial_file is not None and str(tutorial_file) not in report.created:
        # The example exists but the wiring could not be confirmed.
        report.manual_step = (
            f"{report.manual_step} (the example import is: '{import_line}')"
        )
    return report