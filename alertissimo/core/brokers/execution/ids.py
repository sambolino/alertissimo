"""ID generation owned by the endpoint executor."""

from uuid import uuid4

from alertissimo.core.portfolio import InternalExecutionId


def new_internal_execution_id() -> InternalExecutionId:
    return InternalExecutionId(f"exec:{uuid4().hex}")

