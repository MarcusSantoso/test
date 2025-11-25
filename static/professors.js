document.addEventListener('DOMContentLoaded', function() {
    const lookupForm = document.getElementById('lookupForm');
    const createForm = document.getElementById('createForm');
    const searchTabs = document.querySelectorAll('.search-tab');
    const professorDetails = document.getElementById('professorDetails');
    const loading = document.getElementById('loading');
    const scrapeBtn = document.getElementById('scrapeBtn');
    
    let currentProfId = null;
    const searchResultsEl = document.getElementById('searchResults');

    // Tab switching
    searchTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            searchTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            if (tab.dataset.tab === 'lookup') {
                lookupForm.classList.remove('hidden');
                createForm.classList.add('hidden');
                // Clear create form when switching to lookup
                createForm.reset();
            } else {
                lookupForm.classList.add('hidden');
                createForm.classList.remove('hidden');
                // Clear lookup form when switching to create
                lookupForm.reset();
            }
            clearMessages();
        });
    });

    // Lookup professor by name (search)
    lookupForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearMessages();
        searchResultsEl.innerHTML = '';
        const query = document.getElementById('profQuery').value.trim();
        if (!query) return;
        // Call list endpoint which supports `q` for case-insensitive name search
        try {
            const res = await fetch(`/professors/?q=${encodeURIComponent(query)}`);
            if (!res.ok) {
                document.getElementById('searchError').textContent = 'Search failed';
                return;
            }
            const data = await res.json();
            const results = data.professors || [];
            if (results.length === 0) {
                document.getElementById('searchError').textContent = 'No professors found';
                return;
            }
            if (results.length === 1) {
                // Single match — load full details by id
                await loadProfessor(results[0].id);
                return;
            }
            // Multiple matches — show a selectable list
            searchResultsEl.innerHTML = `<ul class="result-list">${results.map(r => `<li class="result-item" data-id="${r.id}"><strong>${escapeHtml(r.name)}</strong> <span class="small muted">${escapeHtml(r.department || '')}</span></li>`).join('')}</ul>`;
            // attach click handlers
            searchResultsEl.querySelectorAll('.result-item').forEach(el => {
                el.addEventListener('click', async () => {
                    const id = el.dataset.id;
                    document.getElementById('profQuery').value = el.textContent.trim();
                    searchResultsEl.innerHTML = '';
                    await loadProfessor(id);
                });
            });
        } catch (err) {
            document.getElementById('searchError').textContent = 'Network error during search';
        }
    });

    // Create professor
    createForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearMessages();
        const name = document.getElementById('profName').value.trim();
        const dept = document.getElementById('profDept').value.trim();
        const rmpUrl = document.getElementById('profRmpUrl').value.trim();
        const errEl = document.getElementById('createError');
        const successEl = document.getElementById('createSuccess');
        const btn = createForm.querySelector('button[type="submit"]');

        btn.disabled = true;
        btn.textContent = 'Creating...';

        try {
            const res = await fetch('/professors/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    department: dept || null,
                    rmp_url: rmpUrl || null
                })
            });
            const data = await res.json();
            if (res.status === 201) {
                successEl.textContent = `Professor created with ID: ${data.professor.id}`;
                createForm.reset();
                setTimeout(() => {
                    document.getElementById('profId').value = data.professor.id;
                    searchTabs[0].click();
                    loadProfessor(data.professor.id);
                }, 1000);
            } else {
                errEl.textContent = data.detail || 'Failed to create professor';
            }
        } catch (err) {
            errEl.textContent = 'Network error. Please try again.';
        } finally {
            btn.disabled = false;
            btn.textContent = 'Add Professor';
        }
    });

    // Scrape reviews
    scrapeBtn.addEventListener('click', async () => {
        if (!currentProfId) return;
        scrapeBtn.disabled = true;
        scrapeBtn.textContent = '⏳ Fetching...';
        try {
            const res = await fetch(`/scrape/${currentProfId}`, { method: 'POST' });
            const data = await res.json();
            if (res.ok) {
                alert(`Scraping complete! Added ${data.added} new reviews.`);
                await loadProfessor(currentProfId);
            } else {
                alert(data.detail || 'Scraping failed');
            }
        } catch (err) {
            alert('Network error during scraping');
        } finally {
            scrapeBtn.disabled = false;
            scrapeBtn.textContent = '🔄 Fetch New Reviews';
        }
    });

    async function loadProfessor(profId) {
        clearMessages();
        professorDetails.classList.add('hidden');
        loading.classList.remove('hidden');
        document.getElementById('searchError').textContent = '';

        try {
            const res = await fetch(`/professors/${profId}`);
            if (res.status === 404) {
                document.getElementById('searchError').textContent = 'Professor not found';
                loading.classList.add('hidden');
                return;
            }
            const data = await res.json();
            if (data.professor) {
                currentProfId = data.professor.id;
                renderProfessor(data.professor);
                professorDetails.classList.remove('hidden');
            }
        } catch (err) {
            document.getElementById('searchError').textContent = 'Failed to load professor';
        } finally {
            loading.classList.add('hidden');
        }
    }

    function renderProfessor(prof) {
        document.getElementById('profNameDisplay').textContent = prof.name;
        document.getElementById('profDeptDisplay').textContent = prof.department || 'Department not specified';
        document.getElementById('profIdDisplay').textContent = prof.id;
        // Render course codes as badges
        const coursesEl = document.getElementById('profCoursesDisplay');
        coursesEl.innerHTML = '';
        const codes = (function(val) {
            if (!val) return [];
            if (Array.isArray(val)) return val;
            try {
                const parsed = JSON.parse(val);
                if (Array.isArray(parsed)) return parsed;
            } catch (e) {
                // fall through
            }
            return [String(val)];
        })(prof.course_codes);

        if (codes && codes.length > 0) {
            const fragment = document.createDocumentFragment();
            codes.forEach(c => {
                const span = document.createElement('span');
                span.className = 'course-badge';
                span.textContent = c;
                fragment.appendChild(span);
                fragment.appendChild(document.createTextNode(' '));
            });
            coursesEl.appendChild(fragment);
        } else {
            coursesEl.textContent = 'No courses listed';
        }
        
        const rmpLink = document.getElementById('profRmpLink');
        if (prof.rmp_url) {
            rmpLink.href = prof.rmp_url;
            rmpLink.classList.remove('hidden');
        } else {
            rmpLink.classList.add('hidden');
        }

        // Render AI Summary
        const noSummary = document.getElementById('noSummary');
        const summaryCards = document.getElementById('summaryCards');
        const summaryUpdated = document.getElementById('summaryUpdated');
        
        if (prof.ai_summary) {
            noSummary.classList.add('hidden');
            summaryCards.classList.remove('hidden');
            renderList('prosList', prof.ai_summary.pros);
            renderList('consList', prof.ai_summary.cons);
            renderList('neutralList', prof.ai_summary.neutral);
            if (prof.ai_summary.updated_at) {
                summaryUpdated.textContent = `Last updated: ${formatDate(prof.ai_summary.updated_at)}`;
                summaryUpdated.classList.remove('hidden');
            } else {
                summaryUpdated.classList.add('hidden');
            }
        } else {
            noSummary.classList.remove('hidden');
            summaryCards.classList.add('hidden');
            summaryUpdated.classList.add('hidden');
        }

        // Render Reviews
        const noReviews = document.getElementById('noReviews');
        const reviewsList = document.getElementById('reviewsList');
        const reviewCount = document.getElementById('reviewCount');
        
        if (prof.reviews && prof.reviews.length > 0) {
            noReviews.classList.add('hidden');
            reviewCount.textContent = `(${prof.reviews.length})`;

            // Progressive rendering: show first N reviews and reveal more on demand
            const INITIAL_REVIEW_COUNT = 5;
            let shown = Math.min(INITIAL_REVIEW_COUNT, prof.reviews.length);

            function renderSlice(count) {
                reviewsList.innerHTML = prof.reviews.slice(0, count).map(r => `
                    <div class="review-card">
                        <div class="review-header">
                            <span class="source-badge ${getSourceClass(r.source)}">${getSourceIcon(r.source)} ${escapeHtml(r.source || 'Unknown')}</span>
                            ${r.rating ? `<span class="rating">⭐ ${r.rating}/5</span>` : ''}
                        </div>
                        <p class="review-text">${escapeHtml(r.text || 'No text')}</p>
                        ${r.timestamp ? `<p class="review-time">${formatDate(r.timestamp)}</p>` : ''}
                    </div>
                `).join('');
            }

            renderSlice(shown);

            const controls = document.getElementById('reviewsControls');
            const showMoreBtn = document.getElementById('showMoreBtn');
            if (prof.reviews.length > INITIAL_REVIEW_COUNT) {
                controls.classList.remove('hidden');
                showMoreBtn.textContent = `Show more reviews (${prof.reviews.length - shown})`;
                showMoreBtn.onclick = () => {
                    // reveal all reviews when clicked
                    shown = prof.reviews.length;
                    renderSlice(shown);
                    controls.classList.add('hidden');
                };
            } else {
                controls.classList.add('hidden');
            }
        } else {
            noReviews.classList.remove('hidden');
            reviewCount.textContent = '(0)';
            reviewsList.innerHTML = '';
            const controls = document.getElementById('reviewsControls');
            if (controls) controls.classList.add('hidden');
        }
    }

    function renderList(elementId, items) {
        const el = document.getElementById(elementId);
        if (items && items.length > 0) {
            el.innerHTML = items.map(item => `<li>${escapeHtml(item)}</li>`).join('');
        } else {
            el.innerHTML = '<li class="empty">None listed</li>';
        }
    }

    function getSourceClass(source) {
        if (!source) return '';
        const s = source.toLowerCase();
        if (s.includes('reddit')) return 'source-reddit';
        if (s.includes('ratemyprofessor') || s === 'rmp') return 'source-rmp';
        return '';
    }

    function getSourceIcon(source) {
        if (!source) return '📝';
        const s = source.toLowerCase();
        if (s.includes('reddit')) return '🔴';
        if (s.includes('ratemyprofessor') || s === 'rmp') return '📊';
        return '📝';
    }

    function formatDate(dateStr) {
        if (!dateStr) return '';
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        } catch { return dateStr; }
    }

    function clearMessages() {
        document.querySelectorAll('.error-message, .success-message').forEach(el => el.textContent = '');
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Check URL params for direct professor lookup by id or name
    const params = new URLSearchParams(window.location.search);
    if (params.get('id')) {
        // legacy support for direct ID param
        loadProfessor(params.get('id'));
    } else if (params.get('q')) {
        document.getElementById('profQuery').value = params.get('q');
        // Trigger search automatically
        lookupForm.dispatchEvent(new Event('submit'));
    }
});
