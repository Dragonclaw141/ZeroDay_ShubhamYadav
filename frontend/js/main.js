// EventADDA frontend — vanilla JS integrated with Stage 1 & Stage 2 FastAPI Backend.
// Authentication, onboarding, profile management, and event discovery use live backend API endpoints.
// In-app event registration belongs to Stage 3 and is clearly marked.
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
      localStorage.removeItem('eventaddaUsers');
      localStorage.removeItem('user');
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
        'Cannot reach the EventADDA backend at ' + getApiBaseUrl() +
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

  const BACKEND_TO_UI_CATEGORY = {
    'hackathons': 'Hackathon',
    'summits_conferences': 'Tech Talk',
    'workshops': 'Workshop',
    'business': 'Startup',
    'arts': 'Music',
    'sports': 'Sports',
    'design': 'Art',
    'meetups': 'Food',
    'tech': 'Tech Talk'
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
      organizerName: 'EventADDA Preview Catalogue'
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

  /* ---------- Onboarding & Profile Panel ---------- */
  function renderParticipantSummaryBar(user) {
    const summaryBar = $('participantSummaryBar');
    if (!summaryBar || !user) return;
    const city = (user.location && user.location.city) ? user.location.city : '';
    const affiliation = user.affiliation_details || '';
    const interests = Array.isArray(user.interests) ? user.interests : [];
    const pills = [];
    if (city) {
      pills.push('<span class="summary-pill">📍 ' + esc(city) + '</span>');
    }
    if (affiliation) {
      pills.push('<span class="summary-pill">🎓 ' + esc(affiliation) + '</span>');
    }
    interests.slice(0, 5).forEach((slug) => {
      const opt = BACKEND_INTEREST_OPTIONS.find((o) => o.slug === slug);
      const label = opt ? opt.label : (BACKEND_TO_UI_CATEGORY[slug] || slug);
      pills.push('<span class="summary-pill summary-pill-interest">✦ ' + esc(label) + '</span>');
    });
    summaryBar.innerHTML = pills.join('');
  }

  function renderProfileAndOnboardingPanel(user) {
    const container = $('stage1ProfileSection');
    if (!container || !user) return;

    const isParticipant = user.role === 'participant';
    const currentCity = (user.location && user.location.city) ? user.location.city : '';
    const currentLocality = (user.location && user.location.locality) ? user.location.locality : '';
    const currentAffiliation = user.affiliation_details ? user.affiliation_details : '';
    const currentOrganization = user.organization_name ? user.organization_name : '';
    const userInterests = Array.isArray(user.interests) ? user.interests : [];
    const needsOnboarding = isParticipant && !user.onboarding_completed;

    if (isParticipant) {
      renderParticipantSummaryBar(user);
    }

    const toggleBtn = $('toggleProfileBtn');
    if (toggleBtn) {
      if (!toggleBtn.dataset.bound) {
        toggleBtn.dataset.bound = '1';
        container.hidden = !needsOnboarding;
        toggleBtn.setAttribute('aria-expanded', needsOnboarding ? 'true' : 'false');
        toggleBtn.addEventListener('click', () => {
          const nextOpen = container.hidden;
          container.hidden = !nextOpen;
          toggleBtn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
        });
      } else if (needsOnboarding) {
        container.hidden = false;
        toggleBtn.setAttribute('aria-expanded', 'true');
      }
    }

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
          '<div><b>Complete your participant onboarding:</b> Select at least one interest and set your preferred city below so EventADDA can personalize your experience.</div>' +
        '</div>'
      : '';

    container.innerHTML =
      onboardingAlertHtml +
      '<section class="auth-card">' +
        '<div class="profile-header">' +
          '<div>' +
            '<span class="eyebrow">ACCOUNT &amp; PROFILE</span>' +
            '<h2 style="margin:6px 0 0;font-size:24px">' + esc(user.full_name) + '</h2>' +
            '<div class="profile-summary">' +
              '<span>📧 ' + esc(user.email) + '</span>' +
              '<span>📱 ' + esc(user.phone) + '</span>' +
              '<span>🔑 Role: <b>' + esc(user.role) + '</b> (immutable)</span>' +
              (currentAffiliation ? '<span>🎓 ' + esc(currentAffiliation) + '</span>' : '') +
              (currentOrganization ? '<span>🏛️ ' + esc(currentOrganization) + '</span>' : '') +
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
            (isParticipant
              ? '<div class="field"><label for="profAffiliation">College Name/Organization Name/Major</label><input id="profAffiliation" maxlength="150" placeholder="Thakur College/IIT/Software Eng" value="' + esc(currentAffiliation) + '"></div>'
              : '<div class="field"><label for="profOrganization">Organization / Club name / College Name</label><input id="profOrganization" maxlength="150" placeholder="e.g. Tech Club, IIT, Shree LR Tiwari College" value="' + esc(currentOrganization) + '"></div>') +
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
      say('Saving to EventADDA backend…', true, 'profileFormMessage');

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
        if (isParticipant && $('profAffiliation')) {
          profilePayload.affiliation_details = $('profAffiliation').value.trim();
        }
        if (!isParticipant && $('profOrganization')) {
          profilePayload.organization_name = $('profOrganization').value.trim();
        }
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

  /* ---------- Live Backend Event Adaptation & Editorial Cards ---------- */
  const CATEGORY_THEME_CLASS = {
    'Hackathon': 'theme-hackathon',
    'Tech Talk': 'theme-techtalk',
    'Workshop': 'theme-workshop',
    'Startup': 'theme-startup',
    'Music': 'theme-music',
    'Sports': 'theme-sports',
    'Art': 'theme-art',
    'Food': 'theme-food'
  };

  function hashString(str) {
    let h = 2166136261;
    const s = String(str || '');
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return Math.abs(h);
  }

  function parseMonthDay(dateStr) {
    const dt = new Date(dateStr + 'T00:00:00');
    if (isNaN(dt)) return { month: 'TBD', day: '—' };
    return {
      month: dt.toLocaleDateString('en-US', { month: 'short' }).toUpperCase(),
      day: String(dt.getDate()).padStart(2, '0')
    };
  }

  function adaptBackendEvent(ev) {
    const startIso = ev.start_date || new Date().toISOString();
    const dt = new Date(startIso);
    const dateStr = isNaN(dt) ? todayISO() : toISO(dt);
    const timeStr = isNaN(dt)
      ? '10:00'
      : String(dt.getHours()).padStart(2, '0') + ':' + String(dt.getMinutes()).padStart(2, '0');
    const rawDesc = String(ev.description || '');
    const parts = rawDesc.split('\n\n');
    const shortDesc = parts[0] || rawDesc;
    const extraDetails = parts.length > 1 ? parts.slice(1).join('\n\n') : '';
    const uiCategory = BACKEND_TO_UI_CATEGORY[ev.category] || ev.category || 'Hackathon';
    const venueObj = ev.venue || {};
    return {
      id: ev.id,
      category: uiCategory,
      backendCategory: ev.category,
      title: ev.title,
      description: shortDesc,
      details: extraDetails,
      fullDescription: rawDesc,
      mode: ev.mode || 'In-person',
      city: venueObj.city || 'Online',
      venue: venueObj.name || venueObj.address || '',
      date: dateStr,
      time: timeStr,
      priceType: ev.price_type || (ev.is_free === false ? 'paid' : 'free'),
      priceAmount: ev.price_amount != null ? ev.price_amount : null,
      formUrl: ev.registration_url || '',
      status: ev.status || 'published',
      maxCapacity: ev.max_capacity != null ? Number(ev.max_capacity) : 100,
      registeredCount: ev.registered_count != null ? Number(ev.registered_count) : 0,
      spotsRemaining: ev.spots_remaining != null ? Number(ev.spots_remaining) : 100,
      registrationOpen: ev.registration_open !== false,
      registrationDeadline: ev.registration_deadline || ev.start_date || startIso,
      isRegistered: Boolean(ev.is_registered),
      myRegistration: ev.my_registration || null,
      organizerId: ev.organizer_id,
      organizerName: ev.organizer_name || 'Event Organizer'
    };
  }

  function priceBadgeHTML(e) {
    if (e.priceType === 'paid' && e.priceAmount != null) {
      return ' <span class="tag tag-orange">₹' + esc(e.priceAmount) + '</span>';
    }
    return ' <span class="tag tag-green">FREE</span>';
  }

  function posterPricePillHTML(e) {
    if (e.priceType === 'paid' && e.priceAmount != null) {
      return '<span class="price-pill price-pill-paid">₹' + esc(e.priceAmount) + '</span>';
    }
    return '<span class="price-pill price-pill-free">FREE ENTRY</span>';
  }

  function cardHTML(e, user, opts) {
    opts = opts || {};
    const c = catInfo(e.category);
    const id = encodeURIComponent(e.id);
    const own = Boolean(user && user.role === 'organizer' && e.organizerId === user.id);
    const statusBadge = opts.manage && own
      ? (e.status === 'draft'
          ? ' <span class="tag tag-purple">DRAFT</span>'
          : ' <span class="tag tag-green">PUBLISHED</span>')
      : '';
    let actions;
    if (opts.manage && own) {
      actions =
        '<div class="stack">' +
          '<a class="btn btn-light full-width" href="event.html?id=' + id + '">View details</a>' +
          (e.status === 'draft'
            ? '<button class="btn btn-primary full-width" type="button" data-publish="' + esc(e.id) + '">Publish event</button>'
            : '') +
          (e.status !== 'cancelled'
            ? '<button class="btn btn-light full-width" type="button" data-edit="' + esc(e.id) + '">Edit</button>' +
              '<button class="btn btn-light full-width" type="button" data-delete="' + esc(e.id) + '">Cancel event</button>'
            : '') +
        '</div>';
    } else if (!user) {
      actions = '<a class="btn btn-light full-width" href="event.html?id=' + id + '">Explore event →</a>';
    } else if (user.role === 'participant') {
      actions = '<a class="btn btn-primary full-width" href="event.html?id=' + id + '">View details &amp; register →</a>';
    } else if (own) {
      actions = '<a class="btn btn-light full-width" href="dashboard-organizer.html?edit=' + id + '">Manage in dashboard →</a>';
    } else {
      actions = '<a class="btn btn-light full-width" href="event.html?id=' + id + '">Explore event →</a>';
    }

    const themeCls = CATEGORY_THEME_CLASS[e.category] || 'theme-hackathon';
    const patternIdx = hashString(String(e.id) + ':' + String(e.title)) % 6;
    const md = parseMonthDay(e.date);
    const modeIcon = e.mode === 'Online' ? '🌐' : (e.mode === 'Hybrid' ? '⚡' : '📍');
    const locLabel = e.venue && e.venue !== e.city ? (e.venue + ', ' + e.city) : e.city;
    const orgInitial = String(e.organizerName || 'E').trim().charAt(0).toUpperCase() || 'E';
    const featuredCls = opts.featured ? ' event-card-featured' : '';

    return '<article class="event-card' + featuredCls + '" data-category="' + esc(e.category) + '">' +
      '<div class="event-card-art ' + themeCls + ' art-' + c.tone + '">' +
        '<div class="poster-backdrop"></div>' +
        '<div class="poster-pattern pattern-v' + patternIdx + '"></div>' +
        '<div class="poster-glyph" aria-hidden="true">' + c.icon + '</div>' +
        '<div class="poster-top-bar">' +
          '<div class="poster-date-badge">' +
            '<span class="month">' + esc(md.month) + '</span>' +
            '<span class="day">' + esc(md.day) + '</span>' +
          '</div>' +
          '<div class="poster-badges-right">' +
            posterPricePillHTML(e) +
          '</div>' +
        '</div>' +
        '<div class="poster-bottom-bar">' +
          '<span class="poster-mode-chip">' + modeIcon + ' ' + esc(e.mode) + ' · ' + esc(e.city) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="event-card-body">' +
        '<div class="card-tag-row">' +
          '<span class="tag tag-' + c.tone + '">' + esc(e.category) + '</span>' +
          priceBadgeHTML(e) +
          statusBadge +
          (opts.forYou ? ' <span class="match">✦ Matches your interest</span>' : '') +
        '</div>' +
        '<h3>' + esc(e.title) + '</h3>' +
        '<p>' + esc((e.description || '').slice(0, 145)) + '</p>' +
        '<div class="card-details-list">' +
          '<div class="card-detail-item" title="' + esc(fmtDate(e.date) + ' · ' + locLabel) + '">' +
            '<span>📅 <strong>' + esc(fmtDate(e.date)) + '</strong>' + (e.time ? ' at ' + esc(fmtTime(e.time)) : '') + '</span>' +
          '</div>' +
          '<div class="card-detail-item" title="' + esc(locLabel) + '">' +
            '<span>📍 ' + esc(locLabel) + '</span>' +
          '</div>' +
          '<div class="card-detail-item" title="Hosted by ' + esc(e.organizerName) + '">' +
            '<span class="organizer-monogram">' + esc(orgInitial) + '</span>' +
            '<span>' + esc(e.organizerName) + '</span>' +
          '</div>' +
        '</div>' +
        actions +
      '</div>' +
    '</article>';
  }

  async function setupListing(user) {
    const grid = $('eventGrid'), search = $('eventSearch'), filter = $('categoryFilter'), empty = $('emptyState');
    if (!grid || !search || !filter) return;

    let priceFilter = $('priceFilter');
    if (!priceFilter && filter.parentElement) {
      priceFilter = document.createElement('select');
      priceFilter.id = 'priceFilter';
      priceFilter.setAttribute('aria-label', 'Filter by price');
      priceFilter.innerHTML =
        '<option value="All">All prices</option>' +
        '<option value="free">Free entry</option>' +
        '<option value="paid">Paid / Ticketed</option>';
      filter.parentElement.appendChild(priceFilter);
    }

    const pillsWrap = $('categoryPills');
    const countBadge = $('eventCountBadge');
    const resultsSummary = $('resultsSummary');
    const resetBtn = $('resetFiltersBtn');
    const emptyResetBtn = $('emptyResetBtn');

    const syncPillsWithSelect = () => {
      if (!pillsWrap) return;
      const activeVal = filter.value || 'All';
      pillsWrap.querySelectorAll('[data-pill-category]').forEach((btn) => {
        const isMatch = btn.getAttribute('data-pill-category') === activeVal;
        btn.classList.toggle('active', isMatch);
      });
    };

    const param = new URLSearchParams(location.search).get('category');
    if (param && !search.dataset.bound) {
      const m = Array.from(filter.options).find((o) => o.value.toLowerCase() === param.toLowerCase());
      if (m) filter.value = m.value;
    }
    syncPillsWithSelect();

    let liveEvents = [];
    let fetchFailed = false;

    const showSkeletons = () => {
      if (grid.children.length === 0) {
        grid.innerHTML = Array.from({ length: 6 })
          .map(() => '<div class="skeleton-card" aria-hidden="true"></div>')
          .join('');
      }
    };

    const loadEventsFromApi = async () => {
      showSkeletons();
      try {
        const params = new URLSearchParams();
        params.set('limit', '50');
        if (filter.value && filter.value !== 'All') {
          params.set('category', filter.value);
        }
        if (priceFilter && priceFilter.value !== 'All') {
          params.set('price_type', priceFilter.value);
        }
        if (search.value.trim()) {
          params.set('search', search.value.trim());
        }
        const res = await apiRequest('/api/events?' + params.toString(), { method: 'GET', auth: false });
        liveEvents = Array.isArray(res.events) ? res.events.map(adaptBackendEvent) : [];
        fetchFailed = false;
        if ($('eventsStatusBanner') && !$('eventsStatusBanner').dataset.sessionError) {
          $('eventsStatusBanner').innerHTML = '';
        }
      } catch (err) {
        liveEvents = [];
        fetchFailed = true;
        if ($('eventsStatusBanner')) {
          $('eventsStatusBanner').innerHTML =
            '<div class="status-banner error">' +
              '<div><b>Unable to load events from backend:</b> ' + esc(err.message || 'Check that FastAPI and MongoDB are running.') + '</div>' +
              '<button type="button" class="btn btn-light" id="retryLoadEventsBtn">Retry</button>' +
            '</div>';
          const retryBtn = $('retryLoadEventsBtn');
          if (retryBtn) {
            retryBtn.addEventListener('click', async () => {
              await loadEventsFromApi();
              render();
            });
          }
        }
      }
    };

    const render = () => {
      const q = search.value.toLowerCase().trim(), cat = filter.value;
      const pt = priceFilter ? priceFilter.value : 'All';
      const hasActiveFilters = Boolean(q || cat !== 'All' || pt !== 'All');

      if (resetBtn) resetBtn.hidden = !hasActiveFilters;
      syncPillsWithSelect();

      const list = liveEvents
        .filter((e) =>
          (cat === 'All' || e.category === cat) &&
          (pt === 'All' || e.priceType === pt) &&
          [e.title, e.description, e.details, e.category, e.city, e.venue, e.organizerName].join(' ').toLowerCase().indexOf(q) !== -1
        )
        .sort((a, b) => (Number(userMatchesCategory(user, b.category)) - Number(userMatchesCategory(user, a.category))) || byDate(a, b));

      if (countBadge) {
        countBadge.textContent = list.length + (list.length === 1 ? ' Live Experience' : ' Live Experiences');
      }

      if (resultsSummary) {
        const activeChips = [];
        if (cat !== 'All') activeChips.push('<span class="active-filter-chip">' + esc(cat) + '</span>');
        if (pt !== 'All') activeChips.push('<span class="active-filter-chip">' + (pt === 'free' ? 'Free Entry' : 'Paid / Ticketed') + '</span>');
        if (q) activeChips.push('<span class="active-filter-chip">“' + esc(search.value.trim()) + '”</span>');

        const matchCount = user ? list.filter((e) => userMatchesCategory(user, e.category)).length : 0;
        const matchNote = matchCount > 0 ? ' · <strong>' + matchCount + '</strong> matched to your interests' : '';

        resultsSummary.innerHTML =
          '<div>Showing <strong>' + list.length + '</strong> upcoming ' + (list.length === 1 ? 'event' : 'events') + matchNote + '</div>' +
          (activeChips.length ? '<div class="results-active-tags">' + activeChips.join('') + '</div>' : '');
      }

      grid.innerHTML = list.map((e, idx) => cardHTML(e, user, {
        forYou: userMatchesCategory(user, e.category),
        featured: idx === 0 && list.length >= 4 && !q && cat === 'All'
      })).join('');

      if (empty) empty.hidden = list.length > 0 || fetchFailed;
    };

    const resetAllFilters = async () => {
      search.value = '';
      filter.value = 'All';
      if (priceFilter) priceFilter.value = 'All';
      syncPillsWithSelect();
      await loadEventsFromApi();
      render();
    };

    if (!search.dataset.bound) {
      search.dataset.bound = '1';
      let debounceTimer = null;
      search.addEventListener('input', () => {
        render();
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
          await loadEventsFromApi();
          render();
        }, 250);
      });
      filter.addEventListener('change', async () => {
        syncPillsWithSelect();
        await loadEventsFromApi();
        render();
      });
      if (priceFilter) {
        priceFilter.addEventListener('change', async () => {
          await loadEventsFromApi();
          render();
        });
      }
      if (pillsWrap) {
        pillsWrap.addEventListener('click', async (ev) => {
          const pill = ev.target.closest('[data-pill-category]');
          if (!pill) return;
          const nextCat = pill.getAttribute('data-pill-category') || 'All';
          if (filter.value === nextCat) return;
          filter.value = nextCat;
          syncPillsWithSelect();
          await loadEventsFromApi();
          render();
        });
      }
      if (resetBtn) {
        resetBtn.addEventListener('click', resetAllFilters);
      }
      if (emptyResetBtn) {
        emptyResetBtn.addEventListener('click', resetAllFilters);
      }
    }

    await loadEventsFromApi();
    render();
  }

  /* ---------- Stage 1 Auth: Signup & Login ---------- */
  function initSignup() {
    const form = $('signupForm');
    if (!form || form.dataset.bound === '1') return;
    form.dataset.bound = '1';
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
      const signupDetails = val('signupDetails');
      const organization = val('organization');

      const uiInterests = Array.from(form.querySelectorAll('input[name="interest"]:checked')).map((x) => x.value);
      const backendInterests = mapUiInterestsToBackend(uiInterests);

      if (role === 'participant' && backendInterests.length === 0) {
        return say('Please choose at least one interest to personalize your event feed.');
      }
      if (role === 'participant' && !city) {
        return say('Please enter your preferred city.');
      }
      if (role === 'participant' && !signupDetails) {
        return say('Please enter your college, organization, or major.');
      }
      if (role === 'organizer' && !organization) {
        return say('Please enter your organization, club, or college name.');
      }
      if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
        return say('Password must be at least 8 characters and include at least one letter and one number.');
      }

      if (submitBtn) submitBtn.disabled = true;
      say('Creating your account on EventADDA…', true);

      try {
        const signupBody = {
          full_name: fullName,
          email: email,
          phone: phone,
          password: password,
          role: role
        };
        if (role === 'participant' && signupDetails) {
          signupBody.affiliation_details = signupDetails;
        }
        if (role === 'organizer' && organization) {
          signupBody.organization_name = organization;
        }

        const authRes = await apiRequest('/api/auth/signup', {
          method: 'POST',
          auth: false,
          body: signupBody
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

        form.reset();
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
    if (!form || form.dataset.bound === '1') return;
    form.dataset.bound = '1';
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

  /* ---------- Landing Page Live Featured Events, Dashboards & Event Detail Page ---------- */
  async function initLandingFeatured(user) {
    const grid = $('landingEventGrid');
    const section = $('featured');
    if (!grid) return;

    grid.innerHTML = Array.from({ length: 3 })
      .map(() => '<div class="skeleton-card" aria-hidden="true"></div>')
      .join('');

    try {
      const res = await apiRequest('/api/events?limit=6', { method: 'GET', auth: false });
      const list = Array.isArray(res.events) ? res.events.map(adaptBackendEvent) : [];
      if (list.length === 0) {
        if (section) section.hidden = true;
        return;
      }
      grid.innerHTML = list
        .slice(0, 6)
        .map((e) => cardHTML(e, user, { forYou: userMatchesCategory(user, e.category) }))
        .join('');
    } catch (err) {
      if (section) section.hidden = true;
    }
  }

  function fmtDateTimeISO(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    if (isNaN(d)) return String(isoStr);
    return d.toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
  }

  /* ---------- Stage 3: Razorpay Test Mode Checkout Modal & Bookings (POST /api/registrations/{event_id}) ---------- */
  let razorpayScriptPromise = null;
  function loadRazorpayScript() {
    if (typeof window.Razorpay === 'function') {
      return Promise.resolve(true);
    }
    if (razorpayScriptPromise) {
      return razorpayScriptPromise;
    }
    razorpayScriptPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[src*="checkout.razorpay.com"]');
      if (existing && typeof window.Razorpay === 'function') {
        return resolve(true);
      }
      const script = document.createElement('script');
      script.src = 'https://checkout.razorpay.com/v1/checkout.js';
      script.async = true;
      script.onload = () => resolve(true);
      script.onerror = () => {
        razorpayScriptPromise = null;
        reject(new Error('Failed to load Razorpay Checkout script'));
      };
      document.head.appendChild(script);
    });
    return razorpayScriptPromise;
  }

  async function startRazorpayCheckout(mutationRes, onComplete) {
    const checkout = mutationRes && mutationRes.razorpay_checkout;
    const reg = mutationRes && mutationRes.registration;
    if (!checkout || !reg) {
      if (typeof onComplete === 'function') onComplete(mutationRes);
      return;
    }

    // Branch: If sandbox_mode is enabled (local offline development), open simulated test modal
    if (checkout.sandbox_mode) {
      openRazorpayTestCheckoutModal(mutationRes, onComplete);
      return;
    }

    // Branch: Genuine Razorpay Test Mode flow via official Checkout.js
    try {
      await loadRazorpayScript();
    } catch (err) {
      const errMsg = 'Could not load Razorpay Checkout script. Please verify your internet connection or ad blocker.';
      if (typeof onComplete === 'function') {
        onComplete({
          message: errMsg,
          booking_status: reg.status || 'pending_payment',
          registration: reg
        });
      }
      return;
    }

    if (typeof window.Razorpay !== 'function') {
      const errMsg = 'Razorpay Checkout SDK is not available in the browser.';
      if (typeof onComplete === 'function') {
        onComplete({
          message: errMsg,
          booking_status: reg.status || 'pending_payment',
          registration: reg
        });
      }
      return;
    }

    const expLabel = reg.reservation_expires_at
      ? fmtDateTimeISO(reg.reservation_expires_at)
      : '15 minutes from reservation';

    const options = {
      key: checkout.key_id,
      amount: checkout.amount_paise,
      currency: checkout.currency || 'INR',
      name: 'EventADDA',
      description: checkout.event_title || 'Event Booking',
      order_id: checkout.order_id,
      prefill: {
        name: checkout.participant_name || '',
        email: checkout.participant_email || ''
      },
      notes: {
        registration_id: reg.id || '',
        event_id: reg.event_id || ''
      },
      theme: {
        color: '#6d4aff'
      },
      modal: {
        ondismiss: function () {
          if (typeof onComplete === 'function') {
            onComplete({
              message: 'Checkout window closed. Your 15-minute seat reservation remains active until ' + expLabel + ' — you can resume payment anytime before expiry.',
              booking_status: reg.status || 'pending_payment',
              registration: reg
            });
          }
        }
      },
      handler: async function (response) {
        try {
          const verifyRes = await apiRequest('/api/registrations/' + encodeURIComponent(reg.id) + '/verify-payment', {
            method: 'POST',
            body: {
              razorpay_order_id: response.razorpay_order_id || checkout.order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature
            }
          });
          if (typeof onComplete === 'function') onComplete(verifyRes);
        } catch (err) {
          if (typeof onComplete === 'function') {
            onComplete({
              message: err.message || 'Payment verification failed.',
              booking_status: reg.status || 'pending_payment',
              registration: reg
            });
          }
        }
      }
    };

    try {
      const rzp = new window.Razorpay(options);
      rzp.on('payment.failed', async function (resp) {
        try {
          const errObj = (resp && resp.error) || {};
          const meta = errObj.metadata || {};
          const failedRes = await apiRequest('/api/registrations/' + encodeURIComponent(reg.id) + '/payment-failed', {
            method: 'POST',
            body: {
              razorpay_order_id: meta.order_id || checkout.order_id,
              razorpay_payment_id: meta.payment_id || 'pay_failed_' + Date.now(),
              error_code: errObj.code || 'BAD_REQUEST_ERROR',
              error_description: errObj.description || 'Payment failed at gateway'
            }
          });
          if (typeof onComplete === 'function') onComplete(failedRes);
        } catch (err) {
          if (typeof onComplete === 'function') {
            onComplete({
              message: err.message || 'Payment failed and error could not be recorded.',
              booking_status: reg.status || 'pending_payment',
              registration: reg
            });
          }
        }
      });
      rzp.open();
    } catch (err) {
      if (typeof onComplete === 'function') {
        onComplete({
          message: 'Could not open Razorpay checkout: ' + (err.message || String(err)),
          booking_status: reg.status || 'pending_payment',
          registration: reg
        });
      }
    }
  }

  function openRazorpayTestCheckoutModal(mutationRes, onComplete) {
    const checkout = mutationRes && mutationRes.razorpay_checkout;
    const reg = mutationRes && mutationRes.registration;
    const attempt = mutationRes && mutationRes.payment_attempt;
    if (!checkout || !reg) {
      if (typeof onComplete === 'function') onComplete(mutationRes);
      return;
    }

    const existingModal = $('razorpayTestModal');
    if (existingModal) existingModal.remove();

    const modalWrap = document.createElement('div');
    modalWrap.id = 'razorpayTestModal';
    modalWrap.className = 'rzp-modal-backdrop';
    modalWrap.setAttribute('role', 'dialog');
    modalWrap.setAttribute('aria-modal', 'true');
    modalWrap.setAttribute('aria-labelledby', 'rzpModalTitle');

    const expLabel = reg.reservation_expires_at ? fmtDateTimeISO(reg.reservation_expires_at) : '15 minutes from reservation';
    const attemptNum = attempt ? attempt.attempt_number : 1;
    // Local sandbox only: the backend supplies the simulated payment ID it signed for.
    // In real Razorpay Test Mode no token is issued, so this modal cannot confirm a booking.
    const isSandbox = Boolean(
      checkout.sandbox_mode && checkout.local_test_payment_id && checkout.local_test_signature_Token
    );

    modalWrap.innerHTML =
      '<div class="rzp-modal-card">' +
        '<div class="rzp-modal-header">' +
          '<div>' +
            '<span class="rzp-test-badge">' + (isSandbox ? 'LOCAL SIMULATED CHECKOUT · NO REAL PAYMENT' : 'RAZORPAY TEST MODE') + '</span>' +
            '<h3 id="rzpModalTitle">EventADDA</h3>' +
            '<div style="font-size:13px;opacity:0.86">' + esc(checkout.event_title || 'Event Booking') + '</div>' +
          '</div>' +
          '<div class="rzp-amount-hero">' +
            '<strong>₹' + esc(checkout.amount_inr) + '</strong>' +
            '<span>' + esc(checkout.amount_paise) + ' paise · INR</span>' +
          '</div>' +
        '</div>' +
        '<div class="rzp-modal-body">' +
          '<div class="rzp-order-meta">' +
            '<div><b>Razorpay Order ID:</b> <code>' + esc(checkout.order_id) + '</code></div>' +
            '<div><b>Payment Attempt:</b> #' + esc(attemptNum) + ' · <b>Key:</b> <code>' + esc(checkout.key_id) + '</code></div>' +
            '<div><b>Participant:</b> ' + esc(checkout.participant_name || 'Participant') + (checkout.participant_email ? ' (' + esc(checkout.participant_email) + ')' : '') + '</div>' +
            '<div><b>Seat Hold Expires:</b> ' + esc(expLabel) + '</div>' +
          '</div>' +
          '<div class="rzp-method-tabs" id="rzpMethodTabs">' +
            '<button type="button" class="rzp-method-tab active" data-rzp-method="upi">⚡ UPI (success@razorpay)</button>' +
            '<button type="button" class="rzp-method-tab" data-rzp-method="card">💳 Test Card (4111)</button>' +
            '<button type="button" class="rzp-method-tab" data-rzp-method="netbanking">🏦 Netbanking</button>' +
          '</div>' +
          '<p id="rzpModalMessage" class="form-message" aria-live="polite"></p>' +
          '<div class="rzp-actions-stack">' +
            '<button type="button" id="rzpSimulateSuccessBtn" class="btn btn-rzp-success full-width"' + (isSandbox ? '' : ' disabled') + '>' +
              (isSandbox
                ? '✓ Simulate ₹' + esc(checkout.amount_inr) + ' Payment (Server Verifies Sandbox Signature)'
                : 'Real Razorpay Checkout is not available in this simulated modal') +
            '</button>' +
            '<button type="button" id="rzpSimulateFailBtn" class="btn btn-rzp-danger full-width">' +
              '✕ Simulate Payment Failure (Keep 15m Seat Hold for Retry)' +
            '</button>' +
            '<button type="button" id="rzpDismissBtn" class="btn btn-light full-width">' +
              'Close / Interrupt Checkout (Pay Later within 15m)' +
            '</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.appendChild(modalWrap);

    const tabsWrap = $('rzpMethodTabs');
    if (tabsWrap) {
      tabsWrap.addEventListener('click', (ev) => {
        const tab = ev.target.closest('[data-rzp-method]');
        if (!tab) return;
        Array.from(tabsWrap.querySelectorAll('.rzp-method-tab')).forEach((b) => b.classList.remove('active'));
        tab.classList.add('active');
      });
    }

    const closeModal = (resPayload) => {
      modalWrap.remove();
      if (typeof onComplete === 'function') onComplete(resPayload);
    };

    const successBtn = $('rzpSimulateSuccessBtn');
    const failBtn = $('rzpSimulateFailBtn');
    const dismissBtn = $('rzpDismissBtn');

    if (successBtn) {
      successBtn.addEventListener('click', async () => {
        if (!isSandbox) {
          say('This modal only simulates local sandbox payments. Configure real Razorpay Checkout to pay in Razorpay Test Mode.', false, 'rzpModalMessage');
          return;
        }
        successBtn.disabled = true;
        if (failBtn) failBtn.disabled = true;
        say('Submitting simulated payment for server-side signature verification…', true, 'rzpModalMessage');
        try {
          const verifiedRes = await apiRequest('/api/registrations/' + encodeURIComponent(reg.id) + '/verify-payment', {
            method: 'POST',
            body: {
              razorpay_order_id: checkout.order_id,
              razorpay_payment_id: checkout.local_test_payment_id,
              razorpay_signature: checkout.local_test_signature_Token
            }
          });
          closeModal(verifiedRes);
        } catch (err) {
          say(err.message || 'Payment verification failed.', false, 'rzpModalMessage');
          successBtn.disabled = false;
          if (failBtn) failBtn.disabled = false;
        }
      });
    }

    if (failBtn) {
      failBtn.addEventListener('click', async () => {
        failBtn.disabled = true;
        if (successBtn) successBtn.disabled = true;
        say('Recording failed checkout attempt while preserving your 15-minute seat hold…', false, 'rzpModalMessage');
        try {
          const failedRes = await apiRequest('/api/registrations/' + encodeURIComponent(reg.id) + '/payment-failed', {
            method: 'POST',
            body: {
              razorpay_order_id: checkout.order_id,
              razorpay_payment_id: 'pay_failed_' + Date.now(),
              error_code: 'BAD_REQUEST_ERROR',
              error_description: 'Simulated test payment declined by bank'
            }
          });
          closeModal(failedRes);
        } catch (err) {
          say(err.message || 'Could not record payment failure.', false, 'rzpModalMessage');
          failBtn.disabled = false;
          if (successBtn) successBtn.disabled = false;
        }
      });
    }

    if (dismissBtn) {
      dismissBtn.addEventListener('click', () => {
        closeModal({
          message: 'Checkout interrupted. Your seat remains reserved until ' + expLabel + ' — you can resume payment anytime before expiry.',
          booking_status: reg.status,
          registration: reg
        });
      });
    }
  }

  async function setupParticipantBookings(user) {
    const upcomingSec = $('upcomingBookingsSection');
    const upcomingGrid = $('upcomingBookingsGrid');
    const upcomingCount = $('upcomingConfirmedCount');
    const bookingsList = $('myBookingsList');
    const bookingsEmpty = $('myBookingsEmpty');
    const filterWrap = $('bookingStatusFilters');
    const countBadge = $('myBookingsCountBadge');
    if (!bookingsList) return;

    let activeStatusFilter = 'all';

    const renderBookingBadge = (statusVal, labelText) => {
      const cls = 'status-badge status-badge-' + esc(statusVal || 'confirmed');
      return '<span class="' + cls + '">' + esc(labelText || statusVal) + '</span>';
    };

    const loadBookings = async () => {
      try {
        const querySuffix = activeStatusFilter && activeStatusFilter !== 'all'
          ? '?status=' + encodeURIComponent(activeStatusFilter)
          : '';
        const [allRes, upRes] = await Promise.all([
          apiRequest('/api/registrations/me' + querySuffix, { method: 'GET' }),
          apiRequest('/api/registrations/upcoming', { method: 'GET' })
        ]);

        const bookings = Array.isArray(allRes.registrations) ? allRes.registrations : [];
        const upcoming = Array.isArray(upRes.registrations) ? upRes.registrations : [];

        if (countBadge) {
          countBadge.hidden = bookings.length === 0 && activeStatusFilter === 'all';
          if (activeStatusFilter === 'all') {
            countBadge.textContent = String(bookings.length);
          }
        }

        // Render Upcoming Confirmed Events section
        if (upcomingSec && upcomingGrid) {
          if (upcoming.length === 0) {
            upcomingSec.hidden = true;
            upcomingGrid.innerHTML = '';
          } else {
            upcomingSec.hidden = false;
            if (upcomingCount) {
              upcomingCount.textContent = upcoming.length + (upcoming.length === 1 ? ' Confirmed Event' : ' Confirmed Events');
            }
            upcomingGrid.innerHTML = upcoming.map((reg) => {
              const ev = reg.event || {};
              const dtStr = ev.start_date ? fmtDateTimeISO(ev.start_date) : 'Upcoming';
              return (
                '<article class="upcoming-booking-card">' +
                  '<div>' +
                    '<div class="booking-row-badges">' +
                      renderBookingBadge('confirmed', '✓ Confirmed Seat') +
                      '<span class="tag tag-purple">' + esc(BACKEND_TO_UI_CATEGORY[ev.category] || ev.category || 'Event') + '</span>' +
                    '</div>' +
                    '<h3><a href="event.html?id=' + encodeURIComponent(reg.event_id) + '">' + esc(ev.title || 'Event') + '</a></h3>' +
                    '<div class="booking-row-meta">📅 ' + esc(dtStr) + '</div>' +
                    '<div class="booking-row-meta">📍 ' + esc(ev.venue_name ? ev.venue_name + ', ' : '') + esc(ev.city || 'Online') + ' · ' + esc(ev.mode || 'In-person') + '</div>' +
                    '<div class="fine-print" style="margin-top:6px">🔔 24-hour automated reminder scheduled</div>' +
                  '</div>' +
                  '<div class="booking-actions-row">' +
                    '<a class="btn btn-light" href="event.html?id=' + encodeURIComponent(reg.event_id) + '">View Event →</a>' +
                    (reg.can_cancel
                      ? '<button type="button" class="btn btn-rzp-danger" data-cancel-reg="' + esc(reg.id) + '">Cancel Booking</button>'
                      : '') +
                  '</div>' +
                '</article>'
              );
            }).join('');
          }
        }

        // Render My Bookings history list
        if (bookings.length === 0) {
          bookingsList.innerHTML = '';
          if (bookingsEmpty) bookingsEmpty.hidden = false;
        } else {
          if (bookingsEmpty) bookingsEmpty.hidden = true;
          bookingsList.innerHTML = bookings.map((reg) => {
            const ev = reg.event || {};
            const uiCat = BACKEND_TO_UI_CATEGORY[ev.category] || ev.category || 'Event';
            const priceLabel = reg.price_type === 'paid' && reg.price_amount > 0
              ? '₹' + esc(reg.price_amount) + ' (Paid)'
              : 'Free Entry';
            const pay = reg.latest_payment;
            const paySummaryHtml = pay
              ? '<div class="booking-payment-summary">' +
                  '<span><b>Payment Attempt #' + esc(pay.attempt_number) + ':</b></span>' +
                  renderBookingBadge(pay.status, pay.status_label) +
                  '<span>Order: <code>' + esc(pay.razorpay_order_id) + '</code></span>' +
                  (pay.razorpay_payment_id ? '<span>Payment ID: <code>' + esc(pay.razorpay_payment_id) + '</code></span>' : '') +
                  (pay.failure_reason ? '<span>· ' + esc(pay.failure_reason) + '</span>' : '') +
                '</div>'
              : '';

            const holdExpiryNote = reg.status === 'pending_payment' && reg.reservation_expires_at
              ? '<div class="booking-row-meta" style="color:#b45309;font-weight:700">⏳ 15m Seat Hold expires: ' + esc(fmtDateTimeISO(reg.reservation_expires_at)) + '</div>'
              : '';

            const cancelNote = reg.status === 'cancelled' && reg.cancellation_reason
              ? '<div class="booking-row-meta">Reason: ' + esc(reg.cancellation_reason) + '</div>'
              : '';

            const resolutionNote = reg.status === 'resolution_required' && reg.resolution_reason
              ? '<div class="booking-row-meta" style="color:#b91c1c;font-weight:600">⚠ ' + esc(reg.resolution_reason) + '</div>'
              : '';

            const showReconcile = Boolean(
              pay && (reg.status === 'pending_payment' || reg.status === 'resolution_required' || pay.status === 'pending')
            );

            return (
              '<article class="booking-row-card" data-reg-id="' + esc(reg.id) + '" data-booking-status-item="' + esc(reg.status) + '">' +
                '<div class="booking-row-main">' +
                  '<div class="booking-row-badges">' +
                    renderBookingBadge(reg.status, reg.status_label) +
                    '<span class="tag tag-purple">' + esc(uiCat) + '</span>' +
                    '<span class="tag ' + (reg.price_type === 'paid' ? 'tag-orange' : 'tag-green') + '">' + priceLabel + '</span>' +
                  '</div>' +
                  '<h3 class="booking-row-title"><a href="event.html?id=' + encodeURIComponent(reg.event_id) + '">' + esc(ev.title || 'Event #' + reg.event_id) + '</a></h3>' +
                  '<div class="booking-row-meta">' +
                    '📅 ' + esc(ev.start_date ? fmtDateTimeISO(ev.start_date) : '—') +
                    ' · 📍 ' + esc(ev.venue_name ? ev.venue_name + ', ' : '') + esc(ev.city || 'Online') +
                  '</div>' +
                  holdExpiryNote +
                  cancelNote +
                  resolutionNote +
                  paySummaryHtml +
                '</div>' +
                '<div class="booking-row-actions">' +
                  (reg.can_retry_payment
                    ? '<button type="button" class="btn btn-primary" data-retry-payment="' + esc(reg.id) + '">Pay ₹' + esc(reg.price_amount) + ' / Retry →</button>'
                    : '') +
                  (showReconcile
                    ? '<button type="button" class="btn btn-light" data-reconcile-payment="' + esc(reg.id) + '">↻ Reconcile Status</button>'
                    : '') +
                  (reg.can_cancel
                    ? '<button type="button" class="btn btn-rzp-danger" data-cancel-reg="' + esc(reg.id) + '">Cancel Booking</button>'
                    : '') +
                  '<a class="btn btn-light" href="event.html?id=' + encodeURIComponent(reg.event_id) + '">Event Details →</a>' +
                '</div>' +
              '</article>'
            );
          }).join('');
        }
      } catch (err) {
        say(err.message || 'Could not load your bookings.', false, 'bookingsActionMessage');
      }
    };

    const handleBookingActionClick = async (ev) => {
      const retryBtn = ev.target.closest('[data-retry-payment]');
      const reconcileBtn = ev.target.closest('[data-reconcile-payment]');
      const cancelBtn = ev.target.closest('[data-cancel-reg]');

      if (retryBtn) {
        const regId = retryBtn.getAttribute('data-retry-payment');
        retryBtn.disabled = true;
        say('Creating Razorpay Test Mode payment order…', true, 'bookingsActionMessage');
        try {
          const orderRes = await apiRequest('/api/registrations/' + encodeURIComponent(regId) + '/payment-order', {
            method: 'POST'
          });
          startRazorpayCheckout(orderRes, async (finalRes) => {
            if (finalRes && finalRes.message) {
              say(finalRes.message, finalRes.booking_status === 'confirmed', 'bookingsActionMessage');
            }
            await loadBookings();
          });
        } catch (err) {
          say(err.message || 'Could not initiate payment retry.', false, 'bookingsActionMessage');
        } finally {
          retryBtn.disabled = false;
        }
      }

      if (reconcileBtn) {
        const regId = reconcileBtn.getAttribute('data-reconcile-payment');
        reconcileBtn.disabled = true;
        say('Reconciling authoritative payment status with server…', true, 'bookingsActionMessage');
        try {
          const recRes = await apiRequest('/api/registrations/' + encodeURIComponent(regId) + '/reconcile', {
            method: 'POST',
            body: {}
          });
          say(recRes.message || 'Status reconciled.', recRes.booking_status === 'confirmed', 'bookingsActionMessage');
          await loadBookings();
        } catch (err) {
          say(err.message || 'Could not reconcile payment status.', false, 'bookingsActionMessage');
        } finally {
          reconcileBtn.disabled = false;
        }
      }

      if (cancelBtn) {
        const regId = cancelBtn.getAttribute('data-cancel-reg');
        if (!confirm('Cancel this booking? Your seat will be released and future reminders suppressed. Note: Cancellation does not perform or imply a payment refund.')) {
          return;
        }
        cancelBtn.disabled = true;
        say('Cancelling booking…', true, 'bookingsActionMessage');
        try {
          const cancelRes = await apiRequest('/api/registrations/' + encodeURIComponent(regId) + '/cancel', {
            method: 'POST',
            body: { reason: 'Cancelled by participant from dashboard' }
          });
          say(cancelRes.message || 'Booking cancelled.', true, 'bookingsActionMessage');
          await loadBookings();
          setupListing(user);
        } catch (err) {
          say(err.message || 'Could not cancel booking.', false, 'bookingsActionMessage');
        } finally {
          cancelBtn.disabled = false;
        }
      }
    };

    if (filterWrap && !filterWrap.dataset.bound) {
      filterWrap.dataset.bound = '1';
      filterWrap.addEventListener('click', async (ev) => {
        const pill = ev.target.closest('[data-booking-status]');
        if (!pill) return;
        const nextStatus = pill.getAttribute('data-booking-status') || 'all';
        activeStatusFilter = nextStatus;
        Array.from(filterWrap.querySelectorAll('[data-booking-status]')).forEach((btn) => {
          btn.classList.toggle('active', btn.getAttribute('data-booking-status') === nextStatus);
        });
        await loadBookings();
      });
    }

    if (bookingsList && !bookingsList.dataset.bound) {
      bookingsList.dataset.bound = '1';
      bookingsList.addEventListener('click', handleBookingActionClick);
    }
    if (upcomingGrid && !upcomingGrid.dataset.bound) {
      upcomingGrid.dataset.bound = '1';
      upcomingGrid.addEventListener('click', handleBookingActionClick);
    }

    await loadBookings();
  }

  function initParticipantDashboard(user) {
    if (!user || user.role !== 'participant') {
      location.replace('login-participant.html');
      return;
    }
    if ($('userName')) $('userName').textContent = user.full_name;
    renderProfileAndOnboardingPanel(user);
    setupParticipantBookings(user);
    setupListing(user);
  }

  async function initOrganizerDashboard(user) {
    if (!user || user.role !== 'organizer') {
      location.replace('login-organizer.html');
      return;
    }
    if ($('userName')) $('userName').textContent = user.full_name;
    renderProfileAndOnboardingPanel(user);

    const form = $('eventForm'), mine = $('myEvents'), others = $('otherEvents');
    if (!form || !mine || !others) return;

    // Ensure Free/Paid pricing fields exist and toggle visibility cleanly
    const formGrid = form.querySelector('.form-grid');
    if (formGrid && !$('evPriceType')) {
      const ptField = document.createElement('div');
      ptField.className = 'field';
      ptField.innerHTML =
        '<label for="evPriceType">Event pricing</label>' +
        '<select id="evPriceType" required>' +
          '<option value="free">Free</option>' +
          '<option value="paid">Paid</option>' +
        '</select>';
      const paField = document.createElement('div');
      paField.className = 'field';
      paField.id = 'evPriceAmountField';
      paField.hidden = true;
      paField.innerHTML =
        '<label for="evPriceAmount">Price in INR (₹)</label>' +
        '<input id="evPriceAmount" type="number" min="1" step="0.01" placeholder="e.g. 499">';
      formGrid.appendChild(ptField);
      formGrid.appendChild(paField);
    }

    const syncPriceFieldVisibility = () => {
      const ptSelect = $('evPriceType');
      const paInput = $('evPriceAmount');
      const paWrap = $('evPriceAmountField');
      if (!ptSelect || !paInput) return;
      const isPaid = ptSelect.value === 'paid';
      if (paWrap) paWrap.hidden = !isPaid;
      paInput.disabled = !isPaid;
      paInput.required = isPaid;
      if (!isPaid) paInput.value = '';
    };

    if ($('evPriceType') && !$('evPriceType').dataset.bound) {
      $('evPriceType').dataset.bound = '1';
      $('evPriceType').addEventListener('change', syncPriceFieldVisibility);
    }
    syncPriceFieldVisibility();

    let editingId = null;
    let myEventsCache = [];

    const draw = async () => {
      try {
        const [myRes, pubRes] = await Promise.all([
          apiRequest('/api/organizer/events?limit=50', { method: 'GET' }),
          apiRequest('/api/events?limit=50', { method: 'GET', auth: false })
        ]);
        const myRaw = Array.isArray(myRes.events) ? myRes.events : [];
        const pubRaw = Array.isArray(pubRes.events) ? pubRes.events : [];

        myEventsCache = myRaw.filter((e) => e.status !== 'cancelled').map(adaptBackendEvent);
        const otherList = pubRaw
          .filter((e) => e.organizer_id !== user.id)
          .map(adaptBackendEvent)
          .sort(byDate);

        mine.innerHTML = myEventsCache.map((e) => cardHTML(e, user, { manage: true })).join('');
        others.innerHTML = otherList.map((e) => cardHTML(e, user)).join('');

        if ($('myEmpty')) {
          $('myEmpty').hidden = myEventsCache.length > 0;
          $('myEmpty').textContent = 'You have not published any events yet. Use the form above to publish your first one.';
        }
        if ($('otherEmpty')) {
          $('otherEmpty').hidden = otherList.length > 0;
        }
      } catch (err) {
        say(err.message || 'Could not load events from backend.', false);
      }
    };

    const setMode = (editing) => {
      if ($('formTitle')) $('formTitle').textContent = editing ? 'Edit your event' : 'Publish a new event';
      if ($('submitBtn')) $('submitBtn').textContent = editing ? 'Save changes →' : 'Publish event →';
      if ($('cancelWrap')) $('cancelWrap').hidden = !editing;
      if ($('evDate')) {
        if (editing) $('evDate').removeAttribute('min');
        else $('evDate').min = todayISO();
      }
    };

    const resetForm = () => {
      form.reset();
      editingId = null;
      syncPriceFieldVisibility();
      setMode(false);
    };

    const startEdit = (id) => {
      const e = myEventsCache.find((x) => x.id === id);
      if (!e) return;
      editingId = id;
      $('evTitle').value = e.title;
      $('evCategory').value = e.category;
      $('evDate').value = e.date;
      $('evTime').value = e.time || '10:00';
      $('evMode').value = e.mode || 'In-person';
      $('evCity').value = e.city;
      $('evVenue').value = e.venue || '';
      $('evDesc').value = e.description || '';
      $('evDetails').value = e.details || '';
      if ($('evFormUrl')) $('evFormUrl').value = e.formUrl || '';
      if ($('evPriceType') && $('evPriceAmount')) {
        $('evPriceType').value = e.priceType || 'free';
        syncPriceFieldVisibility();
        if (e.priceType === 'paid' && e.priceAmount != null) {
          $('evPriceAmount').value = String(e.priceAmount);
        }
      }
      setMode(true);
      say('');
      form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    if (!form.dataset.bound) {
      form.dataset.bound = '1';
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const submitBtn = $('submitBtn');
        const v = (id) => ($(id) ? $(id).value.trim() : '');
        const title = v('evTitle');
        const category = $('evCategory') ? $('evCategory').value : 'Hackathon';
        const dateVal = v('evDate');
        const timeVal = v('evTime') || '10:00';
        const modeVal = $('evMode') ? $('evMode').value : 'In-person';
        const cityVal = v('evCity');
        const venueVal = v('evVenue') || cityVal;
        const shortDesc = v('evDesc');
        const fullDetails = v('evDetails');
        const formUrl = v('evFormUrl');
        const priceType = $('evPriceType') ? $('evPriceType').value : 'free';
        const rawPriceAmt = $('evPriceAmount') && $('evPriceAmount').value !== ''
          ? Number($('evPriceAmount').value)
          : null;

        if (priceType === 'paid' && (rawPriceAmt === null || isNaN(rawPriceAmt) || rawPriceAmt <= 0)) {
          return say('Please enter a valid positive INR price for paid events.', false);
        }

        const combinedDescription = fullDetails ? (shortDesc + '\n\n' + fullDetails) : shortDesc;
        if (combinedDescription.length < 10) {
          return say('Please provide a description of at least 10 characters.', false);
        }

        const startDateObj = new Date(dateVal + 'T' + timeVal + ':00');
        if (isNaN(startDateObj)) {
          return say('Please enter a valid event date and start time.', false);
        }
        const endDateObj = new Date(startDateObj.getTime() + 2 * 60 * 60 * 1000);

        const payload = {
          title: title,
          description: combinedDescription,
          category: category,
          venue: {
            name: venueVal,
            address: venueVal,
            city: cityVal
          },
          mode: modeVal,
          start_date: startDateObj.toISOString(),
          end_date: endDateObj.toISOString(),
          registration_deadline: startDateObj.toISOString(),
          price_type: priceType,
          price_amount: priceType === 'paid' ? rawPriceAmt : null
        };
        if ($('evFormUrl')) {
          payload.registration_url = formUrl || null;
        }

        if (submitBtn) submitBtn.disabled = true;
        say(editingId ? 'Saving changes…' : 'Publishing event to MongoDB…', true);

        try {
          if (editingId) {
            await apiRequest('/api/organizer/events/' + encodeURIComponent(editingId), {
              method: 'PUT',
              body: payload
            });
            say('Event updated successfully!', true);
          } else {
            payload.status = 'published';
            payload.max_capacity = 200;
            await apiRequest('/api/organizer/events', {
              method: 'POST',
              body: payload
            });
            say('Event published! It is now stored in MongoDB and visible across EventADDA.', true);
          }
          resetForm();
          await draw();
        } catch (err) {
          say(err.message || 'Could not save event.', false);
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });

      if ($('cancelEdit')) {
        $('cancelEdit').addEventListener('click', () => {
          resetForm();
          say('');
        });
      }

      mine.addEventListener('click', async (ev) => {
        const pub = ev.target.closest('[data-publish]');
        const edit = ev.target.closest('[data-edit]');
        const del = ev.target.closest('[data-delete]');
        if (pub) {
          try {
            await apiRequest('/api/organizer/events/' + encodeURIComponent(pub.dataset.publish) + '/publish', {
              method: 'PATCH'
            });
            say('Draft event published!', true);
            await draw();
          } catch (err) {
            say(err.message || 'Could not publish event.', false);
          }
        }
        if (edit) {
          startEdit(edit.dataset.edit);
        }
        if (del && confirm('Cancel this event? Cancelled events are removed from public discovery.')) {
          try {
            await apiRequest('/api/organizer/events/' + encodeURIComponent(del.dataset.delete) + '/cancel', {
              method: 'PATCH'
            });
            if (editingId === del.dataset.delete) resetForm();
            say('Event cancelled.', true);
            await draw();
          } catch (err) {
            say(err.message || 'Could not cancel event.', false);
          }
        }
      });
    }

    setMode(false);
    await draw();
    const editParam = new URLSearchParams(location.search).get('edit');
    if (editParam) startEdit(editParam);
  }

  async function initEventPage(user) {
    const box = $('eventDetail');
    if (!box) return;
    const eventId = new URLSearchParams(location.search).get('id');
    if (!eventId) {
      box.innerHTML =
        '<section class="auth-card auth-card-wide">' +
          '<h1>Event not found</h1>' +
          '<a class="btn btn-light full-width" href="events.html">Back to events</a>' +
        '</section>';
      return;
    }

    let e = null;
    try {
      const evData = await apiRequest('/api/events/' + encodeURIComponent(eventId), {
        method: 'GET'
      });
      e = adaptBackendEvent(evData);
    } catch (err) {
      box.innerHTML =
        '<section class="auth-card auth-card-wide">' +
          '<h1>Event not found</h1>' +
          '<p class="muted">' + esc(err.message || 'This event may have been removed or cancelled.') + '</p>' +
          '<a class="btn btn-light full-width" href="events.html">Back to events</a>' +
        '</section>';
      return;
    }

    const c = catInfo(e.category);
    const own = Boolean(user && user.role === 'organizer' && e.organizerId === user.id);

    const pctFilled = e.maxCapacity > 0
      ? Math.min(100, Math.round((e.registeredCount / e.maxCapacity) * 100))
      : 100;
    const isSoldOut = e.spotsRemaining <= 0;
    const deadlinePassed = new Date(e.registrationDeadline) <= new Date();

    const capacityMeterHtml =
      '<div class="capacity-meter-box">' +
        '<div class="capacity-meter-top">' +
          '<span>🎟 Seat Availability: <strong>' + (isSoldOut ? 'SOLD OUT' : (esc(e.spotsRemaining) + ' of ' + esc(e.maxCapacity) + ' seats remaining')) + '</strong></span>' +
          '<span>' + esc(e.registeredCount) + ' booked / held</span>' +
        '</div>' +
        '<div class="capacity-bar-track">' +
          '<div class="capacity-bar-fill' + (isSoldOut ? ' sold-out' : '') + '" style="width:' + pctFilled + '%"></div>' +
        '</div>' +
        '<div class="fine-print" style="margin-top:6px">Registration deadline: ' + esc(fmtDateTimeISO(e.registrationDeadline)) + '</div>' +
      '</div>';

    const secondaryExtHtml = e.formUrl
      ? '<div style="margin-top:10px">' +
          '<a class="text-link" id="externalRegisterBtn" href="' + esc(e.formUrl) + '" target="_blank" rel="noopener noreferrer">' +
            'Organizer supplemental link / external form ↗' +
          '</a>' +
        '</div>'
      : '';

    let actionHtml = '';
    if (!user) {
      actionHtml =
        '<a class="btn btn-primary full-width" href="login-participant.html">Log in as a participant to book your seat →</a>' +
        '<p class="fine-print">Participant accounts can book seats directly on EventADDA with instant confirmation or Razorpay Test Mode checkout.</p>' +
        secondaryExtHtml;
    } else if (user.role === 'participant') {
      const myReg = e.myRegistration;
      const regStatus = myReg ? myReg.status : null;
      const latestPay = myReg ? myReg.latest_payment : null;

      if (regStatus === 'confirmed') {
        actionHtml =
          '<div class="booking-state-box confirmed" id="participantBookingCard">' +
            '<div class="booking-state-header">' +
              '<span class="status-badge status-badge-confirmed">✓ Booking Confirmed</span>' +
              '<span class="fine-print">Booking ID: <code>' + esc(myReg.id) + '</code></span>' +
            '</div>' +
            '<p style="margin:4px 0 6px;font-weight:600;color:#14532d">' +
              'Your seat is confirmed! A confirmation email and an automated reminder 24 hours before the event are scheduled.' +
            '</p>' +
            (latestPay && latestPay.razorpay_payment_id
              ? '<div class="fine-print">Paid ₹' + esc(myReg.price_amount) + ' · Razorpay Payment ID: <code>' + esc(latestPay.razorpay_payment_id) + '</code></div>'
              : '') +
            '<div class="booking-actions-row">' +
              '<a class="btn btn-light" href="dashboard-participant.html#myBookingsSection">View in My Bookings →</a>' +
              (myReg.can_cancel
                ? '<button class="btn btn-rzp-danger" type="button" id="cancelEventBookingBtn" data-reg-id="' + esc(myReg.id) + '">Cancel Booking</button>'
                : '<span class="fine-print">Cancellation deadline has passed.</span>') +
            '</div>' +
          '</div>' +
          '<p id="regMessage" class="form-message" aria-live="polite"></p>' +
          secondaryExtHtml;
      } else if (regStatus === 'pending_payment') {
        const isPayPending = Boolean(latestPay && latestPay.status === 'pending');
        actionHtml =
          '<div class="booking-state-box pending_payment" id="participantBookingCard">' +
            '<div class="booking-state-header">' +
              '<span class="status-badge status-badge-pending_payment">⏳ Seat Reserved — Payment Pending</span>' +
              (myReg.reservation_expires_at
                ? '<span class="fine-print">Hold expires: <strong>' + esc(fmtDateTimeISO(myReg.reservation_expires_at)) + '</strong></span>'
                : '') +
            '</div>' +
            '<p style="margin:4px 0 8px;color:#78350f">' +
              (isPayPending
                ? 'Your payment attempt is currently awaiting authoritative gateway confirmation. Your seat remains held while we reconcile.'
                : 'Your seat is held for 15 minutes. Complete Razorpay Test Mode checkout to confirm your booking.') +
            '</p>' +
            (latestPay
              ? '<div class="fine-print">Latest Attempt #' + esc(latestPay.attempt_number) + ': <strong>' + esc(latestPay.status_label) + '</strong> (Order <code>' + esc(latestPay.razorpay_order_id) + '</code>)</div>'
              : '') +
            '<div class="booking-actions-row">' +
              (myReg.can_retry_payment
                ? '<button class="btn btn-primary" type="button" id="retryEventPaymentBtn" data-reg-id="' + esc(myReg.id) + '">Complete / Retry Payment (₹' + esc(myReg.price_amount) + ') →</button>'
                : '') +
              '<button class="btn btn-light" type="button" id="reconcileEventPaymentBtn" data-reg-id="' + esc(myReg.id) + '">↻ Reconcile Payment Status</button>' +
              (myReg.can_cancel
                ? '<button class="btn btn-rzp-danger" type="button" id="cancelEventBookingBtn" data-reg-id="' + esc(myReg.id) + '">Cancel Reservation</button>'
                : '') +
            '</div>' +
          '</div>' +
          '<p id="regMessage" class="form-message" aria-live="polite"></p>' +
          secondaryExtHtml;
      } else if (regStatus === 'resolution_required') {
        actionHtml =
          '<div class="booking-state-box resolution_required" id="participantBookingCard">' +
            '<div class="booking-state-header">' +
              '<span class="status-badge status-badge-resolution_required">⚠ Payment Resolution Required</span>' +
              '<span class="fine-print">Booking ID: <code>' + esc(myReg.id) + '</code></span>' +
            '</div>' +
            '<p style="margin:4px 0 8px;color:#991b1b">' +
              esc(myReg.resolution_reason || 'This booking has a payment record requiring manual organizer resolution.') +
            '</p>' +
            '<div class="booking-actions-row">' +
              '<button class="btn btn-light" type="button" id="reconcileEventPaymentBtn" data-reg-id="' + esc(myReg.id) + '">↻ Reconcile Status</button>' +
              '<a class="btn btn-light" href="dashboard-participant.html#myBookingsSection">View in My Bookings →</a>' +
            '</div>' +
          '</div>' +
          '<p id="regMessage" class="form-message" aria-live="polite"></p>' +
          secondaryExtHtml;
      } else {
        const prevHistoryNote = myReg && (regStatus === 'cancelled' || regStatus === 'expired')
          ? '<div class="fine-print" style="margin-bottom:8px">Previous booking status: <strong>' + esc(myReg.status_label) + '</strong>' +
            (latestPay ? ' · <button type="button" class="text-link" id="reconcileEventPaymentBtn" data-reg-id="' + esc(myReg.id) + '" style="background:none;border:none;padding:0;cursor:pointer">Reconcile previous payment</button>' : '') +
            '</div>'
          : '';

        let primaryBtnHtml = '';
        if (e.status !== 'published') {
          primaryBtnHtml = '<button class="btn btn-light full-width" type="button" disabled>Registration Closed (Event ' + esc(e.status) + ')</button>';
        } else if (deadlinePassed) {
          primaryBtnHtml = '<button class="btn btn-light full-width" type="button" disabled>Registration Deadline Passed</button>';
        } else if (isSoldOut) {
          primaryBtnHtml = '<button class="btn btn-light full-width" type="button" disabled>Sold Out — No Seats Remaining</button>';
        } else if (e.priceType === 'paid' && e.priceAmount > 0) {
          primaryBtnHtml =
            '<button class="btn btn-primary full-width" id="inAppRegisterBtn" type="button">' +
              'Book Seat &amp; Pay ₹' + esc(e.priceAmount) + ' (Razorpay Test Mode) →' +
            '</button>' +
            '<p class="fine-print">Reserves 1 seat for 15 minutes while you complete Razorpay Test Mode checkout.</p>';
        } else {
          primaryBtnHtml =
            '<button class="btn btn-primary full-width" id="inAppRegisterBtn" type="button">' +
              'Register Now (Free Entry) →' +
            '</button>' +
            '<p class="fine-print">Instant seat confirmation with automated email acknowledgement and 24-hour event reminder.</p>';
        }

        actionHtml =
          prevHistoryNote +
          primaryBtnHtml +
          '<p id="regMessage" class="form-message" aria-live="polite"></p>' +
          secondaryExtHtml;
      }
    } else if (own) {
      actionHtml = '<a class="btn btn-light full-width" href="dashboard-organizer.html?edit=' + encodeURIComponent(e.id) + '">Edit in dashboard →</a>';
    } else {
      actionHtml =
        '<div class="demo-notice">Organizer accounts can view events, but only participant accounts can register for events.</div>';
    }

    box.innerHTML =
      '<section class="auth-card auth-card-wide">' +
        '<span class="tag tag-' + c.tone + '">' + esc(e.category) + '</span>' +
        priceBadgeHTML(e) +
        '<h1>' + esc(e.title) + '</h1>' +
        '<p class="muted">Organized by ' + esc(e.organizerName) + '</p>' +
        '<div class="event-meta">📅 ' + esc(fmtDate(e.date)) + (e.time ? ' · ⏰ ' + esc(fmtTime(e.time)) : '') + '</div>' +
        '<div class="event-meta">📍 ' + esc(e.venue ? e.venue + ', ' : '') + esc(e.city) + ' · ' + esc(e.mode) + '</div>' +
        capacityMeterHtml +
        '<fieldset><legend>About this event</legend><p>' + esc(e.description) + '</p></fieldset>' +
        (e.details ? '<fieldset><legend>Details</legend><p class="pre">' + esc(e.details) + '</p></fieldset>' : '') +
        '<div class="stack">' + actionHtml + '</div>' +
      '</section>';

    const regBtn = $('inAppRegisterBtn');
    if (regBtn) {
      regBtn.addEventListener('click', async () => {
        regBtn.disabled = true;
        say(
          e.priceType === 'paid'
            ? 'Reserving your seat for 15 minutes and preparing Razorpay Test Mode order…'
            : 'Confirming your free registration…',
          true,
          'regMessage'
        );
        try {
          const mutRes = await apiRequest('/api/registrations/' + encodeURIComponent(e.id), {
            method: 'POST',
            body: {}
          });
          if (mutRes.razorpay_checkout) {
            startRazorpayCheckout(mutRes, async (finalRes) => {
              await initEventPage(user);
              if (finalRes && finalRes.message) {
                say(finalRes.message, finalRes.booking_status === 'confirmed', 'regMessage');
              }
            });
          } else {
            await initEventPage(user);
            say(mutRes.message || 'Booking confirmed!', true, 'regMessage');
          }
        } catch (err) {
          say(err.message || 'Could not complete registration.', false, 'regMessage');
          regBtn.disabled = false;
        }
      });
    }

    const retryBtn = $('retryEventPaymentBtn');
    if (retryBtn) {
      retryBtn.addEventListener('click', async () => {
        const regId = retryBtn.getAttribute('data-reg-id');
        retryBtn.disabled = true;
        say('Creating new Razorpay Test Mode payment order…', true, 'regMessage');
        try {
          const orderRes = await apiRequest('/api/registrations/' + encodeURIComponent(regId) + '/payment-order', {
            method: 'POST'
          });
          startRazorpayCheckout(orderRes, async (finalRes) => {
            await initEventPage(user);
            if (finalRes && finalRes.message) {
              say(finalRes.message, finalRes.booking_status === 'confirmed', 'regMessage');
            }
          });
        } catch (err) {
          say(err.message || 'Could not start payment retry.', false, 'regMessage');
          retryBtn.disabled = false;
        }
      });
    }

    const reconcileBtn = $('reconcileEventPaymentBtn');
    if (reconcileBtn) {
      reconcileBtn.addEventListener('click', async () => {
        const regId = reconcileBtn.getAttribute('data-reg-id');
        reconcileBtn.disabled = true;
        say('Reconciling payment status with server…', true, 'regMessage');
        try {
          const recRes = await apiRequest('/api/registrations/' + encodeURIComponent(regId) + '/reconcile', {
            method: 'POST',
            body: {}
          });
          await initEventPage(user);
          say(recRes.message || 'Status reconciled.', recRes.booking_status === 'confirmed', 'regMessage');
        } catch (err) {
          say(err.message || 'Could not reconcile payment.', false, 'regMessage');
          reconcileBtn.disabled = false;
        }
      });
    }

    const cancelBtn = $('cancelEventBookingBtn');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', async () => {
        const regId = cancelBtn.getAttribute('data-reg-id');
        if (!confirm('Cancel this booking? Your seat will be released and future reminders suppressed. Note: Cancellation does not perform or imply a payment refund.')) {
          return;
        }
        cancelBtn.disabled = true;
        say('Cancelling booking…', true, 'regMessage');
        try {
          const cancelRes = await apiRequest('/api/registrations/' + encodeURIComponent(regId) + '/cancel', {
            method: 'POST',
            body: { reason: 'Cancelled by participant on event page' }
          });
          await initEventPage(user);
          say(cancelRes.message || 'Booking cancelled.', true, 'regMessage');
        } catch (err) {
          say(err.message || 'Could not cancel booking.', false, 'regMessage');
          cancelBtn.disabled = false;
        }
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
      $('eventsStatusBanner').dataset.sessionError = '1';
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
    } else if ($('landingEventGrid')) {
      initLandingFeatured(verifiedUser);
    }
  });
})();
