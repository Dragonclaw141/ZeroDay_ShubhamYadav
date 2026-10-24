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

  function initParticipantDashboard(user) {
    if (!user || user.role !== 'participant') {
      location.replace('login-participant.html');
      return;
    }
    if ($('userName')) $('userName').textContent = user.full_name;
    renderProfileAndOnboardingPanel(user);
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
      $('evFormUrl').value = e.formUrl || '';
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
          price_amount: priceType === 'paid' ? rawPriceAmt : null,
          registration_url: formUrl || null
        };

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
    let actionHtml;
    if (!user) {
      actionHtml =
        '<a class="btn btn-primary full-width" href="login-participant.html">Log in as a participant to register →</a>' +
        '<p class="fine-print">Registration and any event fee payment happen on the organizer\'s external form after logging in.</p>';
    } else if (user.role === 'participant') {
      const extBtn = e.formUrl
        ? '<a class="btn btn-primary full-width" id="externalRegisterBtn" href="' + esc(e.formUrl) + '" target="_blank" rel="noopener noreferrer">Register via Organizer\'s External Form ↗</a>' +
          '<p class="fine-print">Registration and any payment (for paid events) happen directly on the organizer\'s external form. EventADDA does not process payments or mark external form opens as completed registrations.</p>'
        : '<div class="demo-notice">The organizer has not provided an external registration link for this event yet.</div>';
      actionHtml =
        extBtn +
        '<p id="regMessage" class="form-message" aria-live="polite"></p>' +
        '<p class="fine-print">In-app event registration (POST /api/registrations/{event_id}) is scheduled for Stage 3.</p>';
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
        '<fieldset><legend>About this event</legend><p>' + esc(e.description) + '</p></fieldset>' +
        (e.details ? '<fieldset><legend>Details</legend><p class="pre">' + esc(e.details) + '</p></fieldset>' : '') +
        '<div class="stack">' + actionHtml + '</div>' +
      '</section>';

    const regBtn = $('stage3RegisterBtn');
    if (regBtn) {
      regBtn.addEventListener('click', () => {
        say(
          'In-app registration is not yet available in Stage 2: POST /api/registrations/{event_id} will be enabled in Stage 3.',
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
