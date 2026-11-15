"""FastAPI application factory: core routes, optional modules and the static frontend."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import paths
from .core import Core, Invalid, NotFound
from .modules import load_modules
from .routes import activities, segments, system
from .storage import Store

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    db_path: str | Path | None = None, modules: str | None = None, modules_dir: str | Path | None = None
) -> FastAPI:
    """Build the app.

    ``db_path``: SQLite file (default: ``paths.db_path()``, the per-user data directory).
    ``modules``: ``"all"`` (default, env ``FITGIT_MODULES``), ``"none"`` for core only, or ``"a,b"``.
    ``modules_dir``: where modules live (default ``<repo>/modules``, env ``FITGIT_MODULES_DIR``).
    """
    store = Store(db_path or paths.db_path())
    core = Core(store)
    app = FastAPI(title="fit-git", version="0.2.0")
    app.state.store = store
    app.state.core = core

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Invalid)
    async def invalid(_: Request, exc: Invalid):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    for router in (activities.router, segments.router, system.router):
        app.include_router(router)
    app.state.modules = load_modules(app, core, modules, Path(modules_dir) if modules_dir else None)

    @app.middleware("http")
    async def revalidate_frontend(request: Request, call_next):
        # Browsers re-check (ETag) the page and its JS/CSS on every load, so a new
        # version is picked up without a hard refresh.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
