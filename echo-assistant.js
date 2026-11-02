(() => {
  'use strict';

  const root = document.getElementById('echo-assistant');
  if (!root) return;
  const panel = document.getElementById('echo-panel');
  const orb = document.getElementById('echo-orb');
  const status = document.getElementById('echo-status');
  const userCaption = document.getElementById('echo-user-caption');
  const replyCaption = document.getElementById('echo-reply-caption');
  const form = document.getElementById('echo-form');
  const input = document.getElementById('echo-input');
  const muteButton = document.getElementById('echo-mute');
  const speechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let muted = false;
  let listening = false;
  let activeRequest = null;
  let requestNumber = 0;
  let speechNumber = 0;
  let memorySession = null;
  let recognitionStartedAt = null;
  let speechEndedAt = null;
  let availableVoices = 'speechSynthesis' in window ? window.speechSynthesis.getVoices() : [];

  if ('speechSynthesis' in window) {
    window.speechSynthesis.addEventListener('voiceschanged', () => {
      availableVoices = window.speechSynthesis.getVoices();
    });
  }

  function preferredEnglishVoice() {
    if (!availableVoices.length && 'speechSynthesis' in window) availableVoices = window.speechSynthesis.getVoices();
    const english = availableVoices.filter(voice => /^en(?:-|$)/i.test(voice.lang || ''));
    // Prefer voices whose supplied system name explicitly identifies a feminine voice.
    const femaleName = /female|woman|zira|samantha|karen|heera|priya|veena|moira|tessa|susan|sara|salli|aria|jenny|libby|sonia|neerja/i;
    return english.find(voice => femaleName.test(voice.name || ''))
      || english.find(voice => /en-in/i.test(voice.lang || ''))
      || english[0]
      || null;
  }

  function sessionId() {
    let id = null;
    try { id = sessionStorage.getItem('echoVisitorSession'); } catch (_) { /* Private contexts may block storage. */ }
    if (!id) id = memorySession;
    if (!id) {
      id = window.crypto && crypto.randomUUID
        ? crypto.randomUUID()
        : (window.crypto && crypto.getRandomValues
            ? Array.from(crypto.getRandomValues(new Uint8Array(24)), n => n.toString(16).padStart(2, '0')).join('')
            : `${Date.now()}_${Math.random().toString(36).slice(2)}`);
      memorySession = id;
      try { sessionStorage.setItem('echoVisitorSession', id); } catch (_) { /* Keep this tab's in-memory ID. */ }
    }
    return id;
  }

  function setState(value, label) {
    root.dataset.state = value;
    status.textContent = label;
    orb.setAttribute('aria-label', listening ? 'Stop listening to Echo' : 'Start speaking to Echo');
  }

  function showPanel() {
    panel.hidden = false;
    orb.setAttribute('aria-expanded', 'true');
  }

  function stopSpeaking() {
    speechNumber += 1;
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    if (activeRequest) {
      activeRequest.abort();
      activeRequest = null;
      requestNumber += 1;
      replyCaption.textContent = 'Stopped.';
    }
    if (!listening) setState(muted ? 'muted' : 'ready', muted ? 'Muted' : 'Ready');
  }

  function timingLog(stage, timing, extras = {}) {
    if (!timing) return;
    console.info('[Echo timing]', stage, {
      ...timing,
      ...extras,
      at: Math.round(performance.now()),
    });
  }

  function readServerTimings(header) {
    const result = {};
    for (const part of (header || '').split(',')) {
      const match = part.trim().match(/^([\w-]+);dur=([\d.]+)/);
      if (match) result[match[1]] = Number(match[2]);
    }
    return result;
  }

  function speak(text, timing) {
    if (muted || !text) return;
    if (!('speechSynthesis' in window)) { setState('error', 'Speech unavailable'); return; }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = preferredEnglishVoice();
    if (voice) {
      utterance.voice = voice;
      utterance.lang = voice.lang || 'en-IN';
    } else {
      utterance.lang = 'en-IN';
    }
    const thisSpeech = ++speechNumber;
    utterance.rate = 0.94;
    utterance.pitch = 1.0;
    utterance.onstart = () => {
      if (thisSpeech === speechNumber) {
        setState('speaking', 'Speaking');
        const origin = timing.requestStartedAt ?? timing.transcriptFinalAt;
        timingLog('browser_tts_start', timing, { fromTranscriptMs: Math.round(performance.now() - origin) });
      }
    };
    utterance.onend = () => { if (thisSpeech === speechNumber) setState(muted ? 'muted' : 'ready', muted ? 'Muted' : 'Ready'); };
    utterance.onerror = () => { if (thisSpeech === speechNumber) setState('error', 'Voice unavailable'); };
    window.speechSynthesis.speak(utterance);
  }

  function stopListening() {
    if (recognition && listening) recognition.stop();
  }

  function startListening() {
    stopSpeaking();
    if (!speechRecognition) {
      showPanel();
      userCaption.textContent = 'Speech recognition is unavailable in this browser. Type your request below.';
      setState('error', 'Type a request');
      input.focus();
      return;
    }
    try {
      if (!recognition) {
        recognition = new speechRecognition();
        recognition.lang = 'en-IN';
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.onstart = () => {
          listening = true;
          recognitionStartedAt = performance.now();
          speechEndedAt = null;
          setState('listening', 'Listening');
        };
        recognition.onspeechend = () => {
          speechEndedAt = performance.now();
          setState('transcribing', 'Transcribing');
        };
        recognition.onresult = event => {
          let interim = '';
          let finalText = '';
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const text = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalText += text;
            else interim += text;
          }
          if (interim) userCaption.textContent = `Listening: ${interim}`;
          if (finalText.trim()) {
            userCaption.textContent = finalText.trim();
            stopListening();
            const timing = {
              source: 'voice',
              speechEndToTranscriptMs: speechEndedAt === null ? null : Math.round(performance.now() - speechEndedAt),
              recognitionDurationMs: recognitionStartedAt === null ? null : Math.round(performance.now() - recognitionStartedAt),
            };
            timingLog('transcript_final', timing);
            sendTranscript(finalText.trim(), timing);
          }
        };
        recognition.onerror = event => {
          listening = false;
          const messages = {
            'not-allowed': 'Microphone permission was denied. Allow microphone access in your browser settings, or type below.',
            'service-not-allowed': 'This browser blocked speech recognition. Try a supported browser or type below.',
            'no-speech': 'I did not hear speech. Try again or type below.',
            'audio-capture': 'No microphone was found. Check the device or type below.'
          };
          userCaption.textContent = messages[event.error] || `Speech recognition failed (${event.error}). You can type below.`;
          setState('error', 'Microphone issue');
        };
        recognition.onend = () => {
          listening = false;
          if (root.dataset.state === 'listening') setState(muted ? 'muted' : 'ready', muted ? 'Muted' : 'Ready');
        };
      }
      recognition.start();
    } catch (error) {
      userCaption.textContent = 'Could not start the microphone. Check browser permission and try again, or type below.';
      setState('error', 'Microphone issue');
    }
  }

  function enterStudentView() {
    if (typeof currentUserRole === 'undefined' || !['STUDENT', 'VISITOR'].includes(currentUserRole)) {
      replyCaption.textContent = 'Please enter the STUDENT or VISITOR access code on the page before browsing events or contacts.';
      return false;
    }
    if (typeof hideAllViews === 'function') hideAllViews();
    const view = document.getElementById('student-view');
    if (view) view.classList.remove('hidden');
    return true;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[char]);
  }

  function renderSearchResults(results) {
    if (!enterStudentView()) return false;
    if (typeof switchStudentSubTab === 'function') switchStudentSubTab('events', document.querySelector('.seg-2'), false);
    document.querySelectorAll('#student-events-subview .filter-group button').forEach(button => button.classList.remove('active-filter'));
    if (typeof renderStudentEvents === 'function') {
      renderStudentEvents(results.map(item => ({
        id: item.activity_id, title: item.title, category: item.category,
        venue: item.venue, start_time: item.start_time, end_time: item.end_time,
        participation_type: item.participation_type, status: item.status,
        participant_instructions: item.participant_instructions
      })));
    }
    document.getElementById('student-events-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return true;
  }

  function executeAction(action) {
    if (!action || typeof action.action !== 'string') return;
    if (action.action === 'stop_speaking') { stopSpeaking(); return; }
    if (action.action === 'search_events') {
      if (!Array.isArray(action.results)) return;
      return renderSearchResults(action.results);
      return;
    }
    if (action.action === 'open_event' || action.action === 'show_event_details') {
      const event = action.event;
      if (!event || !Number.isSafeInteger(event.activity_id)) return;
      const rendered = renderSearchResults([event]);
      if (!rendered) return false;
      requestAnimationFrame(() => {
        const card = document.querySelector(`[data-activity-id="${event.activity_id}"]`);
        card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card?.setAttribute('tabindex', '-1');
        card?.focus({ preventScroll: true });
      });
      return;
    }
    if (action.action === 'navigate') {
      if (!['home', 'campus', 'map', 'events', 'contacts', 'announcements', 'progress'].includes(action.route)) return;
      if (action.route === 'home') { if (typeof showLandingPage === 'function') showLandingPage(); return; }
      if (!enterStudentView()) return false;
      const tab = action.route === 'contacts' ? 'contact' : action.route;
      if (typeof switchStudentSubTab === 'function') switchStudentSubTab(tab);
      return;
    }
    if (action.action === 'scroll' && ['up', 'down'].includes(action.direction)) {
      window.scrollBy({ top: action.direction === 'down' ? Math.round(innerHeight * 0.7) : -Math.round(innerHeight * 0.7), behavior: 'smooth' });
    }
  }

  function handleLocalCommand(transcript, timing) {
    const clean = transcript.trim();
    if (/^(?:echo[, ]*)?(?:please )?(?:be quiet|stop talking|stop speaking|shut up)(?: now)?[.!\s]*$/i.test(clean)) {
      stopSpeaking();
      replyCaption.textContent = 'Okay, I’ll be quiet.';
      return true;
    }
    if (/^(?:please )?mute(?: echo)?[.!\s]*$/i.test(clean)) {
      setMuted(true);
      replyCaption.textContent = 'Echo is muted.';
      return true;
    }
    if (/^(?:please )?unmute(?: echo)?[.!\s]*$/i.test(clean)) {
      stopSpeaking();
      setMuted(false);
      replyCaption.textContent = 'Echo is unmuted.';
      return true;
    }
    const scroll = clean.match(/^(?:echo[, ]*)?(?:please )?(?:scroll|move)\s+(up|down)(?:\s+(?:the\s+)?page)?[.!\s]*$/i);
    if (scroll) {
      stopSpeaking();
      const direction = scroll[1].toLowerCase();
      window.scrollBy({ top: direction === 'down' ? Math.round(innerHeight * .7) : -Math.round(innerHeight * .7), behavior: 'smooth' });
      replyCaption.textContent = direction === 'down' ? 'Scrolling down.' : 'Scrolling up.';
      setState(muted ? 'muted' : 'ready', muted ? 'Muted' : 'Ready');
      timingLog('local_scroll', timing);
      if (!muted) speak(replyCaption.textContent, timing);
      return true;
    }
    if (/^(?:echo[, ]*)?(?:please )?(?:go back|back|previous page)[.!\s]*$/i.test(clean)) {
      stopSpeaking();
      if (history.length > 1 && document.referrer && new URL(document.referrer).origin === location.origin) {
        history.back();
        replyCaption.textContent = 'Going back.';
      } else {
        replyCaption.textContent = 'There is no previous page in this site session.';
      }
      setState(muted ? 'muted' : 'ready', muted ? 'Muted' : 'Ready');
      timingLog('local_back', timing);
      if (!muted) speak(replyCaption.textContent, timing);
      return true;
    }
    const navigation = clean.match(/^(?:echo[, ]*)?(?:please )?(?:open|show|go to|navigate to|take me to)\s+(?:the\s+)?(home|campus|map|events?|contacts?|announcements?|progress)(?:\s+(?:section|page))?[.!\s]*$/i);
    if (navigation) {
      stopSpeaking();
      const label = navigation[1].toLowerCase();
      const route = label === 'event' ? 'events' : label === 'contact' ? 'contacts' : label;
      const completed = executeAction({ action: 'navigate', route });
      replyCaption.textContent = completed === false ? 'Enter the STUDENT or VISITOR code before opening campus sections.' : ({
        home: 'Going to the role selection page.', campus: 'Opening the campus landing page.', map: 'Opening the campus map section.',
        events: 'Opening events.', contacts: 'Opening the campus contacts.', announcements: 'Opening announcements.', progress: 'Opening the activity progress section.'
      })[route];
      setState(completed === false ? 'error' : (muted ? 'muted' : 'ready'), completed === false ? 'Access code needed' : (muted ? 'Muted' : 'Ready'));
      timingLog('local_navigation', timing, { route });
      if (!muted && completed !== false) speak(replyCaption.textContent, timing);
      return true;
    }
    return false;
  }

  async function sendTranscript(rawText, inputTiming = {}) {
    const transcript = rawText.trim();
    if (!transcript) return;
    const timing = { source: 'typed', ...inputTiming, transcriptFinalAt: performance.now() };
    showPanel();
    userCaption.textContent = transcript;
    if (handleLocalCommand(transcript, timing)) return;
    stopSpeaking();
    if (activeRequest) activeRequest.abort();
    const thisRequest = ++requestNumber;
    activeRequest = new AbortController();
    setState('thinking', 'Thinking');
    replyCaption.textContent = 'Thinking…';
    const requestStartedAt = performance.now();
    timing.requestStartedAt = requestStartedAt;
    timing.transcriptToRequestMs = Math.round(requestStartedAt - timing.transcriptFinalAt);
    try {
      const response = await fetch(`${window.ECHO_API_BASE || window.location.origin}/api/echo/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId(), transcript }),
        signal: activeRequest.signal
      });
      const responseReceivedAt = performance.now();
      timing.clientRequestMs = Math.round(responseReceivedAt - requestStartedAt);
      timing.server = readServerTimings(response.headers.get('Server-Timing'));
      const parseStartedAt = performance.now();
      const data = await response.json().catch(() => ({}));
      timing.responseParseMs = Math.round(performance.now() - parseStartedAt);
      if (thisRequest !== requestNumber) return;
      if (!response.ok) throw new Error(data.detail || `Echo request failed (${response.status}).`);
      if (typeof data.speech_text !== 'string' || !data.action) throw new Error('The website returned an incomplete Echo response.');
      replyCaption.textContent = data.speech_text;
      timing.captionSetAt = performance.now();
      timingLog('caption_text_set', timing, { httpStatus: response.status });
      requestAnimationFrame(() => timingLog('caption_painted', timing, {
        fromTranscriptMs: Math.round(performance.now() - timing.transcriptFinalAt),
      }));
      const actionStartedAt = performance.now();
      const actionCompleted = executeAction(data.action);
      timing.actionExecutionMs = Math.round(performance.now() - actionStartedAt);
      if (data.action.action !== 'stop_speaking' && actionCompleted !== false) {
        if (muted) setState('muted', 'Muted');
        else {
          const expectedSpeech = speechNumber;
          requestAnimationFrame(() => {
            if (thisRequest === requestNumber && expectedSpeech === speechNumber) speak(data.speech_text, timing);
          });
        }
      }
      else setState(muted ? 'muted' : 'ready', muted ? 'Muted' : 'Ready');
    } catch (error) {
      if (error.name === 'AbortError') return;
      if (thisRequest !== requestNumber) return;
      replyCaption.textContent = error.message || 'Echo could not reach the website AI service.';
      setState('error', 'Connection issue');
    } finally {
      if (thisRequest === requestNumber) activeRequest = null;
    }
  }

  function setMuted(value) {
    muted = value;
    muteButton.textContent = muted ? 'Unmute' : 'Mute';
    muteButton.setAttribute('aria-pressed', String(muted));
    if (muted) stopSpeaking();
    setState(muted ? 'muted' : 'ready', muted ? 'Muted' : 'Ready');
  }

  orb.addEventListener('click', () => {
    showPanel();
    if (listening) stopListening();
    else startListening();
  });
  document.getElementById('echo-close').addEventListener('click', () => {
    stopListening(); stopSpeaking(); panel.hidden = true; orb.setAttribute('aria-expanded', 'false');
  });
  document.getElementById('echo-stop').addEventListener('click', stopSpeaking);
  muteButton.addEventListener('click', () => setMuted(!muted));
  form.addEventListener('submit', event => {
    event.preventDefault();
    const value = input.value;
    input.value = '';
    sendTranscript(value);
  });
  setState('ready', 'Ready');
})();
