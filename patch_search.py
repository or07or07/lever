"""Patch index.html to add search + geolocation features (Day 60).

Adds:
  - Leaflet CSS/JS in <head>
  - Map-related CSS styles
  - Enhanced provider search with map view, filters, geocoding
  - Sidebar "Map" item for clients

Run: python patch_search.py
"""
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(BASE, "frontend", "index.html")

with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

# ---------------------------------------------------------------------------
# 1. Add Leaflet CDN + map CSS before </head>
# ---------------------------------------------------------------------------
LEAFLET_HEAD = """
<!-- Leaflet Map (Day 60 — Search + Geolocation) -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css" crossorigin="anonymous"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js" crossorigin="anonymous"></script>
<style>
/* ---- Map View (Day 60) ---- */
.search-controls{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;align-items:flex-end}
.search-controls .form-group{margin-bottom:0;flex:1;min-width:140px}
.search-controls .form-group label{font-size:.72rem;margin-bottom:3px}
.search-controls .form-group input,.search-controls .form-group select{padding:7px 10px;font-size:.85rem}
.search-controls .btn{height:38px;align-self:flex-end}
.view-toggle{display:flex;gap:0;border:1.5px solid var(--gray-200);border-radius:var(--radius);overflow:hidden;margin-left:auto}
.view-toggle button{padding:6px 14px;border:none;background:#fff;font-size:.82rem;font-weight:600;cursor:pointer;color:var(--gray-600);transition:.12s}
.view-toggle button.active{background:var(--brand);color:#fff}
.view-toggle button:hover:not(.active){background:var(--gray-100)}
#provider-map{width:100%;height:480px;border-radius:var(--radius);border:1px solid var(--gray-200);margin-bottom:16px}
.map-split{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.map-split-list{max-height:480px;overflow-y:auto}
.distance-badge{display:inline-flex;align-items:center;gap:3px;background:#e0f2fe;color:#0369a1;padding:2px 8px;border-radius:12px;font-size:.74rem;font-weight:600}
.search-result-count{font-size:.85rem;color:var(--gray-600);margin-bottom:12px}
@media(max-width:768px){.map-split{grid-template-columns:1fr}.search-controls{flex-direction:column}}
</style>
"""

if "leaflet.min.css" not in html:
    html = html.replace("</head>", LEAFLET_HEAD + "\n</head>")
    print("+ Added Leaflet CDN and map CSS")
else:
    print("= Leaflet already present, skipping")


# ---------------------------------------------------------------------------
# 2. Add map nav item to client sidebar
# ---------------------------------------------------------------------------
old_nav_client = """{icon:'\\u{1F50D}', label:'Find Provider',hash:'#/providers'},"""
new_nav_client = """{icon:'\\u{1F50D}', label:'Find Provider',hash:'#/providers'},
    {icon:'\\u{1F5FA}\\u{FE0F}', label:'Map View',hash:'#/map'},"""

if "'Map View'" not in html:
    html = html.replace(old_nav_client, new_nav_client)
    print("+ Added Map View to client sidebar")


# ---------------------------------------------------------------------------
# 3. Add map route to clientView
# ---------------------------------------------------------------------------
old_route = "if (hash==='#/providers')          return renderProviderSearch(el);"
new_route = """if (hash==='#/providers')          return renderProviderSearch(el);
  if (hash==='#/map')                return renderMapView(el);"""

if "#/map" not in html:
    html = html.replace(old_route, new_route)
    print("+ Added map route to clientView")


# ---------------------------------------------------------------------------
# 4. Replace renderProviderSearch with enhanced version + add map view
# ---------------------------------------------------------------------------
old_search_start = "// ---- Provider Search (with profession filter) ----"
old_search_end = "function showProviderDetail(m) {"

start_idx = html.find(old_search_start)
end_idx = html.find(old_search_end)

if start_idx == -1 or end_idx == -1:
    print("X Could not find provider search boundaries")
else:
    new_search = r"""// ---- Provider Search (Day 60: with geo, filters, map) ----
let _providerFilter = '';
let _searchLat = null;
let _searchLng = null;
let _searchRadius = 25;
let _searchView = 'list';
let _searchResults = [];
let _leafletMap = null;

async function renderProviderSearch(el) {
  const params = new URLSearchParams();
  if (_providerFilter) params.set('profession', _providerFilter);
  if (_searchLat && _searchLng) {
    params.set('latitude', _searchLat);
    params.set('longitude', _searchLng);
    params.set('radius_miles', _searchRadius);
  }
  params.set('page_size', '50');

  let results, total;
  try {
    const data = await get('/api/search/providers?' + params.toString());
    results = data.results;
    total = data.total;
  } catch(e) {
    const url = '/api/client/providers' + (_providerFilter ? '?profession='+_providerFilter : '');
    results = await get(url);
    total = results.length;
    results = results.map(r => ({...r, distance_miles: null}));
  }

  _searchResults = results;
  window._providerMap = {};
  results.forEach((m, idx) => { window._providerMap[idx] = m; });

  el.innerHTML = `
    ${pageHeader('Find a Provider', `
      <div class="view-toggle">
        <button class="${_searchView==='list'?'active':''}" onclick="_searchView='list';renderProviderSearch(document.getElementById('content'))">&#x1F4CB; List</button>
        <button class="${_searchView==='split'?'active':''}" onclick="_searchView='split';renderProviderSearch(document.getElementById('content'))">&#x1F5FA; Split</button>
        <button class="${_searchView==='map'?'active':''}" onclick="_searchView='map';renderProviderSearch(document.getElementById('content'))">&#x1F30E; Map</button>
      </div>
    `)}
    ${professionFilterBar(_providerFilter, 'setProviderFilter')}
    <div class="search-controls">
      <div class="form-group">
        <label>Location</label>
        <input id="search-location" placeholder="Enter address or city..." value="">
      </div>
      <div class="form-group" style="max-width:120px">
        <label>Radius (mi)</label>
        <input id="search-radius" type="number" min="1" max="500" value="${_searchRadius}">
      </div>
      <div class="form-group" style="max-width:120px">
        <label>Max $/hr</label>
        <input id="search-max-rate" type="number" min="0" placeholder="Any">
      </div>
      <div class="form-group" style="max-width:120px">
        <label>Min Rating</label>
        <select id="search-min-rating">
          <option value="">Any</option>
          <option value="4.5">4.5+</option>
          <option value="4.0">4.0+</option>
          <option value="3.5">3.5+</option>
          <option value="3.0">3.0+</option>
        </select>
      </div>
      <button class="btn btn-primary" onclick="doProviderSearch()">&#x1F50D; Search</button>
      <button class="btn btn-outline" onclick="useMyLocation()">&#x1F4CD; Use My Location</button>
    </div>
    <div class="search-result-count">${total} provider${total!==1?'s':''} found${_searchLat ? ' within '+_searchRadius+' miles' : ''}</div>`;

  if (_searchView === 'list') {
    renderProviderList(el, results);
  } else if (_searchView === 'map') {
    el.innerHTML += '<div id="provider-map"></div>';
    setTimeout(() => initProviderMap(results), 50);
  } else if (_searchView === 'split') {
    el.innerHTML += '<div class="map-split"><div class="map-split-list" id="split-list"></div><div id="provider-map"></div></div>';
    const listEl = document.getElementById('split-list');
    if (listEl) renderProviderList(listEl, results);
    setTimeout(() => initProviderMap(results), 50);
  }
}

function renderProviderList(container, results) {
  if (results.length === 0) {
    container.innerHTML += emptyState('&#x1F50D;','No providers found','Try expanding your search radius or removing filters');
    return;
  }
  container.innerHTML += results.map((m, idx) => `
    <div class="mech-card" onclick="showProviderDetail(window._providerMap[${idx}])" style="margin-bottom:10px">
      <div class="mech-avatar">${profIcon(m.profession || 'mechanic')}</div>
      <div class="mech-info">
        <div class="mech-name">${m.full_name} ${profBadge(m.profession)}</div>
        <div class="text-sm">&#x1F4CD; ${m.location} &#x2022; ${m.service_radius_miles} mi radius &#x2022; ${fmtMoney(m.hourly_rate)}/hr</div>
        <div style="margin-top:6px"><span class="stars">${stars(Math.round(m.avg_rating))}</span> <span class="text-sm">${m.avg_rating.toFixed(1)} (${m.total_jobs} jobs)</span></div>
        <div class="mech-tags">${(m.specialties||[]).map(s=>'<span class="mech-tag">'+s+'</span>').join('')}</div>
      </div>
      <div style="text-align:right">
        ${m.is_available?'<span class="badge badge-accepted">Available</span>':'<span class="badge badge-cancelled">Busy</span>'}
        ${m.distance_miles!=null?'<br><span class="distance-badge">&#x1F4CD; '+m.distance_miles+' mi</span>':''}
      </div>
    </div>`).join('');
}

function initProviderMap(results) {
  const mapEl = document.getElementById('provider-map');
  if (!mapEl || typeof L === 'undefined') return;

  const centerLat = _searchLat || 30.27;
  const centerLng = _searchLng || -97.74;
  const zoom = _searchLat ? 11 : 10;

  if (_leafletMap) { _leafletMap.remove(); _leafletMap = null; }

  _leafletMap = L.map('provider-map').setView([centerLat, centerLng], zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  }).addTo(_leafletMap);

  if (_searchLat && _searchLng) {
    L.circle([_searchLat, _searchLng], {
      radius: _searchRadius * 1609.34,
      color: '#2563eb', fillColor: '#dbeafe', fillOpacity: 0.15, weight: 1.5,
    }).addTo(_leafletMap);
    L.marker([_searchLat, _searchLng], {
      icon: L.divIcon({className:'', html:'<div style="background:#2563eb;color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:14px;box-shadow:0 2px 6px rgba(0,0,0,.3)">&#x1F4CD;</div>', iconSize:[28,28], iconAnchor:[14,14]})
    }).addTo(_leafletMap).bindPopup('Your search location');
  }

  const profColors = {mechanic:'#2563eb',hvac:'#0891b2',electrician:'#d97706',construction:'#ea580c',carwash:'#16a34a'};
  results.forEach((m, idx) => {
    if (!m.latitude || !m.longitude) return;
    const color = profColors[m.profession] || '#6b7280';
    const marker = L.circleMarker([m.latitude, m.longitude], {
      radius: 10, fillColor: color, color: '#fff', weight: 2, fillOpacity: 0.9,
    }).addTo(_leafletMap);

    marker.bindPopup(
      '<strong>'+m.full_name+'</strong><br>'+
      profLabel(m.profession)+' &bull; '+fmtMoney(m.hourly_rate)+'/hr<br>'+
      '\u2605'.repeat(Math.round(m.avg_rating))+' '+m.avg_rating.toFixed(1)+'<br>'+
      (m.distance_miles!=null ? m.distance_miles+' miles away' : m.location)+'<br>'+
      '<a href="#" onclick="showProviderDetail(window._providerMap['+idx+']);return false;">View Details</a>'
    );
  });

  const latlngs = results.filter(m=>m.latitude&&m.longitude).map(m=>[m.latitude,m.longitude]);
  if (latlngs.length > 1) _leafletMap.fitBounds(latlngs, {padding:[30,30]});
}

async function doProviderSearch() {
  const locInput = document.getElementById('search-location')?.value?.trim();
  const radiusInput = document.getElementById('search-radius')?.value;

  if (radiusInput) _searchRadius = parseInt(radiusInput) || 25;

  if (locInput) {
    try {
      const geo = await post('/api/search/geocode', {address: locInput});
      if (geo.success) {
        _searchLat = geo.latitude;
        _searchLng = geo.longitude;
      } else {
        alert('Could not find that location. Try a more specific address.');
        return;
      }
    } catch(e) {
      alert('Geocoding error: ' + e.message);
      return;
    }
  }

  const el = document.getElementById('content');
  if (el) renderProviderSearch(el);
}

function useMyLocation() {
  if (!navigator.geolocation) {
    alert('Geolocation is not supported by your browser');
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      _searchLat = pos.coords.latitude;
      _searchLng = pos.coords.longitude;
      _searchRadius = parseInt(document.getElementById('search-radius')?.value) || 25;
      const el = document.getElementById('content');
      if (el) renderProviderSearch(el);
    },
    (err) => { alert('Could not get your location: ' + err.message); }
  );
}

function setProviderFilter(prof) {
  _providerFilter = prof;
  const el = document.getElementById('content');
  if (el) renderProviderSearch(el);
}

// ---- Map View (standalone) ----
async function renderMapView(el) {
  el.innerHTML = pageHeader('Service Map');
  el.innerHTML += professionFilterBar(_providerFilter, 'setMapFilter');
  el.innerHTML += '<div id="provider-map" style="height:600px"></div>';

  setTimeout(async () => {
    const mapEl = document.getElementById('provider-map');
    if (!mapEl || typeof L === 'undefined') return;

    const map = L.map('provider-map').setView([30.27, -97.74], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
    }).addTo(map);

    const provUrl = '/api/search/map/providers' + (_providerFilter ? '?profession='+_providerFilter : '');
    const providers = await get(provUrl);
    const profColors = {mechanic:'#2563eb',hvac:'#0891b2',electrician:'#d97706',construction:'#ea580c',carwash:'#16a34a'};

    providers.forEach(p => {
      const color = profColors[p.profession] || '#6b7280';
      L.circleMarker([p.latitude, p.longitude], {
        radius: 10, fillColor: color, color: '#fff', weight: 2, fillOpacity: 0.9,
      }).addTo(map).bindPopup(
        '<strong>'+p.full_name+'</strong><br>'+
        profLabel(p.profession)+' &bull; '+fmtMoney(p.hourly_rate)+'/hr<br>'+
        '\u2605'.repeat(Math.round(p.avg_rating))+' '+p.avg_rating.toFixed(1)
      );
    });

    const reqUrl = '/api/search/map/requests' + (_providerFilter ? '?profession_type='+_providerFilter : '');
    const requests = await get(reqUrl);

    requests.forEach(r => {
      L.marker([r.latitude, r.longitude], {
        icon: L.divIcon({
          className: '',
          html: '<div style="background:#dc2626;color:#fff;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:12px;box-shadow:0 2px 6px rgba(0,0,0,.3)">&#x2757;</div>',
          iconSize: [24, 24], iconAnchor: [12, 12],
        })
      }).addTo(map).bindPopup(
        '<strong>'+r.title+'</strong><br>'+
        profLabel(r.profession_type)+' &bull; '+r.urgency+'<br>'+
        r.location+'<br>'+
        (r.budget_min && r.budget_max ? fmtMoney(r.budget_min)+' - '+fmtMoney(r.budget_max) : '')
      );
    });

    const legend = L.control({position: 'bottomright'});
    legend.onAdd = function() {
      const div = L.DomUtil.create('div', '');
      div.style.cssText = 'background:#fff;padding:10px 14px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.15);font-size:12px;line-height:1.8';
      div.innerHTML = '<strong>Legend</strong><br>' +
        Object.entries(profColors).map(([k,c]) => '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:'+c+';margin-right:5px"></span>'+profLabel(k)).join('<br>') +
        '<br><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#dc2626;margin-right:5px"></span>Service Request';
      return div;
    };
    legend.addTo(map);

    const allLatLngs = [
      ...providers.map(p=>[p.latitude,p.longitude]),
      ...requests.map(r=>[r.latitude,r.longitude]),
    ];
    if (allLatLngs.length > 1) map.fitBounds(allLatLngs, {padding:[40,40]});
  }, 50);
}

function setMapFilter(prof) {
  _providerFilter = prof;
  const el = document.getElementById('content');
  if (el) renderMapView(el);
}

"""

    html = html[:start_idx] + new_search + html[end_idx:]
    print("+ Replaced provider search with enhanced geo search + map view")


# ---------------------------------------------------------------------------
# 5. Add distance to provider detail modal
# ---------------------------------------------------------------------------
old_detail = """<div class="text-sm">\\u{1F4CD} ${m.location} (${m.service_radius_miles} mi radius)</div>"""
new_detail = """<div class="text-sm">\\u{1F4CD} ${m.location} (${m.service_radius_miles} mi radius)</div>
    ${m.distance_miles!=null ? '<div class="distance-badge" style="margin-top:6px">\\u{1F4CD} '+m.distance_miles+' miles from your search</div>' : ''}"""

if "distance_miles" not in html.split("showProviderDetail")[1][:500]:
    html = html.replace(old_detail, new_detail)
    print("+ Added distance to provider detail modal")


# ---------------------------------------------------------------------------
# Write patched file
# ---------------------------------------------------------------------------
with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nDone! Frontend patched ({len(html):,} bytes)")
