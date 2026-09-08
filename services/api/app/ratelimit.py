"""Tiny in-memory sliding-window rate limiter (single-process deploy)."""

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# path prefix -> (max requests, window seconds)
RULES = [
    ("/api/v1/auth/login", 10, 60),
    ("/api/v1/auth/signup", 5, 60),
    ("/api/v1/ai/chat", 30, 60),
    ("/api/v1/ai/onboarding", 10, 60),
    ("/api/v1/photos", 30, 60),
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        for prefix, limit, window in RULES:
            if path.startswith(prefix):
                key = (prefix, request.client.host if request.client else "unknown")
                now = time.monotonic()
                hits = self._hits[key]
                while hits and hits[0] < now - window:
                    hits.popleft()
                if len(hits) >= limit:
                    return JSONResponse({"detail": "Too many requests — slow down a little."}, status_code=429)
                hits.append(now)
                break
        return await call_next(request)
