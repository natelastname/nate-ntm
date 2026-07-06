"""Unit tests for FastAPI runtime API helpers.

These tests currently focus on small, typed helpers that are specific to
:mod:`nate_ntm.api.runtime_api` rather than the transport-agnostic
JSON-RPC dispatcher (:mod:`nate_ntm.api.jsonrpc`).

In particular, they exercise the :class:`EventsHandshake` model used by
the ``/events`` WebSocket endpoint to normalise subscription handshakes
into a stable list of ``subscription_id`` values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nate_ntm.api.runtime_api import EventsHandshake


def test_events_handshake_resolves_single_subscription_id() -> None:
    """A lone ``subscription_id`` is normalised to a one-element list."""

    hs = EventsHandshake(subscription_id="sub-001")
    assert hs.resolved_ids() == ["sub-001"]


def test_events_handshake_resolves_multiple_subscription_ids() -> None:
    """A ``subscription_ids`` list is preserved in order."""

    hs = EventsHandshake(subscription_ids=["sub-001", "sub-002"])
    assert hs.resolved_ids() == ["sub-001", "sub-002"]


def test_events_handshake_handles_mixed_string_and_int_ids() -> None:
    """Integer IDs are converted to strings in ``resolved_ids``."""

    hs = EventsHandshake(subscription_ids=["sub-001", 2, 3])
    assert hs.resolved_ids() == ["sub-001", "2", "3"]


def test_events_handshake_missing_usable_ids_yields_empty_list() -> None:
    """When no usable IDs are present, ``resolved_ids`` returns an empty list.

    The WebSocket ``/events`` handler treats this as a protocol error and
    closes the connection with an appropriate status code. The model
    itself simply exposes the empty list so callers can apply their own
    policy.
    """

    hs = EventsHandshake()
    assert hs.resolved_ids() == []

    hs_empty_list = EventsHandshake(subscription_ids=[])
    assert hs_empty_list.resolved_ids() == []


def test_events_handshake_model_validate_json_rejects_malformed_json() -> None:
    """Malformed JSON payloads raise :class:`ValidationError`."""

    with pytest.raises(ValidationError):
        EventsHandshake.model_validate_json("not-json")


def test_events_handshake_model_validate_json_rejects_invalid_shape() -> None:
    """Type mismatches in the payload are rejected by validation.

    For example, a non-string ``subscription_id`` is not accepted.
    """

    with pytest.raises(ValidationError):
        EventsHandshake.model_validate_json("{""subscription_id"": 123}")
