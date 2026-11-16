"""Module loader: discovers ``modules/<id>/module.json``, validates and loads selected modules.

Selection (``create_app(modules=...)``, ``python -m app --modules``, env ``FITPUSH_MODULES``):
``"all"`` (default: every module with ``enabled_by_default``), ``"none"`` (core only),
or a comma-separated list of ids.

A module that fails validation, import or ``register()`` is marked ``error`` and
skipped; the core and the other modules keep running. ``GET /api/modules`` shows
the status of every discovered module.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from .core import Core
from .paths import setting
from .sdk import SDK_VERSION, CoreAPI, ModuleContext, ModuleDB

log = logging.getLogger("fitpush.modules")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "modules"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
GITHUB_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
PROVIDES = {"page", "activity-card", "api", "events", "service"}
SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SERVICE_VERSION_RE = re.compile(r"^\d+\.\d+$")  # MAJOR.MINOR of one service (docs/SDK.md, "Services")
REQUIRED_DOCS = ("README.md", "MANUAL.md")
FRONTEND_FILES = ("frontend.js", "frontend.css")


@dataclass
class ModuleInfo:
    id: str
    dir: Path
    manifest: dict = field(default_factory=dict)
    status: str = "available"  # available | loaded | disabled | error
    errors: list[str] = field(default_factory=list)

    @property
    def frontend(self) -> bool:
        return (self.dir / "frontend.js").is_file()

    @property
    def css(self) -> bool:
        return (self.dir / "frontend.css").is_file()

    def public(self) -> dict:
        m = self.manifest
        return {
            "id": self.id,
            "name": m.get("name", self.id),
            "version": m.get("version"),
            "summary": m.get("summary"),
            "owner": m.get("owner"),
            "maintainers": m.get("maintainers", []),
            "provides": m.get("provides", []),
            "services": m.get("services", {}),
            "uses": m.get("uses", {}),
            "status": self.status,
            "errors": self.errors,
            "frontend": self.status == "loaded" and self.frontend,
            "css": self.status == "loaded" and self.css,
        }


def validate_manifest(manifest: dict, folder: Path) -> list[str]:
    """Problems with a module's manifest and required files (empty list = valid)."""
    errs: list[str] = []
    mid = manifest.get("id")
    if not isinstance(mid, str) or not ID_RE.match(mid):
        errs.append("id must match [a-z][a-z0-9_]{1,31}")
    elif mid != folder.name:
        errs.append(f"id {mid!r} must equal the folder name {folder.name!r}")
    for key in ("name", "summary"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            errs.append(f"{key} is required (non-empty string)")
    if len(manifest.get("summary") or "") > 140:
        errs.append("summary must be one line (<= 140 characters)")
    if not SEMVER_RE.match(str(manifest.get("version", ""))):
        errs.append("version must be semantic (e.g. 1.0.0)")
    owner = manifest.get("owner")
    if not isinstance(owner, dict) or not GITHUB_RE.match(str(owner.get("github", ""))):
        errs.append('owner must be {"github": "<github user id>"}')
    for m in manifest.get("maintainers", []):
        if not GITHUB_RE.match(str(m)):
            errs.append(f"maintainer {m!r} is not a GitHub user id")
    if str(manifest.get("sdk", "")).split(".")[0] != SDK_VERSION.split(".")[0]:
        errs.append(f'sdk must be "{SDK_VERSION.split(".")[0]}" (this core provides SDK {SDK_VERSION})')
    bad = set(manifest.get("provides", [])) - PROVIDES
    if bad or not manifest.get("provides"):
        errs.append(f"provides must list some of {sorted(PROVIDES)}")
    if not isinstance(manifest.get("depends", []), list):
        errs.append("depends must be a list of module ids")
    errs += _validate_services(manifest)
    for doc in REQUIRED_DOCS:
        if not (folder / doc).is_file():
            errs.append(f"{doc} is missing")
    if not (folder / "backend.py").is_file() and not (folder / "frontend.js").is_file():
        errs.append("a module needs backend.py and/or frontend.js")
    return errs


def _validate_services(manifest: dict) -> list[str]:
    """``services`` (what a service module offers, with versions) and ``uses`` (what a
    module calls in others, with the major version it was written for)."""
    errs = []
    services, uses = manifest.get("services", {}), manifest.get("uses", {})
    if not isinstance(services, dict) or not all(
        isinstance(k, str) and SERVICE_NAME_RE.match(k) and SERVICE_VERSION_RE.match(str(v))
        for k, v in services.items()
    ):
        errs.append('services must map service names to "MAJOR.MINOR" versions, e.g. {"place": "1.0"}')
    elif ("service" in manifest.get("provides", [])) != bool(services):
        errs.append('a module that provides "service" must declare its "services", and only such a module may')
    ok = isinstance(uses, dict) and all(
        isinstance(mid, str)
        and ID_RE.match(mid)
        and isinstance(names, dict)
        and names
        and all(isinstance(k, str) and SERVICE_NAME_RE.match(k) and type(v) is int and v >= 0 for k, v in names.items())
        for mid, names in uses.items()
    )
    if not ok:
        errs.append('uses must map module ids to {service: major version}, e.g. {"osm_places": {"place": 1}}')
    return errs


def discover(directory: Path | None = None) -> list[ModuleInfo]:
    directory = Path(directory or setting("MODULES_DIR") or DEFAULT_DIR)
    infos = []
    for manifest_path in sorted(directory.glob("*/module.json")):
        folder = manifest_path.parent
        info = ModuleInfo(id=folder.name, dir=folder)
        try:
            info.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            info.status, info.errors = "error", [f"module.json: {exc}"]
        else:
            if errs := validate_manifest(info.manifest, folder):
                info.status, info.errors = "error", errs
        infos.append(info)
    return infos


def _selected(infos: list[ModuleInfo], spec: str) -> set[str]:
    spec = (spec or "all").strip().lower()
    if spec == "none":
        return set()
    if spec == "all":
        return {i.id for i in infos if i.manifest.get("enabled_by_default", True)}
    return {s.strip() for s in spec.split(",") if s.strip()}


def load_modules(app: FastAPI, core: Core, spec: str | None = None, directory: Path | None = None) -> list[ModuleInfo]:
    """Discover, select and register modules on ``app``; returns every discovered module with its status."""
    spec = spec if spec is not None else (setting("MODULES") or "all")
    infos = discover(directory)
    by_id = {i.id: i for i in infos}
    wanted = _selected(infos, spec)
    for unknown in sorted(wanted - set(by_id)):
        log.warning("requested module %r not found", unknown)

    loaded: set[str] = set()
    services: dict = {}  # module id -> {name: fn}, shared by every ModuleContext
    versions: dict = {}  # module id -> {name: "MAJOR.MINOR"} of the services actually provided
    app.state.module_services = services
    app.state.module_service_versions = versions
    for info in _dependency_order([i for i in infos if i.id in wanted]):
        if info.status == "error":
            continue
        missing = [d for d in info.manifest.get("depends", []) if d not in loaded]
        if missing:
            info.status, info.errors = "error", [f"depends on modules that are not loaded: {', '.join(missing)}"]
            continue
        if _register(app, core, info, services, versions):
            loaded.add(info.id)
    for info in infos:
        if info.status == "available":
            info.status = "disabled"
    _add_routes(app, infos)
    return infos


def _dependency_order(infos: list[ModuleInfo]) -> list[ModuleInfo]:
    order, seen = [], set()
    by_id = {i.id: i for i in infos}

    def visit(i: ModuleInfo, stack: tuple = ()) -> None:
        if i.id in seen or i.id in stack:
            return
        for d in i.manifest.get("depends", []):
            if d in by_id:
                visit(by_id[d], (*stack, i.id))
        seen.add(i.id)
        order.append(i)

    for i in infos:
        visit(i)
    return order


def _register(app: FastAPI, core: Core, info: ModuleInfo, services: dict, versions: dict) -> bool:
    backend = info.dir / "backend.py"
    if backend.is_file():
        router = APIRouter(prefix=f"/api/m/{info.id}", tags=[f"module: {info.id}"])
        ctx = ModuleContext(
            id=info.id,
            manifest=info.manifest,
            dir=info.dir,
            core=CoreAPI(core),
            db=ModuleDB(core, info.id),
            router=router,
            _on=lambda ev, fn, _id=info.id: core.events.on(ev, fn, owner=_id),
            _services=services,
            _versions=versions,
        )
        try:
            spec = importlib.util.spec_from_file_location(f"fitpush_modules.{info.id}", backend)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {backend}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            if not callable(getattr(module, "register", None)):
                raise TypeError("backend.py must define register(ctx)")
            module.register(ctx)
        except Exception as exc:
            log.exception("module %s failed to load", info.id)
            core.events.off_owner(info.id)
            services.pop(info.id, None)
            versions.pop(info.id, None)
            info.status, info.errors = "error", [f"{type(exc).__name__}: {exc}"]
            return False
        app.include_router(router)
    info.status = "loaded"
    return True


def _add_routes(app: FastAPI, infos: list[ModuleInfo]) -> None:
    by_id = {i.id: i for i in infos}
    core: Core = app.state.core

    @app.get("/api/modules", tags=["modules"])
    def list_modules():
        """Every discovered module with owner, status (loaded/disabled/error) and errors."""
        out = []
        for i in infos:
            d = i.public()
            d["errors"] = d["errors"] + core.events.errors.get(i.id, [])
            out.append(d)
        return out

    @app.get("/api/modules/{module_id}/docs/{doc}", tags=["modules"], response_class=PlainTextResponse)
    def module_doc(module_id: str, doc: str):
        """README (intent) or MANUAL of a module, as Markdown."""
        info = by_id.get(module_id)
        name = {"readme": "README.md", "manual": "MANUAL.md"}.get(doc.lower())
        if not info or not name or not (info.dir / name).is_file():
            raise HTTPException(404, "document not found")
        return (info.dir / name).read_text(encoding="utf-8")

    @app.get("/m/{module_id}/{filename}", include_in_schema=False)
    def module_asset(module_id: str, filename: str):
        info = by_id.get(module_id)
        if not info or info.status != "loaded" or filename not in FRONTEND_FILES or not (info.dir / filename).is_file():
            raise HTTPException(404, "not found")
        media = "text/javascript" if filename.endswith(".js") else "text/css"
        return FileResponse(info.dir / filename, media_type=media, headers={"Cache-Control": "no-cache"})
