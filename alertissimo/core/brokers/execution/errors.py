"""Endpoint execution exceptions."""


class EndpointExecutionError(RuntimeError):
    """Base class for physical endpoint execution failures."""


class EndpointNotFoundError(EndpointExecutionError, LookupError):
    """The requested broker/origin/endpoint is not registered."""


class ParameterValidationError(EndpointExecutionError, ValueError):
    """Physical endpoint parameters do not match the registry declaration."""


class CredentialError(EndpointExecutionError):
    """A required physical credential is unavailable."""
