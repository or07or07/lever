"""Patch Lever frontend index.html to add notification UI."""
import sys

FILE = r"D:\Projects\Lever\frontend\index.html"

with open(FILE, "r", encoding="utf-8-sig") as f:
    html = f.read()

changes = 0

# 1. CSS
NOTIF_CSS = """
/* ---- Notifications ---- */
.notif-bell{position:relative;cursor:pointer;font-size:1.2rem;padding:4px 8px;border-radius:8px;transition:.15s;background:transparent;border:none;color:#fff;line-height:1}
.notif-bell:hover{background:rgba(255,255,255,.2)}
.notif-badge{position:absolute;top:-2px;right:-2px;background:#ef4444;color:#fff;font-size:.65rem;font-weight:700;min-width:16px;height:16px;border-radius:99px;display:flex;align-items:center;justify-content:center;padding:0 4px;line-height:1;border:2px solid #2563eb}
.notif-badge:empty,.notif-badge[data-count="0"]{display:none}
.notif-dropdown{position:absolute;top:46px;right:12px;width:380px;max-height:480px;background:#fff;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.18);z-index:1000;overflow:hidden;display:none}
.notif-dropdown.open{display:block}
.notif-dropdown-header{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid #e5e7eb;background:#f9fafb}
.notif-dropdown-header h3{font-size:.95rem;font-weight:700;margin:0}
.notif-dropdown-body{overflow-y:auto;max-height:380px}
.notif-item{display:flex;gap:12px;padding:12px 16px;border-bottom:1px solid #f3f4f6;cursor:pointer;transition:.1s}
.notif-item:hover{background:#f9fafb}
.notif-item.unread{background:#eff6ff}
.notif-item.unread:hover{background:#dbeafe}
.notif-icon{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.1rem;flex-shrink:0}
.notif-icon.job_update{background:#dbeafe;color:#2563eb}
.notif-icon.message{background:#fef3c7;color:#d97706}
.notif-icon.review{background:#d1fae5;color:#16a34a}
.notif-icon.system{background:#f3f4f6;color:#4b5563}
.notif-body{flex:1;min-width:0}
.notif-title{font-size:.85rem;font-weight:600;color:#111827;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.notif-msg{font-size:.8rem;color:#4b5563;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.notif-time{font-size:.7rem;color:#9ca3af;margin-top:4px}
.notif-empty{padding:40px 16px;text-align:center;color:#9ca3af;font-size:.9rem}
.notif-overlay{position:fixed;inset:0;z-index:999}
.notif-page-item{display:flex;gap:14px;padding:16px 20px;border-bottom:1px solid #f3f4f6;transition:.1s;cursor:pointer;border-radius:8px}
.notif-page-item:hover{background:#f9fafb}
.notif-page-item.unread{background:#eff6ff;border-left:3px solid #2563eb}
.notif-page-actions{display:flex;gap:8px;margin-bottom:16px}

"""
if "/* ---- Notifications ---- */" not in html:
    html = html.replace("/* ---- Cards ---- */", NOTIF_CSS + "/* ---- Cards ---- */")
    changes += 1; print("[+] CSS")

# 2. Topbar bell
old_tb = '<span class="topbar-user">${_user?.email || \'\'}</span>\n          <button class="btn-sm" onclick="logout()">Sign Out</button>'
new_tb = '<span class="topbar-user">${_user?.email || \'\'}</span>\n          <button class="notif-bell" onclick="toggleNotifDropdown(event)" title="Notifications">\\u{1F514}<span class="notif-badge" id="notif-badge"></span></button>\n          <button class="btn-sm" onclick="logout()">Sign Out</button>\n        </div>\n        <div class="notif-dropdown" id="notif-dropdown"></div'
if "notif-bell" not in html:
    # More flexible match
    html = html.replace(
        """<span class="topbar-user">${_user?.email || ''}</span>\n          <button class="btn-sm" onclick="logout()">Sign Out</button>\n        </div>""",
        """<span class="topbar-user">${_user?.email || ''}</span>\n          <button class="notif-bell" onclick="toggleNotifDropdown(event)" title="Notifications">\\u{1F514}<span class="notif-badge" id="notif-badge"></span></button>\n          <button class="btn-sm" onclick="logout()">Sign Out</button>\n        </div>\n        <div class="notif-dropdown" id="notif-dropdown"></div>"""
    )
    changes += 1; print("[+] Topbar bell")

# 3. Sidebar NAV - client
if "'#/notifications'" not in html:
    html = html.replace(
        "{icon:'\\u{1F464}', label:'Profile',      hash:'#/profile'},\n  ],\n  mechanic:[",
        "{icon:'\\u{1F514}', label:'Notifications',hash:'#/notifications'},\n    {icon:'\\u{1F464}', label:'Profile',      hash:'#/profile'},\n  ],\n  mechanic:["
    )
    changes += 1; print("[+] Client sidebar")

# Sidebar NAV - mechanic
html = html.replace(
    "{icon:'\\u{1F464}', label:'Profile',     hash:'#/profile'},\n  ],\n  admin:[",
    "{icon:'\\u{1F514}', label:'Notifications',hash:'#/notifications'},\n    {icon:'\\u{1F464}', label:'Profile',     hash:'#/profile'},\n  ],\n  admin:["
)
changes += 1; print("[+] Mechanic sidebar")

# 4. Client route
if "renderNotifications" not in html:
    html = html.replace(
        "if (hash==='#/profile')            return renderClientProfile(el);",
        "if (hash==='#/notifications')      return renderNotifications(el);\n  if (hash==='#/profile')            return renderClientProfile(el);",
        1
    )
    changes += 1; print("[+] Client route")

# 5. Mechanic route
html = html.replace(
    "if (hash==='#/profile')             return renderMechanicProfile(el);",
    "if (hash==='#/notifications')       return renderNotifications(el);\n  if (hash==='#/profile')             return renderMechanicProfile(el);",
    1
)
changes += 1; print("[+] Mechanic route")

# 6. JS functions
NOTIF_JS = r"""
// ============================================================
//  NOTIFICATIONS
// ============================================================
let _notifDropdownOpen = false;
let _notifPollInterval = null;

const NOTIF_ICONS = {
  job_update: '\u{1F4CB}',
  message:    '\u{1F4AC}',
  review:     '\u{2B50}',
  system:     '\u{2139}\u{FE0F}',
};

function timeAgo(dateStr) {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.max(0, now - then);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  const days = Math.floor(hrs / 24);
  if (days < 7) return days + 'd ago';
  return new Date(dateStr).toLocaleDateString('en-US', {month:'short', day:'numeric'});
}

async function pollNotifCount() {
  if (!_token) return;
  try {
    const data = await get('/api/notifications/count');
    const badge = document.getElementById('notif-badge');
    if (badge) {
      const c = data.unread_count || 0;
      badge.textContent = c > 99 ? '99+' : (c > 0 ? c : '');
      badge.setAttribute('data-count', c);
    }
  } catch(e) { /* silent */ }
}

function startNotifPolling() {
  if (_notifPollInterval) clearInterval(_notifPollInterval);
  pollNotifCount();
  _notifPollInterval = setInterval(pollNotifCount, 30000);
}

function stopNotifPolling() {
  if (_notifPollInterval) { clearInterval(_notifPollInterval); _notifPollInterval = null; }
}

async function toggleNotifDropdown(e) {
  e.stopPropagation();
  const dd = document.getElementById('notif-dropdown');
  if (!dd) return;
  _notifDropdownOpen = !_notifDropdownOpen;
  if (_notifDropdownOpen) {
    dd.classList.add('open');
    dd.innerHTML = '<div class="notif-dropdown-header"><h3>Notifications</h3></div><div class="notif-dropdown-body"><div class="notif-empty">Loading...</div></div>';
    const overlay = document.createElement('div');
    overlay.className = 'notif-overlay';
    overlay.onclick = () => closeNotifDropdown();
    document.body.appendChild(overlay);
    try {
      const notifs = await get('/api/notifications?limit=15');
      const body = dd.querySelector('.notif-dropdown-body');
      if (!notifs.length) {
        body.innerHTML = '<div class="notif-empty">\u{1F514} No notifications yet</div>';
      } else {
        body.innerHTML = notifs.map(n => `
          <div class="notif-item ${n.is_read?'':'unread'}" onclick="openNotification(${n.id}, '${(n.link||'').replace(/'/g,"\\'")}')">
            <div class="notif-icon ${n.type}">${NOTIF_ICONS[n.type]||'\u{1F514}'}</div>
            <div class="notif-body">
              <div class="notif-title">${n.title}</div>
              <div class="notif-msg">${n.message}</div>
              <div class="notif-time">${timeAgo(n.created_at)}</div>
            </div>
          </div>`).join('');
      }
      dd.querySelector('.notif-dropdown-header').innerHTML = `
        <h3>Notifications</h3>
        <div style="display:flex;gap:8px">
          <button class="btn-ghost" style="font-size:.75rem;padding:4px 8px" onclick="markAllNotifRead()">Mark all read</button>
          <button class="btn-ghost" style="font-size:.75rem;padding:4px 8px" onclick="closeNotifDropdown();route('#/notifications')">View all</button>
        </div>`;
    } catch(e) {
      dd.querySelector('.notif-dropdown-body').innerHTML = '<div class="notif-empty">Failed to load notifications</div>';
    }
  } else {
    closeNotifDropdown();
  }
}

function closeNotifDropdown() {
  _notifDropdownOpen = false;
  const dd = document.getElementById('notif-dropdown');
  if (dd) dd.classList.remove('open');
  document.querySelectorAll('.notif-overlay').forEach(o => o.remove());
}

async function openNotification(id, link) {
  closeNotifDropdown();
  try { await post('/api/notifications/mark-read', {notification_ids: [id]}); } catch(e) {}
  pollNotifCount();
  if (link) route('#' + link);
}

async function markAllNotifRead() {
  try {
    await post('/api/notifications/mark-all-read');
    pollNotifCount();
    const dd = document.getElementById('notif-dropdown');
    if (dd) dd.querySelectorAll('.notif-item.unread').forEach(el => el.classList.remove('unread'));
  } catch(e) {}
}

async function renderNotifications(el) {
  const notifs = await get('/api/notifications?limit=100');
  const unreadCount = notifs.filter(n => !n.is_read).length;
  el.innerHTML = `
    ${pageHeader('Notifications')}
    <div class="notif-page-actions">
      ${unreadCount > 0 ? '<button class="btn btn-outline" onclick="markAllReadAndRefresh()">\u{2713} Mark all as read</button>' : ''}
      <span style="color:#9ca3af;font-size:.85rem;padding:8px">${unreadCount} unread of ${notifs.length} total</span>
    </div>
    <div class="card" style="padding:0;overflow:hidden">
      ${notifs.length === 0
        ? '<div class="notif-empty" style="padding:60px 20px">\u{1F514} No notifications yet.<br><span style="font-size:.8rem;margin-top:8px;display:block">When a provider accepts your request or updates a job, you\u2019ll see it here.</span></div>'
        : notifs.map(n => `
          <div class="notif-page-item ${n.is_read?'':'unread'}" onclick="openNotifFromPage(${n.id}, '${(n.link||'').replace(/'/g,"\\'")}')">
            <div class="notif-icon ${n.type}" style="width:42px;height:42px;font-size:1.2rem">${NOTIF_ICONS[n.type]||'\u{1F514}'}</div>
            <div class="notif-body" style="flex:1">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div class="notif-title" style="white-space:normal">${n.title}</div>
                <div class="notif-time" style="flex-shrink:0;margin-left:12px">${timeAgo(n.created_at)}</div>
              </div>
              <div class="notif-msg" style="-webkit-line-clamp:3">${n.message}</div>
            </div>
          </div>`).join('')
      }
    </div>`;
}

async function openNotifFromPage(id, link) {
  try { await post('/api/notifications/mark-read', {notification_ids: [id]}); } catch(e) {}
  pollNotifCount();
  if (link) route('#' + link);
  else { const el = document.getElementById('content'); if (el) renderNotifications(el); }
}

async function markAllReadAndRefresh() {
  try { await post('/api/notifications/mark-all-read'); } catch(e) {}
  pollNotifCount();
  const el = document.getElementById('content');
  if (el) renderNotifications(el);
}
"""

if "renderNotifications" not in html:
    last_script = html.rfind("</script>")
    html = html[:last_script] + NOTIF_JS + "\n" + html[last_script:]
    changes += 1; print("[+] JS functions")

# 7. Start polling in render()
if "startNotifPolling" not in html:
    html = html.replace(
        "buildSidebar(role, hash);\n  loadContent(role, hash);\n}",
        "buildSidebar(role, hash);\n  loadContent(role, hash);\n  startNotifPolling();\n}",
        1
    )
    changes += 1; print("[+] Polling in render()")

# 8. Stop polling on logout
if "stopNotifPolling" not in html:
    html = html.replace(
        "localStorage.removeItem('lever_user');\n  route('#/login');",
        "localStorage.removeItem('lever_user');\n  stopNotifPolling();\n  route('#/login');",
        1
    )
    changes += 1; print("[+] Stop polling on logout")

with open(FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n[OK] {changes} patches applied")
