"""Ontology-derived validation of provider semantic mapping paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from alertissimo.data_layer.paths import ONTOLOGY_PATH


_DECLARATION = re.compile(r"^(?P<indent>\s*)(?P<open><|\[)(?P<name>[^>\]]+)[>\]]:")
_REFERENCE = re.compile(r"^\s*\$ref:\s*<([^>]+)>")
_RECORD_REFERENCE = re.compile(r"^\s*\$refs:\s*<([^>]+)>@")
_FAMILY = re.compile(r"^\s*\$is:\s*<([^>]+)>\s*$")


@dataclass
class _Node:
    name: str
    dynamic: bool = False
    children: list["_Node"] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    abstract: bool = False


class SemanticPathModel:
    """Structural path model composed from the ordered ontology notation."""

    def __init__(self, roots: dict[str, _Node], record_types: frozenset[str]):
        self.roots = roots
        # Membership is independent of field composition. Validate even unused
        # families so malformed declarations cannot silently alter DSL nouns.
        for name in roots:
            self._ancestors(name)
        self.record_types = frozenset(
            name for name in roots
            if name in record_types or any(self.is_a(name, family) for family in record_types)
        )
        self.abstract_record_types = frozenset(
            name for name in self.record_types if roots[name].abstract
        )
        self.concrete_record_types = self.record_types - self.abstract_record_types

    def _ancestors(self, name: str, seen: frozenset[str] = frozenset()) -> frozenset[str]:
        if name in seen:
            raise ValueError(f"cyclic container $is relationship at {name!r}")
        if name not in self.roots:
            raise ValueError(f"unknown container $is parent {name!r}")
        result: set[str] = set()
        for parent in self.roots[name].parents:
            result.add(parent)
            result.update(self._ancestors(parent, seen | {name}))
        return frozenset(result)

    def is_a(self, name: str, family: str) -> bool:
        """Test declared transitive membership, without adding path segments."""
        return name in self.roots and (name == family or family in self._ancestors(name))

    def descendants(self, family: str) -> tuple[str, ...]:
        """Concrete Portfolio nouns admitted through a named family."""
        return tuple(sorted(
            name for name in self.concrete_record_types
            if name != family and self.is_a(name, family)
        ))

    @classmethod
    def from_ontology(cls, path: str | Path | None = None) -> "SemanticPathModel":
        source = Path(path) if path is not None else ONTOLOGY_PATH
        roots: dict[str, _Node] = {}
        stack: list[tuple[int, _Node]] = []
        record_types: set[str] = set()

        for source_line in source.read_text(encoding="utf-8").splitlines():
            line = source_line.split("#", 1)[0].rstrip()
            if not line:
                continue
            indent = len(line) - len(line.lstrip())
            while stack and stack[-1][0] >= indent:
                stack.pop()
            record_reference = _RECORD_REFERENCE.match(line)
            if record_reference and stack and stack[0][1].name == "portfolio":
                record_types.add(record_reference.group(1))
            declaration = _DECLARATION.match(line)
            if declaration:
                indent = len(declaration.group("indent"))
                name = declaration.group("name")
                node = _Node(name, dynamic="{" in name)
                if stack:
                    stack[-1][1].children.append(node)
                elif declaration.group("open") == "<":
                    roots[name] = node
                stack.append((indent, node))
                continue
            reference = _REFERENCE.match(line)
            if reference and stack:
                stack[-1][1].references.append(reference.group(1))
            family = _FAMILY.match(line)
            if family and len(stack) == 1:
                stack[0][1].parents.append(family.group(1))
            if line.strip() == "abstract: true" and len(stack) == 1:
                stack[0][1].abstract = True

        return cls(roots, frozenset(record_types))

    def _children(self, node: _Node, seen: frozenset[str] = frozenset()) -> list[_Node]:
        children = list(node.children)
        for reference in node.references:
            if reference in seen:
                continue
            target_name = reference
            if reference.startswith("_") and reference not in self.roots:
                target_name = reference[1:]
            target = self.roots.get(target_name)
            if target is None:
                continue
            if reference.startswith("_"):
                children.extend(self._children(target, seen | {reference}))
            else:
                children.append(target)
        return children

    def is_valid(self, semantic_path: str) -> bool:
        """Return whether *semantic_path* can be composed from the ontology."""
        head, separator, tail = semantic_path.partition(".")
        record_type, at, provider = head.partition("@")
        provider_parts = provider.split(":")
        if (
            head.count("@") != 1
            or not at
            or len(provider_parts) not in (1, 2)
            or not all(provider_parts)
            or record_type not in self.concrete_record_types
            or not tail
        ):
            return False
        nodes = self._children(self.roots[record_type])
        for component in tail.split("."):
            matches = [node for node in nodes if node.dynamic or node.name == component]
            if not matches:
                return False
            nodes = [child for match in matches for child in self._children(match)]
        return True
