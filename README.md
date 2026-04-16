# Where2Go — Scheduling Assistant

A single-file Flask web application that helps a sales representative plan their daily client visits. It pulls client firm data from Airtable, reads the day's meetings from Google Calendar, suggests which firms to visit based on a chosen strategy, and optimizes the driving route using OpenRouteService.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Requirements](#2-requirements)
3. [Environment Variables](#3-environment-variables)
4. [Local Setup](#4-local-setup)
5. [Deployment (Railway)](#5-deployment-railway)
6. [Signing In](#6-signing-in)
7. [The Interface](#7-the-interface)
   - 7.1 [Left Column — Controls](#71-left-column--controls)
   - 7.2 [Left Column — Calendar Panel](#72-left-column--calendar-panel)
   - 7.3 [Right Column — Map](#73-right-column--map)
   - 7.4 [Right Column — Suggested Stops](#74-right-column--suggested-stops)
   - 7.5 [Right Column — Day Summary Panel](#75-right-column--day-summary-panel)
8. [Planning Modes](#8-planning-modes)
9. [Start Location](#9-start-location)
10. [Route Optimization](#10-route-optimization)
11. [Google Calendar Integration](#11-google-calendar-integration)
12. [Airtable Integration](#12-airtable-integration)
13. [Stop Management](#13-stop-management)
14. [Resizable Panels](#14-resizable-panels)
15. [Dark Mode](#15-dark-mode)
16. [Mobile Layout](#16-mobile-layout)
17. [API Reference](#17-api-reference)
18. [Files on Disk](#18-files-on-disk)
19. [Security](#19-security)
20. [Troubleshooting](#20-troubleshooting)

---

## 1. Overview

Where2Go is designed for a single sales user (Rachel). Each day she opens the app, sets a date and start time, picks a planning strategy, sets her starting location, and clicks **Build plan**. The app responds with:

- Up to 4 suggested client firm stops, ranked by the chosen strategy and proximity to her start location.
- A plain-text day summary showing her schedule with estimated arrival times.
- A map with pins for all known firms and her start location.
- Optional route optimization that reorders the stops for minimum driving time and draws the route on the map.
- A Calendar tab showing that day's Google Calendar events with their locations, which can also be route-optimized separately.

---

## 2. Requirements

**Python 3.10 or later** is required (uses the `dict | None` union type syntax).

Install Python dependencies:

```
pip install -r requirements.txt
```

The `requirements.txt` file should include:

```
flask
requests
werkzeug
python-dotenv
google-auth
google-auth-oauthlib
google-api-python-client
```

---

## 3. Environment Variables

All configuration is done through environment variables. For local development, create a `.env` file in the same directory as `client_route_planner.py`. The `.gitignore` excludes this file from version control.

| Variable | Required | Description |
|---|---|---|
| `FLASK_SECRET_KEY` | **Yes** | A long random string used to sign session cookies. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `AUTH_USERNAME` | No | Login username. Defaults to `Rachel`. |
| `AUTH_PASSWORD_HASH` | **Yes** | Bcrypt hash of the login password. Generate with: `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('yourpassword'))"` |
| `FLASK_ENV` | No | Set to `development` for local dev. Enables HTTP OAuth and disables HTTPS-only cookies. |
| `AIRTABLE_TOKEN` | **Yes** | Airtable personal access token. |
| `AIRTABLE_BASE_ID` | No | Airtable base ID. Defaults to `appMyfeC34lHkDSsB`. |
| `AIRTABLE_FIRMS_TABLE` | No | Airtable table name or ID for client firms. Defaults to `tbljj8mS0HybpvFxx`. |
| `AIRTABLE_VISITS_TABLE` | No | Airtable table name for sales visit records. Defaults to `Sales Visits`. |
| `AIRTABLE_NAME_FIELD` | No | Field name for the firm's name in the firms table. Defaults to `Name`. |
| `AIRTABLE_ADDRESS_FIELD` | No | Field name for the firm's address. Defaults to `Address`. |
| `AIRTABLE_NEIGHBORHOOD_FIELD` | No | Field name for neighborhood. Defaults to `Neighborhood`. |
| `AIRTABLE_CONTACT_FIELD` | No | Field name for the contacts linked field. Defaults to `Contacts`. |
| `ORS_API_KEY` | **Yes** | OpenRouteService API key for route optimization. Get one free at openrouteservice.org. |
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID. Required for Google Calendar integration. |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret. Required for Google Calendar integration. |
| `GOOGLE_REDIRECT_URI` | No | The OAuth callback URL. In production this must match exactly what is registered in the Google Cloud Console. Defaults to `https://crp-production.up.railway.app/google/callback`. |

**Example `.env` for local development:**

```
FLASK_SECRET_KEY=replace_with_random_hex_string
FLASK_ENV=development
AUTH_USERNAME=Rachel
AUTH_PASSWORD_HASH=pbkdf2:sha256:...paste hash here...
AIRTABLE_TOKEN=pat...
AIRTABLE_BASE_ID=appMyfeC34lHkDSsB
ORS_API_KEY=5b3ce...
GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/google/callback
```

---

## 4. Local Setup

1. Clone or download the repository.
2. Create a `.env` file (see Section 3).
3. Install dependencies:
   ```
   python -m pip install -r requirements.txt
   ```
4. Run the app:
   ```
   python client_route_planner.py
   ```
5. Open your browser to `http://127.0.0.1:5000`.

The app binds to `127.0.0.1:5000` when run directly. It does not start a public server.

> **Note:** When `FLASK_ENV=development`, OAuth callbacks are allowed over plain HTTP and session cookies do not require HTTPS. Do not use this setting in production.

---

## 5. Deployment (Railway)

The app is deployed on Railway at:

```
https://crp-production.up.railway.app
```

**Steps to deploy or update:**

1. Push your changes to the `testENV` branch on GitHub (`JoelHauser/client_route_planner`).
2. Railway auto-deploys from that branch.
3. All environment variables listed in Section 3 must be set in the Railway project's **Variables** panel. Do **not** set `FLASK_ENV` in production.

**Google OAuth in production:**

The `GOOGLE_REDIRECT_URI` must be set to `https://crp-production.up.railway.app/google/callback` and that exact URL must be added as an authorized redirect URI in the Google Cloud Console for your OAuth client.

---

## 6. Signing In

The app requires a username and password login before anything is accessible. The login page is shown at `/login`.

- **Username:** Set via `AUTH_USERNAME` (default: `Rachel`).
- **Password:** Set by generating a hash with Werkzeug and storing it in `AUTH_PASSWORD_HASH`.
- Sessions last **30 days**. The user stays logged in across browser restarts.
- There is brute-force protection: a maximum of 10 login attempts per IP address per 5-minute window.
- Click **Sign out** (top-right of the app) to end the session immediately.

---

## 7. The Interface

The desktop layout is a two-column grid. The left column holds planning controls and the calendar. The right column holds the map on top and a results strip on the bottom. All panels are resizable (see Section 14).

### 7.1 Left Column — Controls

This panel contains all the inputs needed to build a daily plan.

| Control | Description |
|---|---|
| **Where2Go** title | App title. |
| **◐ Dark / ☀ Light** | Toggles dark mode. Preference is saved in `localStorage` and persists across sessions. |
| **Sign out** | Ends the session and redirects to the login page. |
| **Sync Airtable** button | Manually triggers a full sync of firms and sales visits from Airtable. The sync also runs automatically on page load. The badge next to the button shows the number of firms loaded or "Not synced". |
| **Fit map** button | Resets the map view to show all loaded firm pins. |
| **Connect Google Calendar** button | Starts the Google OAuth flow to link the user's calendar. See Section 11. After connection the button label changes to "Reconnect calendar". |
| **Calendar badge** | Shows "Calendar connected" (green) or "Calendar not connected". |
| **Date** | The date to plan for. Defaults to today. Changing the date also refreshes the calendar events panel. |
| **Start time** | A dropdown from 7:00 AM to 7:00 PM in 30-minute increments. Defaults to 9:00 AM. Calendar events before this time are excluded from the day summary and suggestions. Changing the dropdown automatically rebuilds the plan if stops have already been generated. |
| **Mode** | The planning strategy (see Section 8). |
| **Neighborhood** | Optional text filter. If filled in, only firms whose Neighborhood field contains this text (case-insensitive) will be considered. |
| **Start location** | A text field for a manually typed address. Press **Enter** or click **Use typed address** to geocode it and set it as the start location. Setting the start location automatically builds a new plan. |
| **Use my location** button | Uses the browser's GPS/geolocation to set the start location. Also automatically builds a new plan. |
| **Build plan** button | Triggers the recommendation engine with all current settings. |
| **Status bar** | The bottom of the controls panel. Shows the current operation ("Syncing Airtable…", "Plan ready.", etc.) with a green dot when active. |

### 7.2 Left Column — Calendar Panel

This panel fills the remaining height below the controls and shows that day's Google Calendar events.

- Events are displayed with their **time** and **title**.
- If an event has a **location address**, it is shown as a clickable underlined link. Clicking it geocodes the address and sets it as the start location, then automatically rebuilds the plan.
- The badge in the panel header shows the event count.
- The **Refresh day** button re-fetches events for the currently selected date.
- If the calendar is not connected, the panel shows "No events loaded."

### 7.3 Right Column — Map

An interactive Leaflet.js map centered on the Boston area by default.

- **Blue filled circles** — all firms from Airtable with known coordinates.
- **Dark filled circles (larger)** — firms currently in the suggested stops list.
- **Start location marker** — shown when a start location is set. GPS location shows as a blue marker; typed/calendar address shows as a dark marker.
- **Clicking a pin** opens a popup with the firm's name, address, and neighborhood.
- **Double-clicking a stop** in the Suggested Stops list centers the map on that firm.
- **Scroll wheel / trackpad** zooms the map. Trackpad pinch-zoom is smoothed (`wheelDebounceTime: 60`, `wheelPxPerZoomLevel: 80`).
- In dark mode, the map tiles are inverted to a dark style using a CSS filter.
- After optimizing a route, a **polyline** is drawn on the map following actual roads:
  - Suggested stops route: solid line, **black** in light mode, **orange** in dark mode.
  - Calendar route: dashed line, **blue** in light mode, **sky blue** in dark mode.

### 7.4 Right Column — Suggested Stops

The left half of the bottom results strip.

- Lists up to 4 suggested firm stops with a numbered circle, firm name, address, and a badge showing why it was selected (e.g., "Not seen this quarter", "Near meeting").
- An **amber badge** indicates the firm has not been visited this quarter.
- The **stop count badge** in the header updates as stops are added or removed.
- The **⋯ hamburger menu** on each stop opens a context menu with three actions:
  - **Remove this stop** — removes the stop from the list without rebuilding the whole plan.
  - **Add stop from firms list** — opens a search panel to find and insert another firm from Airtable, positioned after the chosen stop.
  - **Create custom stop** — opens a form to enter any name and address. The address is geocoded automatically.
- If no stops exist yet, a small **+ Add stop** button is shown inline.
- **Optimize route** button — sends the current stop list to OpenRouteService for optimization (see Section 10).
- **Open in Maps** button — opens the current stop list as a Google Maps directions URL in a new tab, using the current start location as the origin.
- **Clear** button — removes the route polyline and resets optimized waypoints.

### 7.5 Right Column — Day Summary Panel

The right half of the bottom results strip. Has three tabs:

| Tab | Contents |
|---|---|
| **Summary** | A plain-text day summary. Shows the date, start time, and a schedule of suggested stops with estimated arrival times (spaced 45 minutes apart from the start time). |
| **Route** | Step-by-step route directions for the suggested stops route after optimization. Shows each stop's name, address, distance, and estimated drive time per segment. |
| **Calendar** | Step-by-step route directions for the calendar events route after calendar route optimization. Shows each event's name, time, location, distance, and estimated drive time per segment. Also shows an **Optimize calendar route** button and an **Open in Maps** button. |

---

## 8. Planning Modes

The **Mode** dropdown controls how the app selects and ranks suggested stops. All modes also factor in proximity to the start location when ranking (closer stops rank higher, all else being equal).

### Near existing meeting
Finds firms within 15 minutes' drive of the first calendar event on that day (or the start location if there is no meeting). Returns up to 3 firms. The closest firm that has not been visited this quarter is prioritized. The last stop is flagged as a "quick hello".

**Best for:** Days when you already have a fixed meeting and want to make nearby drop-ins.

### Quarter coverage
Finds firms that have **not been visited at all this quarter**. Ranks by longest time since the last-ever visit (most neglected first), then by proximity. Returns up to 4 firms.

**Best for:** Ensuring every account gets at least one touch per quarter.

### Frequency protection
Considers **all** firms regardless of whether they were seen this quarter. Ranks by the largest gap since the last visit (most overdue first), then by proximity. Returns up to 4 firms.

**Best for:** Protecting high-frequency relationships — making sure key accounts don't slip.

### Outreach-first
Finds firms that have **not been visited this quarter**, ranks by proximity first (nearest first), then by neighborhood, then by time since last visit. Returns up to 4 firms.

**Best for:** Efficient outreach days where you want the tightest possible geographic cluster.

---

## 9. Start Location

The start location is used in two ways:

1. **Proximity ranking** — All modes (except Near meeting when a calendar anchor is available) rank candidate firms partly by estimated drive time from the start location. This uses the Haversine formula (straight-line distance divided by an assumed 25 mph average speed) as a proxy for drive time.
2. **Route optimization** — OpenRouteService uses the start location as the route's origin point.

**Ways to set the start location:**

- **Type an address** into the Start location field and press **Enter** or click **Use typed address**. The address is geocoded via Nominatim (OpenStreetMap).
- **Click "Use my location"** to use the browser's GPS. Requires granting location permission.
- **Click a calendar event's location address** in the Calendar panel. The address is geocoded and set as the start, and the plan rebuilds automatically.

Setting the start location via any method automatically triggers a plan rebuild.

---

## 10. Route Optimization

Route optimization uses the **OpenRouteService (ORS) Vehicle Routing Problem API** to find the most efficient order to visit the suggested stops, then fetches turn-by-turn directions along actual roads.

**How it works:**

1. The current stop list and start location are sent to the ORS `/optimization` endpoint.
2. ORS reorders the stops to minimize total travel time.
3. The reordered coordinates are sent to ORS `/v2/directions/driving-car/geojson` for the full road geometry.
4. The polyline is drawn on the map and the Route tab in the summary panel is populated with per-segment distances (miles) and drive times (minutes).

**Requirements:**
- A start location must be set.
- At least one stop must have valid coordinates. Firms without geocoded addresses are silently skipped.

**Calendar route optimization** works identically but uses calendar events with locations instead of suggested stops, and draws a separate dashed polyline.

**Opening in Google Maps:**

The **Open in Maps** buttons construct a `google.com/maps/dir/` URL using the current start location as the origin, the last stop as the destination, and all intermediate stops as waypoints, then open it in a new browser tab.

---

## 11. Google Calendar Integration

The calendar integration is optional but enhances all planning modes by pulling the day's meetings.

### Connecting

1. Click **Connect Google Calendar** in the controls panel.
2. You are redirected to Google's OAuth consent screen. Sign in with the Google account whose calendar you want to use.
3. Grant read-only calendar access.
4. You are redirected back to the app.

The OAuth flow uses PKCE (Proof Key for Code Exchange) for security.

### Token persistence

After a successful login, the OAuth token is saved to `google_token.json` on the server. This means the calendar connection **persists across browser sessions and server restarts** — you do not need to reconnect every time. The token is refreshed automatically when it expires, using the stored refresh token.

### What it does

- Calendar events for the selected date are shown in the left-column Calendar panel with their time, title, and location.
- When building a plan, events before the selected start time are filtered out.
- The first remaining event with a location is used as the geographic anchor for **Near existing meeting** mode.
- Calendar events with locations appear in the **Calendar** route tab and can be optimized into a driving route.

### Revoking access

To disconnect, click **Connect Google Calendar** again to go through the OAuth flow and replace the token, or manually delete `google_token.json` from the server.

### Local development note

When running locally with `FLASK_ENV=development`, the `GOOGLE_REDIRECT_URI` in `.env` must point to `http://127.0.0.1:5000/google/callback`, and that URI must be added as an authorized redirect URI in your Google Cloud Console OAuth client settings.

---

## 12. Airtable Integration

The app reads two tables from Airtable:

### Firms table

Each record represents a client firm. The following fields are read:

| Field (configurable) | Default env var key | Description |
|---|---|---|
| Name | `AIRTABLE_NAME_FIELD` | The firm's display name. |
| Address | `AIRTABLE_ADDRESS_FIELD` | Street address used for geocoding. |
| Neighborhood | `AIRTABLE_NEIGHBORHOOD_FIELD` | Used for the neighborhood filter and proximity grouping. |
| Contacts | `AIRTABLE_CONTACT_FIELD` | Linked contacts field. The first value is stored as the primary contact. |

### Sales Visits table

Each record represents one recorded visit. The app looks for these fields (automatically, by trying common names):

- **Firm/Firms/Name/Company** — matched against the firms table by name.
- **Date/Visit Date/Created/Created time** — the date of the visit.
- **Contact/Contacts** — the contact seen.

Visit history is used to calculate:
- Whether a firm was visited this quarter.
- How many days since the last visit (used for frequency and outreach scoring).

### Geocoding

Firm addresses are geocoded using the **Nominatim** (OpenStreetMap) API. Results are cached in `geocode_cache.json` so each address is only looked up once. The cache persists across restarts. Requests are rate-limited to one per 1.1 seconds to comply with Nominatim's usage policy.

Firms that cannot be geocoded (no coordinates found) are still listed but cannot be used for proximity ranking or route optimization.

### Auto-sync

Airtable syncs automatically every time the page loads. The **Sync Airtable** button allows a manual refresh at any time. The sync badge shows the number of firms loaded.

---

## 13. Stop Management

After a plan is built, the Suggested Stops list can be freely edited without rebuilding from scratch.

### Hamburger menu (⋯)

Click the three-dot button on any stop to open its context menu:

**Remove this stop**
Removes the stop from the list. The map pins update immediately to reflect that the firm is no longer a suggested stop (reverts to a small blue pin).

**Add stop from firms list**
Opens a search panel at the bottom of the Suggested Stops column. Search by firm name or address. Click a firm to insert it after the current stop in the list. Only firms not already in the list are shown.

**Create custom stop**
Opens a form to enter a custom stop name and address. The address is geocoded on the server. The new stop is inserted after the current stop. Useful for locations not in Airtable (e.g., a coffee meeting, a new prospect).

### Manual + Add stop

When the stop list is empty, a **+ Add stop** button appears. It opens the same "Add stop from firms list" panel.

---

## 14. Resizable Panels

On desktop (screen width ≥ 768 px), all three main panel boundaries can be dragged to resize.

| Drag handle | What it resizes |
|---|---|
| **Vertical bar** between the left column and the map | Left column width. Range: 220 px – 540 px. Default: 340 px. |
| **Horizontal bar** between the map and the results strip | Height of the results strip at the bottom. Range: 100 px – (total height − 120 px). Default: 310 px. |

Dragging any handle also triggers a Leaflet map resize so the map fills its new container correctly.

The resize handles are hidden on mobile.

---

## 15. Dark Mode

Click **◐ Dark** (top-right of the controls panel) to switch to dark mode. Click **☀ Light** to switch back. The preference is saved in `localStorage` and applied immediately on page load (before any rendering, to avoid a flash of light mode).

In dark mode:
- The map tiles are inverted using a CSS `filter: invert(100%) hue-rotate(180deg)` to produce a dark map.
- The suggested-stop route polyline changes from black to **orange** (#f97316) for visibility.
- The calendar route polyline changes from blue to **sky blue** (#38bdf8) for visibility.
- All UI colors shift to a dark palette defined with CSS custom properties.

---

## 16. Mobile Layout

On screens narrower than 768 px, the layout switches to a single-panel view with a tab bar fixed to the bottom of the screen.

| Tab | Panel shown |
|---|---|
| Plan | Controls panel (left column) |
| Map | Leaflet map |
| Stops | Suggested stops + day summary results strip |
| Calendar | Calendar events panel |

Only one panel is visible at a time. The resize handles are hidden. After building a plan the app automatically switches to the Stops tab. After optimizing a route it automatically switches to the Map tab.

The tab bar respects the iOS safe area inset so it does not overlap the home indicator on notched devices.

---

## 17. API Reference

All endpoints require an active session (login). Unauthenticated requests are redirected to `/login`.

### `GET /api/firms-cache`
Returns the current in-memory Airtable cache without re-fetching from Airtable.

**Response:** `{ "firms": [...], "sales_visits": [...], "last_sync": "ISO timestamp or null" }`

---

### `GET /api/sync-airtable`
Fetches all firms and sales visits from Airtable, geocodes addresses (using cache), and updates the in-memory cache.

**Response:** Same shape as `/api/firms-cache`.

**Error responses:** `502` if the Airtable API call fails, `500` for other errors.

---

### `GET /api/calendar/day?date=YYYY-MM-DD`
Returns Google Calendar events for the given date.

**Response:**
```json
{
  "connected": true,
  "events": [
    {
      "summary": "Meeting with Client",
      "location": "123 Main St, Boston MA",
      "start_time": "10:00 AM",
      "start_raw": "2026-04-15T10:00:00-04:00"
    }
  ]
}
```

**Error responses:** `400` if calendar is not connected, `500` for other errors.

---

### `POST /api/geocode-address`
Geocodes a single address using Nominatim (with caching).

**Request body:** `{ "address": "123 Main St, Boston MA" }`

**Response:** `{ "formatted_address": "...", "lat": 42.36, "lng": -71.06 }`

**Error responses:** `400` if no address provided, `404` if not found, `502` for API errors.

---

### `POST /api/recommend-schedule`
Runs the recommendation engine and returns suggested stops and a day summary.

**Request body:**
```json
{
  "date": "2026-04-15",
  "mode": "near_meeting",
  "neighborhood": "",
  "current_location": { "lat": 42.36, "lng": -71.06 },
  "start_time": "9:00"
}
```

**Response:**
```json
{
  "suggested_stops": [ { "id": "...", "name": "...", "address": "...", "lat": ..., "lng": ..., "reason": "Near meeting" } ],
  "summary_text": "Wednesday, April 15\nStarting at 9:00 AM\n...",
  "calendar_events": [ ... ]
}
```

---

### `POST /api/optimize-route`
Optimizes a stop list using OpenRouteService.

**Request body:**
```json
{
  "current_location": { "lat": 42.36, "lng": -71.06 },
  "stops": [ { "name": "...", "address": "...", "lat": ..., "lng": ... } ]
}
```

**Response:**
```json
{
  "ordered_stops": [ ... ],
  "geometry": [ [lng, lat], ... ],
  "segments": [
    { "distance_text": "2.1 mi", "duration_text": "8 min" }
  ]
}
```

**Error responses:** `502` if ORS API fails, `500` for other errors.

---

### `GET /google/login`
Initiates the Google OAuth flow. Redirects to Google's consent screen.

### `GET /google/callback`
OAuth redirect handler. Exchanges the authorization code for tokens, saves the token to the session and to `google_token.json`, then redirects to the main app.

### `GET /login` / `POST /login`
Login page and form submission handler.

### `GET /logout`
Clears the session and redirects to `/login`.

---

## 18. Files on Disk

| File | Purpose |
|---|---|
| `client_route_planner.py` | The entire application — Flask routes, HTML/CSS/JS template, and all business logic. |
| `requirements.txt` | Python package dependencies. |
| `.env` | Local environment variables. **Never commit this file.** |
| `.gitignore` | Excludes `.env`, `google_token.json`, `geocode_cache.json`, and Python cache files from git. |
| `geocode_cache.json` | Auto-generated. Caches Nominatim geocoding results so addresses are not looked up twice. **Not committed.** |
| `google_token.json` | Auto-generated when Google Calendar is connected. Stores the OAuth access/refresh token so the calendar connection persists across restarts. **Not committed.** |

---

## 19. Security

- **Authentication:** Username + bcrypt-hashed password. Sessions last 30 days and are stored in a signed, HTTP-only cookie.
- **Brute-force protection:** Maximum 10 login attempts per IP per 5 minutes.
- **HTTPS enforcement:** In production, session cookies are `Secure` (HTTPS-only), `HttpOnly`, and `SameSite=Lax`. HSTS headers are added.
- **OAuth PKCE:** Google OAuth uses PKCE (code challenge/verifier) to protect the authorization flow against interception.
- **Security headers:** Every response includes `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and `Permissions-Policy` (geolocation self only).
- **Secret isolation:** All secrets are environment variables, never in code. Google token and geocode cache are excluded from version control.

---

## 20. Troubleshooting

**"FLASK_SECRET_KEY environment variable must be set"**
The `.env` file is missing or the `python-dotenv` package is not installed. Run `pip install python-dotenv` and ensure `.env` has a `FLASK_SECRET_KEY` line.

**"Sync Airtable first." when building a plan**
The in-memory Airtable cache is empty. Click **Sync Airtable** or wait for the auto-sync to complete on page load.

**"None of the suggested stops have valid coordinates."**
All stops in the current list failed to geocode. This usually means the addresses in Airtable are malformed or too vague for Nominatim to resolve. Check the addresses in Airtable, clear `geocode_cache.json` to force a re-geocode, then sync again.

**Calendar panel shows "No events loaded." / Calendar badge shows "not connected"**
Google Calendar has not been connected in this session, or the token in `google_token.json` is invalid. Click **Connect Google Calendar** to re-authorize.

**Google OAuth redirect_uri_mismatch error**
The `GOOGLE_REDIRECT_URI` environment variable does not match an authorized redirect URI registered in Google Cloud Console. Make sure they are identical (including `http` vs `https` and trailing slashes).

**Map does not resize after dragging a panel**
This should not happen as `map.invalidateSize()` is called on both `mousemove` and `mouseup`. If it does, click **Fit map** to force a refresh.

**Route optimization returns an error about invalid location**
One or more stops have `lat` or `lng` set to `null` (failed geocoding). These are filtered out automatically. If all stops fail this filter the error is surfaced. Fix the addresses in Airtable and sync again.

**Local testing with Google Calendar**
Because the Railway OAuth callback URI (`crp-production.up.railway.app/google/callback`) is the default, local testing requires setting `GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/google/callback` in `.env` and adding that URI as an authorized redirect URI in Google Cloud Console.
