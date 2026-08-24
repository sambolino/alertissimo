"""Conservative validation against the lexical semantic-model index."""

from __future__ import annotations

from alertissimo.data_layer.representations import Portfolio

from .index import SemanticModelIndex, load_semantic_model_index


class SemanticModelValidationError(ValueError):
    """Raised when a portfolio contradicts a known semantic-model declaration."""


def _validate_relative_field(field_path: str) -> bool:
    return not (
        not field_path
        or "@" in field_path
        or field_path.startswith("portfolio.")
        or field_path.startswith("--")
        or ".." in field_path
        or any(not segment.strip() for segment in field_path.split("."))
    )


def _is_connection_plane_symbol(edge_type: str) -> bool:
    return edge_type.startswith("--") and "--" in edge_type[2:]


def validate_portfolio_against_semantic_model(
    portfolio: Portfolio,
    semantic_model: SemanticModelIndex | None = None,
) -> None:
    """Validate only declarations and syntax understood by the lexical MVP."""
    model = semantic_model or load_semantic_model_index()

    for record in portfolio.records:
        base_type = record.semantic_type.split("@", 1)[0]
        if base_type.startswith("_") or base_type not in model.containers:
            raise SemanticModelValidationError(
                f"unknown semantic record type {base_type!r} "
                f"(from {record.semantic_type!r})"
            )
        for field_path in record.fields:
            if not _validate_relative_field(field_path):
                raise SemanticModelValidationError(
                    f"invalid relative record field path {field_path!r}"
                )

    for edge in portfolio.edges:
        if model.edge_types:
            valid_edge = edge.edge_type in model.edge_types
        else:
            valid_edge = _is_connection_plane_symbol(edge.edge_type)
        if not valid_edge:
            raise SemanticModelValidationError(
                f"unknown semantic edge type {edge.edge_type!r}"
            )
        for field_path in edge.fields:
            if not _validate_relative_field(field_path):
                raise SemanticModelValidationError(
                    f"invalid relative edge field path {field_path!r}"
                )
