function showTab(tab) {
  document.getElementById('tab-login').classList.toggle('active', tab === 'login');
  document.getElementById('tab-signup').classList.toggle('active', tab === 'signup');
  document.getElementById('login-form').classList.toggle('hidden', tab !== 'login');
  document.getElementById('signup-form').classList.toggle('hidden', tab !== 'signup');
  document.getElementById('error-msg').textContent = '';
}

async function doLogin(e) {
  e.preventDefault();
  const email = document.getElementById('login-email').value;
  const password = document.getElementById('login-password').value;
  const errorEl = document.getElementById('error-msg');
  errorEl.textContent = '';

  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();

    if (!res.ok) {
      errorEl.textContent = data.detail || 'Login failed';
      return false;
    }

    localStorage.setItem('token', data.token);
    localStorage.setItem('name', data.name);
    window.location.href = '/dashboard.html';
  } catch (err) {
    errorEl.textContent = 'Could not reach the server: ' + err.message;
  }
  return false;
}

async function doSignup(e) {
  e.preventDefault();
  const name = document.getElementById('signup-name').value;
  const email = document.getElementById('signup-email').value;
  const phone = document.getElementById('signup-phone').value;
  const password = document.getElementById('signup-password').value;
  const errorEl = document.getElementById('error-msg');
  errorEl.textContent = '';

  try {
    const res = await fetch('/api/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, phone, password }),
    });

    const data = await res.json();

    if (!res.ok) {
      errorEl.textContent = data.detail || 'Signup failed';
      return false;
    }

    localStorage.setItem('token', data.token);
    localStorage.setItem('name', data.name);
    window.location.href = '/dashboard.html';
  } catch (err) {
    errorEl.textContent = 'Could not reach the server: ' + err.message;
  }
  return false;
}