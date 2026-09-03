const token = localStorage.getItem('token');
if (!token) window.location.href = '/';

document.getElementById('user-name').textContent = localStorage.getItem('name') || '';

function logout() { localStorage.clear(); window.location.href = '/'; }

async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Authorization': 'Bearer ' + token } };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

// ---- Tab navigation ----
document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item[data-tab]').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.remove('hidden');
  });
});

function show(id, html) { document.getElementById(id).innerHTML = html; }
function showError(id, e) { show(id, `<span style="color:var(--error)">${e.message}</span>`); }

// ---- Job ----
async function submitJob() {
  const box = 'job-result';
  show(box, 'Extracting...');
  try {
    const data = await api('/api/job', 'POST', {
      text: document.getElementById('job-text').value,
      company_name: document.getElementById('job-company').value || null,
      url: document.getElementById('job-url').value || null,
    });
    let rows = data.requirements.map(r => `<tr><td>${r.text}</td><td>${r.type}</td><td>${r.priority}</td></tr>`).join('');
    show(box, `<b>${data.title}</b><table><tr><th>Requirement</th><th>Type</th><th>Priority</th></tr>${rows}</table>`);
  } catch (e) { showError(box, e); }
}

// ---- Candidate ----
document.getElementById('cand-pdf').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const box = 'candidate-result';
  show(box, 'Extracting text from PDF...');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/extract-pdf-text', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'PDF extraction failed');

    document.getElementById('cand-resume').value = data.text;
    show(box, 'Text extracted from PDF - review below, then click Extract Candidate.');
  } catch (e) { showError(box, e); }
});

async function submitCandidate() {
  const box = 'candidate-result';
  show(box, 'Extracting...');
  try {
    const links = {};
    const gh = document.getElementById('cand-github').value;
    const li = document.getElementById('cand-linkedin').value;
    if (gh) links.github = gh;
    if (li) links.linkedin = li;

    const data = await api('/api/candidate', 'POST', {
      name: document.getElementById('cand-name').value,
      resume_text: document.getElementById('cand-resume').value,
      email: document.getElementById('cand-email').value || null,
      phone: document.getElementById('cand-phone').value || null,
      portfolio_url: document.getElementById('cand-portfolio').value || null,
      links: Object.keys(links).length ? links : null,
    });
    show(box, `Saved candidate: ${data.name}`);
  } catch (e) { showError(box, e); }
}

// ---- Match & Resume ----
async function runMatch() {
  show('loop-result', 'Matching...');
  try { await api('/api/match', 'POST'); show('loop-result', 'Matched.'); }
  catch (e) { showError('loop-result', e); }
}

async function runLoop() {
  show('loop-result', 'Running loop (this can take a minute)...');
  try {
    const data = await api('/api/loop', 'POST');
    let rows = data.history.map(h =>
      `<tr><td>v${h.version_number}</td><td>${h.score}</td><td>${h.passed ? '<span class="badge pass">PASS</span>' : '<span class="badge fail">FAIL</span>'}</td></tr>`
    ).join('');
    show('loop-result', `<table><tr><th>Version</th><th>Score</th><th>Fact Check</th></tr>${rows}</table>
      <p style="margin-top:10px">Final score: <b>${data.final_score}</b></p>`);
  } catch (e) { showError('loop-result', e); }
}

async function loadResume() {
  show('resume-result', 'Loading...');
  try {
    const data = await api('/api/resume');
    show('resume-result', `Version ${data.version} - Score ${data.score} - ${data.fact_check_passed ? '<span class="badge pass">PASS</span>' : '<span class="badge fail">FAIL</span>'}\n\n${data.content}`);
  } catch (e) { showError('resume-result', e); }
}

// ---- Assessments ----
async function runAssess(type) {
  show('assessments-result', `Running ${type}...`);
  try { await api('/api/assess/' + type, 'POST'); await loadAssessments(); }
  catch (e) { showError('assessments-result', e); }
}

async function runJudge() {
  show('assessments-result', 'Judging...');
  try { await api('/api/judge', 'POST'); await loadAssessments(); }
  catch (e) { showError('assessments-result', e); }
}

async function runDebate() {
  show('assessments-result', 'Running debate...');
  try { await api('/api/debate', 'POST'); await loadAssessments(); }
  catch (e) { showError('assessments-result', e); }
}

async function loadAssessments() {
  try {
    const data = await api('/api/assessments');
    let html = data.assessments.map(a => `<p><b>${a.agent_type}</b>: ${a.score}/100 - ${a.reasoning}</p>`).join('');
    if (data.recommendation) html += `<p style="margin-top:12px"><b>Recommendation:</b> ${data.recommendation}</p><p>${data.disagreement_analysis || ''}</p>`;
    if (data.debate_transcript) html += data.debate_transcript.map(t => `<p><b>${t.agent_type}</b>: ${t.rebuttal}</p>`).join('');
    show('assessments-result', html || 'No assessments yet.');
  } catch (e) { showError('assessments-result', e); }
}

// ---- Skill gaps ----
async function loadGaps() {
  show('gaps-result', 'Computing...');
  try {
    const data = await api('/api/gaps');
    if (!data.gaps.length) { show('gaps-result', 'No gaps found.'); return; }
    let html = '';
    for (const bucket of ['urgent', 'important', 'optional']) {
      const items = data.gaps.filter(g => g.urgency === bucket);
      if (!items.length) continue;
      html += `<p style="margin-top:10px"><b>${bucket.toUpperCase()}</b></p>`;
      html += items.map(g => `<p>- ${g.requirement}<br><span style="color:var(--text-muted)">-&gt; ${g.suggestion}</span></p>`).join('');
    }
    show('gaps-result', html);
  } catch (e) { showError('gaps-result', e); }
}

// ---- Applications ----
async function logApplication() {
  show('applications-result', 'Logging...');
  try { await api('/api/applications', 'POST'); await loadApplications(); }
  catch (e) { showError('applications-result', e); }
}

async function loadApplications() {
  try {
    const data = await api('/api/applications');
    if (!data.applications.length) { show('applications-result', 'No applications yet.'); return; }
    let html = data.applications.map(a => `
      <p><b>${a.job_title}</b> - ${a.status} (score ${a.resume_score})
      <select onchange="updateAppStatus('${a.application_id}', this.value)">
        ${data.valid_statuses.map(s => `<option value="${s}" ${s === a.status ? 'selected' : ''}>${s}</option>`).join('')}
      </select></p>
    `).join('');
    show('applications-result', html);
  } catch (e) { showError('applications-result', e); }
}

async function updateAppStatus(id, status) {
  await api('/api/applications/' + id, 'PATCH', { status });
  await loadApplications();
}

document.querySelector('[data-tab="applications"]').addEventListener('click', loadApplications);

// ---- Analytics ----
async function loadAnalytics() {
  show('analytics-result', 'Loading...');
  try {
    const s = await api('/api/analytics');
    let html = `Total applications: <b>${s.total}</b><br>`;
    if (s.submitted_count) {
      html += `Response rate: ${s.response_rate}% | Interview rate: ${s.interview_rate}% | Offer rate: ${s.offer_rate}%<br>`;
    }
    if (s.total < 10) {
      html += `<p style="color:var(--text-muted);margin-top:10px">Sample size: ${s.total}. Too small for real patterns - describes what happened, not what to expect.</p>`;
    }
    show('analytics-result', html);
  } catch (e) { showError('analytics-result', e); }
}

// ---- Company research ----
async function runResearch() {
  show('research-result', 'Searching the web...');
  try {
    const data = await api('/api/research', 'POST', { company_name: document.getElementById('research-company').value });
    let html = `<p>Confidence: ${data.confidence}</p><p>${data.summary}</p>`;
    html += data.claims.map(c => `<p>- ${c.text}<br><a href="${c.url}" target="_blank" style="color:var(--primary)">${c.url}</a></p>`).join('');
    show('research-result', html);
  } catch (e) { showError('research-result', e); }
}

// ---- Job Discovery ----
async function runDiscover() {
  show('discover-result', 'Searching...');
  try {
    const data = await api('/api/discover', 'POST', { query: document.getElementById('discover-query').value });
    if (!data.results.length) { show('discover-result', 'No usable postings found.'); return; }
    let html = data.results.map(r => `<p><b>${r.fit_score}%</b> - ${r.title}<br><a href="${r.url}" target="_blank" style="color:var(--primary)">${r.url}</a></p>`).join('');
    show('discover-result', html);
  } catch (e) { showError('discover-result', e); }
}

// ---- Interview ----
let interviewSessionId = null;

async function startInterview() {
  show('interview-feedback', 'Generating questions...');
  document.getElementById('interview-question-box').classList.add('hidden');
  try {
    const data = await api('/api/interview/start', 'POST');
    interviewSessionId = data.session_id;
    showInterviewQuestion(data);
    show('interview-feedback', '');
  } catch (e) { showError('interview-feedback', e); }
}

function showInterviewQuestion(data) {
  if (data.done) {
    document.getElementById('interview-question-box').classList.add('hidden');
    show('interview-feedback', `Interview complete. Average score: ${data.average_score}/5`);
    return;
  }
  document.getElementById('interview-question-box').classList.remove('hidden');
  document.getElementById('interview-category').textContent = data.category || (data.next_is_followup ? 'follow-up' : (data.next_category || ''));
  document.getElementById('interview-question').textContent = data.question || data.next_question;
  document.getElementById('interview-answer').value = '';
}

async function submitInterviewAnswer() {
  const answer = document.getElementById('interview-answer').value;
  show('interview-feedback', 'Evaluating...');
  try {
    const data = await api('/api/interview/answer', 'POST', { session_id: interviewSessionId, answer });
    show('interview-feedback', `Score: ${data.score}/5 - ${data.feedback}`);
    showInterviewQuestion(data);
  } catch (e) { showError('interview-feedback', e); }
}

async function submitInterviewVoice() {
  const file = document.getElementById('interview-voice').files[0];
  if (!file) return;
  show('interview-feedback', 'Transcribing and evaluating...');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`/api/interview/answer-voice?session_id=${interviewSessionId}`, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Voice answer failed');

    show('interview-feedback', `(heard: "${data.transcribed_text}")<br>Score: ${data.score}/5 - ${data.feedback}`);
    showInterviewQuestion(data);
  } catch (e) { showError('interview-feedback', e); }
}

// ---- Browser autofill ----
async function runBrowserAutofill() {
  show('browser-result', 'Opening browser...');
  try {
    const data = await api('/api/browser/autofill', 'POST', { url: document.getElementById('browser-url').value });
    show('browser-result', `Filled: ${data.filled_fields.join(', ') || 'none found'}<br>${data.note}`);
  } catch (e) { showError('browser-result', e); }
}