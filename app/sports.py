"""Sport catalogue: the single source of truth for sport keys and their properties.

Everything that depends on the sport (labels and icons in the UI, pace vs speed,
moving-time threshold, best-effort distances, export codes, recognising the sport
in imported files) reads it from here. ``GET /api/sports`` hands it to the
frontend.

Unknown sport strings from files are kept as their normalised key and get the
generic defaults, so nothing is lost.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

RUN_EFFORTS = [400, 1000, 1609.344, 5000, 10000, 21097.5, 42195]
RIDE_EFFORTS = [5000, 10000, 20000, 40000, 100000]
FOOT_EFFORTS = [1000, 5000, 10000, 21097.5]
SKI_EFFORTS = [1000, 5000, 10000, 20000]
WATER_EFFORTS = [500, 1000, 5000, 10000]
SWIM_EFFORTS = [100, 400, 1000, 1500]


@dataclass(frozen=True)
class Sport:
    key: str
    label: str
    icon: str
    family: str  # running | cycling | foot | skiing | water | swimming | other
    pace: bool = False  # show pace (time per km/mi) instead of speed
    moving_ms: float = 0.5  # below this speed (m/s) the athlete counts as stopped
    efforts: list = field(default_factory=lambda: RUN_EFFORTS)
    cadence_unit: str = "spm"
    tcx: str = "Other"  # TCX Activity/@Sport
    fit: tuple[int, int] = (0, 0)  # FIT (sport, sub_sport)


SPORTS: dict[str, Sport] = {
    s.key: s
    for s in [
        Sport("running", "Running", "🏃", "running", pace=True, moving_ms=0.6, tcx="Running", fit=(1, 0)),
        Sport(
            "cycling",
            "Cycling",
            "🚴",
            "cycling",
            moving_ms=1.0,
            efforts=RIDE_EFFORTS,
            cadence_unit="rpm",
            tcx="Biking",
            fit=(2, 0),
        ),
        Sport(
            "road_cycling",
            "Road cycling",
            "🚴",
            "cycling",
            moving_ms=1.0,
            efforts=RIDE_EFFORTS,
            cadence_unit="rpm",
            tcx="Biking",
            fit=(2, 7),
        ),
        Sport(
            "gravel_cycling",
            "Gravel cycling",
            "🚲",
            "cycling",
            moving_ms=1.0,
            efforts=RIDE_EFFORTS,
            cadence_unit="rpm",
            tcx="Biking",
            fit=(2, 46),
        ),
        Sport(
            "mountain_biking",
            "Mountain biking (MTB)",
            "🚵",
            "cycling",
            moving_ms=0.8,
            efforts=RIDE_EFFORTS,
            cadence_unit="rpm",
            tcx="Biking",
            fit=(2, 8),
        ),
        Sport("walking", "Walking", "🚶", "foot", pace=True, moving_ms=0.3, efforts=FOOT_EFFORTS, fit=(11, 0)),
        Sport("hiking", "Hiking", "🥾", "foot", pace=True, moving_ms=0.3, efforts=FOOT_EFFORTS, fit=(17, 0)),
        Sport("skiing", "Skiing", "⛷️", "skiing", moving_ms=1.0, efforts=SKI_EFFORTS, fit=(13, 38)),
        Sport("ski_touring", "Ski touring", "🎿", "skiing", moving_ms=0.3, efforts=SKI_EFFORTS, fit=(13, 37)),
        Sport("sailing", "Sailing", "⛵", "water", moving_ms=0.3, efforts=WATER_EFFORTS, fit=(32, 0)),
        Sport(
            "kayaking", "Kayaking", "🛶", "water", moving_ms=0.3, efforts=WATER_EFFORTS, cadence_unit="spm", fit=(41, 0)
        ),
        Sport("swimming", "Swimming", "🏊", "swimming", pace=True, moving_ms=0.2, efforts=SWIM_EFFORTS, fit=(5, 0)),
        Sport("unknown", "Other", "⏱️", "other"),
    ]
}

# Names used by devices and apps (Garmin, Strava, Wahoo, FIT enums, GPX <type>, TCX),
# compared after lower-casing and removing spaces, dashes and underscores.
_ALIASES = {
    "running": [
        "run",
        "running",
        "trailrun",
        "trailrunning",
        "treadmill",
        "treadmillrunning",
        "virtualrun",
        "trackrunning",
        "indoorrunning",
    ],
    "cycling": [
        "cycling",
        "biking",
        "bike",
        "ride",
        "cycle",
        "ebikeride",
        "ebiking",
        "ebike",
        "virtualride",
        "indoorcycling",
        "handcycle",
        "velomobile",
    ],
    "road_cycling": ["road", "roadcycling", "roadbiking", "roadbike", "roadride"],
    "gravel_cycling": ["gravel", "gravelride", "gravelcycling", "gravelbiking", "cyclocross", "mixedsurface"],
    "mountain_biking": [
        "mtb",
        "mountain",
        "mountainbiking",
        "mountainbikeride",
        "mountainbike",
        "emountainbikeride",
        "ebikemountain",
        "downhill",
        "enduro",
    ],
    "walking": ["walk", "walking", "casualwalking", "speedwalking"],
    "hiking": ["hike", "hiking"],
    "skiing": [
        "skiing",
        "ski",
        "alpineski",
        "alpineskiing",
        "downhillskiing",
        "resort",
        "resortskiing",
        "resortskiingsnowboarding",
        "snowboard",
        "snowboarding",
    ],
    "ski_touring": [
        "skitouring",
        "skitour",
        "backcountryski",
        "backcountryskiing",
        "backcountry",
        "splitboard",
        "skimountaineering",
    ],
    "sailing": ["sail", "sailing", "boating"],
    "kayaking": ["kayak", "kayaking", "paddling", "canoe", "canoeing", "whitewater", "whitewaterkayaking"],
    "swimming": ["swim", "swimming", "openwaterswimming", "lapswimming"],
}
_LOOKUP = {alias: key for key, aliases in _ALIASES.items() for alias in aliases}


def _squash(raw) -> str:
    return str(raw).strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def normalise(raw, sub=None) -> str:
    """Map a sport name (and optional sub-sport) from any source to a catalogue key.

    The sub-sport wins when it is more specific (FIT ``cycling`` + ``mountain`` ->
    ``mountain_biking``; ``alpine_skiing`` + ``backcountry`` -> ``ski_touring``).
    Unknown names are kept, lower-case with underscores.
    """
    if raw is None or str(raw).strip() == "":
        return "unknown"
    base = _LOOKUP.get(_squash(raw))
    if sub is not None and str(sub).strip():
        refined = _LOOKUP.get(_squash(sub))
        # Only generic parents are refined, and only within their family (a "trail"
        # sub-sport must not turn a ride into a run, nor "whitewater" a sail into a kayak).
        if refined and base in ("cycling", "skiing", "kayaking") and SPORTS[refined].family == SPORTS[base].family:
            base = refined
    if base:
        return base
    key = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    return key or "unknown"


def get(key: str) -> Sport:
    """Catalogue entry for ``key``; unknown keys get the generic defaults with their own name."""
    if key in SPORTS:
        return SPORTS[key]
    return Sport(key, key.replace("_", " ").capitalize(), "⏱️", "other")


def catalogue() -> list[dict]:
    """JSON-ready list for the frontend (fixed order, as defined above)."""
    return [{k: v for k, v in asdict(s).items() if k not in ("efforts", "fit", "tcx")} for s in SPORTS.values()]
