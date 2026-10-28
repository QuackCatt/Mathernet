class MathernetError(Exception):
    """Base error for user-facing Mathernet failures."""


class ValidationError(MathernetError):
    """Raised when stored or user-provided data is invalid."""


class StorageError(MathernetError):
    """Raised when local persistence cannot be completed safely."""


class SynthesisError(MathernetError):
    """Raised when the configured language model fails or returns invalid data."""


class RefusalError(MathernetError):
    """Raised when Mathernet must refuse a request."""

    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


class NotFoundError(MathernetError):
    """Raised when a requested local object does not exist."""


class ConflictError(MathernetError):
    """Raised when a change conflicts with a newer saved version."""
