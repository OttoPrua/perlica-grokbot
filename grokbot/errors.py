"""Typed failures with stable exit codes. Messages must never include secrets."""

from __future__ import annotations

from typing import Optional


class GrokbotError(Exception):
    """Operator-visible failure. ``str(self)`` is the public message."""

    exit_code = 1
    status = "rejected"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigError(GrokbotError):
    exit_code = 3
    status = "rejected"


class InputError(GrokbotError):
    exit_code = 4
    status = "rejected"


class HttpStatusError(GrokbotError):
    exit_code = 5
    status = "http_error"

    def __init__(self, message: str, http_status: int) -> None:
        super().__init__(message)
        self.http_status = http_status


class RedirectRejected(GrokbotError):
    exit_code = 6
    status = "redirect_rejected"

    def __init__(
        self,
        message: str,
        http_status: int,
        location_safe: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.location_safe = location_safe


class UnknownOutcome(GrokbotError):
    exit_code = 7
    status = "unknown"
