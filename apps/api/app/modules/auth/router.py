"""HTTP for the auth module.

Thin: validate -> call one service method -> map to a response. A route function
is at most ~15 lines and contains no `if` on business state
(`AC-FOUND-05.2`).

The rate-limit wiring is `AUTH-09`'s limiter applied at §9's specified
dimensions. It is *here* rather than in the service because it needs the request
- the client address and the submitted identifier - and a service that took a
`Request` would be a service that knows it is being called over HTTP.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.core import ratelimit
from app.modules.auth.schemas import RegisterRequest, RegisterResponse
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_service(request: Request) -> AuthService:
    """The service, built once in the app factory and injected.

    `01-foundations.md` §2: settings are "instantiated once in the app factory
    and injected". The same applies to what they configure.
    """
    service: AuthService = request.app.state.auth_service
    return service


def client_address(request: Request) -> str:
    """`AUTH-09` §9's client IP, resolved under the configured trust boundary."""
    settings = request.app.state.settings
    return ratelimit.client_ip(
        peer=request.client.host if request.client else None,
        forwarded_for=request.headers.get("X-Forwarded-For"),
        cf_connecting_ip=request.headers.get("CF-Connecting-IP"),
        trusted_cidrs=ratelimit.parse_cidrs(settings.TRUSTED_PROXY_CIDRS),
    )


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RegisterResponse,
    summary="Register an account",
)
async def register(
    body: RegisterRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_service)],
) -> RegisterResponse:
    """§1's registration. Always 202, whether or not the address was taken.

    `AC-AUTH-01.4` requires the two responses to be byte-identical, so the
    status and the body are fixed here and the service returns nothing to vary
    them with.
    """
    ip = client_address(request)
    limiter: ratelimit.RateLimiter = request.app.state.limiter
    await limiter.guard(
        "POST /api/v1/auth/register",
        ratelimit.register_buckets(request.app.state.settings, ip=ip),
    )

    await service.register(body, ip=ip)
    return RegisterResponse()


__all__ = ["router"]
