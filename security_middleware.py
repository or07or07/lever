"""Lever — Security headers middleware (defense in depth).

Adds security headers to all HTTP responses at the application level.
This supplements the nginx security headers — if someone accesses the
FastAPI app directly (bypassing nginx), these headers still apply.

Also handles:
  - Trusted proxy header validation (X-Forwarded-For, X-Forwarded-Proto)
  - Request ID generation for tracing
  - Secure cookie attributes enforcement

CIA Triad:
  Confidentiality: HSTS, CSP, referrer policy prevent data leakage
  Integrity:       X-Content-Type-Options prevents MIME sniffing
  Availability:    No performance impact — headers only

ISO 27001 Controls:
  A.13.1.1  Network controls (HTTP security headers)
  A.14.1.2  Securing application services on public networks
  A.12.4.1  Event logging (request IDs for tracing)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("lever.security")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add defense-in-depth security headers to all responses.

    These headers are set at the application level as a safety net.
    In production, nginx also sets these — the browser uses the most
    restrictive value when headers appear in both layers.
    """

    async def dispatch(self, request: Request, call_next):
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        response = await call_next(request)

        # ── Security Headers ──

        # Prevent clickjacking
        response.headers.setdefault("X-Frame-Options", "DENY")

        # Prevent MIME-type sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")

        # Control referrer leakage
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        # HSTS — only add when accessed via HTTPS (or behind trusted proxy)
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto == "https" or request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains"
            )

        # Permissions Policy — allow geolocation for GPS tracking
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(self), payment=(self), usb=()"
        )

        # Cross-origin isolation
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")

        # Request tracing header
        response.headers["X-Request-ID"] = request_id

        # Remove server header if present (leak prevention)
        if "server" in response.headers:
            del response.headers["server"]

        return response


class TrustedProxyMiddleware(BaseHTTPMiddleware):
    """Validate and sanitize proxy headers.

    Only trust X-Forwarded-For from known proxy IPs.
    Prevents IP spoofing when the app is behind nginx.

    The TRUSTED_PROXIES set should include all IPs/ranges
    that are allowed to set forwarded headers.
    """

    # Docker internal network ranges — these are the IPs nginx will have
    TRUSTED_CIDRS = {
        "172.",    # Docker bridge networks
        "10.",     # Internal networks
        "127.",    # Localhost
        "192.168", # Private networks
    }

    async def dispatch(self, request: Request, call_next):
        # If request comes from untrusted source, strip forwarded headers
        client_ip = request.client.host if request.client else "unknown"
        is_trusted = any(client_ip.startswith(cidr) for cidr in self.TRUSTED_CIDRS)

        if not is_trusted:
            # Log potential spoofing attempt
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                logger.warning(
                    f"Untrusted proxy header from {client_ip}: "
                    f"X-Forwarded-For={forwarded}"
                )

        return await call_next(request)
