"""Application factory and local entry point (`python -m fit_ai`)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fit_ai import __version__
from fit_ai.adapters.octave import OctaveProvider
from fit_ai.api.chat_routes import install_chat_error_handlers
from fit_ai.api.chat_routes import router as chat_router
from fit_ai.api.routes import router, telemetry_error_handler
from fit_ai.api.speech_routes import install_speech
from fit_ai.api.security import BrowserGuard, HostGuard, RequestContext
from fit_ai.config import ConfigError, Settings
from fit_ai.conversation.config import ChatSettings
from fit_ai.conversation.factory import ChatRuntime, build_chat_runtime
from fit_ai.conversation.service import ConversationService
from fit_ai.conversation.warmup import start_background_warmup
from fit_ai.domain.telemetry import TelemetryError, TelemetryProvider
from fit_ai.services.llm_status import LLMStatusService
from fit_ai.services.telemetry import TelemetryService
from fit_ai.speech.config import SpeechSettings
from fit_ai.speech.faster_whisper_provider import FasterWhisperProvider
from fit_ai.speech.service import SpeechService

log = logging.getLogger("fit_ai")


def create_app(
    provider: TelemetryProvider | None = None,
    settings: Settings | None = None,
    conversation_service: ConversationService | None = None,
    chat_settings: ChatSettings | None = None,
    speech_service: SpeechService | None = None,
    speech_settings: SpeechSettings | None = None,
) -> FastAPI:
    """Build the app. Pass a `provider` to replace OCTAVE (tests, other sources).

    Chat: pass a `conversation_service` to use your own; when the real OCTAVE provider is used (no `provider`
    given) the production chat is wired automatically. Injecting only a `provider` does NOT create any
    database or model client, so tests stay hermetic. If chat cannot be set up, `POST /api/v1/chat` answers 503
    `chat_unavailable` and everything else keeps working."""
    production = provider is None
    if provider is None:
        settings = settings or Settings.from_env()
        provider = OctaveProvider(
            host=settings.octave_host,
            port=settings.octave_port,
            timeout_s=settings.octave_timeout_s,
            sdk_path=settings.octave_sdk_path,
        )

    chat_ok = True
    if chat_settings is None:
        try:
            chat_settings = ChatSettings.from_env()
        except ConfigError as exc:
            log.error("invalid chat settings, chat is disabled and the strict defaults apply: %s", exc)
            chat_settings, chat_ok = ChatSettings(), False

    # Speech recognition (P9.1) is built only in production, like the chat: injecting a provider alone creates no engine. Building the
    # service loads nothing: the model is read on the first transcription. Bad settings disable it, they never stop the Core.
    if speech_service is None and production:
        try:
            speech_settings = speech_settings or SpeechSettings.from_env()
            speech_service = SpeechService(FasterWhisperProvider(speech_settings), speech_settings)
        except ConfigError as exc:
            log.error("invalid speech settings, speech recognition is disabled: %s", exc)
    speech_limits = {"/api/v1/voice/transcribe": (speech_settings or SpeechSettings()).max_body_bytes}

    telemetry_service = TelemetryService(provider)
    runtime: ChatRuntime | None = None
    if conversation_service is None and production and chat_ok:
        runtime = build_chat_runtime(telemetry_service, chat_settings)
        conversation_service = runtime.service if runtime else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        warming = start_background_warmup(runtime)  # opt-in; returns at once, never delays the start
        yield
        if warming is not None and not warming.done():
            warming.cancel()
        if runtime is not None:
            await runtime.close()
        if speech_service is not None:
            await speech_service.close()
        close = getattr(provider, "aclose", None)
        if close is not None:
            await close()

    app = FastAPI(title="Fit AI Core", version=__version__, lifespan=lifespan)
    app.state.telemetry_service = telemetry_service
    app.state.conversation_service = conversation_service
    app.state.speech_service = speech_service
    # without a production chat runtime (tests, or chat disabled) there is no language model to report on
    app.state.llm_status_service = LLMStatusService(runtime.llm_health if runtime else None, model=runtime.model if runtime else None)
    app.add_exception_handler(TelemetryError, telemetry_error_handler)
    install_chat_error_handlers(app)
    app.include_router(router)
    app.include_router(chat_router)
    install_speech(app)
    # innermost first; HostGuard is outermost so a bad Host is refused before anything else looks at the request
    app.add_middleware(BrowserGuard, allowed_origins=chat_settings.allowed_origins,
                       max_body_bytes=chat_settings.max_body_bytes, audio_paths=speech_limits)
    app.add_middleware(RequestContext)
    app.add_middleware(HostGuard)  # DNS-rebinding protection: only local Host headers are served
    return app


def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env()  # refuses non-loopback hosts
        app = create_app(settings=settings)  # fails fast if the OCTAVE SDK is missing
    except (ConfigError, TelemetryError) as exc:
        raise SystemExit(f"fit-ai: cannot start: {exc}") from None
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    run()
