function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getAuthToken() {
    return localStorage.getItem('jwt');
}

function getCurrentUser() {
    const data = localStorage.getItem('userData');
    if (data) {
        try {
            return JSON.parse(data);
        } catch {
            return null;
        }
    }
    return null;
}

function isLoggedIn() {
    return !!(getAuthToken() && getCurrentUser());
}

async function authFetch(url, options = {}) {
    const token = getAuthToken();
    const headers = options.headers || {};
    
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    return fetch(url, { ...options, headers });
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return dateStr;
    }
}

function clearMessages() {
    document.querySelectorAll('.error-message, .success-message').forEach(el => {
        el.textContent = '';
    });
}
