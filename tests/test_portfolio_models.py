"""Tests for canonical internal portfolio data contracts."""

from dataclasses import FrozenInstanceError

import pytest

from alertissimo.core.portfolio import (
    InternalExecutionId,
    InternalExecutionProvenance,
    SemanticRecord,
)


def test_execution_provenance_optional_fields_can_be_absent():
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("exec:fixed"),
        broker="lasair",
        origin="ztf",
        endpoint="object",
    )

    assert provenance.params == {}
    assert provenance.sanitized_headers is None
    assert provenance.status is None
    assert not isinstance(provenance, SemanticRecord)


def test_execution_provenance_defensively_copies_mappings():
    params = {"objectId": "ZTF25aazqavg"}
    headers = {"Authorization": "<redacted>"}
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("exec:fixed"),
        broker="lasair",
        origin="ztf",
        endpoint="object",
        params=params,
        sanitized_headers=headers,
    )

    params["objectId"] = "changed"
    headers["Authorization"] = "secret"
    assert provenance.params == {"objectId": "ZTF25aazqavg"}
    assert provenance.sanitized_headers == {"Authorization": "<redacted>"}
    with pytest.raises(TypeError):
        provenance.params["new"] = True
    with pytest.raises(FrozenInstanceError):
        provenance.status = "changed"

