import os
import re
import time
import json
import hashlib
import hmac
import secrets
import threading
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, case
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from fastapi.responses import FileResponse, JSONResponse, Response
from echo_assistant import (
    EchoError, MissingAIConfiguration, SessionStore, capture_timings, interpret,
    resolve_contextual_followup, validate_intent,
)

# ---------- DATABASE SETUP ----------
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./campus.db")
engine_options = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ---------- MODELS ----------
class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, index=True)
    roll_no = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    department = Column(String, nullable=True)

class Program(Base):
    __tablename__ = "programs"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    start_date = Column(String, nullable=True)
    end_date = Column(String, nullable=True)
    status = Column(String, default="Draft")

class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, index=True)
    program_id = Column(Integer, ForeignKey("programs.id"), nullable=True)
    title = Column(String, nullable=False)
    category = Column(String, nullable=True)
    venue = Column(String, nullable=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    participation_type = Column(String, default="Individual")
    participant_instructions = Column(String, nullable=True)
    metadata_json = Column("metadata", String, nullable=True)
    status = Column(String, default="Draft")

class Registration(Base):
    __tablename__ = "registrations"
    id = Column(Integer, primary_key=True, index=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=False)
    student_name = Column(String, nullable=True)
    student_roll_no = Column(String, nullable=False)
    team_name = Column(String, nullable=True)
    team_members = Column(String, nullable=True)
    checked_in = Column(Boolean, default=False)
    created_at = Column(String, nullable=True)

class Requirement(Base):
    __tablename__ = "requirements"
    id = Column(Integer, primary_key=True, index=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=False)
    item_name = Column(String, nullable=False)
    quantity = Column(Integer, default=1)
    assigned_to = Column(String, nullable=True)
    status = Column(String, default="Pending")

# ---------- PYDANTIC SCHEMAS ----------
class HostLogin(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)

class RequirementIn(BaseModel):
    item_name: str
    quantity: int = 1
    assigned_to: Optional[str] = None

class ActivityCreate(BaseModel):
    program_id: Optional[int] = None
    title: str
    category: Optional[str] = None
    venue: Optional[str] = None
    start_time: str
    end_time: str
    participation_type: str = "Individual"
    participant_instructions: Optional[str] = None
    metadata: Optional[str] = None
    status: str = "Draft"
    requirements: List[RequirementIn] = Field(default_factory=list)

class StatusUpdate(BaseModel):
    status: str

class RegisterIn(BaseModel):
    student_name: str
    student_roll_no: str
    team_name: Optional[str] = None
    team_members: Optional[str] = None

class CheckinUpdate(BaseModel):
    checked_in: bool

class RequirementUpdate(BaseModel):
    status: str
    assigned_to: Optional[str] = None

# ---------- HOST AUTH ----------
def _admin_credentials_path() -> Path:
    configured = os.environ.get("ECHO_ADMIN_CREDENTIALS_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "EchoWeb" / "admin.env"


def _load_admin_credentials() -> tuple[Optional[str], Optional[str]]:
    values = {}
    path = _admin_credentials_path()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"ECHO_ADMIN_USERNAME", "ECHO_ADMIN_PASSWORD_HASH"}:
                values[key] = value.strip()
    except OSError:
        pass
    username = os.environ.get("ECHO_ADMIN_USERNAME") or values.get("ECHO_ADMIN_USERNAME")
    password_hash = os.environ.get("ECHO_ADMIN_PASSWORD_HASH") or values.get("ECHO_ADMIN_PASSWORD_HASH")
    return (username.strip() if username and username.strip() else None,
            password_hash.strip() if password_hash and password_hash.strip() else None)


ADMIN_USERNAME, ADMIN_PASSWORD_HASH = _load_admin_credentials()
ADMIN_SESSION_COOKIE = "echo_admin_session"
ADMIN_SESSION_SECONDS = 8 * 60 * 60
ADMIN_COOKIE_SECURE = os.environ.get("ECHO_ADMIN_COOKIE_SECURE", "1").strip().lower() not in {"0", "false", "no"}
_ADMIN_SESSIONS: dict[str, tuple[str, float]] = {}
_ADMIN_SESSION_LOCK = threading.Lock()
_ADMIN_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_ADMIN_LOGIN_LOCK = threading.Lock()
_ADMIN_LOGIN_WINDOW_SECONDS = 15 * 60
_ADMIN_LOGIN_MAX_ATTEMPTS = 8


def _verify_admin_password(password: str) -> bool:
    """Verify only salted PBKDF2-SHA256 hashes; plaintext credentials are unsupported."""
    if not ADMIN_PASSWORD_HASH:
        return False
    try:
        algorithm, rounds_text, salt_text, digest_text = ADMIN_PASSWORD_HASH.split("$", 3)
        rounds = int(rounds_text)
        if algorithm != "pbkdf2_sha256" or not 300_000 <= rounds <= 5_000_000:
            return False
        salt = bytes.fromhex(salt_text)
        expected = bytes.fromhex(digest_text)
        if len(salt) < 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def _admin_login_allowed(client_key: str) -> bool:
    now = time.monotonic()
    with _ADMIN_LOGIN_LOCK:
        attempts = [stamp for stamp in _ADMIN_LOGIN_ATTEMPTS.get(client_key, [])
                    if now - stamp < _ADMIN_LOGIN_WINDOW_SECONDS]
        if len(attempts) >= _ADMIN_LOGIN_MAX_ATTEMPTS:
            _ADMIN_LOGIN_ATTEMPTS[client_key] = attempts
            return False
        attempts.append(now)
        _ADMIN_LOGIN_ATTEMPTS[client_key] = attempts
        return True


def _new_admin_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _ADMIN_SESSION_LOCK:
        expired = [digest for digest, (_, expiry) in _ADMIN_SESSIONS.items() if expiry <= now]
        for digest in expired:
            _ADMIN_SESSIONS.pop(digest, None)
        _ADMIN_SESSIONS[hashlib.sha256(token.encode("ascii")).hexdigest()] = (
            username, now + ADMIN_SESSION_SECONDS
        )
    return token


def _get_admin_session(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _ADMIN_SESSION_LOCK:
        session = _ADMIN_SESSIONS.get(digest)
        if not session:
            return None
        username, expiry = session
        if expiry <= now:
            _ADMIN_SESSIONS.pop(digest, None)
            return None
        return username


def _revoke_admin_session(token: Optional[str]) -> None:
    if token:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with _ADMIN_SESSION_LOCK:
            _ADMIN_SESSIONS.pop(digest, None)


def require_admin(request: Request) -> str:
    username = _get_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE))
    if not username:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return username


def optional_admin(request: Request) -> Optional[str]:
    return _get_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE))

# ---------- APP ----------
app = FastAPI(title="Campus Activity Platform")
PUBLIC_DEMO_MODE = os.environ.get("ECHO_PUBLIC_DEMO_MODE", "0").strip().lower() in {"1", "true", "yes"}

allowed_origins = [origin.strip() for origin in os.environ.get(
    "ECHO_ALLOWED_ORIGINS",
    "http://localhost:5500,http://127.0.0.1:5500,http://localhost:8000,http://127.0.0.1:8000",
).split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)

Base.metadata.create_all(bind=engine)

# The live-test launcher uses this exact named SQLite shared-memory URI as an
# explicitly disposable demo database. Seed only this database, only when its
# Activity table is empty, and never run the destructive seed.py from the app.
_DISPOSABLE_DEMO_DATABASE_URL = "sqlite:///file:echo_web_ephemeral?mode=memory&cache=shared&uri=true"
# India observes one fixed offset year-round (UTC+05:30, no daylight saving).
_IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
_DISPOSABLE_DEMO_EVENTS = (
    {
        "title": "VEDA 2026 — National Conference on Emerging Trends in Vacuum Electronic Devices & Applications",
        "category": "Academic conference",
        "venue": "BITS Pilani, Hyderabad Campus",
        "start_time": "2026-12-20",
        "end_time": "2026-12-22",
        "participation_type": "Individual",
        "participant_instructions": "See the official BITS Pilani page for conference and registration information.",
        "official_source": "https://www.bits-pilani.ac.in/hyderabad/veda2026/",
        "status": "Published",
    },
    {
        "title": "ACEF 2027 — 8th Annual Conference on Economics and Finance",
        "category": "Academic conference",
        "venue": "BITS Pilani, Hyderabad Campus",
        "start_time": "2027-01-29",
        "end_time": "2027-01-30",
        "participation_type": "Individual",
        "participant_instructions": "See the official ACEF 2027 schedule and registration information.",
        "official_source": "https://www.bits-pilani.ac.in/hyderabad/acef2026/schedule/",
        "status": "Published",
    },
    {
        "title": "ATMOS 2026 — ATMOS '26: Augmented Ascension",
        "category": "Technical festival",
        "venue": "BITS Pilani, Hyderabad Campus",
        "start_time": "2026-10-23",
        "end_time": "2026-10-25",
        "participation_type": "Individual",
        "participant_instructions": "This event has ended. See the official ATMOS website for archived information.",
        "official_source": "https://www.atmos-bits.com/",
        "status": "Completed",
    },
)

def seed_verified_disposable_demo_events() -> int:
    if DATABASE_URL != _DISPOSABLE_DEMO_DATABASE_URL:
        return 0
    with SessionLocal() as db:
        existing = db.query(Activity).all()
        existing_titles = {" ".join((event.title or "").casefold().split()) for event in existing}
        existing_sources = set()
        for event in existing:
            try:
                metadata = json.loads(event.metadata_json or "{}")
                if isinstance(metadata, dict) and isinstance(metadata.get("official_source"), str):
                    existing_sources.add(metadata["official_source"].rstrip("/"))
            except (TypeError, json.JSONDecodeError):
                continue

        inserted = 0
        for item in _DISPOSABLE_DEMO_EVENTS:
            normalized_title = " ".join(item["title"].casefold().split())
            source_key = item["official_source"].rstrip("/")
            if normalized_title in existing_titles or source_key in existing_sources:
                continue
            metadata = {
                "official_source": item["official_source"],
                "timezone": "Asia/Kolkata",
                "time_precision": "date",
            }
            db.add(Activity(
                title=item["title"], category=item["category"], venue=item["venue"],
                start_time=item["start_time"], end_time=item["end_time"],
                participation_type=item["participation_type"],
                participant_instructions=item["participant_instructions"],
                metadata_json=json.dumps(metadata, ensure_ascii=False), status=item["status"],
            ))
            existing_titles.add(normalized_title)
            existing_sources.add(source_key)
            inserted += 1
        if inserted:
            db.commit()
        return inserted

if DATABASE_URL == _DISPOSABLE_DEMO_DATABASE_URL:
    seeded_count = seed_verified_disposable_demo_events()
    with SessionLocal() as db:
        demo_event_count = db.query(Activity).count()
    print(f"DEMO_EVENT_DB database=ephemeral-memory seeded={seeded_count} events={demo_event_count}", flush=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- ALGORITHMS ----------
def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end

def parse_dt(s):
    return datetime.fromisoformat(s)

VALID_TRANSITIONS = {
    "Draft": ["Published"],
    "Published": ["Ongoing"],
    "Ongoing": ["Completed"],
    "Completed": [],
}

def activity_student_dict(a, db):
    reqs = db.query(Requirement).filter(Requirement.activity_id == a.id).all()
    ready = sum(1 for r in reqs if r.status == "Arranged")
    return {
        "id": a.id,
        "program_id": a.program_id,
        "title": a.title,
        "category": a.category,
        "venue": a.venue,
        "start_time": a.start_time,
        "end_time": a.end_time,
        "participation_type": a.participation_type,
        "participant_instructions": a.participant_instructions,
        "status": a.status,
        "metadata": a.metadata_json,
        "requirements_ready": ready,
        "requirements_total": len(reqs),
    }

def activity_host_dict(a, db):
    d = activity_student_dict(a, db)
    reqs = db.query(Requirement).filter(Requirement.activity_id == a.id).all()
    regs = db.query(Registration).filter(Registration.activity_id == a.id).all()
    d["requirements"] = [
        {"id": r.id, "item_name": r.item_name, "quantity": r.quantity,
         "assigned_to": r.assigned_to, "status": r.status}
        for r in reqs
    ]
    d["registrations"] = [
        {"id": r.id, "student_name": r.student_name,
         "student_roll_no": r.student_roll_no, "team_name": r.team_name,
         "team_members": r.team_members, "checked_in": r.checked_in,
         "created_at": r.created_at}
        for r in regs
    ]
    return d

# ---------- ENDPOINTS ----------
@app.get("/")
def root():
    return {"message": "Campus Activity Platform API", "docs": "/docs"}


# Serve the existing site through the API origin so its browser client never
# needs a hard-coded LAN address or a public CORS wildcard.
ROOT_DIR = Path(__file__).resolve().parent

@app.get("/assets/style.css", include_in_schema=False)
def website_style():
    return FileResponse(ROOT_DIR / "style.css", media_type="text/css")

@app.get("/assets/script.js", include_in_schema=False)
def website_script():
    return FileResponse(ROOT_DIR / "script.js", media_type="application/javascript")

@app.get("/assets/echo-assistant.js", include_in_schema=False)
def echo_script():
    return FileResponse(ROOT_DIR / "echo-assistant.js", media_type="application/javascript")

@app.get("/assets/topography.svg", include_in_schema=False)
def website_topography():
    return FileResponse(ROOT_DIR / "assets" / "topography.svg", media_type="image/svg+xml")

@app.get("/assets/campus-bh.webp", include_in_schema=False)
def website_campus_background():
    return FileResponse(ROOT_DIR / "assets" / "campus-bh.webp", media_type="image/webp")

@app.get("/assets/topography-background.js", include_in_schema=False)
def website_topography_bundle():
    return FileResponse(ROOT_DIR / "assets" / "topography-background.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

@app.get("/assets/topography-background.css", include_in_schema=False)
def website_topography_styles():
    return FileResponse(ROOT_DIR / "assets" / "topography-background.css", media_type="text/css",
                        headers={"Cache-Control": "no-cache"})

@app.get("/website", include_in_schema=False)
@app.get("/website/", include_in_schema=False)
def website():
    return FileResponse(ROOT_DIR / "index.html")


class EchoCommand(BaseModel):
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    transcript: str = Field(min_length=1, max_length=1000)


echo_sessions = SessionStore(ttl_seconds=900, max_sessions=2000)
_echo_rate_lock = __import__("threading").Lock()
_echo_rate = {}


def _rate_check(key: str, maximum: int = 20):
    now = time.monotonic()
    with _echo_rate_lock:
        if len(_echo_rate) > 5000:
            for old_key in [k for k, stamps in _echo_rate.items() if not any(now - stamp < 60 for stamp in stamps)]:
                _echo_rate.pop(old_key, None)
        recent = [stamp for stamp in _echo_rate.get(key, []) if now - stamp < 60]
        if len(recent) >= maximum:
            raise HTTPException(status_code=429, detail="Echo is receiving requests too quickly. Try again in a minute.")
        recent.append(now)
        _echo_rate[key] = recent


@app.middleware("http")
async def limit_echo_request_body(request: Request, call_next):
    if request.url.path == "/api/echo/command":
        try:
            body_size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid request size."}, status_code=400)
        if body_size > 8192:
            return JSONResponse({"detail": "Echo requests must be under 8 KB."}, status_code=413)
    return await call_next(request)


@app.middleware("http")
async def echo_server_timing(request: Request, call_next):
    if request.url.path != "/api/echo/command":
        return await call_next(request)
    request.state.echo_metrics = {}
    started = time.perf_counter()
    response = await call_next(request)
    metrics = request.state.echo_metrics
    metrics["gateway"] = round((time.perf_counter() - started) * 1000, 2)
    fields = [f"{name};dur={value:.2f}" for name, value in metrics.items()]
    response.headers["Server-Timing"] = ", ".join(fields)
    return response


@app.middleware("http")
async def public_demo_route_guard(request: Request, call_next):
    """Fail closed for private/admin APIs when this process serves a public demo."""
    if not PUBLIC_DEMO_MODE:
        return await call_next(request)

    path = request.url.path
    method = request.method
    allowed = (
        (method == "GET" and path in {
            "/", "/website", "/website/", "/assets/style.css",
            "/assets/script.js", "/assets/echo-assistant.js",
            "/assets/topography.svg", "/assets/campus-bh.webp",
            "/assets/topography-background.js", "/assets/topography-background.css",
        })
        or (method == "POST" and path == "/api/echo/command")
        or (method == "GET" and path == "/api/activities")
        or (method == "GET" and re.fullmatch(r"/api/activities/\d+", path)
            and request.query_params.get("view", "student") != "host")
    )
    if not allowed:
        return JSONResponse({"detail": "This route is disabled in public demo mode."}, status_code=404)
    return await call_next(request)


@app.middleware("http")
async def prevent_admin_response_caching(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    private_read = (
        path.startswith("/api/host/")
        or path == "/api/programs"
        or (path == "/api/activities" and request.query_params.get("status") == "Draft")
        or (re.fullmatch(r"/api/activities/\d+", path)
            and request.query_params.get("view") == "host")
    )
    if private_read or (path == "/api/host/login" and request.method == "POST"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


def _public_activity(a):
    timing_status = "Unknown"
    try:
        start = datetime.fromisoformat(a.start_time)
        end = datetime.fromisoformat(a.end_time)
        if start.tzinfo is None:
            start = start.replace(tzinfo=_IST)
        if len(a.end_time) == 10:
            end = end.replace(hour=23, minute=59, second=59, tzinfo=_IST)
        elif end.tzinfo is None:
            end = end.replace(tzinfo=_IST)
        now = datetime.now(_IST)
        if end < now:
            timing_status = "Past"
        elif start > now:
            timing_status = "Upcoming"
        else:
            timing_status = "Ongoing"
    except (TypeError, ValueError):
        pass
    return {
        "activity_id": a.id, "title": a.title, "category": a.category,
        "venue": a.venue, "start_time": a.start_time, "end_time": a.end_time,
        "participation_type": a.participation_type, "status": a.status,
        "timing_status": timing_status,
        "participant_instructions": a.participant_instructions,
    }


def _search_activities(db: Session, query: str, status: Optional[str] = None, upcoming: bool = False):
    q = db.query(Activity).filter(Activity.status != "Draft")
    if status in {"Published", "Ongoing", "Completed"}:
        q = q.filter(Activity.status == status)
    if upcoming:
        q = q.filter(Activity.start_time >= datetime.now(_IST).isoformat(timespec="minutes"))
        q = q.filter(Activity.status.in_(["Published", "Ongoing"]))
    ignored = {"find", "show", "search", "event", "events", "the", "some", "upcoming", "next", "please", "for", "all"}
    terms = [part.strip(".,!?;:").casefold() for part in query.split()
             if len(part.strip(".,!?;:").strip()) >= 2 and part.strip(".,!?;:").casefold() not in ignored][:8]
    for term in terms:
        pattern = f"%{term}%"
        q = q.filter((Activity.title.ilike(pattern)) | (Activity.category.ilike(pattern)) | (Activity.venue.ilike(pattern)))
    return q.order_by(case((Activity.status == "Published", 0),
                           (Activity.status == "Ongoing", 1), else_=2),
                      Activity.start_time.asc(), Activity.id.asc()).limit(50).all()


@app.post("/api/echo/command")
def echo_command(body: EchoCommand, request: Request, db: Session = Depends(get_db)):
    transcript = body.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="Please say or type a request for Echo.")
    client_host = request.client.host if request.client else "unknown"
    _rate_check(f"session:{body.session_id}", 5 if PUBLIC_DEMO_MODE else 20)
    # Tunnel requests can share a loopback client address, so public mode uses
    # a conservative aggregate client limit as well as per-session limiting.
    _rate_check(f"client:{client_host}", 30 if PUBLIC_DEMO_MODE else 120)
    state = echo_sessions.ensure(body.session_id)

    lower = transcript.casefold().strip()
    # These controls are local browser actions, but intercept them server-side
    # too so typed commands never incur an AI call or speech delay.
    if re.fullmatch(r"(?:echo[, ]*)?(?:please )?(?:be quiet|stop talking|stop speaking|shut up)(?: now)?[.! ]*", lower):
        return {"session_id": body.session_id, "speech_text": "Okay, I’ll be quiet.", "action": {"action": "stop_speaking"}}

    try:
        followup_started = time.perf_counter()
        intent = resolve_contextual_followup(transcript, state)
        if intent is not None:
            request.state.echo_metrics["local_followup"] = round((time.perf_counter() - followup_started) * 1000, 2)
        else:
            with capture_timings(request.state.echo_metrics):
                intent = validate_intent(interpret(transcript, state["history"], state.get("result_titles", [])))
    except MissingAIConfiguration as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EchoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    action_started = time.perf_counter()
    kind = intent["intent"]
    speech = ""
    action = {"action": "answer", "text": ""}

    if kind == "answer":
        speech = intent["text"]
        action = {"action": "answer", "text": speech}
    elif kind == "clarify":
        speech = intent["prompt"]
        action = {"action": "clarify", "prompt": speech}
    elif kind == "unsupported":
        speech = intent["message"]
        action = {"action": "unsupported", "message": speech}
    elif kind == "search_events":
        query = intent["query"]
        all_matches = _search_activities(db, query, intent.get("status"), intent.get("upcoming", False))
        ids = [row.id for row in all_matches]
        echo_sessions.remember_results(body.session_id, ids, query=query, offset=min(5, len(ids)),
                                       titles=[row.title for row in all_matches])
        page = all_matches[:5]
        results = [_public_activity(row) for row in page]
        if results:
            speech = f"I found {len(all_matches)} matching event{'s' if len(all_matches) != 1 else ''}. Showing the first {len(results)}."
        else:
            speech = "I couldn't find a matching event in the published event list. Try another title, category, or venue."
        action = {"action": "search_events", "query": query, "results": results, "has_more": len(all_matches) > 5}
    elif kind == "show_more_events":
        saved = echo_sessions.get(body.session_id)
        matches = db.query(Activity).filter(Activity.id.in_(saved["result_ids"])).all() if saved["result_ids"] else []
        by_id = {row.id: row for row in matches}
        offset = saved["offset"]
        page_ids = saved["result_ids"][offset:offset + 5]
        rows = [by_id[event_id] for event_id in page_ids if event_id in by_id]
        echo_sessions.set_offset(body.session_id, offset + len(page_ids))
        results = [_public_activity(row) for row in rows]
        speech = f"Here are {len(results)} more events." if results else "There aren't any more results to show."
        action = {"action": "search_events", "query": saved["query"] or "", "results": results,
                  "has_more": offset + len(page_ids) < len(saved["result_ids"])}
    elif kind in {"open_event", "show_event_details"}:
        saved = echo_sessions.get(body.session_id)
        index = intent.get("result_index")
        event_id = echo_sessions.select_result(body.session_id, index) if index else saved["selected_id"]
        if not event_id:
            speech = "Which event do you mean? Search for an event first, or say a result number."
            action = {"action": "clarify", "prompt": speech}
        else:
            event = db.query(Activity).filter(Activity.id == event_id, Activity.status != "Draft").first()
            if not event:
                speech = "That event is no longer available. Search for it again and I’ll refresh the results."
                action = {"action": "clarify", "prompt": speech}
            else:
                echo_sessions.select_event(body.session_id, event_id)
                details = _public_activity(event)
                speech = f"{event.title}. {event.status}. At {event.venue or 'venue to be announced'}. Starts {event.start_time}."
                action = {"action": "open_event" if kind == "open_event" else "show_event_details", "event": details}
    elif kind == "navigate":
        route = intent["route"]
        speech = {
            "home": "Going to the role selection page.",
            "campus": "Opening the campus landing page.",
            "map": "Opening the campus map section.",
            "events": "Opening events.",
            "contacts": "Opening the campus contacts.",
            "announcements": "Opening announcements.",
            "progress": "Opening the activity progress section.",
        }[route]
        action = {"action": "navigate", "route": route}
    elif kind == "scroll":
        direction = intent["direction"]
        speech = "Scrolling down." if direction == "down" else "Scrolling up."
        action = {"action": "scroll", "direction": direction}

    echo_sessions.add_turn(body.session_id, transcript, speech)
    request.state.echo_metrics["action"] = round((time.perf_counter() - action_started) * 1000, 2)
    return {"session_id": body.session_id, "speech_text": speech, "action": action}

@app.post("/api/host/login")
def host_login(body: HostLogin, request: Request, response: Response):
    client_key = request.client.host if request.client else "unknown"
    if not _admin_login_allowed(client_key):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")

    username = ADMIN_USERNAME or ""
    username_matches = hmac.compare_digest(body.username.encode("utf-8"), username.encode("utf-8"))
    password_matches = _verify_admin_password(body.password)
    if not (username_matches and password_matches):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = _new_admin_session(username)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        secure=ADMIN_COOKIE_SECURE,
        samesite="strict",
        path="/api",
    )
    return {"success": True, "name": "Administrator"}


@app.get("/api/host/session")
def host_session(request: Request):
    username = require_admin(request)
    return {"authenticated": True, "name": "Administrator"}


@app.post("/api/host/logout", status_code=204)
def host_logout(request: Request, response: Response):
    _revoke_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE))
    response.status_code = 204
    response.delete_cookie(
        ADMIN_SESSION_COOKIE,
        path="/api",
        secure=ADMIN_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
    return response

@app.get("/api/programs")
def list_programs(_admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    ps = db.query(Program).all()
    return [
        {"id": p.id, "title": p.title, "description": p.description,
         "start_date": p.start_date, "end_date": p.end_date, "status": p.status}
        for p in ps
    ]

@app.get("/api/activities")
def list_activities(
    program_id: Optional[int] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    _admin: Optional[str] = Depends(optional_admin),
    db: Session = Depends(get_db),
):
    if status == "Draft" and not _admin:
        if PUBLIC_DEMO_MODE:
            return []
        raise HTTPException(status_code=401, detail="Admin authentication required")
    q = db.query(Activity)
    if PUBLIC_DEMO_MODE:
        q = q.filter(Activity.status != "Draft")
    if program_id is not None:
        q = q.filter(Activity.program_id == program_id)
    if category:
        q = q.filter(Activity.category == category)
    if status:
        q = q.filter(Activity.status == status)
    else:
        q = q.filter(Activity.status != "Draft")
    return [activity_student_dict(a, db) for a in q.all()]

@app.get("/api/activities/{activity_id}")
def get_activity(activity_id: int, view: str = "student", _admin: Optional[str] = Depends(optional_admin), db: Session = Depends(get_db)):
    if view == "host" and not _admin:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    a = db.query(Activity).filter(Activity.id == activity_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Activity not found")
    if a.status == "Draft" and not _admin:
        raise HTTPException(status_code=404, detail="Activity not found")
    if view == "host":
        return activity_host_dict(a, db)
    return activity_student_dict(a, db)

@app.post("/api/activities")
def create_activity(body: ActivityCreate, _admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    new_act = Activity(
        program_id=body.program_id,
        title=body.title,
        category=body.category,
        venue=body.venue,
        start_time=body.start_time,
        end_time=body.end_time,
        participation_type=body.participation_type,
        participant_instructions=body.participant_instructions,
        metadata_json=body.metadata,
        status=body.status,
    )
    db.add(new_act)
    db.flush()
    for r in body.requirements:
        db.add(Requirement(
            activity_id=new_act.id,
            item_name=r.item_name,
            quantity=r.quantity,
            assigned_to=r.assigned_to,
            status="Pending",
        ))
    db.commit()
    db.refresh(new_act)
    return activity_host_dict(new_act, db)

@app.patch("/api/activities/{activity_id}/status")
def update_status(activity_id: int, body: StatusUpdate, _admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.query(Activity).filter(Activity.id == activity_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Activity not found")
    if body.status not in VALID_TRANSITIONS.get(a.status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {a.status} to {body.status}",
        )
    a.status = body.status
    db.commit()
    db.refresh(a)
    return activity_host_dict(a, db)

@app.post("/api/activities/{activity_id}/register")
def register(activity_id: int, body: RegisterIn, db: Session = Depends(get_db)):
    a = db.query(Activity).filter(Activity.id == activity_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Activity not found")
    if a.status != "Published":
        raise HTTPException(
            status_code=400,
            detail="Activity is not open for registration",
        )
    existing = db.query(Registration).filter(
        Registration.activity_id == activity_id,
        Registration.student_roll_no == body.student_roll_no,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="You are already registered for this activity",
        )
    my_regs = db.query(Registration).filter(
        Registration.student_roll_no == body.student_roll_no
    ).all()
    new_start = parse_dt(a.start_time)
    new_end = parse_dt(a.end_time)
    for r in my_regs:
        other = db.query(Activity).filter(Activity.id == r.activity_id).first()
        if not other:
            continue
        if overlaps(new_start, new_end, parse_dt(other.start_time), parse_dt(other.end_time)):
            raise HTTPException(
                status_code=400,
                detail=f"Time conflict with '{other.title}'",
            )
    reg = Registration(
        activity_id=activity_id,
        student_name=body.student_name,
        student_roll_no=body.student_roll_no,
        team_name=body.team_name,
        team_members=body.team_members,
        checked_in=False,
        created_at=datetime.now().isoformat(),
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return {
        "id": reg.id, "activity_id": reg.activity_id,
        "student_name": reg.student_name,
        "student_roll_no": reg.student_roll_no,
        "team_name": reg.team_name, "team_members": reg.team_members,
        "checked_in": reg.checked_in, "created_at": reg.created_at,
    }

@app.patch("/api/registrations/{reg_id}/checkin")
def checkin(reg_id: int, body: CheckinUpdate, _admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.query(Registration).filter(Registration.id == reg_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Registration not found")
    r.checked_in = body.checked_in
    db.commit()
    db.refresh(r)
    return {"id": r.id, "checked_in": r.checked_in}

@app.patch("/api/requirements/{req_id}")
def update_requirement(req_id: int, body: RequirementUpdate, _admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Requirement not found")
    if body.status not in ["Pending", "Arranged"]:
        raise HTTPException(status_code=400, detail="Status must be Pending or Arranged")
    r.status = body.status
    if body.assigned_to is not None:
        r.assigned_to = body.assigned_to
    db.commit()
    db.refresh(r)
    return {"id": r.id, "item_name": r.item_name, "status": r.status, "assigned_to": r.assigned_to}

@app.get("/api/students/{roll_no}")
def get_student(roll_no: str, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.roll_no == roll_no).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student roll number not found")
    return {
        "roll_no": student.roll_no,
        "name": student.name,
        "department": student.department
    }

@app.get("/api/students/{roll_no}/schedule")
def schedule(roll_no: str, db: Session = Depends(get_db)):
    regs = db.query(Registration).filter(Registration.student_roll_no == roll_no).all()
    items = []
    for r in regs:
        a = db.query(Activity).filter(Activity.id == r.activity_id).first()
        if not a:
            continue
        items.append({
            "activity_id": a.id,
            "title": a.title,
            "venue": a.venue,
            "start_time": a.start_time,
            "end_time": a.end_time,
            "team_name": r.team_name,
            "participant_instructions": a.participant_instructions,
            "checked_in": r.checked_in,
        })
    items.sort(key=lambda x: x["start_time"])
    return items

if __name__ == "__main__":
    import uvicorn
    print("Starting Campus Activity Platform backend")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
