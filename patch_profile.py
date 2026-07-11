"""Patch: Merge vehicles into client profile page"""
import sys

path = r'D:\Projects\Lever\frontend\index.html'

with open(path, 'r', encoding='utf-8-sig') as f:
    c = f.read()

print(f'Read {len(c)} chars')

# 1. Replace renderClientProfile to include vehicles section
old_profile = """async function renderClientProfile(el) {
  const profile = await get('/api/client/profile');
  el.innerHTML = `
    ${pageHeader('My Profile')}
    <div class="card" style="max-width:500px">
      <div class="form-group"><label>Full Name</label><input id="cp-name" value="${profile.full_name||''}"></div>
      <div class="form-group"><label>Phone</label><input id="cp-phone" value="${profile.phone||''}"></div>
      <div class="form-group"><label>Address</label><input id="cp-address" value="${profile.address||''}"></div>
      <div id="cp-msg"></div>
      <button class="btn btn-primary" onclick="saveClientProfile()">Save Changes</button>
    </div>`;
}"""

new_profile = """async function renderClientProfile(el) {
  const [profile, vehicles] = await Promise.all([
    get('/api/client/profile'),
    get('/api/client/vehicles'),
  ]);
  const vList = vehicles.length === 0
    ? `<div class="empty" style="padding:24px;text-align:center"><div class="empty-icon">\\u{1F697}</div><p>No vehicles added yet</p></div>`
    : vehicles.map(v => `
        <div class="card" style="margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <strong>${v.year} ${v.make} ${v.model}</strong>
              <div class="text-sm" style="color:var(--gray-500)">${v.color} \\u2022 ${v.license_plate||'No plate'} \\u2022 ${v.mileage?.toLocaleString()||0} mi</div>
              ${v.vin ? `<div class="text-sm" style="color:var(--gray-400)">VIN: ${v.vin}</div>` : ''}
            </div>
            <div style="display:flex;gap:8px">
              <button class="btn btn-outline" style="padding:4px 10px;font-size:.75rem" onclick="showEditVehicle(${v.id})">Edit</button>
              <button class="btn btn-danger" style="padding:4px 10px;font-size:.75rem" onclick="deleteVehicle(${v.id})">Delete</button>
            </div>
          </div>
        </div>`).join('');
  el.innerHTML = `
    ${pageHeader('My Profile')}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;max-width:900px">
      <div class="card">
        <h3 style="margin:0 0 16px">Personal Info</h3>
        <div class="form-group"><label>Full Name</label><input id="cp-name" value="${profile.full_name||''}"></div>
        <div class="form-group"><label>Phone</label><input id="cp-phone" value="${profile.phone||''}"></div>
        <div class="form-group"><label>Address</label><input id="cp-address" value="${profile.address||''}"></div>
        <div id="cp-msg"></div>
        <button class="btn btn-primary" onclick="saveClientProfile()">Save Changes</button>
      </div>
      <div>
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
            <h3 style="margin:0">My Vehicles</h3>
            <button class="btn btn-primary" style="padding:6px 14px;font-size:.8rem" onclick="showAddVehicle()">\\uFF0B Add</button>
          </div>
          ${vList}
        </div>
      </div>
    </div>`;
}"""

if old_profile in c:
    c = c.replace(old_profile, new_profile, 1)
    print('1. Profile merged with vehicles - OK')
else:
    print('1. ERROR: old profile pattern not found')
    # Try with \n only
    old_n = old_profile.replace('\r\n', '\n')
    if old_n in c:
        c = c.replace(old_n, new_profile.replace('\r\n', '\n'), 1)
        print('1. Profile merged (LF mode) - OK')
    else:
        print('1. FATAL: Cannot find profile function')
        sys.exit(1)

# 2. Change vehicle form redirects from #/vehicles to #/profile
count = c.count("route('#/vehicles')")
c = c.replace("route('#/vehicles')", "route('#/profile')")
print(f'2. Replaced {count} vehicle route redirects')

# 3. Remove the #/vehicles route handler from clientView (if still there)
old_route = "  if (hash==='#/vehicles')           return renderVehicles(el);\r\n"
if old_route in c:
    c = c.replace(old_route, '', 1)
    print('3. Removed #/vehicles route (CRLF)')
else:
    old_route_n = "  if (hash==='#/vehicles')           return renderVehicles(el);\n"
    if old_route_n in c:
        c = c.replace(old_route_n, '', 1)
        print('3. Removed #/vehicles route (LF)')
    else:
        print('3. #/vehicles route not found (may already be removed)')

with open(path, 'w', encoding='utf-8-sig') as f:
    f.write(c)

print(f'Written {len(c)} chars')
print('DONE')
