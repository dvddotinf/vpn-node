import base64
from collections.abc import Callable
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route


STATIC_DIR = Path(__file__).with_name("static")

HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


def valid_public_key(value: str) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (ValueError, TypeError):
        return False


def create_app(
    register: Callable[[str, str], dict | None],
    get_status: Callable[[str], dict],
) -> Starlette:
    async def enrollment_page(request: Request):
        return FileResponse(
            STATIC_DIR / "enroll.html",
            headers=HEADERS,
        )

    async def style(request: Request):
        return FileResponse(
            STATIC_DIR / "style.css",
            media_type="text/css",
        )

    async def enrollment_js(request: Request):
        return FileResponse(
            STATIC_DIR / "enroll.js",
            media_type="text/javascript",
        )

    async def complete_enrollment(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "invalid request"},
                status_code=400,
                headers=HEADERS,
            )

        public_key = body.get("public_key")

        if not isinstance(public_key, str) or not valid_public_key(public_key):
            return JSONResponse(
                {"error": "invalid public key"},
                status_code=400,
                headers=HEADERS,
            )

        result = register(request.path_params["token"], public_key)

        if result is None:
            return JSONResponse(
                {"error": "enrollment expired or already used"},
                status_code=410,
                headers=HEADERS,
            )

        return JSONResponse(result, headers=HEADERS)

    async def health(request: Request):
        return Response(status_code=200)

    async def status_page(request: Request):
        return FileResponse(
            STATIC_DIR / "status.html",
            headers=HEADERS,
        )

    async def status_js(request: Request):
        return FileResponse(
            STATIC_DIR / "status.js",
            media_type="text/javascript",
        )

    async def status_data(request: Request):
        address = request.client.host if request.client else ""
        return JSONResponse(
            get_status(address),
            headers=HEADERS,
        )

    return Starlette(
        routes=[
            Route("/assets/style.css", style, methods=["GET"]),

            Route("/enroll/{token}", enrollment_page, methods=["GET"]),
            Route("/enroll/{token}", complete_enrollment, methods=["POST"]),

            Route("/health", health, methods=["GET"]),

            Route("/status", status_page, methods=["GET"]),
            Route("/status/data", status_data, methods=["GET"]),

            Route("/assets/enroll.js", enrollment_js, methods=["GET"]),
            Route("/assets/status.js", status_js, methods=["GET"]),
        ]
    )
