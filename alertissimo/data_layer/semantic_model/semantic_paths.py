"""Ontology-backed validation of provider mapping semantic paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from alertissimo.data_layer.paths import ONTOLOGY_PATH


_DECLARATION = re.compile(r"^(<([^>]+)>|\[([^]]+)])\s*:")
_REFERENCE = re.compile(r"^\$(?:ref|refs):\s*<([^>]+)>")


@dataclass
class _Node:
    children: list[tuple[str, "_Node"]] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


class SemanticPathModel:
    """Resolve mapping paths through declarations and references in the ontology."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else ONTOLOGY_PATH
        self._roots: dict[str, _Node] = {}
        self._parse()
        portfolio = self._roots.get("portfolio")
        self.record_types = frozenset(portfolio.references if portfolio else ())

    def _parse(self) -> None:
        stack: list[tuple[int, _Node]] = []
        for source_line in self.path.read_text(encoding="utf-8").splitlines():
            line = source_line.lstrip()
            if not line or line.startswith("#"):
                continue
            indentation = len(source_line) - len(line)
            declaration = _DECLARATION.match(line)
            if declaration:
                name = declaration.group(2) or declaration.group(3)
                node = _Node()
                while stack and stack[-1][0] >= indentation:
                    stack.pop()
                if stack:
                    stack[-1][1].children.append((name, node))
                elif declaration.group(2) is not None:
                    self._roots[name] = node
                stack.append((indentation, node))
                continue

            reference = _REFERENCE.match(line)
            if reference:
                while stack and stack[-1][0] >= indentation:
                    stack.pop()
                if stack:
                    stack[-1][1].references.append(reference.group(1))

    @staticmethod
    def _matches(declared: str, actual: str) -> bool:
        return declared == actual or (
            declared.startswith("{") and declared.endswith("}") and bool(actual)
        )

    def _children(
        self, node: _Node, seen: frozenset[str] = frozenset()
    ) -> list[tuple[str, _Node]]:
        children = list(node.children)
        for reference in node.references:
            target = self._roots.get(reference)
            if target is None or reference in seen:
                continue
            if reference.startswith("_"):
                children.extend(self._children(target, seen | {reference}))
            else:
                children.append((reference, target))
        return children

    def is_valid_mapping_path(self, semantic_path: str) -> bool:
        """Return whether *semantic_path* resolves from a portfolio record type."""
        qualified_type, separator, relative_path = semantic_path.partition(".")
        record_type, qualifier, provenance = qualified_type.partition("@")
        if (
            not separator
            or not qualifier
            or not provenance
            or record_type not in self.record_types
            or not relative_path
        ):
            return False

        nodes = [self._roots[record_type]]
        for segment in relative_path.split("."):
            if not segment:
                return False
            nodes = [
                child
                for node in nodes
                for declared, child in self._children(node)
                if self._matches(declared, segment)
            ]
            if not nodes:
                return False
        return True

