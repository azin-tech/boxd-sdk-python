"""Exception hierarchy for the boxd SDK.

One base (:class:`BoxdError`) and one subclass per gRPC status family. Anything
the server returns that isn't in the table below surfaces as
:class:`APIStatusError` with the raw code attached, so a new server-side status
never turns into an opaque ``Exception``.
"""

from __future__ import annotations

import grpc


class BoxdError(Exception):
    """Base exception for all boxd SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        grpc_code: int | None = None,
    ):
        super().__init__(message)
        self.message = message
        # Canonical gRPC status name ("not_found", "unavailable", ...), or None
        # for errors raised before a call was ever made.
        self.code = code
        self.grpc_code = grpc_code


class AuthenticationError(BoxdError):
    """`unauthenticated` — no usable credential, or the credential was rejected.

    **Terminal.** An API-key session re-reads the key row on every request, so a
    mid-session rejection means the key is gone, not stale: refreshing and
    retrying would only spin against a revoked key.
    """


class PermissionDeniedError(BoxdError):
    """`permission_denied` — authenticated, but not allowed to do this."""


class NotFoundError(BoxdError):
    """`not_found` — no such machine/snapshot/disk/…"""


class ConflictError(BoxdError):
    """`already_exists`, `failed_precondition` or `aborted` — the request fights
    the current state, or the state changed while it ran (e.g. a machine's spec
    changed during ``update_spec``, which then changes nothing: read it again
    and retry)."""


class RateLimitError(BoxdError):
    """`resource_exhausted` — rate limit or quota."""


class APIStatusError(BoxdError):
    """Any other non-OK gRPC status."""


class APIConnectionError(BoxdError):
    """Transport failure — the request never got a status back."""


# gRPC status → exception class. Codes absent here fall through to
# APIStatusError; UNAVAILABLE is a transport failure by another name, so it
# lands on APIConnectionError (and is the one status we retry).
_STATUS_MAP: dict[grpc.StatusCode, type[BoxdError]] = {
    grpc.StatusCode.UNAUTHENTICATED: AuthenticationError,
    grpc.StatusCode.PERMISSION_DENIED: PermissionDeniedError,
    grpc.StatusCode.NOT_FOUND: NotFoundError,
    grpc.StatusCode.ALREADY_EXISTS: ConflictError,
    grpc.StatusCode.FAILED_PRECONDITION: ConflictError,
    grpc.StatusCode.ABORTED: ConflictError,
    grpc.StatusCode.RESOURCE_EXHAUSTED: RateLimitError,
    grpc.StatusCode.UNAVAILABLE: APIConnectionError,
}


def from_grpc_error(err: grpc.RpcError) -> BoxdError:
    """Convert a gRPC error (sync or aio) into the matching BoxdError."""
    code = err.code() if callable(getattr(err, "code", None)) else None
    details = err.details() if callable(getattr(err, "details", None)) else None
    cls = _STATUS_MAP.get(code, APIStatusError) if code is not None else APIConnectionError
    name = code.name.lower() if code is not None else None
    numeric = code.value[0] if code is not None else None
    return cls(details or str(err), code=name, grpc_code=numeric)


def is_retryable(err: grpc.RpcError) -> bool:
    """Retry only transport failures.

    `unavailable` is the sole retryable status. `deadline_exceeded` is
    deliberately *not* here: the server may already have applied a mutation, and
    the SDK can't tell a mutation from a read at this layer.
    """
    code = err.code() if callable(getattr(err, "code", None)) else None
    return code == grpc.StatusCode.UNAVAILABLE
