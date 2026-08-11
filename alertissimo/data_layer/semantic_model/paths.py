"""Ontology-backed semantic path reachability.

The ontology is an ordered YAML-like DSL, so this module intentionally parses
its declarations from text instead of passing it through a YAML loader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from alertissimo.data_layer.paths import ONTOLOGY_PATH


_CONTAINER = re.compile(r"^<([^>]+)>:\s*(?:#.*)?$")
_FIELD = re.compile(r"^\[([^]]+)](?:\s*:.*)?$")
_REFERENCE = re.compile(r"^\$refs?:\s*<([^>]+)>")


@dataclass
class _Node:
    name: str
    kind: str
    children: list["_Node"] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticPathModel:
    """Composed path model built from the ordered ontology source."""

    path: Path
    _roots: dict[str, _Node] = field(repr=False)

    @property
    def record_types(self) -> frozenset[str]:
        """Return the public, instantiable top-level container names."""
        return frozenset(name for name in self._roots if not name.startswith("_"))

    def is_valid(self, semantic_path: str) -> bool:
        """Return whether an unqualified ontology path is reachable."""
        parts = semantic_path.split(".")
        if not parts or any(not part for part in parts):
            return False
        root = self._roots.get(parts[0])
        return root is not None and self._matches_contents(root, parts[1:], frozenset())

    def is_valid_mapping_path(self, semantic_path: str) -> bool:
        """Validate a provider path after removing its record qualifier."""
        head, separator, tail = semantic_path.partition(".")
        if "@" not in head or not separator:
            return False
        record_type = head.split("@", 1)[0]
        return self.is_valid(f"{record_type}.{tail}")

    def is_valid_relative(self, record_type: str, field_path: str) -> bool:
        """Return whether *field_path* is reachable beneath *record_type*."""
        return self.is_valid(f"{record_type}.{field_path}")

    def normalize_mapping_path(self, semantic_path: str) -> str:
        """Return a provider semantic key in ontology path form."""
        head, separator, tail = semantic_path.partition(".")
        record_type = head.split("@", 1)[0]
        return f"{record_type}.{tail}" if separator else record_type

    def _matches_contents(
        self, node: _Node, parts: list[str], resolving: frozenset[str]
    ) -> bool:
        if not parts:
            # Parameter values and some records are mapped directly, so an
            # explicitly declared container is itself reachable as well.
            return True

        for child in node.children:
            if child.name == "{field}":
                # Dynamic fields are deliberately terminal and local.
                if len(parts) == 1:
                    return True
            elif child.name.startswith("{") or child.name == parts[0]:
                if self._matches_contents(child, parts[1:], resolving):
                    return True

        for reference in node.references:
            target_name = reference
            flatten = target_name.startswith("_")
            target = self._roots.get(target_name)
            # ``<_foo>`` is also the projection notation for the contents of
            # an instantiable ``<foo>`` container.
            if target is None and flatten:
                target = self._roots.get(target_name[1:])
            if target is None or target_name in resolving:
                continue
            next_resolving = resolving | {target_name}
            if flatten:
                if self._matches_contents(target, parts, next_resolving):
                    return True
            elif parts[0] == target.name and self._matches_contents(
                target, parts[1:], next_resolving
            ):
                return True
        return False


def load_semantic_path_model(path: Path | None = None) -> SemanticPathModel:
    """Parse ordered container, field, and reference declarations from *path*."""
    source_path = Path(path) if path is not None else ONTOLOGY_PATH
    roots: dict[str, _Node] = {}
    stack: list[tuple[int, _Node]] = []

    for source_line in source_path.read_text(encoding="utf-8").splitlines():
        stripped = source_line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(source_line) - len(stripped)
        while stack and stack[-1][0] >= indent:
            stack.pop()

        declaration = _CONTAINER.match(stripped)
        kind = "container"
        if declaration is None:
            declaration = _FIELD.match(stripped)
            kind = "field"
        if declaration is not None:
            node = _Node(declaration.group(1), kind)
            if stack:
                stack[-1][1].children.append(node)
            elif kind == "container":
                # Declarations are unique today; retaining the latest node is
                # preferable to pretending duplicate DSL keys were YAML data.
                roots[node.name] = node
            stack.append((indent, node))
            continue

        reference = _REFERENCE.match(stripped)
        if reference is not None and stack:
            stack[-1][1].references.append(reference.group(1))

    return SemanticPathModel(path=source_path, _roots=roots)
