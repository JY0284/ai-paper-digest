// State
let currentLang = 'zh';

// DOM Elements
const titleEl = document.getElementById('main-title');
const subtitleEl = document.getElementById('subtitle');
const timelineContainer = document.getElementById('timeline');
const statsContainer = document.getElementById('stats');
const footerTextEl = document.getElementById('footer-text');
const btnEn = document.getElementById('btn-en');
const btnZh = document.getElementById('btn-zh');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    renderContent();
    setupEventListeners();
    setupIntersectionObserver();
});

function setupEventListeners() {
    btnEn.addEventListener('click', () => setLang('en'));
    btnZh.addEventListener('click', () => setLang('zh'));
}

function setLang(lang) {
    if (currentLang === lang) return;
    currentLang = lang;
    
    // Update buttons
    btnEn.classList.toggle('active', lang === 'en');
    btnZh.classList.toggle('active', lang === 'zh');
    
    // Re-render
    renderContent();
    setupIntersectionObserver(); // Re-attach observers to new elements
}

function renderContent() {
    // Header
    titleEl.textContent = storyData.meta.title[currentLang];
    subtitleEl.textContent = storyData.meta.subtitle[currentLang];
    footerTextEl.textContent = storyData.meta.footer[currentLang];

    // Stats Section
    if (storyData.stats) {
        renderStats();
    }

    // Timeline
    timelineContainer.innerHTML = storyData.chapters.map((chapter, index) => {
        return `
            <div class="timeline-item">
                <div class="timeline-icon">${chapter.icon}</div>
                <div class="timeline-content">
                    <span class="date">${chapter.date}</span>
                    <h3 class="chapter-title">${chapter.title[currentLang]}</h3>
                    <p>${chapter.description[currentLang]}</p>
                    <div class="tags">
                        ${chapter.tags.map(tag => `<span class="tag">#${tag}</span>`).join('')}
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    // Trigger animations for elements already in view
    setTimeout(() => {
        const items = document.querySelectorAll('.timeline-item');
        items.forEach(item => {
           item.classList.add('visible'); 
        });
    }, 100);
}

function renderStats() {
    const s = storyData.stats;
    
    // Metrics HTML
    const metricsHtml = Object.keys(s.metrics).map(key => `
        <div class="stat-card">
            <div class="stat-value">${s.metrics[key].value}</div>
            <div class="stat-label">${s.metrics[key].label[currentLang]}</div>
        </div>
    `).join('');

    // Heatmap HTML - Full Calendar Style
    const startDate = new Date("2025-07-01"); 
    const endDate = new Date("2025-12-31");
    
    // Generate all dates
    const dates = [];
    let curr = new Date(startDate);
    while (curr <= endDate) {
        dates.push(new Date(curr));
        curr.setDate(curr.getDate() + 1);
    }

    // Group by weeks
    const weeks = [];
    let currentWeek = [];
    
    // Pad first week to start on Sunday
    const firstDayPadding = startDate.getDay(); 
    for (let i = 0; i < firstDayPadding; i++) {
        currentWeek.push(null);
    }

    dates.forEach(date => {
        currentWeek.push(date);
        if (currentWeek.length === 7) {
            weeks.push(currentWeek);
            currentWeek = [];
        }
    });
    if (currentWeek.length > 0) {
        while(currentWeek.length < 7) currentWeek.push(null);
        weeks.push(currentWeek);
    }

    // Build the calendar
    let calendarHtml = '<div class="calendar-wrapper">';
    
    // Month Labels Row
    calendarHtml += '<div class="months-row" style="grid-template-columns: repeat(' + weeks.length + ', 1fr);">';
    let lastMonth = -1;
    weeks.forEach((week, i) => {
        const firstValidDay = week.find(d => d !== null);
        if (firstValidDay && firstValidDay.getMonth() !== lastMonth) {
            lastMonth = firstValidDay.getMonth();
            const monthName = firstValidDay.toLocaleDateString(currentLang === 'en' ? 'en-US' : 'zh-CN', { month: 'short' });
            calendarHtml += `<div class="month-label" style="grid-column: ${i + 1}">${monthName}</div>`;
        }
    });
    calendarHtml += '</div>';

    // Days Grid (7 rows, N weeks columns)
    calendarHtml += '<div class="days-grid" style="grid-template-columns: repeat(' + weeks.length + ', 1fr);">';
    
    for (let dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
        weeks.forEach((week, weekIdx) => {
            const date = week[dayOfWeek];
            if (!date) {
                calendarHtml += `<div class="heat-box empty"></div>`;
                return;
            }
            
            const dateStr = date.toISOString().split('T')[0];
            const count = s.heatmap[dateStr] || 0;
            
            let intensity = 0;
            if (count > 0) intensity = 1;
            if (count > 2) intensity = 2;
            if (count > 5) intensity = 3;
            if (count > 10) intensity = 4;
            
            calendarHtml += `<div class="heat-box intensity-${intensity}" title="${dateStr}: ${count} commits"></div>`;
        });
    }
    calendarHtml += '</div></div>';

    // Time Distribution HTML (Simple bars)
    const maxTime = Math.max(...Object.values(s.time_dist));
    const timeHtml = Object.keys(s.time_dist).map(key => {
        const val = s.time_dist[key];
        const pct = (val / maxTime) * 100;
        return `
            <div class="time-bar-group">
                <div class="time-label">${s.time_labels[key][currentLang]}</div>
                <div class="time-track">
                    <div class="time-fill" style="width: ${pct}%"></div>
                    <span class="time-val">${val}</span>
                </div>
            </div>
        `;
    }).join('');

    statsContainer.innerHTML = `
        <h2 class="section-title">${s.title[currentLang]}</h2>
        
        <div class="metrics-grid">
            ${metricsHtml}
        </div>

        <div class="charts-grid">
            <div class="chart-box full-width">
                <h3>${s.heatmap_title[currentLang]}</h3>
                <div class="heatmap-container">
                    ${calendarHtml}
                </div>
                <div class="heatmap-legend">
                    <span>Less</span>
                    <div class="heat-box intensity-0"></div>
                    <div class="heat-box intensity-1"></div>
                    <div class="heat-box intensity-2"></div>
                    <div class="heat-box intensity-3"></div>
                    <div class="heat-box intensity-4"></div>
                    <span>More</span>
                </div>
            </div>
            
            <div class="chart-box full-width">
                <h3>${s.time_title[currentLang]}</h3>
                <div class="time-chart">
                    ${timeHtml}
                </div>
            </div>
        </div>
    `;
}

function setupIntersectionObserver() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, {
        threshold: 0.2,
        rootMargin: "0px 0px -50px 0px"
    });

    document.querySelectorAll('.timeline-item').forEach(item => {
        item.classList.remove('visible'); // Reset initially
        observer.observe(item);
    });
}
