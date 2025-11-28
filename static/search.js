document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const modeCards = document.querySelectorAll('.mode-card');
    const searchSection = document.querySelector('.search-section');
    const recommendSection = document.querySelector('.recommend-section');
    const loginPrompt = document.getElementById('loginPrompt');
    const recommendContent = document.getElementById('recommendContent');
    
    // Search elements
    const searchBtn = document.getElementById('searchBtn');
    const searchQuery = document.getElementById('searchQuery');
    const searchDept = document.getElementById('searchDept');
    const searchResults = document.getElementById('searchResults');
    const searchError = document.getElementById('searchError');
    const searchLoading = document.getElementById('searchLoading');
    
    // Recommendation elements
    const recommendBtn = document.getElementById('recommendBtn');
    const clarityWeight = document.getElementById('clarityWeight');
    const workloadWeight = document.getElementById('workloadWeight');
    const gradingWeight = document.getElementById('gradingWeight');
    const clarityValue = document.getElementById('clarityValue');
    const workloadValue = document.getElementById('workloadValue');
    const gradingValue = document.getElementById('gradingValue');
    const recommendResults = document.getElementById('recommendResults');
    const recommendError = document.getElementById('recommendError');
    const recommendLoading = document.getElementById('recommendLoading');
    const savePrefsBtn = document.getElementById('savePrefsBtn');
    const prefsSaved = document.getElementById('prefsSaved');
    
    // Check authentication for recommendations
    checkAuthForRecommendations();
    
    // Load saved preferences
    loadSavedPreferences();
    
    // Mode switching
    modeCards.forEach(card => {
        card.addEventListener('click', () => {
            modeCards.forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            
            const mode = card.dataset.mode;
            if (mode === 'search') {
                searchSection.classList.add('active');
                recommendSection.classList.remove('active');
            } else {
                searchSection.classList.remove('active');
                recommendSection.classList.add('active');
                checkAuthForRecommendations();
            }
        });
    });
    
    // Weight sliders
    clarityWeight.addEventListener('input', () => {
        clarityValue.textContent = parseFloat(clarityWeight.value).toFixed(1);
    });
    
    workloadWeight.addEventListener('input', () => {
        workloadValue.textContent = parseFloat(workloadWeight.value).toFixed(1);
    });
    
    gradingWeight.addEventListener('input', () => {
        gradingValue.textContent = parseFloat(gradingWeight.value).toFixed(1);
    });
    
    // Search functionality
    searchBtn.addEventListener('click', performSearch);
    searchQuery.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') performSearch();
    });
    
    // Recommendation functionality
    recommendBtn.addEventListener('click', getRecommendations);
    
    // Save preferences
    savePrefsBtn.addEventListener('click', savePreferences);
    
    function checkAuthForRecommendations() {
        if (isLoggedIn()) {
            loginPrompt.classList.add('hidden');
            recommendContent.classList.remove('hidden');
        } else {
            loginPrompt.classList.remove('hidden');
            recommendContent.classList.add('hidden');
        }
    }
    
    function loadSavedPreferences() {
        const saved = localStorage.getItem('recommendPreferences');
        if (saved) {
            try {
                const prefs = JSON.parse(saved);
                clarityWeight.value = prefs.clarity || 1.0;
                workloadWeight.value = prefs.workload || 1.0;
                gradingWeight.value = prefs.grading || 1.0;
                
                clarityValue.textContent = parseFloat(clarityWeight.value).toFixed(1);
                workloadValue.textContent = parseFloat(workloadWeight.value).toFixed(1);
                gradingValue.textContent = parseFloat(gradingWeight.value).toFixed(1);
            } catch (e) {
                console.error('Failed to load preferences:', e);
            }
        }
    }
    
    function savePreferences() {
        const prefs = {
            clarity: parseFloat(clarityWeight.value),
            workload: parseFloat(workloadWeight.value),
            grading: parseFloat(gradingWeight.value)
        };
        
        localStorage.setItem('recommendPreferences', JSON.stringify(prefs));
        
        // Show saved indicator
        prefsSaved.classList.add('show');
        setTimeout(() => {
            prefsSaved.classList.remove('show');
        }, 2000);
    }
    
    async function performSearch() {
        const query = searchQuery.value.trim();
        if (!query) {
            searchError.textContent = 'Please enter a search query';
            return;
        }
        
        searchError.textContent = '';
        searchResults.innerHTML = '';
        searchLoading.classList.remove('hidden');
        searchBtn.disabled = true;
        
        try {
            const params = new URLSearchParams({ q: query });
            if (searchDept.value) {
                params.append('department', searchDept.value);
            }
            
            const res = await fetch(`/search?${params}`);
            const data = await res.json();
            
            if (!res.ok) {
                throw new Error(data.detail || 'Search failed');
            }
            
            displaySearchResults(data.results || []);
        } catch (err) {
            searchError.textContent = err.message || 'Search failed. Please try again.';
        } finally {
            searchLoading.classList.add('hidden');
            searchBtn.disabled = false;
        }
    }
    
    async function getRecommendations() {
        const user = getCurrentUser();
        if (!user) {
            recommendError.textContent = 'Please log in to get recommendations';
            return;
        }
        
        recommendError.textContent = '';
        recommendResults.innerHTML = '';
        recommendLoading.classList.remove('hidden');
        recommendBtn.disabled = true;
        
        try {
            const payload = {
                user_id: user.id,
                clarity_weight: parseFloat(clarityWeight.value),
                workload_weight: parseFloat(workloadWeight.value),
                grading_weight: parseFloat(gradingWeight.value),
                limit: 10
            };
            
            const res = await fetch('/recommend', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            
            const data = await res.json();
            
            if (!res.ok) {
                throw new Error(data.detail || 'Failed to get recommendations');
            }
            
            displayRecommendations(data.results || []);
        } catch (err) {
            recommendError.textContent = err.message || 'Failed to get recommendations. Please try again.';
        } finally {
            recommendLoading.classList.add('hidden');
            recommendBtn.disabled = false;
        }
    }
    
    function displaySearchResults(results) {
        if (!results || results.length === 0) {
            searchResults.innerHTML = '<div class="no-results">No professors found. Try adjusting your search query.</div>';
            return;
        }
        
        searchResults.innerHTML = results.map(result => `
            <div class="result-card" onclick="viewProfessor(${result.id})">
                <div class="result-header">
                    <div class="result-info">
                        <h4>${escapeHtml(result.name)}</h4>
                        <p class="dept">${escapeHtml(result.department || 'Department not specified')}</p>
                    </div>
                    <div class="result-score">
                        <div class="score-badge">${(result.similarity * 100).toFixed(0)}%</div>
                        <div class="score-label">Match</div>
                    </div>
                </div>
            </div>
        `).join('');
    }
    
    function displayRecommendations(results) {
        if (!results || results.length === 0) {
            recommendResults.innerHTML = '<div class="no-results">No recommendations available. Try adjusting your preferences or check back later.</div>';
            return;
        }
        
        recommendResults.innerHTML = results.map(result => {
            const breakdown = result.breakdown || {};
            return `
                <div class="result-card" onclick="viewProfessor(${result.professor_id})">
                    <div class="result-header">
                        <div class="result-info">
                            <h4>${escapeHtml(result.name)}</h4>
                            <p class="dept">${escapeHtml(result.department || 'Department not specified')}</p>
                        </div>
                        <div class="result-score">
                            <div class="score-badge">${(result.score * 100).toFixed(0)}%</div>
                            <div class="score-label">Match Score</div>
                        </div>
                    </div>
                    ${breakdown ? `
                        <div class="result-breakdown">
                            <div class="breakdown-item">
                                <span class="label">Clarity:</span>
                                <span class="value">${(breakdown.clarity_score * 100).toFixed(0)}%</span>
                            </div>
                            <div class="breakdown-item">
                                <span class="label">Workload:</span>
                                <span class="value">${(breakdown.workload_score * 100).toFixed(0)}%</span>
                            </div>
                            <div class="breakdown-item">
                                <span class="label">Grading:</span>
                                <span class="value">${(breakdown.grading_score * 100).toFixed(0)}%</span>
                            </div>
                            ${breakdown.avg_rating ? `
                                <div class="breakdown-item">
                                    <span class="label">Avg Rating:</span>
                                    <span class="value">⭐ ${breakdown.avg_rating.toFixed(1)}/5</span>
                                </div>
                            ` : ''}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
    }
    
    // Global function to navigate to professor page
    window.viewProfessor = function(profId) {
        window.location.href = `/static/professors.html?id=${profId}`;
    };
});
