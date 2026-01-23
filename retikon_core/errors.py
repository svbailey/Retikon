class RetikonError(Exception):
    """Base error for Retikon."""


class RecoverableError(RetikonError):
    """Indicates the operation can be retried safely."""


class PermanentError(RetikonError):
    """Indicates the operation should not be retried."""


class AuthError(RetikonError):
    """Authentication or authorization failure."""


class ValidationError(RetikonError):
    """Input validation failure."""
