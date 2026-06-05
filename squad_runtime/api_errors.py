"""Unified exception handlers for the Squad Runtime FastAPI app."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api_schemas import ErrorDetail, ErrorResponse


def _json_error(status_code: int, code: str, message: str, trace_id: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, traceId=trace_id))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    """Register unified exception handlers on a FastAPI application.

    Converts Python exceptions into structured JSON error responses:
      KeyError   -> 404
      ValueError -> 400
      PermissionError -> 403
    """

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
        trace_id = str(uuid.uuid4())
        message = f"Resource not found: {exc}"
        return _json_error(404, "not_found", message, trace_id)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        trace_id = str(uuid.uuid4())
        return _json_error(400, "bad_request", str(exc), trace_id)

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
        trace_id = str(uuid.uuid4())
        return _json_error(403, "forbidden", str(exc), trace_id)
