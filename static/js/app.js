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

  function openStopAddMenu(btnEl) {
    const menu = document.getElementById('stopAddMenu');
    const alreadyOpen = menu.classList.contains('open');
    closeStopAddMenu();
    if (alreadyOpen) return;
    const rect = btnEl.getBoundingClientRect();
    menu.style.top = (rect.bottom + 4) + 'px';
    const right = window.innerWidth - rect.right;
    menu.style.right = right + 'px';
    menu.style.left = 'auto';
    menu.classList.add('open');
  }

  function closeStopAddMenu() {
    document.getElementById('stopAddMenu').classList.remove('open');
  }

  function addClosestSuggestion() {
    if (!state.currentLocation) {
      setStatus('Set a start location first.', false);
      return;
    }
    const existing = new Set(state.suggestedStops.map(s => s.id).filter(Boolean));
    const candidates = state.firms.filter(f =>
      !existing.has(f.id) && f.lat != null && f.lng != null
    );
    if (!candidates.length) {
      setStatus('No more firms to add.', false);
      return;
    }
    // find closest by straight-line distance
    let best = null, bestDist = Infinity;
    const { lat: sLat, lng: sLng } = state.currentLocation;
    candidates.forEach(f => {
      const dlat = f.lat - sLat, dlng = f.lng - sLng;
      const d = dlat * dlat + dlng * dlng;
      if (d < bestDist) { bestDist = d; best = f; }
    });
    if (best) {
      insertStop(Object.assign({}, best, { reason: 'Closest to start' }), state.suggestedStops.length - 1);
      setStatus('Closest firm added.', true);
    }
  }

  function rebuildSummaryText() {
    const dateVal = document.getElementById('planDate').value;
    const startVal = document.getElementById('startTimeSelect').value;
    if (!dateVal || !state.suggestedStops.length) { renderSummaryPane(); return; }
    const dt = new Date(dateVal + 'T12:00:00');
    const days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const [sh, smRaw] = startVal.split(':').map(Number);
    const sm = isNaN(smRaw) ? 0 : smRaw;
    const sfx = sh < 12 ? 'AM' : 'PM';
    let dh = sh <= 12 ? sh : sh - 12; if (dh === 0) dh = 12;
    const lines = [
      days[dt.getDay()] + ', ' + months[dt.getMonth()] + ' ' + dt.getDate(),
      'Starting at ' + dh + ':' + String(sm).padStart(2,'0') + ' ' + sfx,
    ];
    if (state.suggestedStops.length) {
      lines.push('Add:');
      state.suggestedStops.forEach((firm, idx) => {
        const tot = sh * 60 + sm + idx * 45;
        const fh = Math.floor(tot / 60), fm = tot % 60;
        const fs = fh < 12 ? 'AM' : 'PM';
        let fdh = fh <= 12 ? fh : fh - 12; if (fdh === 0) fdh = 12;
        const t = fdh + ':' + String(fm).padStart(2,'0') + ' ' + fs;
        lines.push(firm.quick_hello ? '- stop by ' + firm.name + ' around ' + t : '- ' + firm.name + ' at ' + t);
      });
    }
    state.summaryText = lines.join('\n');
    if (state.view === 'summary') renderSummaryPane();
  }

  function ignoreStop(idx) {
    closeStopCtxMenu();
    state.suggestedStops.splice(idx, 1);
    state.suggestedStopIds = new Set(state.suggestedStops.map(x => x.id));
    hideAddStopPanel();
    renderSuggestedStops();
    renderMapPins(state.firms, true);  // preserve zoom when removing a stop
    rebuildSummaryText();
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
    renderMapPins(state.firms, true);  // preserve zoom when adding a stop
    rebuildSummaryText();
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
    if (!e.target.closest('#stopAddMenu') && !e.target.closest('#addStopHeaderBtn')) {
      closeStopAddMenu();
    }
  });

  document.getElementById('addStopHeaderBtn').addEventListener('click', function(e) {
    e.stopPropagation();
    openStopAddMenu(this);
  });

  function initResizers() {
    const shell = document.querySelector('.shell');
    const rightPanel = document.querySelector('.right');

    // ── Left column: controls ↕ calendar ──
    const leftVResizer = document.getElementById('leftVResizer');
    leftVResizer.addEventListener('mousedown', function(e) {
      e.preventDefault();
      leftVResizer.classList.add('dragging');
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      const planPanel = document.getElementById('panel-plan');
      const leftCol = document.querySelector('.left');
      const onMove = function(e) {
        const rect = leftCol.getBoundingClientRect();
        let h = e.clientY - rect.top;
        h = Math.max(180, Math.min(rect.height - 100, h));
        planPanel.style.height = h + 'px';
        planPanel.style.flexShrink = '0';
      };
      const onUp = function() {
        leftVResizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });

    // ── Horizontal (left ↔ right) ──
    const hResizer = document.getElementById('hResizer');
    hResizer.addEventListener('mousedown', function(e) {
      e.preventDefault();
      hResizer.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      const onMove = function(e) {
        const rect = shell.getBoundingClientRect();
        let w = e.clientX - rect.left - 14;
        w = Math.max(220, Math.min(540, w));
        shell.style.gridTemplateColumns = w + 'px 14px 1fr';
        if (state.map) state.map.invalidateSize();
      };
      const onUp = function() {
        hResizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        if (state.map) state.map.invalidateSize();
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });

    // ── Vertical (map ↕ results) ──
    const vResizer = document.getElementById('vResizer');
    vResizer.addEventListener('mousedown', function(e) {
      e.preventDefault();
      vResizer.classList.add('dragging');
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      const onMove = function(e) {
        const rect = rightPanel.getBoundingClientRect();
        let h = rect.bottom - e.clientY;
        h = Math.max(100, Math.min(rect.height - 120, h));
        rightPanel.style.gridTemplateRows = '1fr 14px ' + h + 'px';
        if (state.map) state.map.invalidateSize();
      };
      const onUp = function() {
        vResizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        if (state.map) state.map.invalidateSize();
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  function initialize() {
    state.map = L.map('map', { scrollWheelZoom: true, wheelDebounceTime: 0, wheelPxPerZoomLevel: 120, zoomSnap: 0.25 }).setView([42.3601, -71.0589], 8);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(state.map);
    document.getElementById('planDate').value = new Date().toISOString().slice(0, 10);
    populateStartTimes();
    initResizers();
    if (isMobile()) switchMobileTab('plan');
    restoreCache();
    refreshCalendarDay();
    syncAirtable();
  }

  const STOP_COLORS = [
    '#e53935','#fb8c00','#43a047','#1e88e5','#8e24aa','#00acc1',
    '#d81b60','#5c6bc0','#00897b','#f4511e','#7cb342','#039be5',
    '#ff7043','#ab47bc','#26a69a','#ec407a'
  ];

  function stopColor(idx) { return STOP_COLORS[idx % STOP_COLORS.length]; }

  function clearMarkers() { state.markers.forEach(m => m.remove()); state.markers = []; }

  function renderMapPins(firms, skipFit) {
    clearMarkers();
    const stopIndexMap = {};
    state.suggestedStops.forEach((s, i) => { if (s.id) stopIndexMap[s.id] = i; });

    // Build a flat list of all pins
    const pins = [];
    firms.forEach(firm => {
      if (firm.lat == null || firm.lng == null) return;
      const stopIdx = firm.id != null ? stopIndexMap[firm.id] : undefined;
      pins.push({ firm, isSuggested: stopIdx !== undefined, stopIdx, lat: firm.lat, lng: firm.lng });
    });
    state.suggestedStops.forEach((s, i) => {
      if (s.id && s.id.startsWith('custom_') && s.lat != null && s.lng != null)
        pins.push({ firm: s, isSuggested: true, stopIdx: i, lat: s.lat, lng: s.lng });
    });

    // Group by rounded coords (~11m grid) to detect co-located firms
    const groups = {};
    pins.forEach((pin, idx) => {
      const key = pin.lat.toFixed(4) + ',' + pin.lng.toFixed(4);
      if (!groups[key]) groups[key] = [];
      groups[key].push(idx);
    });

    // Spread co-located pins in a small circle so they sit side by side
    const offsets = {};
    Object.values(groups).forEach(indices => {
      if (indices.length <= 1) return;
      const r = 0.00025; // ~25 metres
      indices.forEach((pinIdx, i) => {
        const angle = (2 * Math.PI * i) / indices.length - Math.PI / 2;
        offsets[pinIdx] = {
          lat: pins[pinIdx].lat + r * Math.cos(angle),
          lng: pins[pinIdx].lng + r * Math.sin(angle),
        };
      });
    });

    const bounds = [];
    pins.forEach((pin, idx) => {
      const { firm, isSuggested, stopIdx } = pin;
      const color = isSuggested ? stopColor(stopIdx) : '#2563eb';
      const pos = offsets[idx] || { lat: pin.lat, lng: pin.lng };
      const marker = L.circleMarker([pos.lat, pos.lng], {
        radius: isSuggested ? 12 : 6,
        fillColor: color,
        color: '#ffffff', weight: isSuggested ? 3 : 2, opacity: 1, fillOpacity: 1
      }).addTo(state.map);
      const label = isSuggested ? ` <span style="background:${color};color:#fff;border-radius:999px;padding:1px 6px;font-size:10px;font-weight:700;">${stopIdx + 1}</span>` : '';
      marker.bindPopup(`<strong>${esc(firm.name)}</strong>${label}<br>${esc(firm.address || '')}<br><span style="color:#6b7280">${esc(firm.neighborhood||'')}</span>`);
      state.markers.push(marker);
      bounds.push([pin.lat, pin.lng]);
    });

    if (state.currentLocation) bounds.push([state.currentLocation.lat, state.currentLocation.lng]);
    if (!skipFit && bounds.length) state.map.fitBounds(bounds, { padding: [50, 50] });
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
        <div class="stop-n" style="background:${stopColor(i)}">${i + 1}</div>
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
      const mapped = state.firms.filter(f => f.lat != null && f.lng != null).length;
      const noAddr = state.firms.filter(f => !f.raw_address).length;
      const notGeocoded = state.firms.length - mapped - noAddr;
      let badgeText = '<span class="dot"></span> ' + mapped + ' on map';
      if (notGeocoded > 0) badgeText += ' · ' + notGeocoded + ' not mapped';
      if (noAddr > 0) badgeText += ' · ' + noAddr + ' no address';
      badge.innerHTML = badgeText;
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
        neighborhood: '',
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
      renderMapPins(state.firms, true);  // redraw pins without auto-fit
      // fit map to the suggested stops (+ start location) so we zoom into the relevant area
      const planBounds = [];
      state.suggestedStops.forEach(s => { if (s.lat != null && s.lng != null) planBounds.push([s.lat, s.lng]); });
      if (state.currentLocation) planBounds.push([state.currentLocation.lat, state.currentLocation.lng]);
      if (planBounds.length) state.map.fitBounds(planBounds, { padding: [60, 60] });
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

  // ── Custom stop name autocomplete ──
  (function() {
    const nameInput = document.getElementById('customStopName');
    const addrInput = document.getElementById('customStopAddr');
    const sugBox = document.getElementById('customNameSuggestions');

    function renderNameSuggestions(q) {
      if (!q) { sugBox.classList.remove('open'); sugBox.innerHTML = ''; return; }
      const existing = new Set(state.suggestedStops.map(s => s.id).filter(Boolean));
      const ql = q.toLowerCase();
      const hits = state.firms.filter(f =>
        !existing.has(f.id) && (f.name || '').toLowerCase().includes(ql)
      ).slice(0, 8);
      if (!hits.length) { sugBox.classList.remove('open'); sugBox.innerHTML = ''; return; }
      sugBox.innerHTML = hits.map(f => `
        <div class="custom-name-suggestion" data-firm-id="${esc(f.id)}">
          <div>${esc(f.name)}</div>
          ${f.address ? `<div class="csug-addr">${esc(f.address)}</div>` : ''}
        </div>
      `).join('');
      sugBox.classList.add('open');
      sugBox.querySelectorAll('.custom-name-suggestion').forEach(el => {
        el.addEventListener('mousedown', function(e) {
          e.preventDefault(); // prevent blur before click
          const firm = state.firms.find(f => f.id === el.dataset.firmId);
          if (firm) {
            nameInput.value = firm.name;
            addrInput.value = firm.address || '';
          }
          sugBox.classList.remove('open');
          sugBox.innerHTML = '';
        });
      });
    }

    nameInput.addEventListener('input', function() { renderNameSuggestions(this.value.trim()); });
    nameInput.addEventListener('blur', function() {
      setTimeout(() => { sugBox.classList.remove('open'); }, 150);
    });
  })();

  // ── Firms search (controls panel) ──
  (function() {
    const input = document.getElementById('firmSearch');
    const sugBox = document.getElementById('firmSearchSuggestions');

    function renderFirmSuggestions(q) {
      if (!q) { sugBox.classList.remove('open'); sugBox.innerHTML = ''; return; }
      const existing = new Set(state.suggestedStops.map(s => s.id).filter(Boolean));
      const ql = q.toLowerCase();
      const hits = state.firms.filter(f =>
        !existing.has(f.id) &&
        ((f.name || '').toLowerCase().includes(ql) || (f.address || '').toLowerCase().includes(ql))
      ).slice(0, 8);
      if (!hits.length) { sugBox.classList.remove('open'); sugBox.innerHTML = ''; return; }
      sugBox.innerHTML = hits.map(f => `
        <div class="custom-name-suggestion" data-firm-id="${esc(f.id)}">
          <div>${esc(f.name)}</div>
          ${f.address ? `<div class="csug-addr">${esc(f.address)}</div>` : ''}
        </div>
      `).join('');
      sugBox.classList.add('open');
      sugBox.querySelectorAll('.custom-name-suggestion').forEach(el => {
        el.addEventListener('mousedown', function(e) {
          e.preventDefault();
          const firm = state.firms.find(f => f.id === el.dataset.firmId);
          if (firm) insertStop(Object.assign({}, firm, { reason: 'Added manually' }), state.suggestedStops.length - 1);
          input.value = '';
          sugBox.classList.remove('open');
          sugBox.innerHTML = '';
        });
      });
    }

    input.addEventListener('input', function() { renderFirmSuggestions(this.value.trim()); });
    input.addEventListener('blur', function() { setTimeout(() => { sugBox.classList.remove('open'); }, 150); });
  })();

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
