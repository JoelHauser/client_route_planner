from flask import Flask, jsonify, render_template, request, redirect, session, url_for
import os
import json
import time
from datetime import datetime, timedelta
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

import requests

try:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build
except Exception:
    Flow = None
    Credentials = None
    GoogleRequest = None
    build = None

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geocode_cache.json")
GOOGLE_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_token.json")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

from werkzeug.security import check_password_hash

app = Flask(__name__)

_secret_key = os.getenv("FLASK_SECRET_KEY")
if not _secret_key:
    raise RuntimeError("FLASK_SECRET_KEY environment variable must be set before starting the app.")
app.secret_key = _secret_key

# Allow OAuth over plain HTTP only when explicitly running in development mode.
# In production this must be unset so the OAuth library enforces HTTPS.
_dev_mode = os.getenv("FLASK_ENV") == "development"
if _dev_mode:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "Rachel")
# To generate a new hash run:
#   python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('yourpassword'))"
# Then set the output as the AUTH_PASSWORD_HASH environment variable.
AUTH_PASSWORD_HASH = os.getenv("AUTH_PASSWORD_HASH", "")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,       # JS cannot read the session cookie
    SESSION_COOKIE_SAMESITE="Lax",      # Blocks cross-site request forgery
    SESSION_COOKIE_SECURE=not _dev_mode, # HTTPS-only in production
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self)"
    if not _dev_mode:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Simple in-memory brute-force protection: max 10 attempts per IP per 5 minutes
_login_attempts: dict[str, list[float]] = {}

def _check_login_rate(ip: str) -> bool:
    now = time.time()
    window = [t for t in _login_attempts.get(ip, []) if now - t < 300]
    if len(window) >= 10:
        return False
    window.append(now)
    _login_attempts[ip] = window
    return True

def verify_password(password: str) -> bool:
    if not AUTH_PASSWORD_HASH:
        return False
    return check_password_hash(AUTH_PASSWORD_HASH, password)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

AIRTABLE_CACHE = {"firms": [], "sales_visits": [], "last_sync": None}


def require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v is not None)
    return str(value).strip()


def load_geocode_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_geocode_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def normalize_address_key(address: str) -> str:
    return " ".join(address.strip().lower().split())


import re as _re

def strip_subunit(address: str) -> str:
    """Remove suite/floor/unit suffixes that confuse geocoders, keeping the street address."""
    # Remove anything after a comma that looks like a suite/floor/unit
    # e.g. "123 Main St, Suite 400, Boston MA" -> "123 Main St, Boston MA"
    cleaned = _re.sub(
        r",?\s*(?:suite|ste\.?|floor|fl\.?|unit|apt\.?|#)\s*[\w\-]+",
        "",
        address,
        flags=_re.IGNORECASE,
    )
    # Also strip ordinal floor patterns like "3rd Floor" or "Floor 3" anywhere in the string
    cleaned = _re.sub(
        r"\b\d+(?:st|nd|rd|th)?\s+floor\b|\bfloor\s+\d+\b",
        "",
        cleaned,
        flags=_re.IGNORECASE,
    )
    return " ".join(cleaned.split())


def geocode_address(address: str, cache: dict) -> dict:
    cache_key = normalize_address_key(address)
    cached = cache.get(cache_key)
    if cached and cached.get("lat") is not None:
        return cached

    api_key = os.getenv("GOOGLE_GEOCODING_KEY")
    if not api_key:
        return {"formatted_address": address, "lat": None, "lng": None}

    response = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": strip_subunit(address), "components": "country:US", "key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "OK" or not data.get("results"):
        return {"formatted_address": address, "lat": None, "lng": None}

    first = data["results"][0]
    result = {
        "formatted_address": first.get("formatted_address", address),
        "lat": first["geometry"]["location"]["lat"],
        "lng": first["geometry"]["location"]["lng"],
    }
    cache[cache_key] = result
    save_geocode_cache(cache)
    return result


def airtable_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def airtable_list_records(base_id: str, table: str) -> list[dict]:
    token = require_env("AIRTABLE_TOKEN")
    endpoint = f"https://api.airtable.com/v0/{base_id}/{quote(table, safe='')}"
    sess = requests.Session()
    sess.headers.update(airtable_headers(token))
    all_records = []
    offset = None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        response = sess.get(endpoint, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        all_records.extend(payload.get("records", []))
        offset = payload.get("offset")
        if not offset:
            break
    return all_records


def extract_primary_contact(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def sync_airtable_data() -> dict:
    base_id = require_env("AIRTABLE_BASE_ID", "appMyfeC34lHkDSsB")
    firms_table = require_env("AIRTABLE_FIRMS_TABLE", "tbljj8mS0HybpvFxx")
    visits_table = require_env("AIRTABLE_VISITS_TABLE", "Sales Visits")
    name_field = require_env("AIRTABLE_NAME_FIELD", "Name")
    address_field = require_env("AIRTABLE_ADDRESS_FIELD", "Address")
    neighborhood_field = os.getenv("AIRTABLE_NEIGHBORHOOD_FIELD", "Neighborhood")
    contact_field = os.getenv("AIRTABLE_CONTACT_FIELD", "Contacts")

    firms_records = airtable_list_records(base_id, firms_table)
    visits_records = airtable_list_records(base_id, visits_table)
    cache = load_geocode_cache()

    # Build a lookup of already-geocoded addresses from the in-memory cache so
    # re-syncs don't re-geocode every firm from scratch (avoids timeout on large bases).
    known_geo: dict[str, dict] = {}
    for firm in AIRTABLE_CACHE.get("firms", []):
        raw = firm.get("raw_address") or ""
        if raw and firm.get("lat") is not None:
            known_geo[normalize_address_key(raw)] = {
                "formatted_address": firm["address"],
                "lat": firm["lat"],
                "lng": firm["lng"],
            }

    firms = []
    for record in firms_records:
        fields = record.get("fields", {})
        name = as_text(fields.get(name_field))
        address = as_text(fields.get(address_field))
        if address:
            addr_key = normalize_address_key(address)
            geocode_addr = strip_subunit(address)
            geo = known_geo.get(addr_key) or geocode_address(geocode_addr, cache)
        else:
            geo = {"formatted_address": "", "lat": None, "lng": None}
        firms.append({
            "id": record.get("id"),
            "name": name,
            "address": address,
            "raw_address": address,
            "neighborhood": as_text(fields.get(neighborhood_field)),
            "contact": as_text(fields.get(contact_field)),
            "primary_contact": extract_primary_contact(fields.get(contact_field)),
            "lat": geo.get("lat"),
            "lng": geo.get("lng"),
            "fields": fields,
        })

    sales_visits = []
    for record in visits_records:
        fields = record.get("fields", {})
        sales_visits.append({
            "id": record.get("id"),
            "fields": fields,
            "firm_name_guess": as_text(fields.get("Firm") or fields.get("Firms") or fields.get("Name") or fields.get("Company")),
            "visit_date_guess": as_text(fields.get("Date") or fields.get("Visit Date") or fields.get("Created") or fields.get("Created time")),
            "contact_guess": as_text(fields.get("Contact") or fields.get("Contacts")),
        })

    AIRTABLE_CACHE["firms"] = firms
    AIRTABLE_CACHE["sales_visits"] = sales_visits
    AIRTABLE_CACHE["last_sync"] = datetime.now().isoformat()
    return AIRTABLE_CACHE


def parse_date_flex(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value[:len(fmt.replace('%f', '000000'))] if '%f' in fmt else value, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def quarter_info(dt: datetime):
    q = (dt.month - 1) // 3 + 1
    start_month = (q - 1) * 3 + 1
    start = datetime(dt.year, start_month, 1)
    if q == 4:
        end = datetime(dt.year + 1, 1, 1)
    else:
        end = datetime(dt.year, start_month + 3, 1)
    return q, start, end


def build_firm_visit_index(firms: list[dict], sales_visits: list[dict]):
    index = {
        firm["id"]: {"last_visit": None, "visits_this_quarter": 0, "visited_this_quarter": False, "visit_dates": []}
        for firm in firms
    }
    name_map = {firm["name"].strip().lower(): firm["id"] for firm in firms if firm.get("name")}
    now = datetime.now()
    _, q_start, q_end = quarter_info(now)

    for visit in sales_visits:
        firm_name = (visit.get("firm_name_guess") or "").strip().lower()
        firm_id = name_map.get(firm_name)
        if not firm_id:
            continue
        visit_dt = parse_date_flex(visit.get("visit_date_guess") or "")
        if not visit_dt:
            continue
        index[firm_id]["visit_dates"].append(visit_dt)
        if not index[firm_id]["last_visit"] or visit_dt > index[firm_id]["last_visit"]:
            index[firm_id]["last_visit"] = visit_dt
        if q_start <= visit_dt < q_end:
            index[firm_id]["visits_this_quarter"] += 1
            index[firm_id]["visited_this_quarter"] = True
    return index


def get_google_client_config():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "https://crp-production.up.railway.app/google/callback")
    if not client_id or not client_secret or Flow is None:
        return None
    return {
        "web": {
            "client_id": client_id,
            "project_id": "where2go-local",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
        }
    }


def _save_google_token(token_data: dict) -> None:
    try:
        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_data, f)
    except Exception:
        pass


def _load_google_token() -> dict | None:
    try:
        if os.path.exists(GOOGLE_TOKEN_FILE):
            with open(GOOGLE_TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def get_google_credentials():
    token = session.get("google_token") or _load_google_token()
    if not token or Credentials is None:
        return None
    if not session.get("google_token"):
        session["google_token"] = token
    creds = Credentials.from_authorized_user_info(token, GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        token_data = json.loads(creds.to_json())
        session["google_token"] = token_data
        _save_google_token(token_data)
    return creds


def get_calendar_events_for_day(day_str: str):
    creds = get_google_credentials()
    if not creds or build is None:
        return False, []
    service = build("calendar", "v3", credentials=creds)
    day = datetime.strptime(day_str, "%Y-%m-%d")
    time_min = day.isoformat() + "Z"
    time_max = (day + timedelta(days=1)).isoformat() + "Z"
    resp = service.events().list(
        calendarId="primary", timeMin=time_min, timeMax=time_max,
        singleEvents=True, orderBy="startTime"
    ).execute()
    items = resp.get("items", [])
    events = []
    for item in items:
        start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        display_time = "All day"
        if start_raw and "T" in start_raw:
            try:
                dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                display_time = dt.strftime("%-I:%M %p") if os.name != 'nt' else dt.strftime("%I:%M %p").lstrip('0')
            except Exception:
                display_time = start_raw
        events.append({
            "summary": item.get("summary", "Untitled"),
            "location": item.get("location", ""),
            "description": item.get("description", ""),
            "start_time": display_time,
            "start_raw": start_raw,
        })
    return True, events


def haversine_minutes(a_lat, a_lng, b_lat, b_lng):
    if None in (a_lat, a_lng, b_lat, b_lng):
        return 999
    from math import radians, sin, cos, sqrt, atan2
    R = 3958.8
    dlat = radians(b_lat - a_lat)
    dlng = radians(b_lng - a_lng)
    aa = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(aa), sqrt(1 - aa))
    return R * c / 25 * 60


def geocode_if_needed(address: str):
    cache = load_geocode_cache()
    return geocode_address(address, cache)


def enrich_calendar_locations(events):
    enriched = []
    for ev in events:
        loc = (ev.get("location") or "").strip()
        if loc:
            geo = geocode_if_needed(loc)
            ev = dict(ev)
            ev["lat"] = geo.get("lat")
            ev["lng"] = geo.get("lng")
        enriched.append(ev)
    return enriched


def choose_candidate_firms(firms, visit_index, neighborhood_filter=""):
    candidates = []
    nf = neighborhood_filter.strip().lower()
    for firm in firms:
        if nf and nf not in (firm.get("neighborhood") or "").lower():
            continue
        stats = visit_index.get(firm["id"], {})
        candidate = dict(firm)
        candidate["last_visit"] = stats.get("last_visit")
        candidate["visited_this_quarter"] = stats.get("visited_this_quarter", False)
        candidate["visits_this_quarter"] = stats.get("visits_this_quarter", 0)
        candidates.append(candidate)
    return candidates


def score_frequency_gap(firm):
    last_visit = firm.get("last_visit")
    if not last_visit:
        return 999
    return (datetime.now() - last_visit).days


def _proximity_minutes(firm: dict, current_location: dict | None) -> float:
    """Driving-time proxy (minutes) from start location to firm. 9999 if unknown."""
    if not current_location or firm.get("lat") is None or firm.get("lng") is None:
        return 9999
    return haversine_minutes(
        current_location.get("lat"), current_location.get("lng"),
        firm["lat"], firm["lng"],
    )


def _parse_start_time(start_time_str: str | None) -> tuple[int, int]:
    """Parse '9:00' or '13:30' into (hour, minute). Defaults to 9:00."""
    if not start_time_str:
        return 9, 0
    try:
        h, m = map(int, start_time_str.split(":"))
        return h, m
    except Exception:
        return 9, 0


def _event_after_start(event: dict, start_h: int, start_m: int) -> bool:
    """Return True if the event starts at or after (start_h, start_m)."""
    raw = (event.get("start_raw") or "").strip()
    if not raw or "T" not in raw:
        return True  # all-day events — always keep
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (dt.hour * 60 + dt.minute) >= (start_h * 60 + start_m)
    except Exception:
        return True


def make_summary_text(day_str, mode, nearby_event, chosen, start_time=None):
    dt = datetime.strptime(day_str, "%Y-%m-%d")
    header = dt.strftime("%A, %B %d")
    lines = [header]
    start_h, start_m = _parse_start_time(start_time)
    suffix_label = "AM" if start_h < 12 else "PM"
    display_start_h = start_h if start_h <= 12 else start_h - 12
    if display_start_h == 0:
        display_start_h = 12
    lines.append(f"Starting at {display_start_h}:{start_m:02d} {suffix_label}")
    if nearby_event:
        lines.append(f"Already in {nearby_event.get('location') or 'that area'} at {nearby_event.get('start_time')}")
    if chosen:
        lines.append("Add:")
        for idx, firm in enumerate(chosen):
            total_min = start_h * 60 + start_m + idx * 45
            h = total_min // 60
            m = total_min % 60
            s = "AM" if h < 12 else "PM"
            dh = h if h <= 12 else h - 12
            if dh == 0:
                dh = 12
            if firm.get("quick_hello"):
                lines.append(f"- stop by {firm['name']} around {dh}:{m:02d} {s}")
            else:
                lines.append(f"- {firm['name']} at {dh}:{m:02d} {s}")
    return "\n".join(lines)


def build_recommendations(day_str: str, mode: str, neighborhood: str, current_location: dict | None, start_time: str | None = None):
    firms = AIRTABLE_CACHE.get("firms") or []
    sales_visits = AIRTABLE_CACHE.get("sales_visits") or []
    if not firms:
        raise RuntimeError("Sync Airtable first.")
    visit_index = build_firm_visit_index(firms, sales_visits)
    candidates = choose_candidate_firms(firms, visit_index, neighborhood)
    connected, events = get_calendar_events_for_day(day_str)
    events = enrich_calendar_locations(events) if connected else []
    if start_time:
        sh, sm = _parse_start_time(start_time)
        events = [e for e in events if _event_after_start(e, sh, sm)]

    chosen = []
    nearby_event = events[0] if events else None

    if mode == "near_meeting":
        anchor = None
        if nearby_event and nearby_event.get("lat") is not None:
            anchor = nearby_event
        elif current_location:
            anchor = {"lat": current_location.get("lat"), "lng": current_location.get("lng")}
        ranked = []
        for firm in candidates:
            minutes = haversine_minutes(anchor.get("lat"), anchor.get("lng"), firm.get("lat"), firm.get("lng")) if anchor else 999
            if minutes <= 15:
                firm = dict(firm)
                firm["reason"] = "Near meeting"
                firm["travel_minutes"] = round(minutes)
                ranked.append((minutes, 0 if not firm.get("visited_this_quarter") else 1, firm))
        ranked.sort(key=lambda x: (x[0], x[1], x[2].get("name") or ""))
        chosen = [item[2] for item in ranked[:3]]
        if len(chosen) >= 3:
            chosen[-1]["quick_hello"] = True
    elif mode == "quarter_coverage":
        ranked = []
        for firm in candidates:
            if not firm.get("visited_this_quarter"):
                firm = dict(firm)
                firm["reason"] = "Not seen this quarter"
                prox = _proximity_minutes(firm, current_location)
                ranked.append((score_frequency_gap(firm) * -1, prox, firm.get("neighborhood") or "", firm))
        ranked.sort(key=lambda x: (x[0], x[1], x[2]))
        chosen = [item[3] for item in ranked[:4]]
    elif mode == "frequency_protection":
        ranked = []
        for firm in candidates:
            gap = score_frequency_gap(firm)
            firm = dict(firm)
            firm["reason"] = "Falling behind"
            prox = _proximity_minutes(firm, current_location)
            ranked.append((-gap, prox, 0 if not firm.get("visited_this_quarter") else 1, firm))
        ranked.sort(key=lambda x: (x[0], x[1], x[2]))
        chosen = [item[3] for item in ranked[:4]]
    elif mode == "outreach_first":
        ranked = []
        for firm in candidates:
            if not firm.get("visited_this_quarter"):
                firm = dict(firm)
                firm["reason"] = "Good target"
                prox = _proximity_minutes(firm, current_location)
                ranked.append((prox, firm.get("neighborhood") or "", -score_frequency_gap(firm), firm))
        ranked.sort(key=lambda x: (x[0], x[1], x[2]))
        chosen = [item[3] for item in ranked[:4]]

    summary_text = make_summary_text(day_str, mode, nearby_event, chosen, start_time=start_time)
    return {
        "summary_text": summary_text,
        "suggested_stops": chosen,
        "calendar_events": events,
    }


def optimize_route_ors(current_location: dict, stops: list[dict]) -> dict:
    ors_key = require_env("ORS_API_KEY")
    valid_stops = [s for s in stops if s.get("lat") is not None and s.get("lng") is not None]
    if not valid_stops:
        raise ValueError("None of the suggested stops have valid coordinates. Try syncing Airtable again.")
    coords = [[current_location["lng"], current_location["lat"]]] + [[s["lng"], s["lat"]] for s in valid_stops]
    stops = valid_stops
    jobs = [{"id": i, "location": coords[i], "service": 0} for i in range(1, len(coords))]
    payload = {"jobs": jobs, "vehicles": [{"id": 1, "profile": "driving-car", "start": coords[0]}], "options": {"g": True}}
    response = requests.post(
        "https://api.openrouteservice.org/optimization",
        json=payload,
        headers={"Authorization": ors_key, "Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    routes = data.get("routes", [])
    if not routes:
        return {"ordered_stops": stops, "geometry": [], "segments": []}
    order_ids = [step.get("id") for step in routes[0].get("steps", []) if step.get("type") == "job"]
    by_job = {i + 1: stop for i, stop in enumerate(stops)}
    ordered_stops = [by_job[i] for i in order_ids if i in by_job]
    ordered_coords = [coords[0]] + [[s["lng"], s["lat"]] for s in ordered_stops]
    directions = requests.post(
        "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
        json={"coordinates": ordered_coords},
        headers={"Authorization": ors_key, "Content-Type": "application/json"},
        timeout=60,
    )
    directions.raise_for_status()
    dir_data = directions.json()
    geometry = dir_data.get("features", [{}])[0].get("geometry", {}).get("coordinates", [])
    segments = []
    for seg in dir_data.get("features", [{}])[0].get("properties", {}).get("segments", []):
        segments.append({
            "distance_text": f"{seg.get('distance', 0) / 1609.34:.1f} mi",
            "duration_text": f"{round(seg.get('duration', 0) / 60)} min",
        })
    return {"ordered_stops": ordered_stops, "geometry": geometry, "segments": segments}


@app.get("/login")
def login():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template('login.html', error=None)

@app.post("/login")
def login_post():
    ip = request.remote_addr or "unknown"
    if not _check_login_rate(ip):
        return render_template('login.html', error="Too many attempts. Please wait a few minutes.")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if username == AUTH_USERNAME and verify_password(password):
        session["logged_in"] = True
        session.permanent = True
        return redirect(url_for("index"))
    return render_template('login.html', error="Incorrect username or password.")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
@login_required
def index():
    return render_template('index.html')


@app.get("/google/login")
@login_required
def google_login():
    config = get_google_client_config()
    if not config:
        return redirect(url_for("index"))
    import secrets as _secrets, hashlib, base64
    code_verifier = _secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    session["google_code_verifier"] = code_verifier
    flow = Flow.from_client_config(config, scopes=GOOGLE_SCOPES)
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/google/callback")
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    session["google_oauth_state"] = state
    return redirect(auth_url)


@app.get("/google/callback")
@login_required
def google_callback():
    config = get_google_client_config()
    if not config:
        return redirect(url_for("index"))
    if not request.url.startswith("https"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)
    flow = Flow.from_client_config(
        config,
        scopes=GOOGLE_SCOPES,
        state=session.get("google_oauth_state"),
    )
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/google/callback")
    flow.fetch_token(
        authorization_response=request.url,
        code_verifier=session.get("google_code_verifier"),
    )
    creds = flow.credentials
    token_data = json.loads(creds.to_json())
    session["google_token"] = token_data
    _save_google_token(token_data)
    return redirect(url_for("index"))


@app.get("/api/firms-cache")
@login_required
def api_firms_cache():
    return jsonify(AIRTABLE_CACHE)


@app.get("/api/unmapped-firms")
@login_required
def api_unmapped_firms():
    firms = AIRTABLE_CACHE.get("firms", [])
    unmapped = [
        {"name": f["name"], "raw_address": f.get("raw_address", "")}
        for f in firms
        if f.get("lat") is None and f.get("raw_address")
    ]
    no_address = [
        {"name": f["name"]}
        for f in firms
        if not f.get("raw_address")
    ]
    return jsonify({"not_geocoded": unmapped, "no_address": no_address})


@app.get("/api/sync-airtable")
@login_required
def api_sync_airtable():
    try:
        data = sync_airtable_data()
        return jsonify(data)
    except requests.HTTPError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        return jsonify({"error": f"API request failed: {detail}"}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/calendar/day")
@login_required
def api_calendar_day():
    try:
        date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
        connected, events = get_calendar_events_for_day(date)
        if not connected:
            return jsonify({"connected": False, "error": "Google Calendar not connected."}), 400
        return jsonify({"connected": True, "events": events})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/geocode-address")
@login_required
def api_geocode_address():
    try:
        address = (request.get_json(force=True) or {}).get("address", "").strip()
        if not address:
            return jsonify({"error": "Address is required."}), 400
        result = geocode_address(strip_subunit(address), load_geocode_cache())
        if result.get("lat") is None:
            return jsonify({"error": "Could not find that address."}), 404
        return jsonify(result)
    except requests.HTTPError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        return jsonify({"error": f"API request failed: {detail}"}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/recommend-schedule")
@login_required
def api_recommend_schedule():
    try:
        payload = request.get_json(force=True) or {}
        result = build_recommendations(
            day_str=payload.get("date") or datetime.now().strftime("%Y-%m-%d"),
            mode=payload.get("mode") or "near_meeting",
            neighborhood=payload.get("neighborhood") or "",
            current_location=payload.get("current_location"),
            start_time=payload.get("start_time"),
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/optimize-route")
@login_required
def api_optimize_route():
    try:
        payload = request.get_json(force=True) or {}
        current_location = payload.get("current_location")
        stops = payload.get("stops", [])
        result = optimize_route_ors(current_location, stops)
        return jsonify(result)
    except requests.HTTPError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        return jsonify({"error": f"API request failed: {detail}"}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _background_sync_loop():
    import threading
    def loop():
        while True:
            time.sleep(12 * 60 * 60)
            try:
                sync_airtable_data()
            except Exception:
                pass
    t = threading.Thread(target=loop, daemon=True)
    t.start()

_background_sync_loop()

if __name__ == "__main__":
    app.run(debug=_dev_mode, host="127.0.0.1", port=5000)