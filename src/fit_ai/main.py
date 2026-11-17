"""Application factory and local entry point (`python -m fit_ai`)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fit_ai import __version__
from fit_ai.adapters.octave import OctaveProvider
from fit_ai.api.routes import router, telemetry_error_handler
from fit_ai.api.security import HostGuard
from fit_ai.config import ConfigError, Settings
from fit_ai.domain.telemetry import TelemetryError, TelemetryProvider
from fit_ai.services.telemetry import TelemetryService


def create_app(provider: TelemetryProvider | None = None, settings: Settings | None = None) -> FastAPI:
    """Build the app. Pass a `provider` to replace OCTAVE (tests, other sources)."""
    if provider is None:
        settings = settings or Settings.from_env()
        provider = OctaveProvider(
            host=settings.octave_host,
            port=settings.octave_port,
            timeout_s=settings.octave_timeout_s,
            sdk_path=settings.octave_sdk_path,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        close = getattr(provider, "aclose", None)
        if close is not None:
            await close()

    app = FastAPI(title="Fit AI Core", version=__version__, lifespan=lifespan)
    app.state.telemetry_service = TelemetryService(provider)
    app.add_exception_handler(TelemetryError, telemetry_error_handler)
    app.include_router(router)
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
