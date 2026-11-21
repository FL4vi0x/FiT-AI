"""HTTP layer of the chat: one route, uniform and sanitised errors. All logic lives in ConversationService."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from fit_ai.conversation.errors import ChatUnavailable, ConversationError, ServiceBusy
from fit_ai.conversation.models import ChatRequest, ChatResponse

log = logging.getLogger("fit_ai.api.chat")

# stable error code -> HTTP status (the conversation layer knows nothing about HTTP)
STATUS_BY_CODE = {
    "invalid_message": 422,
    "invalid_conversation_id": 422,
    "invalid_idempotency_key": 422,
    "idempotency_key_reuse": 422,
    "conversation_not_found": 404,
    "request_in_progress": 409,
    "service_busy": 429,
    "request_timeout": 504,
    "model_timeout": 504,
    "model_unavailable": 503,
    "model_not_found": 503,
    "audit_unavailable": 503,
    "storage_unavailable": 503,
    "chat_unavailable": 503,
}


class ErrorBody(BaseModel):
    code: str
    message: str


class ChatErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = None


router = APIRouter(tags=["chat"])
_ERRORS = {s: {"model": ChatErrorResponse} for s in sorted({400, 403, 404, 409, 413, 415, 422, 429, 500, 503, 504})}


def _request_id(request: Request) -> str:
    return request.scope.get("state", {}).get("request_id") or uuid.uuid4().hex


@router.post("/api/v1/chat", response_model=ChatResponse, responses=_ERRORS)
async def chat(body: ChatRequest, request: Request,
               idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> ChatResponse:
    """One conversation turn. The answer is always verified: numbers about the vehicle come only from readings
    taken in this turn; otherwise the answer is built by code from those readings (`fallback_used`)."""
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise ChatUnavailable()
    return await service.chat(body.message, body.conversation_id, request_id=_request_id(request),
                              idempotency_key=idempotency_key)


def _error(request: Request, status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, headers=headers,
                        content={"error": {"code": code, "message": message}, "request_id": _request_id(request)})


async def conversation_error_handler(request: Request, exc: ConversationError) -> JSONResponse:
    status = STATUS_BY_CODE.get(exc.code, 500)
    headers = {"Retry-After": str(exc.retry_after_s)} if isinstance(exc, ServiceBusy) else None
    return _error(request, status, exc.code, exc.safe_message, headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422/400 without echoing any submitted value (a message may contain something private)."""
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return _error(request, 400, "invalid_json", "The request body is not valid JSON.")
    fields = [{"field": ".".join(str(p) for p in e.get("loc", ()) if p != "body") or "body", "problem": e.get("type", "invalid")}
              for e in errors[:8]]
    body = {"error": {"code": "invalid_request", "message": "The request does not match the expected format."},
            "fields": fields, "request_id": _request_id(request)}
    return JSONResponse(status_code=422, content=body)


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    """Router/body errors (405, unreadable body...) get the same safe shape on the chat route; every other
    route keeps its previous behaviour untouched."""
    if request.url.path != "/api/v1/chat":
        return await default_http_exception_handler(request, exc)
    code = {400: "invalid_body", 404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    message = {400: "The request body could not be read.", 405: "Only POST is allowed on this route."}.get(
        exc.status_code, "The request could not be processed.")
    return _error(request, exc.status_code, code, message, dict(exc.headers) if exc.headers else None)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error in %s", request.url.path)  # full detail stays in the server log only
    return _error(request, 500, "internal_error", "An internal error occurred.")


def install_chat_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ConversationError, conversation_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
