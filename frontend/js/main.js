// EventAdda frontend — vanilla JS integrated with Stage 1 FastAPI Backend.
// Authentication, onboarding, and profile management use live backend API endpoints.
// Event discovery and event management belong to Stage 2/3 and are clearly marked.
(function () {
  'use strict';

  /* ---------- Centralized API Configuration ---------- */
  const DEFAULT_API_BASE_URL = 'http://localhost:8000';
  const STORAGE_KEYS = {
    token: 'eventaddaToken',
    userCache: 'eventaddaUserCache',
    apiBaseUrl: 'eventaddaApiBaseUrl'
  };

  function getApiBaseUrl() {
    if (typeof window !== 'undefined' && window.EVENTADDA_API_BASE_URL) {
      return String(window.EVENTADDA_API_BASE_URL).replace(/\/+$/, '');
    }
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.apiBaseUrl);
      if (saved) return saved.replace(/\/+$/, '');
    } catch (e) { /* ignore storage errors */ }
    return DEFAULT_API_BASE_URL;
  }

  function getToken() {
    try { return localStorage.getItem(STORAGE_KEYS.token) || null; } catch (e) { return null; }
  }

  function getCachedUser() {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.userCache);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function saveAuthSession(token, user) {
    try {
      if (token) localStorage.setItem(STORAGE_KEYS.token, token);
      if (user) localStorage.setItem(STORAGE_KEYS.userCache, JSON.stringify(user));
    } catch (e) { /* ignore storage errors */ }
  }

  function clearAuthSession() {
    try {
      localStorage.removeItem(STORAGE_KEYS.token);
      localStorage.removeItem(STORAGE_KEYS.userCache);
      localStorage.removeItem('eventaddaSession');
    } catch (e) { /* ignore storage errors */ }
  }

  function formatApiError(data, status) {
    if (!data) return 'Request failed (HTTP ' + status + ').';
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail) && data.detail.length > 0) {
      return data.detail.map((err) => {
        const field = Array.isArray(err.loc) ? err.loc[err.loc.length - 1] : '';
        const msg = (err.msg || 'Invalid value').replace(/^Value error,\s*/i, '');
        return field && field !== 'body' ? (field + ': ' + msg) : msg;
      }).join(' · ');
    }
    return 'Request failed (HTTP ' + status + ').';
  }

  async function apiRequest(path, options) {
    const opts = options || {};
    const method = opts.method || 'GET';
    const headers = Object.assign({ 'Accept': 'application/json' }, opts.headers || {});
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    if (opts.auth !== false) {
      const token = opts.token || getToken();
      if (token) {
        headers['Authorization'] = 'Bearer ' + token;
      }
    }

    let response;
    try {
      response = await fetch(getApiBaseUrl() + path, {
        method,
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined
      });
    } catch (networkErr) {
      const err = new Error(
        'Cannot reach the EventAdda backend at ' + getApiBaseUrl() +
        '. Ensure the FastAPI server is running.'
      );
      err.status = 0;
      err.isNetworkError = true;
      throw err;
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (e) {
      payload = null;
    }

    if (!response.ok) {
      const err = new Error(formatApiError(payload, response.status));
      err.status = response.status;
      err.payload = payload;
      throw err;
    }

    return payload;
  }

  /* ---------- Backend <-> UI Interest & Category Mapping ---------- */
  const CATEGORIES = [
    { name: 'Hackathon', backendInterest: 'hackathons', icon: '⌘', tone: 'purple', blurb: 'Build, code, solve and compete.' },
    { name: 'Tech Talk', backendInterest: 'summits_conferences', icon: '◎', tone: 'orange', blurb: 'Hear from people shaping tech.' },
    { name: 'Workshop', backendInterest: 'workshops', icon: '✳', tone: 'green', blurb: 'Learn by making and doing.' },
    { name: 'Startup', backendInterest: 'business', icon: '✦', tone: 'pink', blurb: 'Pitch, network and launch ideas.' },
    { name: 'Music', backendInterest: 'arts', icon: '♫', tone: 'purple', blurb: 'Concerts, jams and open mics.' },
    { name: 'Sports', backendInterest: 'sports', icon: '⚽', tone: 'orange', blurb: 'Tournaments, runs and matches.' },
    { name: 'Art', backendInterest: 'design', icon: '✎', tone: 'green', blurb: 'Exhibitions, design and creativity.' },
    { name: 'Food', backendInterest: 'meetups', icon: '🍽', tone: 'pink', blurb: 'Festivals, tastings and cook-offs.' }
  ];

  const UI_TO_BACKEND_INTEREST = {
    'Hackathon': 'hackathons',
    'Tech Talk': 'summits_conferences',
    'Workshop': 'workshops',
    'Startup': 'business',
    'Music': 'arts',
    'Sports': 'sports',
    'Art': 'design',
    'Food': 'meetups'
  };

  const BACKEND_INTEREST_OPTIONS = [
    { slug: 'hackathons', label: 'Hackathons' },
    { slug: 'workshops', label: 'Workshops' },
    { slug: 'summits_conferences', label: 'Summits & Conferences' },
    { slug: 'meetups', label: 'Meetups & Community' },
    { slug: 'tech', label: 'Technology' },
    { slug: 'design', label: 'Design & Creativity' },
    { slug: 'business', label: 'Business & Startups' },
    { slug: 'sports', label: 'Sports' },
    { slug: 'arts', label: 'Arts & Music' },
    { slug: 'science', label: 'Science' },
    { slug: 'education', label: 'Education' },
    { slug: 'health', label: 'Health & Wellness' }
  ];

  function mapUiInterestsToBackend(selectedValues) {
    const out = [];
    (selectedValues || []).forEach((val) => {
      const trimmed = String(val || '').trim();
      const mapped = UI_TO_BACKEND_INTEREST[trimmed] || trimmed.toLowerCase();
      if (mapped && out.indexOf(mapped) === -1) out.push(mapped);
    });
    return out;
  }

  function userMatchesCategory(user, categoryName) {
    if (!user || !Array.isArray(user.interests)) return false;
    const slug = UI_TO_BACKEND_INTEREST[categoryName];
    return Boolean(slug && user.interests.indexOf(slug) !== -1);
  }

  /* ---------- Small helpers ---------- */
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const catInfo = (name) => CATEGORIES.find((c) => c.name === name) || CATEGORIES[0];
  const toISO = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  const todayISO = () => toISO(new Date());
  const plusDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return toISO(d); };
  const fmtDate = (d) => { const x = new Date(d + 'T00:00:00'); return isNaN(x) ? d : x.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); };
  const fmtTime = (t) => { if (!t) return ''; const p = t.split(':'); const x = new Date(); x.setHours(+p[0], +p[1] || 0, 0, 0); return x.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }); };
  const dashboardFor = (role) => (role === 'organizer' ? 'dashboard-organizer.html' : 'dashboard-participant.html');
  const byDate = (a, b) => {
    const t = todayISO();
    const pa = a.date < t ? 1 : 0, pb = b.date < t ? 1 : 0;
    return (pa - pb) || ((a.date + (a.time || '')).localeCompare(b.date + (b.time || '')));
  };

  function say(text, ok, targetId) {
    const m = $(targetId || 'formMessage');
    if (!m) return;
    m.textContent = text;
    m.className = 'form-message' + (ok ? ' success' : '');
  }

  /* ---------- Stage 2/3 Preview Catalogue (Read-Only Until Stage 2 Backend) ---------- */
  function getPreviewEvents() {
    const mk = (n, category, title, description, details, mode, city, venue, time) => ({
      id: 'sample-' + category.toLowerCase().replace(/\s+/g, '-'),
      category,
      title,
      description,
      details: details + '\n\n(Stage 2 Preview Card — Live MongoDB event APIs and in-app registration connect in Stage 2 & Stage 3.)',
      mode,
      city,
      venue,
      date: plusDays(n),
      time,
      organizerId: 'stage2-preview',
      organizerName: 'EventAdda Preview Catalogue'
    });
    return [
      mk(7, 'Hackathon', 'Build for Tomorrow', 'A 24-hour innovation challenge for creative problem-solvers.', 'Teams of 2–4. Bring your laptop and an idea. Mentors and judges on site.', 'Hybrid', 'Mumbai', 'Innovation Hub', '10:00'),
      mk(10, 'Tech Talk', 'Future Minds Talk', 'Industry speakers on AI, cloud and careers in tech.', 'Three short talks followed by an open Q&A.', 'Online', 'Online', 'Meeting link shared after registration', '17:00'),
      mk(12, 'Workshop', 'Design Sprint Lab', 'A hands-on session to practise product design skills.', 'Learn the five-day sprint method in one afternoon.', 'In-person', 'Pune', 'Studio 4, Tech Park', '14:00'),
      mk(15, 'Startup', 'Student Pitch Night', 'Pitch your early idea and meet potential co-founders.', 'Three-minute pitches, feedback from founders and investors.', 'In-person', 'Mumbai', 'Founders Cafe', '18:00'),
      mk(18, 'Music', 'Campus Open Mic', 'An evening of live music, bands and solo acts.', 'Sign up to perform or just come to enjoy the show.', 'In-person', 'Delhi', 'Open Air Theatre', '19:00'),
      mk(21, 'Sports', 'Inter-College Futsal Cup', 'Five-a-side futsal tournament with college teams.', 'Knock-out format. Teams of 7 including substitutes.', 'In-person', 'Bengaluru', 'City Sports Arena', '08:00'),
      mk(24, 'Art', 'Sketch & Colour Day', 'A relaxed day of live sketching, painting and display.', 'All skill levels welcome. Basic materials provided.', 'In-person', 'Jaipur', 'Art Gallery Courtyard', '11:00'),
      mk(27, 'Food', 'Street Food Fest', 'Stalls, tastings and a student cook-off.', 'Over 30 stalls. Entry is free; register to join the cook-off.', 'In-person', 'Hyderabad', 'Central Ground', '12:00')
    ];
  }

  /* ---------- Authoritative Session Verification (/api/auth/me) ---------- */
  async function verifySessionWithBackend() {
    const token = getToken();
    if (!token) return null;
    try {
      const user = await apiRequest('/api/auth/me', { method: 'GET', token });
      saveAuthSession(token, user);
      return user;
    } catch (err) {
      if (err.status === 401 || err.status === 403) {
        clearAuthSession();
        return null;
      }
      throw err;
    }
  }

  function renderHeader(user) {
    const box = document.querySelector('.header-actions');
    if (!box) return;
    if (!user) {
      box.innerHTML = '<a class="btn btn-light" href="login.html">Log in</a><a class="btn btn-primary" href="signup.html">Get started</a>';
      return;
    }
    box.innerHTML =
      '<a class="btn btn-light" href="' + dashboardFor(user.role) + '">Dashboard</a>' +
      '<button class="btn btn-primary" id="logoutBtn" type="button">Log out</button>';
    const logoutBtn = $('logoutBtn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', () => {
        clearAuthSession();
        location.href = 'index.html';
      });
    }
  }

  /* ---------- Stage 1 Onboarding & Profile Panel ---------- */
  function renderProfileAndOnboardingPanel(user) {
    const container = $('stage1ProfileSection');
    if (!container || !user) return;

    const isParticipant = user.role === 'participant';
    const currentCity = (user.location && user.location.city) ? user.location.city : '';
    const currentLocality = (user.location && user.location.locality) ? user.location.locality : '';
    const userInterests = Array.isArray(user.interests) ? user.interests : [];
    const needsOnboarding = isParticipant && !user.onboarding_completed;

    const onboardingBadge = isParticipant
      ? (user.onboarding_completed
          ? '<span class="tag tag-green">ONBOARDING COMPLETE</span>'
          : '<span class="tag tag-orange">ONBOARDING REQUIRED</span>')
      : '<span class="tag tag-purple">ORGANIZER ACCOUNT</span>';

    const interestCheckboxesHtml = isParticipant
      ? '<fieldset><legend>Selected interests (at least 1 required for onboarding)</legend><div class="interest-options">' +
        BACKEND_INTEREST_OPTIONS.map((opt) => {
          const checked = userInterests.indexOf(opt.slug) !== -1 ? ' checked' : '';
          return '<label><input type="checkbox" name="profileInterest" value="' + esc(opt.slug) + '"' + checked + '> ' + esc(opt.label) + '</label>';
        }).join('') +
        '</div></fieldset>'
      : '';

    const onboardingAlertHtml = needsOnboarding
      ? '<div class="status-banner warn" id="onboardingPromptBanner">' +
          '<div><b>Complete your participant onboarding:</b> Select at least one interest and set your preferred city below so EventAdda can personalize your experience.</div>' +
        '</div>'
      : '';

    container.innerHTML =
      onboardingAlertHtml +
      '<section class="auth-card">' +
        '<div class="profile-header">' +
          '<div>' +
            '<span class="eyebrow">ACCOUNT &amp; PROFILE (STAGE 1 LIVE API)</span>' +
            '<h2 style="margin:6px 0 0;font-size:24px">' + esc(user.full_name) + '</h2>' +
            '<div class="profile-summary">' +
              '<span>📧 ' + esc(user.email) + '</span>' +
              '<span>📱 ' + esc(user.phone) + '</span>' +
              '<span>🔑 Role: <b>' + esc(user.role) + '</b> (immutable)</span>' +
              (currentCity ? '<span>📍 ' + esc(currentCity) + (currentLocality ? ', ' + esc(currentLocality) : '') + '</span>' : '') +
            '</div>' +
          '</div>' +
          '<div>' + onboardingBadge + '</div>' +
        '</div>' +
        '<form id="profileAndOnboardingForm" style="margin-top:14px">' +
          '<div class="form-grid">' +
            '<div class="field"><label for="profFullName">Full name</label><input id="profFullName" required minlength="2" maxlength="100" value="' + esc(user.full_name) + '"></div>' +
            '<div class="field"><label for="profPhone">Phone number</label><input id="profPhone" type="tel" required value="' + esc(user.phone) + '"></div>' +
            '<div class="field"><label for="profCity">Preferred city' + (isParticipant ? ' *' : '') + '</label><input id="profCity" ' + (isParticipant ? 'required ' : '') + 'placeholder="e.g. Pune" value="' + esc(currentCity) + '"></div>' +
            '<div class="field"><label for="profLocality">Locality / Area (optional)</label><input id="profLocality" placeholder="e.g. Kothrud" value="' + esc(currentLocality) + '"></div>' +
          '</div>' +
          interestCheckboxesHtml +
          '<div class="inline-actions">' +
            '<button class="btn btn-primary" id="saveProfileBtn" type="submit">' +
              (needsOnboarding ? 'Save preferences &amp; complete onboarding →' : 'Save profile &amp; preferences →') +
            '</button>' +
            (isParticipant ? '<button class="btn btn-light" id="geoLocateBtn" type="button">📍 Use browser coordinates (optional)</button>' : '') +
          '</div>' +
          '<p id="profileFormMessage" class="form-message" aria-live="polite"></p>' +
        '</form>' +
      '</section>';

    let capturedCoords = (user.location && user.location.coordinates) ? user.location.coordinates : null;
    const geoBtn = $('geoLocateBtn');
    if (geoBtn) {
      geoBtn.addEventListener('click', () => {
        if (!navigator.geolocation) {
          say('Browser geolocation is not supported in this browser. You can still save your city manually.', false, 'profileFormMessage');
          return;
        }
        geoBtn.disabled = true;
        say('Requesting browser coordinates…', true, 'profileFormMessage');
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            geoBtn.disabled = false;
            capturedCoords = {
              type: 'Point',
              coordinates: [
                Number(pos.coords.longitude.toFixed(6)),
                Number(pos.coords.latitude.toFixed(6))
              ]
            };
            say('Coordinates captured (' + capturedCoords.coordinates[1] + ', ' + capturedCoords.coordinates[0] + '). Click Save to persist.', true, 'profileFormMessage');
          },
          () => {
            geoBtn.disabled = false;
            say('Location permission denied or unavailable. Manual city selection works without coordinates.', false, 'profileFormMessage');
          },
          { timeout: 6000 }
        );
      });
    }

    const form = $('profileAndOnboardingForm');
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const saveBtn = $('saveProfileBtn');
      const fullName = $('profFullName').value.trim();
      const phone = $('profPhone').value.trim();
      const city = $('profCity').value.trim();
      const locality = $('profLocality').value.trim();

      const selectedInterests = isParticipant
        ? Array.from(form.querySelectorAll('input[name="profileInterest"]:checked')).map((cb) => cb.value)
        : undefined;

      if (isParticipant && (!selectedInterests || selectedInterests.length === 0)) {
        return say('Please select at least one interest.', false, 'profileFormMessage');
      }
      if (isParticipant && !city) {
        return say('Please enter your preferred city.', false, 'profileFormMessage');
      }

      saveBtn.disabled = true;
      say('Saving to EventAdda backend…', true, 'profileFormMessage');

      try {
        if (isParticipant) {
          await apiRequest('/api/onboarding/interests', {
            method: 'PUT',
            body: { interests: selectedInterests }
          });

          const locPayload = { city };
          if (locality) locPayload.locality = locality;
          if (capturedCoords) locPayload.coordinates = capturedCoords;

          await apiRequest('/api/onboarding/location', {
            method: 'PUT',
            body: locPayload
          });

          if (!user.onboarding_completed) {
            await apiRequest('/api/onboarding/complete', { method: 'POST' });
          }
        }

        const profilePayload = {
          full_name: fullName,
          phone: phone
        };
        if (city) {
          profilePayload.location = { city };
          if (locality) profilePayload.location.locality = locality;
          if (capturedCoords) profilePayload.location.coordinates = capturedCoords;
        }
        if (isParticipant && selectedInterests) {
          profilePayload.interests = selectedInterests;
        }

        const updatedRes = await apiRequest('/api/profile', {
          method: 'PUT',
          body: profilePayload
        });

        const freshUser = updatedRes.user || (await verifySessionWithBackend());
        saveAuthSession(getToken(), freshUser);
        if ($('userName')) $('userName').textContent = freshUser.full_name;
        renderProfileAndOnboardingPanel(freshUser);
        if (isParticipant) setupListing(freshUser);
        say('Profile and preferences saved to the backend!', true, 'profileFormMessage');
      } catch (err) {
        say(err.message || 'Could not update profile.', false, 'profileFormMessage');
      } finally {
        if ($('saveProfileBtn')) $('saveProfileBtn').disabled = false;
      }
    });
  }

  /* ---------- Event Cards & Stage 2/3 Honest State ---------- */
  function cardHTML(e, user, opts) {
    opts = opts || {};
    const c = catInfo(e.category);
    const id = encodeURIComponent(e.id);
    let actions;
    if (!user) {
      actions = '<a class="btn btn-light full-width" href="event.html?id=' + id + '">View event preview →</a>';
    } else if (user.role === 'participant') {
      actions = '<a class="btn btn-primary full-width" href="event.html?id=' + id + '">View details →</a>';
    } else {
      actions = '<a class="btn btn-light full-width" href="event.html?id=' + id + '">View details →</a>';
    }
    return '<article class="event-card" data-category="' + esc(e.category) + '">' +
      '<div class="event-card-art art-' + c.tone + '">' + c.icon + '<span>' + esc(e.category.toUpperCase()) + '</span></div>' +
      '<div class="event-card-body"><span class="tag tag-' + c.tone + '">' + esc(e.category) + '</span>' +
      (opts.forYou ? ' <span class="match">Matches your interest</span>' : '') +
      '<h3>' + esc(e.title) + '</h3><p>' + esc((e.description || '').slice(0, 110)) + '</p>' +
      '<div class="event-meta">📅 ' + esc(fmtDate(e.date)) + ' · 📍 ' + esc(e.city) + ' · ' + esc(e.mode) + '</div>' + actions + '</div></article>';
  }

  function renderStage2Banner() {
    const banner = $('eventsStatusBanner');
    if (!banner) return;
    banner.innerHTML =
      '<div class="status-banner">' +
        '<div><b>Stage 1 Integration Active:</b> Authentication, single-role guards, onboarding, and profile sync with the FastAPI backend. Event listings below are read-only preview cards until Stage 2 (`GET /api/events`) and Stage 3 (`POST /api/registrations`) endpoints are enabled.</div>' +
      '</div>';
  }

  function setupListing(user) {
    const grid = $('eventGrid'), search = $('eventSearch'), filter = $('categoryFilter'), empty = $('emptyState');
    if (!grid || !search || !filter) return;
    renderStage2Banner();

    const param = new URLSearchParams(location.search).get('category');
    if (param) {
      const m = Array.from(filter.options).find((o) => o.value.toLowerCase() === param.toLowerCase());
      if (m) filter.value = m.value;
    }
    const render = () => {
      const q = search.value.toLowerCase().trim(), cat = filter.value;
      const list = getPreviewEvents()
        .filter((e) => (cat === 'All' || e.category === cat) &&
          [e.title, e.description, e.details, e.category, e.city, e.venue, e.organizerName].join(' ').toLowerCase().indexOf(q) !== -1)
        .sort((a, b) => (Number(userMatchesCategory(user, b.category)) - Number(userMatchesCategory(user, a.category))) || byDate(a, b));
      grid.innerHTML = list.map((e) => cardHTML(e, user, { forYou: userMatchesCategory(user, e.category) })).join('');
      if (empty) empty.hidden = list.length > 0;
    };
    if (!search.dataset.bound) {
      search.dataset.bound = '1';
      search.addEventListener('input', render);
      filter.addEventListener('change', render);
    }
    render();
  }

  /* ---------- Stage 1 Auth: Signup & Login ---------- */
  function initSignup() {
    const form = $('signupForm');
    if (!form) return;
    const role = form.dataset.role;

    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const submitBtn = form.querySelector('button[type="submit"]');
      const val = (id) => ($(id) ? $(id).value.trim() : '');

      const fullName = val('name');
      const phone = val('phone');
      const email = val('signupEmail').toLowerCase();
      const password = $('signupPassword') ? $('signupPassword').value : '';
      const city = val('city');

      const uiInterests = Array.from(form.querySelectorAll('input[name="interest"]:checked')).map((x) => x.value);
      const backendInterests = mapUiInterestsToBackend(uiInterests);

      if (role === 'participant' && backendInterests.length === 0) {
        return say('Please choose at least one interest to personalize your event feed.');
      }
      if (role === 'participant' && !city) {
        return say('Please enter your preferred city.');
      }
      if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
        return say('Password must be at least 8 characters and include at least one letter and one number.');
      }

      if (submitBtn) submitBtn.disabled = true;
      say('Creating your account on EventAdda…', true);

      try {
        const authRes = await apiRequest('/api/auth/signup', {
          method: 'POST',
          auth: false,
          body: {
            full_name: fullName,
            email: email,
            phone: phone,
            password: password,
            role: role
          }
        });

        const token = authRes.access_token;
        let currentUser = authRes.user;
        saveAuthSession(token, currentUser);

        if (role === 'participant') {
          await apiRequest('/api/onboarding/interests', {
            method: 'PUT',
            token,
            body: { interests: backendInterests }
          });
          await apiRequest('/api/onboarding/location', {
            method: 'PUT',
            token,
            body: { city: city }
          });
          await apiRequest('/api/onboarding/complete', {
            method: 'POST',
            token
          });
          currentUser = await apiRequest('/api/auth/me', { method: 'GET', token });
          saveAuthSession(token, currentUser);
        } else if (city) {
          const profRes = await apiRequest('/api/profile', {
            method: 'PUT',
            token,
            body: { location: { city: city } }
          });
          if (profRes && profRes.user) {
            currentUser = profRes.user;
            saveAuthSession(token, currentUser);
          }
        }

        say('Account created! Redirecting to your ' + currentUser.role + ' dashboard…', true);
        setTimeout(() => {
          location.href = dashboardFor(currentUser.role);
        }, 450);
      } catch (err) {
        say(err.message || 'Signup failed. Please check your details and try again.', false);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  function initLogin() {
    const form = $('loginForm');
    if (!form) return;
    const expectedRole = form.dataset.role;

    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const submitBtn = form.querySelector('button[type="submit"]');
      const email = $('email') ? $('email').value.trim().toLowerCase() : '';
      const password = $('password') ? $('password').value : '';

      if (submitBtn) submitBtn.disabled = true;
      say('Signing in…', true);

      try {
        const authRes = await apiRequest('/api/auth/login', {
          method: 'POST',
          auth: false,
          body: { email, password }
        });

        const token = authRes.access_token;
        const verifiedUser = await apiRequest('/api/auth/me', {
          method: 'GET',
          token
        });

        if (expectedRole && verifiedUser.role !== expectedRole) {
          clearAuthSession();
          const roleLabel = verifiedUser.role === 'organizer' ? 'an organizer' : 'a participant';
          const targetLogin = 'login-' + verifiedUser.role + '.html';
          say(
            'This account is registered as ' + roleLabel +
            '. Single-role accounts cannot switch roles — please log in via ' + targetLogin + '.',
            false
          );
          return;
        }

        saveAuthSession(token, verifiedUser);
        say('Logged in as ' + verifiedUser.full_name + '. Redirecting…', true);
        setTimeout(() => {
          location.href = dashboardFor(verifiedUser.role);
        }, 350);
      } catch (err) {
        say(err.message || 'Invalid email or password.', false);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  /* ---------- Dashboards & Event Detail Page ---------- */
  function initParticipantDashboard(user) {
    if (!user || user.role !== 'participant') {
      location.replace('login-participant.html');
      return;
    }
    if ($('userName')) $('userName').textContent = user.full_name;
    renderProfileAndOnboardingPanel(user);
    setupListing(user);
  }

  function initOrganizerDashboard(user) {
    if (!user || user.role !== 'organizer') {
      location.replace('login-organizer.html');
      return;
    }
    if ($('userName')) $('userName').textContent = user.full_name;
    renderProfileAndOnboardingPanel(user);
    renderStage2Banner();

    const form = $('eventForm'), mine = $('myEvents'), others = $('otherEvents');
    if ($('myEmpty')) {
      $('myEmpty').hidden = false;
      $('myEmpty').textContent = 'Organizer event creation & management endpoints (/api/organizer/events) are scheduled for Stage 2.';
    }
    if (mine) mine.innerHTML = '';

    if (others) {
      const previewList = getPreviewEvents().slice().sort(byDate);
      others.innerHTML = previewList.map((e) => cardHTML(e, user)).join('');
      if ($('otherEmpty')) $('otherEmpty').hidden = previewList.length > 0;
    }

    if (form) {
      form.addEventListener('submit', (ev) => {
        ev.preventDefault();
        say(
          'Event publishing is not yet available in Stage 1: POST /api/organizer/events will be enabled in Stage 2. No fake event was saved.',
          false
        );
      });
    }
  }

  function initEventPage(user) {
    const box = $('eventDetail');
    if (!box) return;
    const eventId = new URLSearchParams(location.search).get('id');
    const e = getPreviewEvents().find((x) => x.id === eventId);
    if (!e) {
      box.innerHTML =
        '<section class="auth-card auth-card-wide">' +
          '<h1>Event not found</h1>' +
          '<p class="muted">Live event lookup (GET /api/events/{id}) will be connected in Stage 2.</p>' +
          '<a class="btn btn-light full-width" href="events.html">Back to events</a>' +
        '</section>';
      return;
    }
    const c = catInfo(e.category);
    let actionHtml;
    if (!user) {
      actionHtml = '<a class="btn btn-primary full-width" href="login-participant.html">Log in as a participant to register →</a>';
    } else if (user.role === 'participant') {
      actionHtml =
        '<button class="btn btn-primary full-width" id="stage3RegisterBtn" type="button">Register in EventAdda →</button>' +
        '<p id="regMessage" class="form-message" aria-live="polite"></p>' +
        '<p class="fine-print">In-app event registration (POST /api/registrations/{event_id}) is scheduled for Stage 3.</p>';
    } else {
      actionHtml =
        '<div class="demo-notice">Organizer accounts can view events, but only participant accounts can register for events.</div>';
    }

    box.innerHTML =
      '<section class="auth-card auth-card-wide">' +
        '<span class="tag tag-' + c.tone + '">' + esc(e.category) + '</span>' +
        '<h1>' + esc(e.title) + '</h1>' +
        '<p class="muted">Organized by ' + esc(e.organizerName) + '</p>' +
        '<div class="event-meta">📅 ' + esc(fmtDate(e.date)) + (e.time ? ' · ⏰ ' + esc(fmtTime(e.time)) : '') + '</div>' +
        '<div class="event-meta">📍 ' + esc(e.venue ? e.venue + ', ' : '') + esc(e.city) + ' · ' + esc(e.mode) + '</div>' +
        '<fieldset><legend>About this event</legend><p>' + esc(e.description) + '</p></fieldset>' +
        (e.details ? '<fieldset><legend>Details</legend><p class="pre">' + esc(e.details) + '</p></fieldset>' : '') +
        '<div class="stack">' + actionHtml + '</div>' +
      '</section>';

    const regBtn = $('stage3RegisterBtn');
    if (regBtn) {
      regBtn.addEventListener('click', () => {
        say(
          'In-app registration is not yet available in Stage 1: POST /api/registrations/{event_id} will be enabled in Stage 3.',
          false,
          'regMessage'
        );
      });
    }
  }

  /* ---------- Boot ---------- */
  document.addEventListener('DOMContentLoaded', async () => {
    const menu = document.querySelector('.menu-toggle');
    const header = document.querySelector('.header');
    if (menu && header) menu.addEventListener('click', () => header.classList.toggle('menu-open'));

    initSignup();
    initLogin();

    const page = document.body.dataset.page;
    let verifiedUser = null;
    let backendError = null;

    if (getToken()) {
      try {
        verifiedUser = await verifySessionWithBackend();
      } catch (err) {
        backendError = err;
        verifiedUser = getCachedUser();
      }
    }

    renderHeader(verifiedUser);

    if (backendError && $('eventsStatusBanner')) {
      $('eventsStatusBanner').innerHTML =
        '<div class="status-banner error">' +
          '<div><b>Backend Connection Warning:</b> ' + esc(backendError.message) + '</div>' +
        '</div>';
    }

    if (page === 'participant-dashboard') {
      initParticipantDashboard(verifiedUser);
    } else if (page === 'organizer-dashboard') {
      initOrganizerDashboard(verifiedUser);
    } else if ($('eventDetail')) {
      initEventPage(verifiedUser);
    } else if ($('eventGrid')) {
      setupListing(verifiedUser);
    }
  });
})();
