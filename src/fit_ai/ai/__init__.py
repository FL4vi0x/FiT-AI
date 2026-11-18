"""AI Engine: a provider-independent contract for local language models (PoC 03 / P4).

Nothing here knows about FastAPI, OCTAVE, SQLite or the Core's HTTP API.
"""
from fit_ai.ai.config import LLMSettings
from fit_ai.ai.contracts import GenerateRequest, LLMProvider, RequestDefaults, prepare_request
from fit_ai.ai.errors import (
    LLMConfigurationError,
    LLMContextExceeded,
    LLMError,
    LLMIncompleteResponse,
    LLMInvalidRequest,
    LLMInvalidResponse,
    LLMModelNotFound,
    LLMModelUnavailable,
    LLMTimeout,
    LLMTransportError,
    LLMUnavailable,
)
from fit_ai.ai.fake_provider import FakeLLMProvider, Reply
from fit_ai.ai.identity import SystemPrompt, load_system_prompt
from fit_ai.ai.models import (
    ChatMessage,
    LLMResponse,
    ProviderHealth,
    Timings,
    ToolCall,
    ToolDefinition,
    Usage,
)
from fit_ai.ai.ollama_provider import OllamaProvider

__all__ = [
    "ChatMessage", "FakeLLMProvider", "GenerateRequest", "LLMConfigurationError", "LLMContextExceeded",
    "LLMError", "LLMIncompleteResponse", "LLMInvalidRequest", "LLMInvalidResponse", "LLMModelNotFound",
    "LLMModelUnavailable", "LLMProvider", "LLMResponse", "LLMSettings", "LLMTimeout", "LLMTransportError",
    "LLMUnavailable", "OllamaProvider", "ProviderHealth", "Reply", "RequestDefaults", "SystemPrompt",
    "Timings", "ToolCall", "ToolDefinition", "Usage", "load_system_prompt", "prepare_request",
]
