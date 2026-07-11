"""Patch: Add i18n (English/Spanish) support to Lever"""
import re

path = r'D:\Projects\Lever\frontend\index.html'
i18n_path = r'D:\Projects\Lever\i18n_strings.js'

with open(i18n_path, 'r', encoding='utf-8') as f:
    i18n_code = f.read()

# Read with BOM-aware encoding
with open(path, 'r', encoding='utf-8-sig') as f:
    c = f.read()

print(f'Read index.html: {len(c)} chars')

changes = 0

# 1. Inject i18n code right after the opening <script> tag
script_start = '<script>\n'
if script_start in c and 'let _lang' not in c:
    c = c.replace(script_start, script_start + i18n_code + '\n', 1)
    changes += 1
    print('1. i18n code injected after <script>')
elif 'let _lang' in c:
    print('1. SKIP - i18n already present')
else:
    # Try CRLF
    script_start_crlf = '<script>\r\n'
    if script_start_crlf in c:
        c = c.replace(script_start_crlf, script_start_crlf + i18n_code + '\r\n', 1)
        changes += 1
        print('1. i18n code injected (CRLF)')

# 2. Add language toggle button in topbar (before bell button)
old_bell = '<button class="notif-bell"'
new_bell = '<button class="lang-toggle" onclick="toggleLang()" title="Language" style="background:none;border:none;color:#fff;font-size:.85rem;cursor:pointer;padding:4px 8px;border-radius:4px;opacity:.85">${_lang===\'en\'?\'ES\':\'EN\'}</button>\n          <button class="notif-bell"'
if old_bell in c and 'lang-toggle' not in c:
    c = c.replace(old_bell, new_bell, 1)
    changes += 1
    print('2. Language toggle added to topbar')
elif 'lang-toggle' in c:
    print('2. SKIP - lang toggle already present')

# 3. Translate NAV labels using t()
# Client nav items
nav_replacements = [
    ("label:'Dashboard'", "label:t('Dashboard')"),
    ("label:'My Requests'", "label:t('My Requests')"),
    ("label:'Find Provider'", "label:t('Find Provider')"),
    ("label:'Messages'", "label:t('Messages')"),
    ("label:'Notifications'", "label:t('Notifications')"),
    ("label:'Profile'", "label:t('Profile')"),
    ("label:'Job Board'", "label:t('Job Board')"),
    ("label:'My Jobs'", "label:t('My Jobs')"),
    ("label:'Reviews'", "label:t('Reviews')"),
]
for old_nav, new_nav in nav_replacements:
    if old_nav in c:
        c = c.replace(old_nav, new_nav)
        changes += 1

print(f'3. NAV labels translated ({changes - 2} replacements)')

# 4. Translate Sign Out button
if ">Sign Out</button>" in c and ">'+t('Sign Out')+'</button>" not in c:
    # In template literal: onclick="logout()">Sign Out</button>
    c = c.replace('onclick="logout()">Sign Out</button>', 'onclick="logout()">${t(\'Sign Out\')}</button>')
    changes += 1
    print('4. Sign Out translated')

# 5. Translate pageHeader calls
header_translations = [
    "pageHeader('Dashboard')",
    "pageHeader('My Profile')",
    "pageHeader('Job Board')",
    "pageHeader('My Jobs')",
    "pageHeader('My Reviews')",
    "pageHeader('Messages')",
    "pageHeader('Notifications')",
    "pageHeader('Service Map')",
    "pageHeader('Admin Dashboard')",
    "pageHeader('User Management')",
    "pageHeader('All Service Requests')",
    "pageHeader('Disputes')",
]
for h in header_translations:
    new_h = h.replace("pageHeader('", "pageHeader(t('").replace("')", "'))")
    if h in c:
        c = c.replace(h, new_h)
        changes += 1

print(f'5. Page headers translated')

# 6. Translate the profile page labels
profile_labels = [
    ('>Personal Info<', '>${t("Personal Info")}<'),
    ('>Full Name<', '>${t("Full Name")}<'),
    ('>Phone<', '>${t("Phone")}<'),
    ('>Address<', '>${t("Address")}<'),
    ('>Save Changes<', '>${t("Save Changes")}<'),
    ('>My Vehicles<', '>${t("My Vehicles")}<'),
    ('>No vehicles added yet<', '>${t("No vehicles added yet")}<'),
]
for old_l, new_l in profile_labels:
    count = c.count(old_l)
    if count > 0:
        c = c.replace(old_l, new_l)
        changes += 1

print(f'6. Profile labels translated')

# 7. Translate Find a Provider header 
if "pageHeader('Find a Provider'" in c:
    c = c.replace("pageHeader('Find a Provider'", "pageHeader(t('Find a Provider')")
    changes += 1
    print('7. Find Provider header translated')

# 8. Translate the notification page strings
if "'Mark all as read'" in c:
    c = c.replace("'Mark all as read'", "t('Mark all as read')")
if ">Mark all read<" in c:
    c = c.replace(">Mark all read<", ">${t('Mark all read')}<")
if ">View all<" in c:
    c = c.replace(">View all<", ">${t('View all')}<")

print(f'8. Notification strings translated')

# 9. Translate login page
if "'>Sign In</button>" in c:
    c = c.replace("'>Sign In</button>", "'>${t('Sign In')}</button>")
    changes += 1

if "Multi-Profession Service Marketplace" in c:
    c = c.replace(
        "Multi-Profession Service Marketplace",
        "${t('Multi-Profession Service Marketplace')}"
    )
    changes += 1

print(f'9. Login page translated')

# 10. Translate + New Request button
if ">+ New Request<" in c:
    c = c.replace(">+ New Request<", ">${t('+ New Request')}<")
    changes += 1
    print('10. New Request button translated')

# 11. Translate table headers
table_headers = ['TITLE', 'PROFESSION', 'STATUS', 'URGENCY', 'CREATED']
for th in table_headers:
    old_th = f'>{th}<'
    new_th = f'>${{t("{th}")}}<'
    if old_th in c:
        c = c.replace(old_th, new_th)

print(f'11. Table headers translated')

# 12. Translate stat labels
stat_labels = [
    ('TOTAL REQUESTS', 'TOTAL REQUESTS'),
    ('ACTIVE', 'ACTIVE'),
    ('COMPLETED', 'COMPLETED'),
]
for label, key in stat_labels:
    old_s = f'>{label}<'
    new_s = f'>${{t("{key}")}}<'
    if old_s in c:
        c = c.replace(old_s, new_s)

print(f'12. Stat labels translated')

with open(path, 'w', encoding='utf-8-sig') as f:
    f.write(c)

print(f'\nTotal changes: {changes}')
print(f'Written: {len(c)} chars')
print('DONE')
