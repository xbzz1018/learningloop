from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from learningloop.models import CallContext, ModelRoute

current_call_context: ContextVar[CallContext | None] = ContextVar(
    "learningloop_call_context", default=None
)
current_model_route: ContextVar[ModelRoute] = ContextVar(
    "learningloop_model_route", default=ModelRoute.FLASH
)


@contextmanager
def call_context(context: CallContext, route: ModelRoute) -> Iterator[None]:
    call_token = current_call_context.set(context)
    route_token = current_model_route.set(route)
    try:
        yield
    finally:
        current_call_context.reset(call_token)
        current_model_route.reset(route_token)
