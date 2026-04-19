# Where2Go — Scheduling Assistant

A Flask web app that helps a sales rep plan daily client visits. Pulls firm data from Airtable, reads Google Calendar meetings, suggests which firms to visit based on a chosen strategy, and optimizes the driving route.

---

## Using the App

### Sign In
Go to the app URL and sign in with your credentials. Sessions last 30 days.

### Building a Plan

1. **Date** — select the day you're planning for.
2. **Start time** — pick when your day begins (7 AM – 7 PM, 30-min increments). Events before this time are excluded.
3. **Mode** — choose a planning strategy (see below).
4. **Neighborhood** — optional filter to limit suggestions to one area.
5. **Start location** — type an address and press Enter, or click **Use my location**. Setting a location automatically builds the plan.
6. Click **Build plan** to generate suggestions.

### Planning Modes

| Mode | What it does |
|---|---|
| **Near existing meeting** | Finds firms within ~15 min of your first calendar event (or start location). Best for drop-ins around a fixed meeting. |
| **Quarter coverage** | Firms not seen this quarter, ranked by most neglected then proximity. Best for hitting every account. |
| **Frequency protection** | All firms ranked by largest gap since last visit, then proximity. Best for protecting key relationships. |
| **Outreach-first** | Firms not seen this quarter, ranked by proximity first. Best for tight geographic clusters. |

### Suggested Stops

Each stop is color-coded — the numbered bubble and map pin share the same color so you can match them instantly.

- **⋯ menu** on a stop — remove it from the list.
- **+ button** in the panel header — create a custom stop or add the closest firm to your start location.
- **Double-click** a stop in the list to center the map on it.

### Day Summary Panel (three tabs)

- **Summary** — plain-text schedule with estimated arrival times.
- **Route** — step-by-step driving directions after optimization, with distances and times.
- **Calendar** — your calendar events with locations, with their own optimize and Open in Maps buttons.

### Route Optimization

Click **Optimize route** to reorder stops for minimum driving time and draw the route on the map. Click **Open in Maps** to hand the route off to Google Maps. Click **Clear** to reset.

### Google Calendar

Click **Connect Google Calendar** and sign in with Google. The connection persists — you won't need to reconnect unless the token expires. Calendar event locations are clickable: tap one to set it as your start location and rebuild the plan.

### Map

- Small blue circles — all Airtable firms.
- Larger colored circles — your suggested stops (color matches the list).
- Solid line — optimized stops route (orange in dark mode).
- Dashed line — optimized calendar route (sky blue in dark mode).
- Drag the vertical bar (left ↔ right panels) or horizontal bar (map ↕ results) to resize.

### Airtable Sync

Syncs automatically on page load. Click **Sync Airtable** to refresh manually. The badge shows how many firms are loaded.

### Dark Mode

Click **◐ Dark** / **☀ Light** to toggle. Preference is saved across sessions.

### Mobile

On small screens the layout switches to a single-panel view with a tab bar (Plan / Map / Stops / Calendar) at the bottom.

---

## Troubleshooting

**"Sync Airtable first."** — the data hasn't loaded yet. Click Sync Airtable or wait for the auto-sync.

**"None of the suggested stops have valid coordinates."** — the addresses in Airtable couldn't be geocoded. Check them in Airtable and sync again.

**Calendar shows "not connected"** — click Connect Google Calendar to re-authorize.

**Stops route error about invalid location** — one or more stops failed geocoding. Bad stops are skipped automatically; if all fail, fix the addresses in Airtable and sync.
