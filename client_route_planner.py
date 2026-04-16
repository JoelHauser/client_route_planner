from flask import Flask, jsonify, render_template_string, request, redirect, session, url_for
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

CACHE_FILE = "geocode_cache.json"
GOOGLE_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_token.json")
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
  <script>(function(){var t=localStorage.getItem('theme');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');})()</script>
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
    [data-theme="dark"] {
      --bg: #0f1117;
      --panel: #1a1d27;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --line: #2a2d3e;
      --line-strong: #3a3d52;
      --accent: #e5e7eb;
      --soft-bg: #14172a;
      --success-bg: #052e16;
      --success-text: #4ade80;
      --success-border: #166534;
      --amber-bg: #1c1400;
      --amber-text: #fbbf24;
      --amber-border: #92400e;
    }
    [data-theme="dark"] .leaflet-tile { filter: invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%); }
    [data-theme="dark"] button.primary { background: #e5e7eb; color: #111827; }
    [data-theme="dark"] .stop-n { background: #4b5563; color: #f9fafb; }
    /* ── LAYOUT ── */
    body { font-family: Inter, system-ui, sans-serif; background: var(--bg); color: var(--text); font-size: 13px; line-height: 1.5; height: 100vh; overflow: hidden; }
    .shell { display: grid; grid-template-columns: 340px 1fr; grid-template-rows: calc(100vh - 34px); gap: 14px; padding: 14px 14px 20px; height: 100vh; }
    .left { display: flex; flex-direction: column; gap: 14px; min-height: 0; }
    .right { display: grid; grid-template-rows: 1fr 310px; gap: 14px; min-height: 0; }
    /* panels */
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-lg); }
    .controls-panel { flex-shrink: 0; padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }
    .calendar-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
    .map-panel { overflow: hidden; }
    #map { width: 100%; height: 100%; }
    .results-panel { display: grid; grid-template-columns: 1fr 1fr; min-height: 0; overflow: hidden; }
    /* controls panel internals */
    .app-title { display: flex; align-items: center; gap: 8px; }
    .app-title h1 { font-size: 18px; font-weight: 700; letter-spacing: -0.02em; }
    .app-title span { font-size: 11px; color: var(--muted); }
    .ctrl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .ctrl-grid .full { grid-column: 1 / -1; }
    label { font-size: 11px; color: var(--muted); display: block; margin-bottom: 5px; }
    input[type="text"], input[type="date"], select {
      width: 100%; border: 1px solid var(--line-strong); border-radius: var(--radius-md);
      padding: 9px 12px; font: inherit; font-size: 13px; background: var(--panel); color: var(--text); outline: none;
    }
    input:focus, select:focus { border-color: #6b7280; }
    /* buttons */
    button { font: inherit; border: 1px solid var(--line-strong); border-radius: var(--radius-md); padding: 9px 12px; cursor: pointer; font-size: 13px; font-weight: 600; background: var(--panel); color: var(--text); transition: background .12s; white-space: nowrap; }
    button:hover { background: var(--soft-bg); }
    button.primary { background: var(--accent); color: #fff; border-color: transparent; }
    button.primary:hover { opacity: .88; }
    button.ghost { background: var(--soft-bg); border-color: transparent; color: var(--muted); font-weight: 500; }
    button.ghost:hover { background: var(--line); color: var(--text); }
    .btn-row { display: flex; gap: 8px; }
    .btn-row > * { flex: 1 1 0; min-width: 0; }
    /* badges */
    .badge { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 600; border: 1px solid var(--line); background: var(--soft-bg); color: var(--muted); white-space: nowrap; }
    .badge.green { background: var(--success-bg); color: var(--success-text); border-color: var(--success-border); }
    .badge.amber { background: var(--amber-bg); color: var(--amber-text); border-color: var(--amber-border); }
    .dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex-shrink: 0; display: inline-block; }
    /* section header inside panels */
    .sec-head { padding: 10px 16px; background: var(--soft-bg); border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
    .sec-label { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
    /* calendar panel */
    .cal-body { flex: 1; overflow-y: auto; padding: 10px 16px; }
    .cal-footer { padding: 10px 16px; border-top: 1px solid var(--line); display: flex; gap: 8px; flex-shrink: 0; }
    .cal-footer button { flex: 1; }
    .event-row { display: flex; gap: 8px; align-items: flex-start; padding: 9px 0; border-bottom: 1px solid var(--line); }
    .event-row:last-of-type { border-bottom: none; }
    .event-time { font-size: 11px; color: var(--muted); min-width: 52px; padding-top: 1px; flex-shrink: 0; }
    .event-title { font-size: 12px; font-weight: 600; }
    .event-loc { font-size: 11px; color: var(--muted); margin-top: 1px; }
    .event-loc-link { cursor: pointer; text-decoration: underline dotted; }
    .event-loc-link:hover { color: var(--text); }
    /* results panel */
    .res-col { display: flex; flex-direction: column; min-height: 0; overflow: hidden; border-right: 1px solid var(--line); }
    .res-col:last-child { border-right: none; }
    .res-body { flex: 1; overflow-y: auto; padding: 10px 14px; }
    /* stops */
    .stop { display: flex; gap: 8px; align-items: flex-start; padding: 9px 0; border-bottom: 1px solid var(--line); }
    .stop:last-of-type { border-bottom: none; }
    .stop-n { width: 20px; height: 20px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 10px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
    .stop-name { font-size: 12px; font-weight: 600; }
    .stop-addr { font-size: 11px; color: var(--muted); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .stop-badge { margin-left: auto; flex-shrink: 0; }
    /* stop context menu */
    .stop-menu-btn { padding: 2px 7px; font-size: 15px; line-height: 1; border: none; background: transparent; color: var(--muted); cursor: pointer; border-radius: var(--radius-sm); flex-shrink: 0; margin-left: 4px; }
    .stop-menu-btn:hover { background: var(--soft-bg); color: var(--text); }
    .stop-ctx-menu { position: fixed; z-index: 300; background: var(--panel); border: 1px solid var(--line-strong); border-radius: var(--radius-md); box-shadow: 0 4px 20px rgba(0,0,0,.18); min-width: 200px; padding: 4px; display: none; }
    .stop-ctx-menu.open { display: block; }
    .stop-ctx-item { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; padding: 8px 12px; font-size: 12px; font-weight: 500; border: none; background: none; color: var(--text); cursor: pointer; border-radius: var(--radius-sm); }
    .stop-ctx-item:hover { background: var(--soft-bg); }
    .stop-ctx-item.danger { color: #dc2626; }
    /* add stop panel */
    .add-stop-panel { border-top: 1px solid var(--line); padding: 10px 14px; display: none; flex-direction: column; gap: 7px; }
    .add-stop-panel.open { display: flex; }
    .add-stop-input { padding: 7px 10px; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); font: inherit; font-size: 12px; background: var(--panel); color: var(--text); width: 100%; outline: none; }
    .add-stop-input:focus { border-color: #6b7280; }
    .add-stop-list { max-height: 130px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
    .add-stop-item { display: flex; flex-direction: column; padding: 6px 8px; border-radius: var(--radius-sm); cursor: pointer; border: 1px solid transparent; }
    .add-stop-item:hover { background: var(--soft-bg); border-color: var(--line); }
    .add-stop-item-name { font-size: 12px; font-weight: 600; }
    .add-stop-item-addr { font-size: 11px; color: var(--muted); }
    /* route steps */
    .route-step { display: flex; gap: 8px; align-items: flex-start; padding: 9px 0; border-bottom: 1px solid var(--line); }
    .route-step:last-child { border-bottom: none; }
    .route-step-n { font-size: 11px; font-weight: 700; color: var(--muted); min-width: 16px; padding-top: 1px; }
    .route-step-name { font-size: 12px; font-weight: 600; }
    .route-step-meta { font-size: 11px; color: var(--muted); margin-top: 1px; }
    /* summary text */
    .summary-text { white-space: pre-wrap; font-size: 12px; line-height: 1.6; color: var(--text); }
    .no-content { font-size: 12px; color: var(--muted); padding: 4px 0; }
    /* status bar */
    .status-bar { padding: 9px 20px; border-top: 1px solid var(--line); font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 6px; background: var(--soft-bg); border-radius: 0 0 var(--radius-lg) var(--radius-lg); flex-shrink: 0; }
    .pulse { width: 6px; height: 6px; border-radius: 50%; background: #d1d5db; flex-shrink: 0; }
    /* res footer */
    .res-footer { padding: 10px 14px; border-top: 1px solid var(--line); display: flex; gap: 8px; flex-shrink: 0; }
    .res-footer button { flex: 1; }
    /* ── MOBILE ── */
    @media (max-width: 767px) {
      body { overflow: hidden; }
      .shell {
        display: block; padding: 0; gap: 0;
        height: calc(100dvh - 58px);
        overflow: hidden;
      }
      .left, .right { display: contents; }
      .panel {
        display: none;
        height: calc(100dvh - 58px);
        border-radius: 0;
        border-left: none; border-right: none; border-top: none; border-bottom: none;
      }
      .panel.mob-active { display: flex; flex-direction: column; }
      .map-panel.mob-active { display: block; overflow: hidden; }
      .controls-panel { overflow-y: auto; }
      .status-bar { margin: 0 !important; border-radius: 0 !important; }
      .results-panel.mob-active { display: block; overflow-y: auto; }
      .res-col { display: block; border-right: none; border-bottom: 1px solid var(--line); }
      .res-col:last-child { border-bottom: none; }
      .res-body { overflow-y: visible; height: auto; }
      .mobile-tabs {
        position: fixed; bottom: 0; left: 0; right: 0;
        height: calc(58px + env(safe-area-inset-bottom, 0px));
        padding-bottom: env(safe-area-inset-bottom, 0px);
        display: flex;
        background: var(--panel);
        border-top: 1px solid var(--line);
        z-index: 9999;
      }
      .mobile-tab {
        flex: 1; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 3px;
        border: none; background: transparent;
        color: var(--muted); cursor: pointer;
        font-size: 9px; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.05em;
        padding: 6px 4px; border-radius: 0; white-space: nowrap;
        transition: color .12s;
      }
      .mobile-tab.active { color: var(--text); }
      .mobile-tab svg { display: block; flex-shrink: 0; }
    }
    @media (min-width: 768px) { .mobile-tabs { display: none; } }
  </style>
</head>
<body>
<div class="shell">

  <!-- LEFT COLUMN -->
  <div class="left">

    <!-- Controls panel (fixed height) -->
    <div id="panel-plan" class="panel controls-panel">
      <div class="app-title">
        <h1>Where2Go</h1>
        <span>Scheduling assistant</span>
        <div style="margin-left:auto;display:flex;gap:6px;align-items:center;">
          <button id="themeBtn" class="ghost" style="padding:5px 11px;font-size:11px;font-weight:500;">◐ Dark</button>
          <a href="/logout" style="font-size:11px;color:var(--muted);text-decoration:none;padding:5px 10px;border:1px solid var(--line);border-radius:var(--radius-sm);">Sign out</a>
        </div>
      </div>

      <!-- top action row -->
      <div class="btn-row">
        <button class="primary" id="syncBtn">Sync Airtable</button>
        <button class="ghost" id="fitBtn">Fit map</button>
      </div>
      <div class="btn-row">
        <button class="ghost" id="googleConnectBtn">Connect Google Calendar</button>
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
          <label for="startTimeSelect">Start time</label>
          <select id="startTimeSelect"></select>
        </div>
        <div class="full">
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
      </div>
      <div class="btn-row">
        <button class="primary" id="recommendBtn">Build plan</button>
      </div>

      <div class="status-bar" style="margin: -4px -20px -18px; border-radius: 0 0 var(--radius-lg) var(--radius-lg); border-top: 1px solid var(--line);">
        <span class="pulse" id="statusPulse"></span>
        <span id="statusText">Ready.</span>
      </div>
    </div>

    <!-- Calendar panel (scrollable, fills remaining height) -->
    <div id="panel-calendar" class="panel calendar-panel">
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
    <div id="panel-map" class="panel map-panel">
      <div id="map"></div>
    </div>

    <!-- Results strip (stops + summary side by side) -->
    <div id="panel-stops" class="panel results-panel">

      <!-- Suggested stops -->
      <div class="res-col">
        <div class="sec-head">
          <span class="sec-label">Suggested stops</span>
          <span class="badge" id="stopsBadge">0</span>
        </div>
        <div class="res-body" id="stopsBody">
          <div class="no-content">Build a plan to see stops.</div>
        </div>
        <div id="addStopPanel" class="add-stop-panel">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="sec-label" id="addStopPanelTitle">ADD STOP</span>
            <button class="ghost" onclick="hideAddStopPanel()" style="padding:2px 8px;font-size:11px;">✕ Close</button>
          </div>
          <div id="addStopFirmSection" style="display:flex;flex-direction:column;gap:6px;">
            <input id="addStopSearch" class="add-stop-input" type="text" placeholder="Search firms…">
            <div id="addStopList" class="add-stop-list"></div>
          </div>
          <div id="addStopCustomSection" style="display:none;flex-direction:column;gap:6px;">
            <input id="customStopName" class="add-stop-input" type="text" placeholder="Stop name…">
            <input id="customStopAddr" class="add-stop-input" type="text" placeholder="Address…">
            <button class="primary" id="customStopAddBtn" style="padding:7px;">Add stop</button>
          </div>
        </div>
        <div class="res-footer">
          <button class="primary" id="optimizeBtn">Optimize route</button>
          <button class="ghost" id="openMapsBtn">Open in Maps</button>
          <button class="ghost" id="clearRouteBtn">Clear</button>
        </div>
      </div>

      <!-- Day summary / route steps / calendar route -->
      <div class="res-col">
        <div class="sec-head">
          <span class="sec-label" id="summaryTabLabel">Day summary</span>
          <div style="display:flex;gap:4px;">
            <button class="ghost" id="showSummaryBtn" style="padding:2px 8px;font-size:10px;">Summary</button>
            <button class="ghost" id="showRouteBtn" style="padding:2px 8px;font-size:10px;">Route</button>
            <button class="ghost" id="showCalRouteBtn" style="padding:2px 8px;font-size:10px;">Calendar</button>
          </div>
        </div>
        <div class="res-body" id="summaryBody">
          <div class="no-content">No plan yet.</div>
        </div>
        <div class="res-footer" id="calRouteFooter" style="display:none;">
          <button class="primary" id="optimizeCalRouteBtn">Optimize calendar route</button>
          <button class="ghost" id="openCalMapsBtn">Open in Maps</button>
        </div>
      </div>

    </div>
  </div>

</div>

<nav class="mobile-tabs">
  <button class="mobile-tab" data-section="plan">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><circle cx="8" cy="6" r="2.5" fill="var(--panel)"/><line x1="4" y1="12" x2="20" y2="12"/><circle cx="16" cy="12" r="2.5" fill="var(--panel)"/><line x1="4" y1="18" x2="20" y2="18"/><circle cx="10" cy="18" r="2.5" fill="var(--panel)"/></svg>
    Plan
  </button>
  <button class="mobile-tab" data-section="map">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>
    Map
  </button>
  <button class="mobile-tab" data-section="stops">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>
    Stops
  </button>
  <button class="mobile-tab" data-section="calendar">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
    Calendar
  </button>
</nav>

<div id="stopCtxMenu" class="stop-ctx-menu">
  <button class="stop-ctx-item danger" onclick="ignoreStop(+document.getElementById('stopCtxMenu').dataset.idx)">✕  Remove this stop</button>
  <button class="stop-ctx-item" onclick="showAddFirmPanel(+document.getElementById('stopCtxMenu').dataset.idx)">＋  Add stop from firms list</button>
  <button class="stop-ctx-item" onclick="showCreateCustomPanel(+document.getElementById('stopCtxMenu').dataset.idx)">✎  Create custom stop</button>
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
    openStopMenu: -1, addStopAfterIdx: -1,
    calendarEventsFull: [], calendarRouteWaypoints: [], calendarRouteLayer: null,
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

  // ── Mobile tab navigation ──
  function isMobile() { return window.innerWidth < 768; }

  function switchMobileTab(name) {
    ['plan', 'map', 'stops', 'calendar'].forEach(s => {
      document.getElementById('panel-' + s).classList.remove('mob-active');
    });
    document.getElementById('panel-' + name).classList.add('mob-active');
    document.querySelectorAll('.mobile-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.section === name);
    });
    if (name === 'map') setTimeout(() => { if (state.map) state.map.invalidateSize(); }, 80);
  }

  document.querySelectorAll('.mobile-tab').forEach(btn => {
    btn.addEventListener('click', () => switchMobileTab(btn.dataset.section));
  });

  async function restoreCache() {
    try {
      const res = await fetch('/api/firms-cache');
      const data = await res.json();
      if (data.firms && data.firms.length) {
        state.firms = data.firms;
        state.visits = data.sales_visits || [];
        const badge = document.getElementById('syncBadge');
        badge.className = 'badge green';
        badge.innerHTML = '<span class="dot"></span> ' + state.firms.length + ' firms';
        renderMapPins(state.firms);
        setStatus('Airtable data restored.', true);
      }
    } catch (err) {}
  }

  function populateStartTimes() {
    const sel = document.getElementById('startTimeSelect');
    for (let h = 7; h <= 19; h++) {
      for (let m = 0; m < 60; m += 30) {
        const suffix = h < 12 ? 'AM' : 'PM';
        const displayH = h === 0 ? 12 : (h > 12 ? h - 12 : h);
        const displayM = m === 0 ? '00' : '30';
        const opt = document.createElement('option');
        opt.value = h + ':' + displayM;
        opt.textContent = displayH + ':' + displayM + ' ' + suffix;
        if (h === 9 && m === 0) opt.selected = true;
        sel.appendChild(opt);
      }
    }
  }

  function openStopCtxMenu(idx, btnEl) {
    if (state.openStopMenu === idx) { closeStopCtxMenu(); return; }
    state.openStopMenu = idx;
    const menu = document.getElementById('stopCtxMenu');
    menu.dataset.idx = idx;
    const rect = btnEl.getBoundingClientRect();
    menu.style.top = (rect.bottom + 4) + 'px';
    const right = window.innerWidth - rect.right;
    menu.style.right = right + 'px';
    menu.style.left = 'auto';
    menu.classList.add('open');
  }

  function closeStopCtxMenu() {
    state.openStopMenu = -1;
    document.getElementById('stopCtxMenu').classList.remove('open');
  }

  function ignoreStop(idx) {
    closeStopCtxMenu();
    state.suggestedStops.splice(idx, 1);
    state.suggestedStopIds = new Set(state.suggestedStops.map(x => x.id));
    hideAddStopPanel();
    renderSuggestedStops();
    renderMapPins(state.firms);
  }

  function showAddFirmPanel(afterIdx) {
    closeStopCtxMenu();
    state.addStopAfterIdx = afterIdx;
    document.getElementById('addStopPanelTitle').textContent = 'ADD STOP FROM FIRMS';
    document.getElementById('addStopFirmSection').style.display = 'flex';
    document.getElementById('addStopCustomSection').style.display = 'none';
    document.getElementById('addStopSearch').value = '';
    document.getElementById('addStopPanel').classList.add('open');
    renderAddStopList('');
    setTimeout(() => document.getElementById('addStopSearch').focus(), 50);
  }

  function showCreateCustomPanel(afterIdx) {
    closeStopCtxMenu();
    state.addStopAfterIdx = afterIdx;
    document.getElementById('addStopPanelTitle').textContent = 'CREATE CUSTOM STOP';
    document.getElementById('addStopFirmSection').style.display = 'none';
    document.getElementById('addStopCustomSection').style.display = 'flex';
    document.getElementById('customStopName').value = '';
    document.getElementById('customStopAddr').value = '';
    document.getElementById('addStopPanel').classList.add('open');
    setTimeout(() => document.getElementById('customStopName').focus(), 50);
  }

  function hideAddStopPanel() {
    document.getElementById('addStopPanel').classList.remove('open');
    state.addStopAfterIdx = -1;
  }

  function renderAddStopList(query) {
    const list = document.getElementById('addStopList');
    const existing = new Set(state.suggestedStops.map(s => s.id).filter(Boolean));
    const q = query.toLowerCase();
    const candidates = state.firms.filter(f =>
      !existing.has(f.id) &&
      (!q || (f.name || '').toLowerCase().includes(q) || (f.address || '').toLowerCase().includes(q))
    ).slice(0, 25);
    if (!candidates.length) {
      list.innerHTML = '<div style="font-size:12px;color:var(--muted);padding:6px 0;">No firms found.</div>';
      return;
    }
    list.innerHTML = candidates.map(f => `
      <div class="add-stop-item" data-firm-id="${esc(f.id)}">
        <div class="add-stop-item-name">${esc(f.name)}</div>
        <div class="add-stop-item-addr">${esc(f.address || '')}</div>
      </div>
    `).join('');
    list.querySelectorAll('.add-stop-item').forEach(el => {
      el.addEventListener('click', () => {
        const firm = state.firms.find(f => f.id === el.dataset.firmId);
        if (firm) insertStop(Object.assign({}, firm, { reason: 'Added manually' }), state.addStopAfterIdx);
      });
    });
  }

  function insertStop(firm, afterIdx) {
    if (afterIdx < 0 || afterIdx >= state.suggestedStops.length) {
      state.suggestedStops.push(firm);
    } else {
      state.suggestedStops.splice(afterIdx + 1, 0, firm);
    }
    state.suggestedStopIds = new Set(state.suggestedStops.map(x => x.id).filter(Boolean));
    hideAddStopPanel();
    renderSuggestedStops();
    renderMapPins(state.firms);
  }

  async function addCustomStop() {
    const name = document.getElementById('customStopName').value.trim();
    const address = document.getElementById('customStopAddr').value.trim();
    if (!name || !address) { setStatus('Enter a name and address.', false); return; }
    setStatus('Geocoding address…', true);
    try {
      const res = await fetch('/api/geocode-address', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ address })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not geocode address.');
      const firm = {
        id: 'custom_' + Date.now(), name,
        address: data.formatted_address || address,
        lat: data.lat || null, lng: data.lng || null,
        reason: 'Custom stop', visited_this_quarter: false,
      };
      insertStop(firm, state.addStopAfterIdx);
      setStatus('Stop added.', true);
    } catch (err) {
      setStatus(err.message || 'Could not add stop.', false);
    }
  }

  document.addEventListener('click', function(e) {
    if (!e.target.closest('#stopCtxMenu') && !e.target.closest('.stop-menu-btn') && state.openStopMenu >= 0) {
      closeStopCtxMenu();
    }
  });

  function initialize() {
    state.map = L.map('map', { scrollWheelZoom: true, wheelDebounceTime: 60, wheelPxPerZoomLevel: 80 }).setView([42.3601, -71.0589], 8);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(state.map);
    document.getElementById('planDate').value = new Date().toISOString().slice(0, 10);
    populateStartTimes();
    if (isMobile()) switchMobileTab('plan');
    restoreCache();
    refreshCalendarDay();
    syncAirtable();
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
      body.innerHTML = '<div class="no-content" style="display:flex;justify-content:space-between;align-items:center;">No stops yet.<button class="ghost" onclick="showAddFirmPanel(-1)" style="padding:4px 8px;font-size:11px;margin-left:8px;">+ Add stop</button></div>';
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
        <button class="stop-menu-btn" title="Options" onclick="event.stopPropagation();openStopCtxMenu(${i},this)">•••</button>
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
          ${ev.location ? `<div class="event-loc event-loc-link" data-address="${ev.location.replace(/"/g,'&quot;')}" title="Use as start location">${esc(ev.location)} ↗</div>` : ''}
        </div>
      </div>
    `).join('');
  }

  function renderSummaryPane() {
    const body = document.getElementById('summaryBody');
    const label = document.getElementById('summaryTabLabel');
    const calFooter = document.getElementById('calRouteFooter');
    calFooter.style.display = 'none';

    if (state.view === 'calroute') {
      label.textContent = 'Calendar route';
      const events = state.calendarRouteWaypoints.length
        ? state.calendarRouteWaypoints
        : state.calendarEventsFull.filter(e => e.location);
      if (!events.length) {
        body.innerHTML = '<div class="no-content">No calendar events with locations. Build a plan with Calendar connected.</div>';
        return;
      }
      const startHtml = `<div class="route-step"><div class="route-step-n">S</div><div><div class="route-step-name">Start</div><div class="route-step-meta">Your chosen location</div></div></div>`;
      const stepsHtml = events.map((ev, idx) => {
        const seg = (state.calendarRouteSegments || [])[idx] || {};
        return `<div class="route-step">
          <div class="route-step-n">${idx + 1}</div>
          <div style="flex:1;min-width:0;">
            <div class="route-step-name">${esc(ev.summary || ev.name || 'Event')}</div>
            <div class="route-step-meta">${esc(ev.start_time || '')}${ev.location ? ' · ' + esc(ev.location) : ''}${seg.distance_text ? ' · ' + esc(seg.distance_text) : ''}${seg.duration_text ? ' · ' + esc(seg.duration_text) : ''}</div>
          </div>
        </div>`;
      }).join('');
      body.innerHTML = startHtml + stepsHtml;
      calFooter.style.display = 'flex';
      return;
    }

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
      const btn = document.getElementById('googleConnectBtn');
      if (!res.ok) {
        badge.className = 'badge';
        badge.textContent = 'Calendar not connected';
        btn.textContent = 'Connect Google Calendar';
        state.calendarEvents = [];
      } else {
        state.calendarEvents = data.events || [];
        if (data.connected) {
          badge.className = 'badge green';
          badge.innerHTML = '<span class="dot"></span> Calendar connected';
          btn.textContent = 'Reconnect calendar';
        }
      }
      renderCalendarEvents();
    } catch (err) {
      document.getElementById('calendarBadge').textContent = 'Calendar not connected';
    }
  }

  async function setLocationFromCalendarEvent(address) {
    if (!address) return;
    setStatus('Setting location from calendar event…', true);
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
      document.getElementById('manualStartInput').value = data.formatted_address || address;
      state.map.setView([data.lat, data.lng], 13);
      renderMapPins(state.firms);
      setStatus('Start location set from calendar.', true);
      buildRecommendations();
    } catch (err) {
      setStatus(err.message || 'Could not set location.', false);
    }
  }

  document.getElementById('calendarEvents').addEventListener('click', function(e) {
    const loc = e.target.closest('.event-loc-link');
    if (loc) setLocationFromCalendarEvent(loc.dataset.address);
  });

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
      buildRecommendations();
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
      buildRecommendations();
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
        start_time: document.getElementById('startTimeSelect').value,
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
      state.calendarEventsFull = (data.calendar_events || []).filter(e => e.location);
      state.calendarRouteWaypoints = [];
      state.calendarRouteSegments = [];
      if (state.calendarRouteLayer) { state.calendarRouteLayer.remove(); state.calendarRouteLayer = null; }
      if (state.view === 'calroute') state.view = 'summary';
      renderSuggestedStops();
      renderSummaryPane();
      renderMapPins(state.firms);
      setStatus('Plan ready.', true);
      if (isMobile()) switchMobileTab('stops');
    } catch (err) {
      setStatus(err.message || 'Could not build plan.', false);
    }
  }

  function clearRoute() {
    if (state.routeLayer) { state.routeLayer.remove(); state.routeLayer = null; }
    if (state.calendarRouteLayer) { state.calendarRouteLayer.remove(); state.calendarRouteLayer = null; }
    state.optimizedWaypoints = [];
    state.lastSegments = [];
    state.calendarRouteWaypoints = [];
    state.calendarRouteSegments = [];
    renderSummaryPane();
    setStatus('Route cleared.', false);
  }

  async function optimizeCalendarRoute() {
    if (!state.currentLocation) return setStatus('Set a start location first.', false);
    const stops = state.calendarEventsFull.filter(e => e.lat != null && e.lng != null)
      .map(e => ({ name: e.summary || 'Event', address: e.location || '', lat: e.lat, lng: e.lng, start_time: e.start_time }));
    if (!stops.length) return setStatus('No calendar events with geocoded locations to optimize.', false);
    setStatus('Optimizing calendar route…', true);
    try {
      const res = await fetch('/api/optimize-route', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ current_location: state.currentLocation, stops })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Route optimization failed.');
      state.calendarRouteWaypoints = (data.ordered_stops || []).map((stop, i) => {
        const orig = stops.find(s => s.lat === stop.lat && s.lng === stop.lng) || stop;
        return Object.assign({}, orig, stop);
      });
      state.calendarRouteSegments = data.segments || [];
      drawCalendarRoute(data.geometry || []);
      renderSummaryPane();
      setStatus('Calendar route optimized.', true);
      if (isMobile()) switchMobileTab('map');
    } catch (err) {
      setStatus(err.message || 'Route optimization failed.', false);
    }
  }

  function drawCalendarRoute(coords) {
    if (state.calendarRouteLayer) state.calendarRouteLayer.remove();
    if (!coords.length) return;
    const isDarkCal = document.documentElement.getAttribute('data-theme') === 'dark';
    state.calendarRouteLayer = L.polyline(coords.map(c => [c[1], c[0]]), {
      weight: 5, color: isDarkCal ? '#38bdf8' : '#2563eb', dashArray: '8 5'
    }).addTo(state.map);
    state.map.fitBounds(state.calendarRouteLayer.getBounds(), { padding: [50, 50] });
  }

  function openCalendarInMaps() {
    const stops = state.calendarRouteWaypoints.length
      ? state.calendarRouteWaypoints
      : state.calendarEventsFull.filter(e => e.location);
    if (!state.currentLocation || !stops.length) return setStatus('Need a start location and calendar events with locations.', false);
    const origin = `${state.currentLocation.lat},${state.currentLocation.lng}`;
    const destination = encodeURIComponent(stops[stops.length - 1].location || stops[stops.length - 1].address || '');
    const waypoints = stops.slice(0, -1).map(s => s.location || s.address || '').filter(Boolean).join('|');
    let url = `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(origin)}&destination=${destination}&travelmode=driving`;
    if (waypoints) url += `&waypoints=${encodeURIComponent(waypoints)}`;
    window.open(url, '_blank');
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
      if (isMobile()) switchMobileTab('map');
    } catch (err) {
      setStatus(err.message || 'Route optimization failed.', false);
    }
  }

  function drawRoute(coords) {
    if (state.routeLayer) state.routeLayer.remove();
    if (!coords.length) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    state.routeLayer = L.polyline(coords.map(c => [c[1], c[0]]), { weight: 5, color: isDark ? '#f97316' : '#111827' }).addTo(state.map);
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
  document.getElementById('startTimeSelect').addEventListener('change', () => {
    if (state.suggestedStops.length) buildRecommendations();
  });
  document.getElementById('setManualLocationBtn').addEventListener('click', setManualStartLocation);
  document.getElementById('manualStartInput').addEventListener('keydown', function(e) { if (e.key === 'Enter') setManualStartLocation(); });
  document.getElementById('locateBtn').addEventListener('click', useCurrentLocation);
  document.getElementById('recommendBtn').addEventListener('click', buildRecommendations);
  document.getElementById('clearRouteBtn').addEventListener('click', clearRoute);
  document.getElementById('optimizeBtn').addEventListener('click', optimizeSuggestedStops);
  document.getElementById('openMapsBtn').addEventListener('click', openInGoogleMaps);
  document.getElementById('showSummaryBtn').addEventListener('click', () => { state.view = 'summary'; renderSummaryPane(); });
  document.getElementById('showRouteBtn').addEventListener('click', () => { state.view = 'route'; renderSummaryPane(); });
  document.getElementById('showCalRouteBtn').addEventListener('click', () => { state.view = 'calroute'; renderSummaryPane(); });
  document.getElementById('optimizeCalRouteBtn').addEventListener('click', optimizeCalendarRoute);
  document.getElementById('openCalMapsBtn').addEventListener('click', openCalendarInMaps);
  document.getElementById('addStopSearch').addEventListener('input', function() { renderAddStopList(this.value); });
  document.getElementById('customStopAddBtn').addEventListener('click', addCustomStop);
  document.getElementById('customStopAddr').addEventListener('keydown', function(e) { if (e.key === 'Enter') addCustomStop(); });

  // ── Dark mode ──
  (function() {
    function applyTheme(dark) {
      document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
      var btn = document.getElementById('themeBtn');
      if (btn) btn.textContent = dark ? '☀ Light' : '◐ Dark';
    }
    applyTheme(localStorage.getItem('theme') === 'dark');
    document.getElementById('themeBtn').addEventListener('click', function() {
      var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      localStorage.setItem('theme', isDark ? 'light' : 'dark');
      applyTheme(!isDark);
    });
  })();

  initialize();
</script>
</body>
</html>
"""

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

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Where2Go — Sign in</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Inter, system-ui, sans-serif; background: #f4f4f5; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
    .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 16px; padding: 36px 32px; width: 100%; max-width: 360px; }
    .logo { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 4px; }
    .sub { font-size: 13px; color: #6b7280; margin-bottom: 28px; }
    label { font-size: 12px; color: #6b7280; display: block; margin-bottom: 4px; }
    input { width: 100%; border: 1px solid #d1d5db; border-radius: 10px; padding: 9px 12px; font: inherit; font-size: 13px; outline: none; margin-bottom: 14px; }
    input:focus { border-color: #6b7280; }
    button { width: 100%; background: #111827; color: #fff; border: none; border-radius: 10px; padding: 10px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; margin-top: 4px; }
    button:hover { opacity: .88; }
    .error { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; border-radius: 10px; padding: 9px 12px; font-size: 13px; margin-bottom: 16px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Where2Go</div>
    <div class="sub">Scheduling assistant — sign in to continue</div>
    {% if error %}
    <div class="error">{{ error }}</div>
    {% endif %}
    <form method="POST" action="/login">
      <label for="username">Username</label>
      <input id="username" name="username" type="text" autocomplete="username" required />
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>
"""

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
    return render_template_string(LOGIN_HTML, error=None)

@app.post("/login")
def login_post():
    ip = request.remote_addr or "unknown"
    if not _check_login_rate(ip):
        return render_template_string(LOGIN_HTML, error="Too many attempts. Please wait a few minutes.")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if username == AUTH_USERNAME and verify_password(password):
        session["logged_in"] = True
        session.permanent = True
        return redirect(url_for("index"))
    return render_template_string(LOGIN_HTML, error="Incorrect username or password.")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
@login_required
def index():
    return render_template_string(APP_HTML)


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


if __name__ == "__main__":
    app.run(debug=_dev_mode, host="127.0.0.1", port=5000)