"""Typed errors of the AI Engine. `code` is stable and machine readable.

Messages never include prompts, model output or server response bodies.
"""
from __future__ import annotations

from fit_ai.config import ConfigError


class LLMError(Exception):
    code = "llm_error"


class LLMConfigurationError(LLMError, ConfigError):
    """The provider was given a setting it refuses (e.g. a non-loopback URL, an untagged model)."""

    code = "llm_configuration_error"


class LLMInvalidRequest(LLMError, ValueError):
    """The request violates the contract (empty messages, unknown tool shape, bad limits...)."""

    code = "llm_invalid_request"


class LLMUnavailable(LLMError):
    """Nothing is serving (connection refused/unreachable) or the provider was closed."""

    code = "llm_unavailable"


class LLMModelNotFound(LLMError):
    """The server is up but the configured model is not installed."""

    code = "llm_model_not_found"


class LLMModelUnavailable(LLMError):
    """The model exists but cannot be run now (for example not enough memory)."""

    code = "llm_model_unavailable"


class LLMTimeout(LLMError):
    code = "llm_timeout"


class LLMTransportError(LLMError):
    """Network or HTTP failure that is neither 'unavailable' nor 'timeout'."""

    code = "llm_transport_error"


class LLMInvalidResponse(LLMError):
    """The answer is malformed, or breaks the request (undeclared tool, invalid JSON when JSON was required)."""

    code = "llm_invalid_response"


class LLMIncompleteResponse(LLMError):
    """The answer stopped before completion in a way that makes it unusable."""

    code = "llm_incomplete_response"


class LLMContextExceeded(LLMError):
    """The prompt did not fit the context window (the server would silently truncate it)."""

    code = "llm_context_exceeded"
