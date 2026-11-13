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
_DOMAIN = re.compile(r"^\s*([a-z][a-z0-9_-]*):\s*\[([^\]]*)\]\s*$")


@dataclass
class _Node:
    name: str
    dynamic: bool = False
    children: list["_Node"] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    abstract: bool = False
    is_array: bool = False
    items: "_Node | None" = None
    domains: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def parameter(self) -> str | None:
        return self.name[1:-1] if self.name.startswith("{") and self.name.endswith("}") else None


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
        domain_owner: tuple[int, _Node] | None = None

        for source_line in source.read_text(encoding="utf-8").splitlines():
            line = source_line.split("#", 1)[0].rstrip()
            if not line:
                continue
            indent = len(line) - len(line.lstrip())
            if domain_owner is not None:
                domain_indent, owner = domain_owner
                if indent > domain_indent:
                    match = _DOMAIN.fullmatch(line)
                    if match is None:
                        raise ValueError("parameter domains require origin-keyed identifier lists")
                    values = tuple(value.strip() for value in match.group(2).split(","))
                    if (not values or len(values) != len(set(values))
                        or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value) for value in values)
                        or match.group(1) in owner.domains):
                        raise ValueError("parameter domains must be nonempty, unique identifier lists")
                    owner.domains[match.group(1)] = values
                    continue
                if not owner.domains:
                    raise ValueError("parameter domains must declare at least one origin")
                domain_owner = None
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
            if stack and line.strip() == "type: array":
                stack[-1][1].is_array = True
            if stack and line.strip() == "items:":
                node = _Node("")
                stack[-1][1].items = node
                stack.append((indent, node))
                continue
            if stack and line.strip() == "domains:":
                if stack[-1][1].parameter is None:
                    raise ValueError("domains belong to an ontology path parameter")
                domain_owner = (indent, stack[-1][1])
                continue
            reference = _REFERENCE.match(line)
            if reference and stack:
                stack[-1][1].references.append(reference.group(1))
            family = _FAMILY.match(line)
            if family and len(stack) == 1:
                stack[0][1].parents.append(family.group(1))
            if line.strip() == "abstract: true" and len(stack) == 1:
                stack[0][1].abstract = True

        if domain_owner is not None and not domain_owner[1].domains:
            raise ValueError("parameter domains must declare at least one origin")
        return cls(roots, frozenset(record_types))

    def _children(self, node: _Node, seen: frozenset[str] = frozenset()) -> list[_Node]:
        children = list(node.children)
        if node.items is not None:
            # Array elements do not introduce an 'items' semantic path segment.
            children.extend(self._children(node.items, seen))
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

    def _path_nodes(self, semantic_path: str) -> tuple[_Node, ...]:
        head, *components = semantic_path.split(".")
        if "@" in head:
            parts = head.split("@")
            if (len(parts) != 2 or not 1 <= len(parts[1].split(":")) <= 2
                or not all(parts[1].split(":"))):
                return ()
        root = self.roots.get(head.split("@", 1)[0])
        if root is None:
            return ()
        nodes = [root]
        for component in components:
            children = [child for node in nodes for child in self._children(node)]
            nodes = ([child for child in children if child.name == component]
                     or [child for child in children if child.dynamic])
        return tuple(nodes)

    def array_boundaries(self, semantic_path: str) -> tuple[str, ...]:
        """Return declared array prefixes, preserving the caller's qualifiers."""
        components = semantic_path.split(".")
        result = []
        for index in range(1, len(components) + 1):
            prefix = ".".join(components[:index])
            if any(node.is_array for node in self._path_nodes(prefix)):
                result.append(prefix)
        return tuple(result)

    def parameter_scopes(self, semantic_path: str) -> tuple[tuple[str, str], ...]:
        """Keep each parameter attached to its path, rather than a global name."""
        result = []
        components = semantic_path.split(".")
        for index in range(1, len(components) + 1):
            prefix = ".".join(components[:index])
            for node in self._path_nodes(prefix):
                if node.parameter is not None and (prefix, node.parameter) not in result:
                    result.append((prefix, node.parameter))
        return tuple(result)

    def parameter_domain(self, parameter_path: str, origin: str) -> tuple[str, ...] | None:
        domains = {node.domains[origin] for node in self._path_nodes(parameter_path)
                   if origin in node.domains}
        if len(domains) > 1:
            raise ValueError(f"ambiguous parameter domain at {parameter_path!r}")
        return next(iter(domains), None)

    def is_valid_element_path(self, collection_path: str, relative_path: str) -> bool:
        """Validate against declared items, never another Portfolio record."""
        if (not relative_path or "@" in relative_path
            or relative_path.split(".", 1)[0] in self.record_types):
            return False
        nodes = [node.items for node in self._path_nodes(collection_path)
                 if node.is_array and node.items is not None]
        for component in relative_path.split("."):
            children = [child for node in nodes for child in self._children(node)]
            nodes = ([child for child in children if child.name == component]
                     or [child for child in children if child.dynamic])
        return bool(nodes)

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
