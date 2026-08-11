const button = document.getElementById("analyzeBtn");
const urlInput = document.getElementById("websiteURL");
const progress = document.querySelector(".progress-fill");
const status = document.getElementById("statusText");
const resultCards = document.querySelectorAll(".result-card");
const categoryDetail = document.getElementById("categoryDetail");
const overallAssessment = document.getElementById("overallAssessment");
const overallContent = document.getElementById("overallContent");
const errorBanner = document.getElementById("errorBanner");

const CATEGORY_LABELS = {
    seo: "SEO",
    security: "Security",
    accessibility: "Accessibility",
    performance: "Performance",
};

const messages = [
    "Crawling the site...",
    "Checking SEO...",
    "Checking Security...",
    "Checking Accessibility...",
    "Generating AI report...",
];

let fakeProgressTimer = null;
let latestCategories = null;
let activeCategory = null;

function startFakeProgress() {
    let width = 0;
    let index = 0;
    progress.style.width = "0%";
    fakeProgressTimer = setInterval(() => {
        if (width < 90) {
            width += 8;
            progress.style.width = width + "%";
        }
        if (index < messages.length) {
            status.innerHTML = messages[index];
            index++;
        }
    }, 1200);
}

function stopFakeProgress() {
    if (fakeProgressTimer) {
        clearInterval(fakeProgressTimer);
        fakeProgressTimer = null;
    }
}

function scoreFor(metrics, label) {
    const m = metrics.find((x) => x.l === label);
    if (!m) return "—";
    return m.v.split("/")[0] + "%";
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function showError(message) {
    errorBanner.innerHTML = escapeHtml(message);
    errorBanner.hidden = false;
}

function clearError() {
    errorBanner.hidden = true;
    errorBanner.innerHTML = "";
}

function priorityBadge(priority) {
    const p = (priority || "medium").toLowerCase();
    const cls = p === "high" ? "badge-high" : p === "low" ? "badge-low" : "badge-medium";
    return `<span class="badge ${cls}">${escapeHtml(p)} priority</span>`;
}

function renderCategoryDetail(key) {
    if (!latestCategories || !latestCategories[key]) {
        categoryDetail.hidden = true;
        return;
    }
    const cat = latestCategories[key];
    const label = CATEGORY_LABELS[key] || key;

    const issuesHtml = (cat.issues || []).map((issue) => `
        <li class="detail-item">
            <div class="detail-item-head">
                <span class="detail-item-title">${escapeHtml(issue.problem)}</span>
                ${priorityBadge(issue.priority)}
            </div>
            <p class="detail-item-why">${escapeHtml(issue.why_it_matters)}</p>
        </li>
    `).join("");

    const recsHtml = (cat.recommendations || []).map((rec) => `
        <li class="detail-item">
            <div class="detail-item-head">
                <span class="detail-item-title">${escapeHtml(rec.text)}</span>
                ${priorityBadge(rec.priority)}
            </div>
        </li>
    `).join("");

    categoryDetail.innerHTML = `
        <div class="detail-header">
            <h2>${escapeHtml(label)} Report</h2>
            <span class="detail-score">${cat.score}/100</span>
        </div>
        <p class="detail-summary">${escapeHtml(cat.summary)}</p>
        <div class="detail-columns">
            <div class="detail-column">
                <h4>Problems Detected</h4>
                <ul class="detail-list">${issuesHtml || "<li class=\"detail-item\">No issues to show.</li>"}</ul>
            </div>
            <div class="detail-column">
                <h4>Recommendations</h4>
                <ul class="detail-list">${recsHtml || "<li class=\"detail-item\">No recommendations to show.</li>"}</ul>
            </div>
        </div>
    `;
    categoryDetail.hidden = false;
}

function setActiveCard(key) {
    resultCards.forEach((card) => {
        const isActive = card.dataset.category === key;
        card.classList.toggle("active", isActive);
        card.setAttribute("aria-expanded", isActive ? "true" : "false");
    });
}

function handleCardClick(card) {
    const key = card.dataset.category;
    if (!latestCategories) return;

    if (activeCategory === key) {
        activeCategory = null;
        categoryDetail.hidden = true;
        setActiveCard(null);
        return;
    }

    activeCategory = key;
    setActiveCard(key);
    renderCategoryDetail(key);
    categoryDetail.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

resultCards.forEach((card) => {
    card.addEventListener("click", () => handleCardClick(card));
    card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleCardClick(card);
        }
    });
});

function renderOverall(overall) {
    if (!overall) {
        overallAssessment.hidden = true;
        return;
    }

    const listOrFallback = (items, fallback) => {
        if (!items || !items.length) return `<li>${escapeHtml(fallback)}</li>`;
        return items.map((i) => `<li>${escapeHtml(i)}</li>`).join("");
    };

    const aiSuggestionsHtml = (overall.ai_suggestions || []).map((s) => `
        <div class="ai-suggestion">
            <span class="ai-suggestion-icon">${s.ico || "\ud83d\udca1"}</span>
            <div>
                <strong>${escapeHtml(s.t)}</strong>
                <p>${escapeHtml(s.d)}</p>
            </div>
        </div>
    `).join("");

    const modernizationHtml = (overall.modernization || []).map((m) => `
        <li class="detail-item">
            <div class="detail-item-head">
                <span class="detail-item-title">${escapeHtml(m.area || "Improvement")}</span>
                ${m.effort ? `<span class="badge badge-medium">${escapeHtml(m.effort)} effort</span>` : ""}
            </div>
            <p class="detail-item-why">${escapeHtml(m.recommendation || "")}</p>
        </li>
    `).join("") || "<li class=\"detail-item\">No modernization recommendations available.</li>";

    const priorityHtml = (overall.priority_actions || []).map((p) => `
        <li class="detail-item">
            <div class="detail-item-head">
                <span class="detail-item-title">[${escapeHtml(p.category)}] ${escapeHtml(p.action)}</span>
                ${priorityBadge(p.priority)}
            </div>
        </li>
    `).join("") || "<li class=\"detail-item\">No priority actions right now.</li>";

    overallContent.innerHTML = `
        <div class="overall-block">
            <h4>Executive Summary</h4>
            <p>${escapeHtml(overall.executive_summary)}</p>
        </div>
        <div class="overall-grid">
            <div class="overall-block">
                <h4>Strengths</h4>
                <ul>${listOrFallback(overall.strengths, "None identified.")}</ul>
            </div>
            <div class="overall-block">
                <h4>Weaknesses</h4>
                <ul>${listOrFallback(overall.weaknesses, "None identified.")}</ul>
            </div>
        </div>
        <div class="overall-block">
            <h4>Business Impact</h4>
            <ul>${listOrFallback(overall.business_impact, "No significant impact identified.")}</ul>
        </div>
        <div class="overall-block">
            <h4>AI-Generated Improvement Suggestions</h4>
            <div class="ai-suggestions">${aiSuggestionsHtml || "<p>No suggestions available.</p>"}</div>
        </div>
        <div class="overall-block">
            <h4>Website Modernization Recommendations</h4>
            <ul class="detail-list">${modernizationHtml}</ul>
        </div>
        <div class="overall-block">
            <h4>Priority Action Items</h4>
            <ul class="detail-list">${priorityHtml}</ul>
        </div>
    `;
    overallAssessment.hidden = false;
}

button.addEventListener("click", () => {
    const url = urlInput.value.trim();
    if (!url) {
        alert("Please enter a website URL.");
        return;
    }

    clearError();
    categoryDetail.hidden = true;
    overallAssessment.hidden = true;
    latestCategories = null;
    activeCategory = null;
    setActiveCard(null);

    button.disabled = true;
    startFakeProgress();

    fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url }),
    })
        .then((r) => r.json().then((data) => ({ ok: r.ok, data: data })))
        .then((res) => {
            stopFakeProgress();
            button.disabled = false;

            if (!res.ok) {
                progress.style.width = "0%";
                status.innerHTML = "Analysis failed ✗";
                showError(res.data.error || "Analysis failed. Please try again.");
                return;
            }

            const payload = res.data.data || {};
            const metrics = payload.metrics || [];
            progress.style.width = "100%";
            status.innerHTML = "Analysis Complete ✔";

            document.getElementById("seoScore").innerHTML = scoreFor(metrics, "SEO");
            document.getElementById("securityScore").innerHTML = scoreFor(metrics, "Security");
            document.getElementById("accessibilityScore").innerHTML = scoreFor(metrics, "Accessibility");
            document.getElementById("performanceScore").innerHTML = scoreFor(metrics, "Technical health");

            try {
                if (payload.categories) {
                    latestCategories = payload.categories;
                } else {
                    showError("Detailed category breakdown is unavailable for this scan, but the scores above are accurate.");
                }
                if (payload.overall) {
                    renderOverall(payload.overall);
                }
            } catch (err) {
                console.error("Failed to render detailed report:", err);
                showError("We couldn't render the detailed report, but your scores above are accurate.");
            }
        })
        .catch(() => {
            stopFakeProgress();
            button.disabled = false;
            progress.style.width = "0%";
            status.innerHTML = "Could not reach the server ✗";
            showError("Could not reach the server. Please check your connection and try again.");
        });
});
