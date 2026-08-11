"""Lexical index of declarations in the ordered semantic-model source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from alertissimo.data_layer.paths import ONTOLOGY_PATH


_CONTAINER = re.compile(r"^<([^>]+)>:")
_FIELD = re.compile(r"^\[([^]]+)]")
_EDGE = re.compile(r"^(--[^:\s]+):")
_REFERENCE = re.compile(r"^\$(?:ref|refs):\s*<([^>]+)>")


@dataclass(frozen=True)
class SemanticModelIndex:
    """Names lexically discoverable in an ordered ontology source."""

    path: Path
    containers: frozenset[str]
    fields: frozenset[str]
    edge_types: frozenset[str]
    record_types: frozenset[str] = frozenset()


def load_semantic_model_index(path: Path | None = None) -> SemanticModelIndex:
    """Read *path* as ordered text and index its static declarations.

    This deliberately does not interpret the ontology as generic YAML: repeated
    directives, declaration order, and scope are reserved for a future loader.
    """
    source_path = Path(path) if path is not None else ONTOLOGY_PATH
    containers: set[str] = set()
    fields: set[str] = set()
    edge_types: set[str] = set()
    record_types: set[str] = set()
    current_top_level: str | None = None

    for source_line in source_path.read_text(encoding="utf-8").splitlines():
        line = source_line.lstrip()
        indentation = len(source_line) - len(line)
        if not line or line.startswith("#"):
            continue

        container = _CONTAINER.match(line)
        if container and "{" not in container.group(1):
            containers.add(container.group(1))
        if container and indentation == 0:
            current_top_level = container.group(1)

        reference = _REFERENCE.match(line)
        if reference and current_top_level == "portfolio" and indentation > 0:
            record_types.add(reference.group(1))

        field = _FIELD.match(line)
        if field and "{" not in field.group(1):
            fields.add(field.group(1))

        edge = _EDGE.match(line)
        if edge:
            edge_types.add(edge.group(1))

    return SemanticModelIndex(
        path=source_path,
        containers=frozenset(containers),
        fields=frozenset(fields),
        edge_types=frozenset(edge_types),
        record_types=frozenset(record_types),
    )
