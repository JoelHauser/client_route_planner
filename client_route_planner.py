from flask import Flask, jsonify, render_template_string, request, redirect, session, url_for
import os
import json
import time
from datetime import datetime, timedelta
from urllib.parse import quote

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

CACHE_FILE = "geocode_cache.json"
GEOCODE_DELAY_SECONDS = 1.1
LAST_GEOCODE_AT = 0.0
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

APP_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Where2Go Scheduling Assistant</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #f4f4f5;
      --panel: #ffffff;
      --text: #111827;
      --muted: #6b7280;
      --line: #e5e7eb;
      --line-strong: #d1d5db;
      --accent: #111827;
      --soft-bg: #f9fafb;
      --success-bg: #f0fdf4;
      --success-text: #166534;
      --success-border: #bbf7d0;
      --amber-bg: #fffbeb;
      --amber-text: #92400e;
      --amber-border: #fde68a;
      --radius-sm: 8px;
      --radius-md: 10px;
      --radius-lg: 14px;
    }
    /* ── LAYOUT ── */
    body { font-family: Inter, system-ui, sans-serif; background: var(--bg); color: var(--text); font-size: 13px; line-height: 1.5; height: 100vh; overflow: hidden; }
    .shell { display: grid; grid-template-columns: 320px 1fr; grid-template-rows: 100vh; gap: 10px; padding: 10px; height: 100vh; }
    .left { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
    .right { display: grid; grid-template-rows: 1fr 240px; gap: 10px; min-height: 0; }
    /* panels */
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-lg); }
    .controls-panel { flex-shrink: 0; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
    .calendar-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
    .map-panel { overflow: hidden; }
    #map { width: 100%; height: 100%; }
    .results-panel { display: grid; grid-template-columns: 1fr 1fr; min-height: 0; overflow: hidden; }
    /* controls panel internals */
    .app-title { display: flex; align-items: baseline; gap: 8px; }
    .app-title h1 { font-size: 18px; font-weight: 700; letter-spacing: -0.02em; }
    .app-title span { font-size: 11px; color: var(--muted); }
    .ctrl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
    .ctrl-grid .full { grid-column: 1 / -1; }
    label { font-size: 11px; color: var(--muted); display: block; margin-bottom: 3px; }
    input[type="text"], input[type="date"], select {
      width: 100%; border: 1px solid var(--line-strong); border-radius: var(--radius-md);
      padding: 7px 10px; font: inherit; font-size: 12px; background: var(--panel); color: var(--text); outline: none;
    }
    input:focus, select:focus { border-color: #6b7280; }
    /* buttons */
    button { font: inherit; border: 1px solid var(--line-strong); border-radius: var(--radius-md); padding: 7px 10px; cursor: pointer; font-size: 12px; font-weight: 600; background: var(--panel); color: var(--text); transition: background .12s; white-space: nowrap; }
    button:hover { background: var(--soft-bg); }
    button.primary { background: var(--accent); color: #fff; border-color: transparent; }
    button.primary:hover { opacity: .88; }
    button.ghost { background: var(--soft-bg); border-color: transparent; color: var(--muted); font-weight: 500; }
    button.ghost:hover { background: var(--line); color: var(--text); }
    .btn-row { display: flex; gap: 6px; }
    .btn-row > * { flex: 1 1 0; min-width: 0; }
    /* badges */
    .badge { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 600; border: 1px solid var(--line); background: var(--soft-bg); color: var(--muted); white-space: nowrap; }
    .badge.green { background: var(--success-bg); color: var(--success-text); border-color: var(--success-border); }
    .badge.amber { background: var(--amber-bg); color: var(--amber-text); border-color: var(--amber-border); }
    .dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex-shrink: 0; display: inline-block; }
    /* section header inside panels */
    .sec-head { padding: 8px 14px; background: var(--soft-bg); border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
    .sec-label { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
    /* calendar panel */
    .cal-body { flex: 1; overflow-y: auto; padding: 8px 14px; }
    .cal-footer { padding: 8px 14px; border-top: 1px solid var(--line); display: flex; gap: 6px; flex-shrink: 0; }
    .cal-footer button { flex: 1; }
    .event-row { display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; border-bottom: 1px solid var(--line); }
    .event-row:last-of-type { border-bottom: none; }
    .event-time { font-size: 11px; color: var(--muted); min-width: 52px; padding-top: 1px; flex-shrink: 0; }
    .event-title { font-size: 12px; font-weight: 600; }
    .event-loc { font-size: 11px; color: var(--muted); margin-top: 1px; }
    /* results panel */
    .res-col { display: flex; flex-direction: column; min-height: 0; overflow: hidden; border-right: 1px solid var(--line); }
    .res-col:last-child { border-right: none; }
    .res-body { flex: 1; overflow-y: auto; padding: 8px 12px; }
    /* stops */
    .stop { display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; border-bottom: 1px solid var(--line); }
    .stop:last-of-type { border-bottom: none; }
    .stop-n { width: 20px; height: 20px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 10px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
    .stop-name { font-size: 12px; font-weight: 600; }
    .stop-addr { font-size: 11px; color: var(--muted); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .stop-badge { margin-left: auto; flex-shrink: 0; }
    /* route steps */
    .route-step { display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; border-bottom: 1px solid var(--line); }
    .route-step:last-child { border-bottom: none; }
    .route-step-n { font-size: 11px; font-weight: 700; color: var(--muted); min-width: 16px; padding-top: 1px; }
    .route-step-name { font-size: 12px; font-weight: 600; }
    .route-step-meta { font-size: 11px; color: var(--muted); margin-top: 1px; }
    /* summary text */
    .summary-text { white-space: pre-wrap; font-size: 12px; line-height: 1.6; color: var(--text); }
    .no-content { font-size: 12px; color: var(--muted); padding: 4px 0; }
    /* status bar */
    .status-bar { padding: 7px 16px; border-top: 1px solid var(--line); font-size: 11px; color: var(--muted); display: flex; align-items: center; gap: 6px; background: var(--soft-bg); border-radius: 0 0 var(--radius-lg) var(--radius-lg); flex-shrink: 0; }
    .pulse { width: 6px; height: 6px; border-radius: 50%; background: #d1d5db; flex-shrink: 0; }
    /* res footer */
    .res-footer { padding: 8px 12px; border-top: 1px solid var(--line); display: flex; gap: 6px; flex-shrink: 0; }
    .res-footer button { flex: 1; }
  </style>
</head>
<body>
<div class="shell">

  <!-- LEFT COLUMN -->
  <div class="left">

    <!-- Controls panel (fixed height) -->
    <div class="panel controls-panel">
      <div class="app-title">
        <h1>Where2Go</h1>
        <span>Scheduling assistant</span>
      </div>

      <!-- top action row -->
      <div class="btn-row">
        <button class="primary" id="syncBtn">Sync Airtable</button>
        <button class="ghost" id="fitBtn">Fit map</button>
        <button class="ghost" id="googleConnectBtn">Connect calendar</button>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span class="badge" id="syncBadge">Not synced</span>
        <span class="badge" id="calendarBadge">Calendar not connected</span>
      </div>

      <hr style="border:none;border-top:1px solid var(--line);" />

      <!-- planning fields -->
      <div class="ctrl-grid">
        <div>
          <label for="planDate">Date</label>
          <input id="planDate" type="date" />
        </div>
        <div>
          <label for="modeSelect">Mode</label>
          <select id="modeSelect">
            <option value="near_meeting">Near existing meeting</option>
            <option value="quarter_coverage">Quarter coverage</option>
            <option value="frequency_protection">Frequency protection</option>
            <option value="outreach_first">Outreach-first</option>
          </select>
        </div>
        <div>
          <label for="neighborhoodFilter">Neighborhood</label>
          <input id="neighborhoodFilter" type="text" placeholder="Seaport, Back Bay…" />
        </div>
        <div>
          <label for="manualStartInput">Start location</label>
          <input id="manualStartInput" type="text" placeholder="Address…" />
        </div>
      </div>
      <div class="btn-row">
        <button class="ghost" id="locateBtn">Use my location</button>
        <button class="ghost" id="setManualLocationBtn">Use typed address</button>
        <button class="primary" id="recommendBtn">Build plan</button>
      </div>

      <div class="status-bar" style="margin: -4px -16px -14px; border-radius: 0 0 var(--radius-lg) var(--radius-lg); border-top: 1px solid var(--line);">
        <span class="pulse" id="statusPulse"></span>
        <span id="statusText">Ready.</span>
      </div>
    </div>

    <!-- Calendar panel (scrollable, fills remaining height) -->
    <div class="panel calendar-panel">
      <div class="sec-head">
        <span class="sec-label">Calendar</span>
        <span class="badge" id="calEventsBadge">No events</span>
      </div>
      <div class="cal-body" id="calendarEvents">
        <div class="no-content">No events loaded.</div>
      </div>
      <div class="cal-footer">
        <button class="ghost" id="calendarRefreshBtn">Refresh day</button>
      </div>
    </div>

  </div>

  <!-- RIGHT COLUMN -->
  <div class="right">

    <!-- Map (takes most of the height) -->
    <div class="panel map-panel">
      <div id="map"></div>
    </div>

    <!-- Results strip (stops + summary side by side) -->
    <div class="panel results-panel">

      <!-- Suggested stops -->
      <div class="res-col">
        <div class="sec-head">
          <span class="sec-label">Suggested stops</span>
          <span class="badge" id="stopsBadge">0</span>
        </div>
        <div class="res-body" id="stopsBody">
          <div class="no-content">Build a plan to see stops.</div>
        </div>
        <div class="res-footer">
          <button class="primary" id="optimizeBtn">Optimize route</button>
          <button class="ghost" id="openMapsBtn">Open in Maps</button>
          <button class="ghost" id="clearRouteBtn">Clear</button>
        </div>
      </div>

      <!-- Day summary / route steps -->
      <div class="res-col">
        <div class="sec-head">
          <span class="sec-label" id="summaryTabLabel">Day summary</span>
          <div style="display:flex;gap:4px;">
            <button class="ghost" id="showSummaryBtn" style="padding:2px 8px;font-size:10px;">Summary</button>
            <button class="ghost" id="showRouteBtn" style="padding:2px 8px;font-size:10px;">Route</button>
          </div>
        </div>
        <div class="res-body" id="summaryBody">
          <div class="no-content">No plan yet.</div>
        </div>
      </div>

    </div>
  </div>

</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
<script>
  const state = {
    map: null, markers: [], routeLayer: null,
    firms: [], visits: [], suggestedStops: [],
    currentLocation: null, currentLocationMarker: null,
    calendarEvents: [], suggestedStopIds: new Set(),
    optimizedWaypoints: [], summaryText: '',
    view: 'summary',
  };

  function setStatus(msg, active) {
    document.getElementById('statusText').textContent = msg;
    document.getElementById('statusPulse').style.background = active ? '#22c55e' : '#d1d5db';
  }

  function esc(str) {
    return String(str || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;').replace(/'/g,'&#039;');
  }

  function initialize() {
    state.map = L.map('map').setView([42.3601, -71.0589], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(state.map);
    document.getElementById('planDate').value = new Date().toISOString().slice(0, 10);
    refreshCalendarDay();
  }

  function clearMarkers() { state.markers.forEach(m => m.remove()); state.markers = []; }

  function renderMapPins(firms) {
    clearMarkers();
    const bounds = [];
    firms.forEach(firm => {
      if (firm.lat == null || firm.lng == null) return;
      const isSuggested = state.suggestedStopIds.has(firm.id);
      const marker = L.circleMarker([firm.lat, firm.lng], {
        radius: isSuggested ? 9 : 6,
        fillColor: isSuggested ? '#111827' : '#2563eb',
        color: '#ffffff', weight: 2, opacity: 1, fillOpacity: 1
      }).addTo(state.map);
      marker.bindPopup(`<strong>${esc(firm.name)}</strong><br>${esc(firm.address)}<br><span style="color:#6b7280">${esc(firm.neighborhood||'')}</span>`);
      state.markers.push(marker);
      bounds.push([firm.lat, firm.lng]);
    });
    if (state.currentLocation) bounds.push([state.currentLocation.lat, state.currentLocation.lng]);
    if (bounds.length) state.map.fitBounds(bounds, { padding: [50, 50] });
    if (state.currentLocationMarker) state.currentLocationMarker.addTo(state.map);
  }

  function renderSuggestedStops() {
    const body = document.getElementById('stopsBody');
    const badge = document.getElementById('stopsBadge');
    badge.textContent = state.suggestedStops.length;
    if (!state.suggestedStops.length) {
      body.innerHTML = '<div class="no-content">No stops suggested yet.</div>';
      return;
    }
    body.innerHTML = state.suggestedStops.map((firm, i) => `
      <div class="stop" data-idx="${i}" style="cursor:pointer;">
        <div class="stop-n">${i + 1}</div>
        <div style="flex:1;min-width:0;">
          <div class="stop-name">${esc(firm.name)}</div>
          <div class="stop-addr">${esc(firm.address || '')}</div>
        </div>
        ${firm.reason ? `<span class="badge stop-badge ${firm.visited_this_quarter ? '' : 'amber'}" style="font-size:10px;">${esc(firm.reason)}</span>` : ''}
      </div>
    `).join('');
    body.querySelectorAll('.stop').forEach((el, i) => {
      el.addEventListener('dblclick', () => {
        const f = state.suggestedStops[i];
        if (f.lat != null && f.lng != null) state.map.setView([f.lat, f.lng], 15);
      });
    });
  }

  function renderCalendarEvents() {
    const container = document.getElementById('calendarEvents');
    const badge = document.getElementById('calEventsBadge');
    if (!state.calendarEvents.length) {
      container.innerHTML = '<div class="no-content">No events for this day.</div>';
      badge.textContent = 'No events';
      badge.className = 'badge';
      return;
    }
    badge.className = 'badge green';
    badge.innerHTML = '<span class="dot"></span> ' + state.calendarEvents.length + ' event' + (state.calendarEvents.length !== 1 ? 's' : '');
    container.innerHTML = state.calendarEvents.map(ev => `
      <div class="event-row">
        <div class="event-time">${esc(ev.start_time || '')}</div>
        <div>
          <div class="event-title">${esc(ev.summary || 'Untitled')}</div>
          ${ev.location ? `<div class="event-loc">${esc(ev.location)}</div>` : ''}
        </div>
      </div>
    `).join('');
  }

  function renderSummaryPane() {
    const body = document.getElementById('summaryBody');
    const label = document.getElementById('summaryTabLabel');
    if (state.view === 'summary') {
      label.textContent = 'Day summary';
      body.innerHTML = state.summaryText
        ? `<div class="summary-text">${esc(state.summaryText)}</div>`
        : '<div class="no-content">Build a plan to see the day summary.</div>';
    } else {
      label.textContent = 'Route';
      const stops = state.optimizedWaypoints.length ? state.optimizedWaypoints : state.suggestedStops;
      if (!stops.length) {
        body.innerHTML = '<div class="no-content">Optimize route to see steps.</div>';
        return;
      }
      const startHtml = `<div class="route-step"><div class="route-step-n">S</div><div><div class="route-step-name">Start</div><div class="route-step-meta">Your chosen location</div></div></div>`;
      const stepsHtml = stops.map((stop, idx) => {
        const seg = (state.lastSegments || [])[idx] || {};
        return `<div class="route-step">
          <div class="route-step-n">${idx + 1}</div>
          <div style="flex:1;min-width:0;">
            <div class="route-step-name">${esc(stop.name)}</div>
            <div class="route-step-meta">${esc(stop.address || '')}${seg.distance_text ? ' · ' + esc(seg.distance_text) : ''}${seg.duration_text ? ' · ' + esc(seg.duration_text) : ''}</div>
          </div>
        </div>`;
      }).join('');
      body.innerHTML = startHtml + stepsHtml;
    }
  }

  async function syncAirtable() {
    setStatus('Syncing Airtable…', true);
    try {
      const res = await fetch('/api/sync-airtable');
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Sync failed.');
      state.firms = data.firms || [];
      state.visits = data.sales_visits || [];
      const badge = document.getElementById('syncBadge');
      badge.className = 'badge green';
      badge.innerHTML = '<span class="dot"></span> ' + state.firms.length + ' firms';
      renderMapPins(state.firms);
      setStatus('Airtable synced.', true);
    } catch (err) {
      setStatus(err.message || 'Sync failed.', false);
    }
  }

  async function refreshCalendarDay() {
    try {
      const date = document.getElementById('planDate').value || new Date().toISOString().slice(0,10);
      const res = await fetch(`/api/calendar/day?date=${encodeURIComponent(date)}`);
      const data = await res.json();
      const badge = document.getElementById('calendarBadge');
      if (!res.ok) {
        badge.className = 'badge';
        badge.textContent = 'Calendar not connected';
        state.calendarEvents = [];
      } else {
        state.calendarEvents = data.events || [];
        if (data.connected) {
          badge.className = 'badge green';
          badge.innerHTML = '<span class="dot"></span> Calendar connected';
        }
      }
      renderCalendarEvents();
    } catch (err) {
      document.getElementById('calendarBadge').textContent = 'Calendar not connected';
    }
  }

  async function setManualStartLocation() {
    const address = document.getElementById('manualStartInput').value.trim();
    if (!address) return setStatus('Type a start address first.', false);
    setStatus('Finding address…', true);
    try {
      const res = await fetch('/api/geocode-address', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ address })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not geocode address.');
      state.currentLocation = { lat: data.lat, lng: data.lng };
      if (state.currentLocationMarker) state.currentLocationMarker.remove();
      state.currentLocationMarker = L.circleMarker([data.lat, data.lng], {
        radius: 8, fillColor: '#111827', color: '#fff', weight: 2, fillOpacity: 1
      }).bindPopup(`Start: ${esc(data.formatted_address)}`).addTo(state.map);
      state.map.setView([data.lat, data.lng], 13);
      renderMapPins(state.firms);
      setStatus('Start location set.', true);
    } catch (err) {
      setStatus(err.message || 'Could not set location.', false);
    }
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) return setStatus('Geolocation not supported.', false);
    setStatus('Getting location…', true);
    navigator.geolocation.getCurrentPosition(pos => {
      state.currentLocation = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      if (state.currentLocationMarker) state.currentLocationMarker.remove();
      state.currentLocationMarker = L.circleMarker(
        [state.currentLocation.lat, state.currentLocation.lng],
        { radius: 8, fillColor: '#2563eb', color: '#fff', weight: 2, fillOpacity: 1 }
      ).bindPopup('Your current location').addTo(state.map);
      state.map.setView([state.currentLocation.lat, state.currentLocation.lng], 13);
      renderMapPins(state.firms);
      setStatus('Location captured.', true);
    }, err => setStatus(`Location error: ${err.message}`, false),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });
  }

  async function buildRecommendations() {
    setStatus('Building plan…', true);
    try {
      const payload = {
        date: document.getElementById('planDate').value,
        mode: document.getElementById('modeSelect').value,
        neighborhood: document.getElementById('neighborhoodFilter').value.trim(),
        current_location: state.currentLocation,
      };
      const res = await fetch('/api/recommend-schedule', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not build recommendations.');
      state.suggestedStops = data.suggested_stops || [];
      state.suggestedStopIds = new Set(state.suggestedStops.map(x => x.id));
      state.summaryText = data.summary_text || '';
      state.view = 'summary';
      renderSuggestedStops();
      renderSummaryPane();
      renderMapPins(state.firms);
      setStatus('Plan ready.', true);
    } catch (err) {
      setStatus(err.message || 'Could not build plan.', false);
    }
  }

  function clearRoute() {
    if (state.routeLayer) { state.routeLayer.remove(); state.routeLayer = null; }
    state.optimizedWaypoints = [];
    state.lastSegments = [];
    renderSummaryPane();
    setStatus('Route cleared.', false);
  }

  async function optimizeSuggestedStops() {
    if (!state.currentLocation) return setStatus('Set a start location first.', false);
    if (!state.suggestedStops.length) return setStatus('Build a plan first.', false);
    setStatus('Optimizing route…', true);
    try {
      const res = await fetch('/api/optimize-route', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ current_location: state.currentLocation, stops: state.suggestedStops })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Route optimization failed.');
      state.optimizedWaypoints = data.ordered_stops || [];
      state.lastSegments = data.segments || [];
      state.view = 'route';
      renderSummaryPane();
      drawRoute(data.geometry || []);
      setStatus('Route optimized.', true);
    } catch (err) {
      setStatus(err.message || 'Route optimization failed.', false);
    }
  }

  function drawRoute(coords) {
    if (state.routeLayer) state.routeLayer.remove();
    if (!coords.length) return;
    state.routeLayer = L.polyline(coords.map(c => [c[1], c[0]]), { weight: 5, color: '#111827' }).addTo(state.map);
    state.map.fitBounds(state.routeLayer.getBounds(), { padding: [50, 50] });
  }

  function openInGoogleMaps() {
    const stops = state.optimizedWaypoints.length ? state.optimizedWaypoints : state.suggestedStops;
    if (!state.currentLocation || !stops.length) return setStatus('Need a start location and stops first.', false);
    const origin = `${state.currentLocation.lat},${state.currentLocation.lng}`;
    const destination = encodeURIComponent(stops[stops.length - 1].address);
    const waypoints = stops.slice(0, -1).map(s => s.address).join('|');
    let url = `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(origin)}&destination=${destination}&travelmode=driving`;
    if (waypoints) url += `&waypoints=${encodeURIComponent(waypoints)}`;
    window.open(url, '_blank');
  }

  document.getElementById('syncBtn').addEventListener('click', syncAirtable);
  document.getElementById('fitBtn').addEventListener('click', () => renderMapPins(state.firms));
  document.getElementById('googleConnectBtn').addEventListener('click', () => { window.location.href = '/google/login'; });
  document.getElementById('calendarRefreshBtn').addEventListener('click', refreshCalendarDay);
  document.getElementById('planDate').addEventListener('change', refreshCalendarDay);
  document.getElementById('setManualLocationBtn').addEventListener('click', setManualStartLocation);
  document.getElementById('locateBtn').addEventListener('click', useCurrentLocation);
  document.getElementById('recommendBtn').addEventListener('click', buildRecommendations);
  document.getElementById('clearRouteBtn').addEventListener('click', clearRoute);
  document.getElementById('optimizeBtn').addEventListener('click', optimizeSuggestedStops);
  document.getElementById('openMapsBtn').addEventListener('click', openInGoogleMaps);
  document.getElementById('showSummaryBtn').addEventListener('click', () => { state.view = 'summary'; renderSummaryPane(); });
  document.getElementById('showRouteBtn').addEventListener('click', () => { state.view = 'route'; renderSummaryPane(); });

  initialize();
</script>
</body>
</html>
"""

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("AIRTABLE_TOKEN", "patIIKKkmoxiRF5z1.526f3499cb66616fe42bbfbafa581cde96d2153a7e07431b49f84135a3598b19")
os.environ.setdefault("AIRTABLE_BASE_ID", "appMyfeC34lHkDSsB")
os.environ.setdefault("AIRTABLE_FIRMS_TABLE", "tbljj8mS0HybpvFxx")
os.environ.setdefault("AIRTABLE_VISITS_TABLE", "Sales Visits")
os.environ.setdefault("AIRTABLE_NAME_FIELD", "Name")
os.environ.setdefault("AIRTABLE_ADDRESS_FIELD", "Address")
os.environ.setdefault("ORS_API_KEY", "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImU3YmE2ZTNmNTNmNTQ0NDE4ZjFlYzk5MmU2OGI5MTc3IiwiaCI6Im11cm11cjY0In0=")
os.environ.setdefault("GOOGLE_CLIENT_ID", "674074737478-123f2c8b2krler67mstk8fhp5fd9abke.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "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")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/google/callback")
os.environ.setdefault("FLASK_SECRET_KEY", "a6eb8c16fd1e02f6de066ac8e3abd27b55296ac8484865416ce297adcd72cec7")

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


def geocode_address(address: str, cache: dict) -> dict:
    global LAST_GEOCODE_AT
    cache_key = normalize_address_key(address)
    if cache_key in cache:
        return cache[cache_key]
    elapsed = time.time() - LAST_GEOCODE_AT
    if elapsed < GEOCODE_DELAY_SECONDS:
        time.sleep(GEOCODE_DELAY_SECONDS - elapsed)
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": address, "format": "jsonv2", "limit": 1},
        headers={"User-Agent": "where2go-scheduling-assistant/1.0"},
        timeout=20,
    )
    LAST_GEOCODE_AT = time.time()
    response.raise_for_status()
    results = response.json()
    if not results:
        result = {"formatted_address": address, "lat": None, "lng": None}
        cache[cache_key] = result
        save_geocode_cache(cache)
        return result
    first = results[0]
    result = {
        "formatted_address": first.get("display_name", address),
        "lat": float(first["lat"]),
        "lng": float(first["lon"]),
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

    firms = []
    for record in firms_records:
        fields = record.get("fields", {})
        name = as_text(fields.get(name_field))
        address = as_text(fields.get(address_field))
        geo = geocode_address(address, cache) if address else {"formatted_address": "", "lat": None, "lng": None}
        firms.append({
            "id": record.get("id"),
            "name": name,
            "address": geo.get("formatted_address") or address,
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
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/google/callback")
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


def get_google_credentials():
    token = session.get("google_token")
    if not token or Credentials is None:
        return None
    creds = Credentials.from_authorized_user_info(token, GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        session["google_token"] = json.loads(creds.to_json())
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


def make_summary_text(day_str, mode, nearby_event, chosen, outreach):
    dt = datetime.strptime(day_str, "%Y-%m-%d")
    header = dt.strftime("%A, %B %d")
    lines = [header]
    if nearby_event:
        lines.append(f"Already in {nearby_event.get('location') or 'that area'} at {nearby_event.get('start_time')}")
    if chosen:
        lines.append("Add:")
        base_hour = 12
        for idx, firm in enumerate(chosen):
            if firm.get("quick_hello"):
                lines.append(f"- stop by {firm['name']} for a quick hello")
            else:
                hour = base_hour + idx
                suffix = "PM" if hour >= 12 else "AM"
                normalized = hour if hour <= 12 else hour - 12
                lines.append(f"- {firm['name']} at {normalized}:30 {suffix}")
    if outreach:
        lines.append("")
        lines.append("Reach out today to:")
        for item in outreach:
            lines.append(f"- {item['contact']} at {item['firm']}")
    return "\n".join(lines)


def build_recommendations(day_str: str, mode: str, neighborhood: str, current_location: dict | None):
    firms = AIRTABLE_CACHE.get("firms") or []
    sales_visits = AIRTABLE_CACHE.get("sales_visits") or []
    if not firms:
        raise RuntimeError("Sync Airtable first.")
    visit_index = build_firm_visit_index(firms, sales_visits)
    candidates = choose_candidate_firms(firms, visit_index, neighborhood)
    connected, events = get_calendar_events_for_day(day_str)
    events = enrich_calendar_locations(events) if connected else []

    chosen = []
    outreach = []
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
                ranked.append((score_frequency_gap(firm) * -1, firm.get("neighborhood") or "", firm))
        ranked.sort(key=lambda x: (x[0], x[1]))
        chosen = [item[2] for item in ranked[:4]]
    elif mode == "frequency_protection":
        ranked = []
        for firm in candidates:
            gap = score_frequency_gap(firm)
            firm = dict(firm)
            firm["reason"] = "Falling behind"
            ranked.append((-gap, 0 if not firm.get("visited_this_quarter") else 1, firm))
        ranked.sort(key=lambda x: (x[0], x[1]))
        chosen = [item[2] for item in ranked[:4]]
    elif mode == "outreach_first":
        ranked = []
        for firm in candidates:
            if not firm.get("visited_this_quarter"):
                firm = dict(firm)
                firm["reason"] = "Good target"
                ranked.append((firm.get("neighborhood") or "", -score_frequency_gap(firm), firm))
        ranked.sort(key=lambda x: (x[0], x[1]))
        chosen = [item[2] for item in ranked[:4]]

    for firm in chosen[:2]:
        if firm.get("primary_contact"):
            outreach.append({"contact": firm["primary_contact"], "firm": firm["name"]})

    summary_text = make_summary_text(day_str, mode, nearby_event, chosen, outreach)
    return {
        "summary_text": summary_text,
        "suggested_stops": chosen,
        "calendar_events": events,
    }


def optimize_route_ors(current_location: dict, stops: list[dict]) -> dict:
    ors_key = require_env("ORS_API_KEY")
    coords = [[current_location["lng"], current_location["lat"]]] + [[s["lng"], s["lat"]] for s in stops]
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


@app.get("/")
def index():
    return render_template_string(APP_HTML)


@app.get("/google/login")
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
def google_callback():
    config = get_google_client_config()
    if not config:
        return redirect(url_for("index"))
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
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
    session["google_token"] = json.loads(creds.to_json())
    return redirect(url_for("index"))


@app.get("/api/sync-airtable")
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
def api_geocode_address():
    try:
        address = (request.get_json(force=True) or {}).get("address", "").strip()
        if not address:
            return jsonify({"error": "Address is required."}), 400
        result = geocode_address(address, load_geocode_cache())
        if result.get("lat") is None:
            return jsonify({"error": "Could not find that address."}), 404
        return jsonify(result)
    except requests.HTTPError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        return jsonify({"error": f"API request failed: {detail}"}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/recommend-schedule")
def api_recommend_schedule():
    try:
        payload = request.get_json(force=True) or {}
        result = build_recommendations(
            day_str=payload.get("date") or datetime.now().strftime("%Y-%m-%d"),
            mode=payload.get("mode") or "near_meeting",
            neighborhood=payload.get("neighborhood") or "",
            current_location=payload.get("current_location"),
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/optimize-route")
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


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
