"""Typed shared-dependency failures, separate from independent model judgments.

Use the official OpenAI/HTTPX exception contracts, not message matching or
timing heuristics. A request timeout alone does not prove a provider outage.
There is deliberately no retry, circuit timer, or semantic fallback here.
"""

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError


class ReviewDependencyError(Exception):
    """Stop the current executor without marking unattempted reviews failed."""

    def __init__(self, dependency: str, cause: Exception):
        self.dependency = dependency
        self.cause_code = type(cause).__name__
        self.status_code = getattr(cause, "status_code", None)
        super().__init__(f"{dependency}_dependency_unavailable:{self.cause_code}:{str(cause)[:1800]}")


def dependency_failure(error: Exception, dependency: str) -> ReviewDependencyError | None:
    if isinstance(error, ReviewDependencyError):
        return error
    if isinstance(error, APIConnectionError) and not isinstance(error, APITimeoutError):
        return ReviewDependencyError(dependency, error)
    if isinstance(error, (httpx.NetworkError, httpx.ProxyError)):
        return ReviewDependencyError(dependency, error)
    # These statuses identify access/configuration, capacity, or gateway
    # unavailability. 400/422, isolated timeouts, and an arbitrary HTTP 500
    # may instead depend on the current input and are not promoted to outages.
    if isinstance(error, (APIStatusError, httpx.HTTPStatusError)):
        status = getattr(error, "status_code", None)
        if status is None:
            status = error.response.status_code
        if status in {401, 403, 429, 502, 503, 504} or (dependency == "model" and status in {402, 404}):
            return ReviewDependencyError(dependency, error)
    return None
