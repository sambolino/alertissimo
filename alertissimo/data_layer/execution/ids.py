"""Identifiers owned by the provider execution boundary."""

from uuid import uuid4

from alertissimo.data_layer.representations import InternalExecutionId


def new_internal_execution_id() -> InternalExecutionId:
    return InternalExecutionId(f"exec:{uuid4().hex}")
