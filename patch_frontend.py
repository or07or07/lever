"""Patch the Lever frontend to add email verification support.

Changes:
1. Add CSS for verification screen
2. Add verification gate in render()
3. Add renderVerification() function
4. Modify doLogin() and doRegister() to store email_verified
5. Add verification code entry logic
"""
import re

with open(r"D:\Projects\08_Lever\frontend\index.html", "r", encoding="utf-8") as f:
    html = f.read()

# =====================================================
# 1. ADD VERIFICATION CSS after the auth-wrap styles
# =====================================================
verification_css = """
/* ---- Verification Screen ---- */
.verify-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#1e3a8a 0%,#2563eb 100%)}
.verify-card{background:#fff;border-radius:12px;padding:40px;width:100%;max-width:480px;box-shadow:var(--shadow-lg);text-align:center}
.verify-icon{font-size:3rem;margin-bottom:16px}
.verify-title{font-size:1.4rem;font-weight:700;color:var(--gray-900);margin-bottom:8px}
.verify-subtitle{font-size:.9rem;color:var(--gray-600);margin-bottom:28px;line-height:1.5}
.verify-email-highlight{font-weight:600;color:var(--brand)}
.code-inputs{display:flex;gap:8px;justify-content:center;margin-bottom:24px}
.code-inputs input{width:48px;height:56px;text-align:center;font-size:1.5rem;font-weight:700;border:2px solid var(--gray-200);border-radius:var(--radius);transition:.15s;color:var(--gray-900)}
.code-inputs input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px rgba(37,99,235,.15)}
.code-inputs input.error{border-color:var(--danger);animation:shake .4s}
.code-inputs input.success{border-color:var(--success);background:#f0fdf4}
@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-4px)}40%,80%{transform:translateX(4px)}}
.verify-actions{display:flex;flex-direction:column;gap:12px;align-items:center}
.verify-resend{font-size:.85rem;color:var(--gray-600);background:none;border:none;cursor:pointer;padding:4px 8px}
.verify-resend:not(:disabled):hover{color:var(--brand)}
.verify-resend:disabled{opacity:.5;cursor:not-allowed}
.verify-timer{font-size:.8rem;color:var(--gray-400);margin-top:4px}
.verify-footer{margin-top:24px;padding-top:16px;border-top:1px solid var(--gray-200);font-size:.8rem;color:var(--gray-400)}
.verify-logout{color:var(--brand);cursor:pointer;background:none;border:none;font-size:.8rem;font-weight:600}
.verify-banner{background:var(--warn);color:#fff;padding:8px 16px;font-size:.82rem;text-align:center;display:flex;align-items:center;justify-content:center;gap:8px}
.verify-banner button{background:rgba(255,255,255,.25);border:none;color:#fff;padding:4px 12px;border-radius:4px;font-size:.78rem;font-weight:600;cursor:pointer}
.verify-banner button:hover{background:rgba(255,255,255,.4)}
"""

# Insert CSS before the auth-wrap style definition
html = html.replace(
    "/* ---- Auth screens ---- */",
    verification_css + "\n/* ---- Auth screens ---- */"
)

# =====================================================
# 2. ADD VERIFICATION GATE in render()
# =====================================================
# Replace the render function's first check
old_render_check = "function render() {\n  if (!_token) { renderAuth(); return; }"
new_render_check = """function render() {
  if (!_token) { renderAuth(); return; }
  // Verification gate — ISO 27001 A.9.4.2: email ownership required before access
  if (_user && _user.email_verified === false && window.location.hash !== '#/verify-email') {
    renderVerification(); return;
  }"""
html = html.replace(old_render_check, new_render_check)

# =====================================================
# 3. MODIFY doLogin() to store email_verified
# =====================================================
old_login_success = "login(data.access_token, {id:data.user_id, email, role:data.role, profession:data.profession||null});\n    await loadProfessions();\n    route('#/');\n  } catch(e) {\n    document.getElementById('l-err').innerHTML = alert_el('error', e.message);\n  }\n}"
new_login_success = """login(data.access_token, {id:data.user_id, email, role:data.role, profession:data.profession||null, email_verified:data.email_verified!==false});
    await loadProfessions();
    if (data.email_verified === false) { route('#/verify-email'); }
    else { route('#/'); }
  } catch(e) {
    document.getElementById('l-err').innerHTML = alert_el('error', e.message);
  }
}"""
html = html.replace(old_login_success, new_login_success)

# =====================================================
# 4. MODIFY doRegister() to store email_verified and redirect to verify
# =====================================================
old_register_success = "login(data.access_token, {id:data.user_id, email, role:data.role, profession:data.profession||profession||null});\n    await loadProfessions();\n    route('#/');\n  } catch(e) {\n    document.getElementById('r-err').innerHTML = alert_el('error', e.message);\n  }\n}"
new_register_success = """login(data.access_token, {id:data.user_id, email, role:data.role, profession:data.profession||profession||null, email_verified:false});
    await loadProfessions();
    route('#/verify-email');
  } catch(e) {
    document.getElementById('r-err').innerHTML = alert_el('error', e.message);
  }
}"""
html = html.replace(old_register_success, new_register_success)

# =====================================================
# 5. ADD renderVerification() function before renderAuth()
# =====================================================
verification_function = """
// ============================================================
//  EMAIL VERIFICATION SCREEN — ISO 27001 A.9.2.1
// ============================================================
let _verifyResendCooldown = 0;
let _verifyResendTimer = null;

function renderVerification() {
  const email = _user?.email || 'your email';
  document.getElementById('app').innerHTML = `
    <div class="verify-wrap">
      <div class="verify-card">
        <div class="verify-icon">\\u{1F4E7}</div>
        <div class="verify-title">Verify Your Email</div>
        <div class="verify-subtitle">
          We sent a 6-digit code to<br>
          <span class="verify-email-highlight">${email}</span>
        </div>

        <div class="code-inputs" id="code-inputs">
          <input type="text" maxlength="1" inputmode="numeric" pattern="[0-9]" autocomplete="one-time-code" data-idx="0">
          <input type="text" maxlength="1" inputmode="numeric" pattern="[0-9]" data-idx="1">
          <input type="text" maxlength="1" inputmode="numeric" pattern="[0-9]" data-idx="2">
          <input type="text" maxlength="1" inputmode="numeric" pattern="[0-9]" data-idx="3">
          <input type="text" maxlength="1" inputmode="numeric" pattern="[0-9]" data-idx="4">
          <input type="text" maxlength="1" inputmode="numeric" pattern="[0-9]" data-idx="5">
        </div>

        <div id="verify-msg"></div>

        <div class="verify-actions">
          <button class="btn btn-primary btn-full" id="verify-btn" onclick="doVerifyEmail()">Verify Email</button>
          <button class="verify-resend" id="resend-btn" onclick="doResendCode()">Resend Code</button>
          <div class="verify-timer" id="resend-timer"></div>
        </div>

        <div class="verify-footer">
          Wrong email? <button class="verify-logout" onclick="logout()">Sign out</button> and register again.
        </div>
      </div>
    </div>`;

  setupCodeInputs();
  startResendCooldown(60);
}

function setupCodeInputs() {
  const container = document.getElementById('code-inputs');
  if (!container) return;
  const inputs = container.querySelectorAll('input');

  inputs.forEach((inp, i) => {
    inp.addEventListener('input', (e) => {
      const val = e.target.value.replace(/[^0-9]/g, '');
      e.target.value = val.charAt(0) || '';
      if (val && i < inputs.length - 1) {
        inputs[i + 1].focus();
      }
      // Auto-submit when all 6 digits entered
      if (i === inputs.length - 1 && val) {
        const code = Array.from(inputs).map(x => x.value).join('');
        if (code.length === 6) doVerifyEmail();
      }
    });

    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !e.target.value && i > 0) {
        inputs[i - 1].focus();
        inputs[i - 1].value = '';
      }
    });

    // Handle paste
    inp.addEventListener('paste', (e) => {
      e.preventDefault();
      const paste = (e.clipboardData || window.clipboardData).getData('text').replace(/[^0-9]/g, '');
      for (let j = 0; j < Math.min(paste.length, inputs.length - i); j++) {
        inputs[i + j].value = paste[j];
      }
      const nextIdx = Math.min(i + paste.length, inputs.length - 1);
      inputs[nextIdx].focus();
      // Auto-submit if pasted full code
      if (paste.length >= 6 - i) {
        const code = Array.from(inputs).map(x => x.value).join('');
        if (code.length === 6) setTimeout(() => doVerifyEmail(), 100);
      }
    });
  });

  // Focus first input
  inputs[0]?.focus();
}

function startResendCooldown(seconds) {
  _verifyResendCooldown = seconds;
  const btn = document.getElementById('resend-btn');
  const timer = document.getElementById('resend-timer');
  if (btn) btn.disabled = true;

  if (_verifyResendTimer) clearInterval(_verifyResendTimer);
  _verifyResendTimer = setInterval(() => {
    _verifyResendCooldown--;
    if (timer) timer.textContent = _verifyResendCooldown > 0 ? `Resend available in ${_verifyResendCooldown}s` : '';
    if (_verifyResendCooldown <= 0) {
      clearInterval(_verifyResendTimer);
      if (btn) btn.disabled = false;
    }
  }, 1000);
}

async function doVerifyEmail() {
  const inputs = document.querySelectorAll('#code-inputs input');
  const code = Array.from(inputs).map(x => x.value).join('');
  if (code.length !== 6) {
    document.getElementById('verify-msg').innerHTML = alert_el('error', 'Please enter all 6 digits');
    return;
  }

  const btn = document.getElementById('verify-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Verifying\\u2026'; }

  try {
    const data = await post('/api/auth/verify-email', { code });
    if (data.success) {
      // Update local state
      _user.email_verified = true;
      localStorage.setItem('lever_user', JSON.stringify(_user));

      // Show success animation
      inputs.forEach(inp => inp.classList.add('success'));
      document.getElementById('verify-msg').innerHTML = alert_el('success', 'Email verified! Redirecting\\u2026');

      setTimeout(() => route('#/'), 1200);
    } else {
      inputs.forEach(inp => { inp.classList.add('error'); inp.value = ''; });
      setTimeout(() => inputs.forEach(inp => inp.classList.remove('error')), 500);
      document.getElementById('verify-msg').innerHTML = alert_el('error', data.message);
      if (btn) { btn.disabled = false; btn.textContent = 'Verify Email'; }
      inputs[0]?.focus();
    }
  } catch (e) {
    document.getElementById('verify-msg').innerHTML = alert_el('error', e.message || 'Verification failed');
    if (btn) { btn.disabled = false; btn.textContent = 'Verify Email'; }
  }
}

async function doResendCode() {
  const btn = document.getElementById('resend-btn');
  if (btn) btn.disabled = true;
  try {
    const data = await post('/api/auth/resend-verification', {});
    if (data.success) {
      document.getElementById('verify-msg').innerHTML = alert_el('success', 'New code sent to your email');
      startResendCooldown(data.cooldown_seconds || 60);
    } else {
      document.getElementById('verify-msg').innerHTML = alert_el('error', data.message);
      if (data.cooldown_seconds > 0) {
        startResendCooldown(data.cooldown_seconds);
      }
    }
  } catch (e) {
    document.getElementById('verify-msg').innerHTML = alert_el('error', e.message || 'Failed to resend');
  }
}

"""

# Insert before the AUTH SCREENS section
html = html.replace(
    "// ============================================================\n//  AUTH SCREENS\n// ============================================================",
    verification_function + "// ============================================================\n//  AUTH SCREENS\n// ============================================================"
)

# =====================================================
# Write the patched file
# =====================================================
with open(r"D:\Projects\08_Lever\frontend\index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"Frontend patched successfully. New size: {len(html)} bytes, ~{html.count(chr(10))} lines")
