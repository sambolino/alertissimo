"""Errors raised by endpoint registry lookup and execution."""


class ExecutionError(RuntimeError):
    """Base error for the endpoint execution layer."""


class EndpointRegistryError(ExecutionError):
    """The endpoint registry is missing or internally inconsistent."""


class EndpointNotFoundError(ExecutionError):
    """No physical endpoint matches the requested broker/origin/name."""


class ParameterValidationError(ExecutionError):
    """Physical endpoint parameters do not satisfy the registry contract."""


class TransportNotConfiguredError(ExecutionError):
    """No transport was supplied for an endpoint's physical transport kind."""


class TransportExecutionError(ExecutionError):
    """A configured transport failed while executing an endpoint."""


class FixtureNotFoundError(ExecutionError):
    """A fixture transport has no payload registered for an endpoint."""


class MissingCredentialError(ExecutionError):
    """A credential required for live endpoint execution is unavailable."""


class ExampleCommandError(ExecutionError):
    """The provisional hardcoded command adapter does not know a command."""


__all__ = [
    "EndpointNotFoundError",
    "EndpointRegistryError",
    "ExampleCommandError",
    "ExecutionError",
    "FixtureNotFoundError",
    "MissingCredentialError",
    "ParameterValidationError",
    "TransportExecutionError",
    "TransportNotConfiguredError",
]
