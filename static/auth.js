document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const authContainer = document.getElementById('authContainer');
    const dashboard = document.getElementById('dashboard');
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const tabs = document.querySelectorAll('.tab');
    const logoutBtn = document.getElementById('logoutBtn');

    // Check if user is already logged in
    checkAuthStatus();

    // Tab switching
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            if (target === 'login') {
                loginForm.classList.remove('hidden');
                registerForm.classList.add('hidden');
            } else {
                loginForm.classList.add('hidden');
                registerForm.classList.remove('hidden');
            }
            clearMessages();
        });
    });

    // Register form submission
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearMessages();
        
        const name = document.getElementById('registerName').value.trim();
        const email = document.getElementById('registerEmail').value.trim();
        const password = document.getElementById('registerPassword').value;
        const confirmPw = document.getElementById('confirmPassword').value;
        const errEl = document.getElementById('registerError');
        const successEl = document.getElementById('registerSuccess');
        const btn = registerForm.querySelector('button[type="submit"]');

        // Validation
        if (!name || !email || !password) {
            errEl.textContent = 'Please fill in all fields';
            return;
        }

        if (password !== confirmPw) {
            errEl.textContent = 'Passwords do not match';
            return;
        }

        if (password.length < 4) {
            errEl.textContent = 'Password must be at least 4 characters';
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Creating account...';

        try {
            const res = await fetch('/users/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, password })
            });
            
            let data;
            try {
                data = await res.json();
            } catch {
                data = { detail: 'Invalid response from server' };
            }

            if (res.status === 201) {
                successEl.textContent = 'Account created! Logging you in...';
                registerForm.reset();
                
                // Auto-login after registration
                setTimeout(async () => {
                    await performLogin(name, password);
                }, 1000);
            } else if (res.status === 409) {
                errEl.textContent = 'Username or email already exists';
                btn.disabled = false;
                btn.textContent = 'Create Account';
            } else if (res.status === 422) {
                // Validation error from FastAPI/Pydantic
                if (data.detail && Array.isArray(data.detail)) {
                    // Extract validation error messages
                    const errors = data.detail.map(err => err.msg || err.message || 'Validation error').join(', ');
                    errEl.textContent = errors;
                } else if (typeof data.detail === 'string') {
                    errEl.textContent = data.detail;
                } else {
                    errEl.textContent = 'Invalid input. Please check your email format.';
                }
                btn.disabled = false;
                btn.textContent = 'Create Account';
            } else {
                // Handle any other error
                const errorMsg = typeof data.detail === 'string' 
                    ? data.detail 
                    : (data.message || 'Registration failed');
                errEl.textContent = errorMsg;
                btn.disabled = false;
                btn.textContent = 'Create Account';
            }
        } catch (err) {
            errEl.textContent = 'Network error. Please try again.';
            btn.disabled = false;
            btn.textContent = 'Create Account';
        }
    });

    // Login form submission
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearMessages();
        
        const name = document.getElementById('loginName').value.trim();
        const password = document.getElementById('loginPassword').value;
        const errEl = document.getElementById('loginError');
        const btn = loginForm.querySelector('button[type="submit"]');

        if (!name || !password) {
            errEl.textContent = 'Please enter username and password';
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Logging in...';

        try {
            await performLogin(name, password);
        } catch (err) {
            errEl.textContent = err.message || 'Login failed';
        } finally {
            btn.disabled = false;
            btn.textContent = 'Login';
        }
    });

    // Logout handler
    logoutBtn.addEventListener('click', () => {
        localStorage.removeItem('jwt');
        localStorage.removeItem('userData');
        showAuth();
    });

    // Perform login API call
    async function performLogin(name, password) {
        const errEl = document.getElementById('loginError');
        
        // Generate expiry 1 hour from now
        const expiry = new Date(Date.now() + 3600000);
        const expiryStr = expiry.toISOString().slice(0, 19).replace('T', ' ');

        const res = await fetch('/v2/authentications/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, password, expiry: expiryStr })
        });
        const data = await res.json();

        if (res.status === 201 && data.jwt) {
            localStorage.setItem('jwt', data.jwt);
            
            // Fetch user details
            const userRes = await fetch(`/users/${encodeURIComponent(name)}`, {
                headers: { 'Authorization': `Bearer ${data.jwt}` }
            });
            const userData = await userRes.json();
            
            if (userData.user) {
                localStorage.setItem('userData', JSON.stringify(userData.user));
                showDashboard(userData.user);
            } else {
                throw new Error('Failed to fetch user data');
            }
        } else if (res.status === 404) {
            errEl.textContent = 'User not found';
            throw new Error('User not found');
        } else if (res.status === 401) {
            errEl.textContent = 'Invalid password';
            throw new Error('Invalid password');
        } else {
            errEl.textContent = data.detail || 'Login failed';
            throw new Error(data.detail || 'Login failed');
        }
    }

    // Check if already logged in
    function checkAuthStatus() {
        const token = localStorage.getItem('jwt');
        const userData = localStorage.getItem('userData');
        
        if (token && userData) {
            try {
                const user = JSON.parse(userData);
                showDashboard(user);
            } catch {
                // Invalid data, clear and show auth
                localStorage.removeItem('jwt');
                localStorage.removeItem('userData');
                showAuth();
            }
        } else {
            showAuth();
        }
    }

    // Show dashboard
    function showDashboard(user) {
        authContainer.classList.add('hidden');
        dashboard.classList.remove('hidden');
        
        document.getElementById('userName').textContent = user.name;
        document.getElementById('userId').textContent = user.id;
        document.getElementById('userNameDisplay').textContent = user.name;
        document.getElementById('userTier').textContent = `Tier ${user.tier || 1}`;
    }

    // Show auth forms
    function showAuth() {
        dashboard.classList.add('hidden');
        authContainer.classList.remove('hidden');
        loginForm.reset();
        registerForm.reset();
        clearMessages();
        
        // Reset to login tab
        tabs.forEach(t => t.classList.remove('active'));
        tabs[0].classList.add('active');
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
    }

    // Clear all messages
    function clearMessages() {
        document.querySelectorAll('.error-message, .success-message').forEach(el => {
            el.textContent = '';
        });
    }
});