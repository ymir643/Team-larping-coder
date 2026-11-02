const API_BASE = window.ECHO_API_BASE || window.location.origin;
let currentUserRole = null; 
let eventCountdownTimer = null;

function hideAllViews() {
  document.getElementById('landing-page').classList.add('hidden');
  document.getElementById('student-view').classList.add('hidden');
  document.getElementById('admin-view').classList.add('hidden');
}

function showLandingPage() {
  currentUserRole = null;
  hideAllViews();
  document.getElementById('landing-page').classList.remove('hidden');
  document.getElementById('active-role-badge').classList.add('hidden');
  document.getElementById('home-btn').classList.add('hidden');
  
  const codeInput = document.getElementById('access-code');
  if (codeInput) {
      codeInput.value = '';
      const slotBoxes = document.querySelectorAll('#code-slots-display .code-slot');
      slotBoxes.forEach(box => {
        const span = box.querySelector('span');
        if (span) span.textContent = '•';
        box.classList.remove('slot-filled');
      });
  }
}

function updateTopBar(roleLabel) {
  const badge = document.getElementById('active-role-badge');
  badge.textContent = roleLabel;
  badge.classList.remove('hidden');
  document.getElementById('home-btn').classList.remove('hidden');
}

function handleCodeSubmit() {
  const codeInput = document.getElementById('access-code').value.trim().toUpperCase();

  if (codeInput === 'ADMIN') {
    // This only opens the sign-in view; server authorization is based solely on
    // the HttpOnly admin session issued after valid credentials are checked.
    currentUserRole = 'ADMIN';
    hideAllViews();
    document.getElementById('admin-view').classList.remove('hidden');
    document.getElementById('admin-login-section').classList.remove('hidden');
    document.getElementById('admin-dashboard-section').classList.add('hidden');
    updateTopBar('ROLE: ADMIN');
    restoreAdminSession();
  } 
  else if (codeInput === 'STUDENT') {
    openStudentIdDialog();
  } 
  else if (codeInput === 'VISITOR') {
    let savedVisitor = localStorage.getItem('visitorName') || '';
    let visitorName = prompt('Please enter your name for your Visitor Pass:', savedVisitor);
    
    if (!visitorName || !visitorName.trim()) {
      alert('Visitor name is required to view events.');
      return;
    }
    
    localStorage.setItem('visitorName', visitorName.trim());
    currentUserRole = 'VISITOR';
    hideAllViews();
    document.getElementById('student-view').classList.remove('hidden');
    document.getElementById('student-welcome-text').textContent = `Welcome, ${visitorName.trim()}.`;
    document.getElementById('student-event-welcome').textContent = `Welcome Visitor: ${visitorName.trim()}. Select an event to learn more.`;
    updateTopBar(`VISITOR: ${visitorName.trim()}`);
    switchStudentSubTab('campus', document.querySelector('.wheel-center-hub'));
  } 
  else {
    alert('Invalid code! Please enter STUDENT, VISITOR, or ADMIN.');
  }
}

function openStudentIdDialog() {
  const dialog = document.getElementById('student-id-dialog');
  const input = document.getElementById('student-id-input');
  const error = document.getElementById('student-id-error');
  if (!dialog || dialog.open) return;
  if (input) input.value = '';
  if (error) error.textContent = '';
  if (!dialog.dataset.cancelHandlerBound) {
    dialog.addEventListener('cancel', () => cancelStudentId());
    dialog.dataset.cancelHandlerBound = 'true';
  }
  dialog.showModal();
  requestAnimationFrame(() => input?.focus());
}

function continueStudentId(event) {
  event.preventDefault();
  const input = document.getElementById('student-id-input');
  const error = document.getElementById('student-id-error');
  const organizationId = (input?.value || '').trim();
  if (!organizationId) {
    if (error) error.textContent = 'Enter your ID number to continue.';
    input?.focus();
    return;
  }

  // The supplied ID is only checked for non-emptiness. It is never stored or sent.
  if (input) input.value = '';
  if (error) error.textContent = '';
  document.getElementById('student-id-dialog')?.close();
  currentUserRole = 'STUDENT';
  hideAllViews();
  document.getElementById('student-view').classList.remove('hidden');
  document.getElementById('student-welcome-text').textContent = 'Welcome, Student.';
  document.getElementById('student-event-welcome').textContent = 'Logged in as Student. Select an event to view details or register with your Roll Number.';
  updateTopBar('ROLE: STUDENT');
  switchStudentSubTab('campus', document.querySelector('.wheel-center-hub'));
}

function cancelStudentId() {
  const dialog = document.getElementById('student-id-dialog');
  if (dialog?.open) dialog.close();
  const idInput = document.getElementById('student-id-input');
  if (idInput) idInput.value = '';
  const error = document.getElementById('student-id-error');
  if (error) error.textContent = '';
  const codeInput = document.getElementById('access-code');
  if (codeInput) {
    codeInput.value = '';
    updateCodeSlotsUI('');
  }
  document.querySelectorAll('.portal-option').forEach(button => {
    button.classList.remove('is-selected');
    button.setAttribute('aria-pressed', 'false');
  });
  document.querySelector('[data-role="STUDENT"]')?.focus();
}

async function loadStudentEvents(statusFilter = 'All') {
  ['All', 'Ongoing', 'Published', 'Completed'].forEach(st => {
    const btn = document.getElementById(`filter-${st}`);
    if (btn) btn.classList.toggle('active-filter', st === statusFilter);
  });

  const grid = document.getElementById('student-events-grid');
  const countBadge = document.getElementById('student-event-count');
  if(!grid) return; 
  grid.innerHTML = '<p class="muted">Loading events from server...</p>';
  if (countBadge) countBadge.textContent = 'Loading count…';

  try {
    // Use one canonical database list for both the total badge and filters.
    const url = `${API_BASE}/api/activities`;

    const response = await fetch(url);
    const data = await response.json();

    if (!response.ok) {
      if (countBadge) countBadge.textContent = 'Unavailable';
      alert(data.detail || 'Error loading activities.');
      return;
    }

    const events = Array.isArray(data) ? data : [];
    if (countBadge) countBadge.textContent = `${events.length} total ${events.length === 1 ? 'event' : 'events'}`;
    renderStudentEvents(statusFilter === 'All' ? events : events.filter(event => event.status === statusFilter));
  } catch (error) {
    console.error('Fetch error:', error);
    if (countBadge) countBadge.textContent = 'Unavailable';
    grid.innerHTML = `<p class="muted" style="color:#ef4444;">Could not connect to ${API_BASE}. Make sure the backend server is running.</p>`;
  }
}

function renderStudentEvents(events) {
  const grid = document.getElementById('student-events-grid');
  if (eventCountdownTimer) {
    clearInterval(eventCountdownTimer);
    eventCountdownTimer = null;
  }
  grid.innerHTML = '';

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);

  if (events.length === 0) {
    grid.innerHTML = '<div class="card"><p class="muted">No activities found for this filter.</p></div>';
    return;
  }

  events.forEach(event => {
    const card = document.createElement('div');
    card.className = 'card event-card';

    const isCompleted = event.status === 'Completed';
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(event.start_time || '') && /^\d{4}-\d{2}-\d{2}$/.test(event.end_time || '');
    const timingStatus = isCompleted ? 'EXPIRED' : (event.timing_status || event.status || 'Unknown').toUpperCase();
    let sourceLink = '';
    try {
      const metadata = typeof event.metadata === 'string' ? JSON.parse(event.metadata) : event.metadata;
      const source = metadata?.official_source;
      if (typeof source === 'string' && (/^https:\/\/www\.bits-pilani\.ac\.in\//i.test(source) || /^https:\/\/www\.atmos-bits\.com\/?$/i.test(source))) {
        sourceLink = `<a class="event-source-link" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">Official event details ↗</a>`;
      }
    } catch (_) { /* Malformed optional metadata does not block event rendering. */ }

    const formatDate = value => {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
      if (!match) return value ? value.replace('T', ' ') : 'TBA';
      const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
      return new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
    };

    card.innerHTML = `
      <div>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
          <span class="pill">${escapeHtml(event.category || 'General')} • ${escapeHtml(event.participation_type || 'Individual')}</span>
          <span class="badge event-time-status" data-event-time-status>${escapeHtml(timingStatus)}</span>
        </div>
        <h3>${escapeHtml(event.title)}</h3>
        <div class="event-meta">
          <div><strong>📍 Venue:</strong> ${escapeHtml(event.venue || 'TBA')}</div>
          <div><strong>🕒 Start:</strong> ${escapeHtml(formatDate(event.start_time))}${dateOnly ? ' · Asia/Kolkata date' : ''}</div>
          ${event.end_time ? `<div><strong>🏁 End:</strong> ${escapeHtml(formatDate(event.end_time))}</div>` : ''}
          <div><strong>📋 Instructions:</strong> ${escapeHtml(event.participant_instructions || 'None')}</div>
          ${sourceLink ? `<div>${sourceLink}</div>` : ''}
          ${dateOnly ? '<div class="event-countdown" data-event-countdown hidden><strong>Date countdown</strong><span data-countdown-value></span><small>Uses 00:00 IST on the event start date.</small></div>' : ''}
        </div>
      </div>
      <button class="btn ${isCompleted ? 'btn-secondary' : 'btn-primary'} full-width" 
              ${isCompleted ? 'disabled' : ''}>
        ${isCompleted ? 'Event Expired' : 'Register'}
      </button>
    `;

    card.dataset.activityId = String(event.id);
    card.dataset.lifecycleStatus = String(event.status || '');
    if (dateOnly) {
      card.dataset.startDate = event.start_time;
      card.dataset.endDate = event.end_time;
    }
    card.querySelector('button').addEventListener('click', () =>
      handleEventRegistration(event.id, event.participation_type || 'Individual', event.title));

    grid.appendChild(card);
  });
  updateEventCountdowns();
  if (grid.querySelector('[data-event-countdown]')) eventCountdownTimer = setInterval(updateEventCountdowns, 1000);
}

function istMidnightTimestamp(dateText, nextDay = false) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateText || '');
  if (!match) return NaN;
  const day = Number(match[3]) + (nextDay ? 1 : 0);
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, day) - (5 * 60 + 30) * 60 * 1000;
}

function getDateEventState(startDate, endDate, now = Date.now()) {
  const start = istMidnightTimestamp(startDate);
  const end = istMidnightTimestamp(endDate, true);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  if (now < start) return { status: 'UPCOMING', secondsRemaining: Math.max(0, Math.floor((start - now) / 1000)) };
  if (now < end) return { status: 'ONGOING', secondsRemaining: 0 };
  return { status: 'EXPIRED', secondsRemaining: 0 };
}

function updateEventCountdowns() {
  const grid = document.getElementById('student-events-grid');
  if (!grid) return;
  const now = Date.now();
  grid.querySelectorAll('.event-card[data-start-date][data-end-date]').forEach(card => {
    const state = getDateEventState(card.dataset.startDate, card.dataset.endDate, now);
    if (!state) return;

    const badge = card.querySelector('[data-event-time-status]');
    const countdown = card.querySelector('[data-event-countdown]');
    const countdownValue = card.querySelector('[data-countdown-value]');
    const registerButton = card.querySelector('button');
    if (state.status === 'UPCOMING') {
      if (badge) badge.textContent = state.status;
      if (countdown) countdown.hidden = false;
      if (countdownValue) {
        const seconds = state.secondsRemaining;
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const remainingSeconds = seconds % 60;
        countdownValue.textContent = `${days} days ${String(hours).padStart(2, '0')} hours ${String(minutes).padStart(2, '0')} minutes ${String(remainingSeconds).padStart(2, '0')} seconds`;
      }
      if (registerButton && card.dataset.lifecycleStatus !== 'Completed') {
        registerButton.disabled = false;
        registerButton.textContent = 'Register';
        registerButton.classList.add('btn-primary');
        registerButton.classList.remove('btn-secondary');
      }
    } else if (state.status === 'ONGOING') {
      if (badge) badge.textContent = state.status;
      if (countdown) countdown.hidden = true;
      if (registerButton && card.dataset.lifecycleStatus !== 'Completed') {
        registerButton.disabled = false;
        registerButton.textContent = 'Event in Progress';
        registerButton.classList.add('btn-primary');
        registerButton.classList.remove('btn-secondary');
      }
    } else {
      if (badge) badge.textContent = state.status;
      if (countdown) countdown.hidden = false;
      if (countdownValue) countdownValue.textContent = 'Event ended';
      if (registerButton) {
        registerButton.disabled = true;
        registerButton.textContent = 'Event Expired';
        registerButton.classList.add('btn-secondary');
        registerButton.classList.remove('btn-primary');
      }
    }
  });
}

async function handleEventRegistration(activityId, participationType, eventTitle) {
  let studentName = '';
  let studentRollNo = '';

  if (currentUserRole === 'VISITOR') {
    studentName = localStorage.getItem('visitorName') || prompt('Enter your Visitor Name:');
    if (!studentName) return;
    studentRollNo = `VISITOR-${Math.floor(1000 + Math.random() * 9000)}`;
  } else {
    const rollInput = prompt(`Registering for "${eventTitle}"\nPlease enter your Student Roll Number (e.g., 22CS101):`);
    if (!rollInput || !rollInput.trim()) return;
    studentRollNo = rollInput.trim().toUpperCase();

    try {
      const studentRes = await fetch(`${API_BASE}/api/students/${encodeURIComponent(studentRollNo)}`);
      if (!studentRes.ok) throw new Error('Not found');
      
      const studentData = await studentRes.json();
      studentName = studentData.name;
      if (!studentName) throw new Error('Not found');
      
    } catch (error) {
      alert(`Student Roll Number "${studentRollNo}" not found in database.`);
      return;
    }
  }

  const payload = { student_name: studentName, student_roll_no: studentRollNo };

  if (participationType === 'Team') {
    const teamName = prompt(`Verified as ${studentName} (${studentRollNo}).\nEnter your Team Name:`);
    if (!teamName || !teamName.trim()) return alert('Team Name is required.');

    const teamMembers = prompt('Enter Team Members Roll Numbers (comma-separated):');
    if (!teamMembers || !teamMembers.trim()) return alert('Team Members are required.');

    payload.team_name = teamName.trim();
    payload.team_members = teamMembers.trim();
  }

  try {
    const regResponse = await fetch(`${API_BASE}/api/activities/${activityId}/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const regData = await regResponse.json();
    if (!regResponse.ok) return alert(regData.detail || 'Registration failed.');

    alert(`Success! ${studentName} is registered for "${eventTitle}".`);
  } catch (error) {
    console.error('Registration Error:', error);
    alert('Network error while registering.');
  }
}

async function handleAdminLogin(event) {
  event.preventDefault();
  const username = document.getElementById('admin-username').value.trim();
  const passwordInput = document.getElementById('admin-password');
  const password = passwordInput.value;
  const error = document.getElementById('admin-login-error');
  error.hidden = true;
  error.textContent = '';

  try {
    const response = await fetch(`${API_BASE}/api/host/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password })
    });

    const data = await response.json().catch(() => ({}));
    passwordInput.value = '';
    if (!response.ok || !data.success) {
      error.textContent = response.status === 401
        ? 'Invalid username or password'
        : (data.detail || 'Unable to sign in. Try again later.');
      error.hidden = false;
      return;
    }
    showAdminDashboard();
  } catch (_) {
    passwordInput.value = '';
    error.textContent = 'Unable to connect to the sign-in service.';
    error.hidden = false;
  }
}

function showAdminDashboard() {
  document.getElementById('admin-login-section').classList.add('hidden');
  document.getElementById('admin-dashboard-section').classList.remove('hidden');
  loadAdminDashboard();
}

async function restoreAdminSession() {
  try {
    const response = await fetch(`${API_BASE}/api/host/session`, { credentials: 'include' });
    if (response.ok) showAdminDashboard();
  } catch (_) {
    // Keep the login form available when the session check cannot reach the server.
  }
}

async function logoutAdmin() {
  const error = document.getElementById('admin-login-error');
  try {
    const response = await fetch(`${API_BASE}/api/host/logout`, {
      method: 'POST',
      credentials: 'include'
    });
    if (!response.ok) throw new Error('Logout failed');
    document.getElementById('admin-password').value = '';
    document.getElementById('admin-username').value = '';
    showLandingPage();
  } catch (_) {
    error.textContent = 'Unable to log out. Check your connection and try again.';
    error.hidden = false;
  }
}

async function loadAdminDashboard() {
  const container = document.getElementById('admin-events-container');
  if(!container) return;
  container.innerHTML = '<p class="muted">Loading dashboard...</p>';

  try {
    // FIXED: Fetch Drafts AND Published/Ongoing/Completed so they all show up
    const draftRes = await fetch(`${API_BASE}/api/activities?status=Draft`, { credentials: 'include' });
    if (draftRes.status === 401) return showAdminLoginExpired();
    const drafts = await draftRes.json();
    
    const otherRes = await fetch(`${API_BASE}/api/activities`, { credentials: 'include' });
    if (otherRes.status === 401) return showAdminLoginExpired();
    const others = await otherRes.json();
    
    const activitiesList = [...drafts, ...others];

    if (!activitiesList.length) {
      container.innerHTML = '<div class="card"><p class="muted">No activities found.</p></div>';
      return;
    }

    const detailedActivities = await Promise.all(
      activitiesList.map(async act => {
        const detailRes = await fetch(`${API_BASE}/api/activities/${act.id}?view=host`, { credentials: 'include' });
        if (detailRes.status === 401) throw new Error('ADMIN_SESSION_EXPIRED');
        return detailRes.ok ? await detailRes.json() : act;
      })
    );

    renderAdminActivities(detailedActivities);
  } catch (error) {
    if (error.message === 'ADMIN_SESSION_EXPIRED') return showAdminLoginExpired();
    container.innerHTML = '<p class="muted" style="color:#ef4444;">Error loading dashboard. Check backend.</p>';
  }
}

function showAdminLoginExpired() {
  document.getElementById('admin-dashboard-section').classList.add('hidden');
  document.getElementById('admin-login-section').classList.remove('hidden');
  const error = document.getElementById('admin-login-error');
  error.textContent = 'Your admin session expired. Please sign in again.';
  error.hidden = false;
}

function renderAdminActivities(activities) {
  const container = document.getElementById('admin-events-container');
  container.innerHTML = '';

  activities.forEach(activity => {
    const card = document.createElement('div');
    card.className = 'card';

    const reqs = activity.requirements || [];
    const regs = activity.registrations || [];

    const reqHtml = reqs.length > 0 
      ? reqs.map(r => `${r.item_name} (Qty: ${r.quantity})`).join(' | ') 
      : 'None';

    const regRows = regs.length === 0 
      ? '<tr><td colspan="4" class="muted">No students registered yet.</td></tr>'
      : regs.map(reg => `
          <tr>
            <td><strong>${reg.student_name}</strong></td>
            <td><code>${reg.student_roll_no}</code></td>
            <td>${reg.team_name ? `${reg.team_name}` : 'Individual'}</td>
            <td>
              ${reg.checked_in 
                ? '<span class="badge" style="color:#10b981;">✓ Checked In</span>' 
                : `<button class="btn btn-success btn-small" onclick="handleCheckIn(${reg.id})">Check-in</button>`}
            </td>
          </tr>
        `).join('');

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:0.5rem;">
        <div>
          <span class="pill">${activity.category || 'Event'}</span>
          <h3 style="margin-top:0.4rem;">${activity.title} (ID: ${activity.id})</h3>
          <p class="muted" style="margin-bottom:0.25rem;">📍 ${activity.venue} | 🕒 ${activity.start_time.replace('T', ' ')}</p>
          <p class="muted" style="margin-bottom:0;"><strong>🧰 Equipment:</strong> ${reqHtml}</p>
        </div>
        <span class="badge">Status: ${activity.status}</span>
      </div>

      <div class="status-bar">
        <span style="font-size:0.8rem; color:#94a3b8; margin-right:0.5rem;">Change Status:</span>
        <button class="btn btn-secondary btn-small" onclick="handleChangeStatus(${activity.id}, 'Draft')">Draft</button>
        <button class="btn btn-primary btn-small" onclick="handleChangeStatus(${activity.id}, 'Published')">Publish</button>
        <button class="btn btn-primary btn-small" onclick="handleChangeStatus(${activity.id}, 'Ongoing')">Ongoing</button>
        <button class="btn btn-secondary btn-small" onclick="handleChangeStatus(${activity.id}, 'Completed')">Completed</button>
      </div>

      <div>
        <h4 style="font-size:0.9rem; color:#cbd5e1; margin-top:1rem;">Registrations (${regs.length})</h4>
        <table class="reg-table">
          <thead><tr><th>Name</th><th>Roll No</th><th>Team</th><th>Attendance</th></tr></thead>
          <tbody>${regRows}</tbody>
        </table>
      </div>
    `;

    container.appendChild(card);
  });
}

async function handleChangeStatus(activityId, newStatus) {
  try {
    const response = await fetch(`${API_BASE}/api/activities/${activityId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ status: newStatus })
    });

    const data = await response.json();
    if (!response.ok) return alert(data.detail || `Cannot change to ${newStatus}.`);
    
    loadAdminDashboard();
  } catch (error) {
    alert('Error updating status.');
  }
}

async function handleCheckIn(registrationId) {
  try {
    const response = await fetch(`${API_BASE}/api/registrations/${registrationId}/checkin`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ checked_in: true })
    });

    if (response.ok) loadAdminDashboard();
  } catch (error) {
    alert('Error during check-in.');
  }
}

async function handleCreateActivity(event) {
  event.preventDefault();

  const startRaw = document.getElementById('new-start').value;
  const endRaw = document.getElementById('new-end').value;
  const reqItem = document.getElementById('new-req-item').value.trim();

  const payload = {
    title: document.getElementById('new-title').value.trim(),
    category: document.getElementById('new-category').value.trim(),
    venue: document.getElementById('new-venue').value.trim(),
    participation_type: document.getElementById('new-part-type').value,
    start_time: startRaw.length === 16 ? `${startRaw}:00` : startRaw,
    end_time: endRaw.length === 16 ? `${endRaw}:00` : endRaw,
    participant_instructions: document.getElementById('new-instructions').value.trim(),
    requirements: reqItem ? [{ item_name: reqItem, quantity: 1, assigned_to: 'Coach' }] : []
  };

  try {
    const response = await fetch(`${API_BASE}/api/activities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const data = await response.json();
      return alert(data.detail || 'Failed to create activity.');
    }

    alert(`Activity "${payload.title}" created as Draft.`);
    document.getElementById('new-title').value = '';
    loadAdminDashboard();
  } catch (error) {
    alert('Error creating activity.');
  }
}
