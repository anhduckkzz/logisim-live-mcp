class LogisimMcpError(Exception):
    """Base error that is safe to expose to CLI and MCP clients."""


class PathNotAllowedError(LogisimMcpError):
    """Raised when a path escapes the configured allowlisted root."""


class ProjectNotOpenError(LogisimMcpError):
    """Raised when an operation requires an open project."""


class CircuitNotFoundError(LogisimMcpError):
    """Raised when a circuit name does not exist."""


class ComponentNotFoundError(LogisimMcpError):
    """Raised when a component selector matches no component."""


class AmbiguousComponentError(LogisimMcpError):
    """Raised when a component selector matches more than one component."""


class ValidationFailedError(LogisimMcpError):
    """Raised when saving an invalid project is attempted."""

