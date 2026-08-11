"""
app/services/scoring.py
Transforms raw pipeline output into the exact JSON shape the frontend
(index.html) expects: score, label, metrics, recs, eff, ai.
All numbers are computed deterministically from real findings.

DETERMINISM CONTRACT -- read this before touching a `_*_score()` function:
  - The four `_*_score()` functions below (and everything they call) may
    ONLY read from `pages`, `crawl_errors`, `tech_findings`,
    `security_findings`, and `test_results` -- all of which come from
    mechanical, deterministic analysis (crawling, regex/header checks,
    Playwright DOM checks).
  - They must NEVER read from `content_analysis` or `modernization`
    (the two Groq/AI-generated inputs). AI output is text-generation --
    even at temperature=0 it isn't guaranteed bit-for-bit reproducible --
    so if a score formula depends on e.g. `len(content_analysis["seo_gaps"])`,
    the score itself becomes non-reproducible for the exact same website.
  - AI output may only be used for human-readable explanations/summaries
    (see `_seo_details` etc. below, where AI issues are appended to the
    *display* list, never fed back into `score`).
  - Any list that's shown to the user (issues, recommendations, priority
    actions) must be deduped and sorted by a deterministic key before
    being returned, regardless of what order the AI (or a dict/set)
    happened to produce it in.
"""


def _status(v):
    if v >= 75:
        return "good"
    if v >= 55:
        return "warn"
    return "bad"


def _label(score):
    if score >= 80:
        return "Excellent"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Needs work"


def _security_score(security_findings, tech_findings):
    score = 100
    missing = security_findings.get("headers", {}).get("missing_headers", [])
    score -= min(len(missing) * 12, 60)

    ssl = security_findings.get("ssl", {})
    if not ssl.get("valid", True):
        score -= 25
    elif ssl.get("expiring_soon"):
        score -= 10

    cookie_issues = security_findings.get("cookies", {}).get("issues", [])
    score -= min(len(cookie_issues) * 8, 20)

    mixed = security_findings.get("mixed_content_flags", [])
    score -= min(len(mixed) * 5, 15)

    outdated = tech_findings.get("outdated_signals", [])
    score -= min(len(outdated) * 10, 30)

    return max(0, min(100, round(score)))


def _seo_score(pages):
    """Deterministic SEO score -- based only on crawled page data (titles/
    meta descriptions actually present or missing). No AI input."""
    if not pages:
        return 50
    score = 100
    no_meta = sum(1 for p in pages if not p.get("meta_description"))
    no_title = sum(1 for p in pages if not p.get("title"))
    score -= round((no_meta / len(pages)) * 35)
    score -= round((no_title / len(pages)) * 25)

    return max(0, min(100, round(score)))


def _accessibility_score(pages, test_results):
    """Deterministic accessibility score -- based only on crawled image alt
    data and Playwright's DOM-level lang-attribute check. No AI input."""
    score = 100
    total_images = sum(len(p.get("images", [])) for p in pages)
    missing_alt = sum(
        sum(1 for i in p.get("images", []) if not i.get("has_alt")) for p in pages
    )
    if total_images:
        score -= round((missing_alt / total_images) * 40)

    if isinstance(test_results, dict) and not test_results.get("skipped"):
        summary = test_results.get("summary", {})
        pages_tested = test_results.get("pages_tested", 0) or 1
        missing_lang = summary.get("pages_missing_lang_attr", 0)
        score -= round((missing_lang / pages_tested) * 30)

    return max(0, min(100, round(score)))


def _technical_health_score(pages, crawl_errors, test_results):
    score = 100
    score -= min(len(crawl_errors) * 8, 30)

    if isinstance(test_results, dict) and not test_results.get("skipped"):
        summary = test_results.get("summary", {})
        pages_tested = test_results.get("pages_tested", 0) or 1
        score -= round((summary.get("pages_with_errors", 0) / pages_tested) * 30)
        score -= round((summary.get("pages_with_broken_images", 0) / pages_tested) * 25)

    return max(0, min(100, round(score)))


def _severity_to_badge(severity):
    return {"high": "critical", "medium": "improve", "low": "enhance"}.get(severity, "improve")


_BADGE_TO_PRIORITY = {"critical": "high", "improve": "medium", "enhance": "low",
                       "security": "medium", "efficiency": "low"}


# ---------------------------------------------------------------------
# Detailed per-category report data (SEO / Security / Accessibility /
# Performance) -- powers the expandable report cards on the frontend.
# ---------------------------------------------------------------------

_WHY_IT_MATTERS = {
    "high": "This is a high-impact issue -- left unresolved it can meaningfully hurt "
            "user trust, search rankings, or conversions.",
    "medium": "This moderately affects user experience, search visibility, or site "
              "trustworthiness and is worth fixing soon.",
    "low": "This is a minor issue, but addressing it polishes the overall quality "
           "of the site.",
}


def _why(severity):
    return _WHY_IT_MATTERS.get(severity, _WHY_IT_MATTERS["medium"])


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _priority_rank(item):
    return _PRIORITY_RANK.get(item.get("priority"), 1)


def _dedupe(items, key):
    seen = set()
    out = []
    for item in items:
        k = (item.get(key) or "")[:80]
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    return out


def _finalize(items, text_key):
    """Dedupe + sort a list of issue/recommendation dicts into a stable,
    reproducible order: highest priority first, alphabetically within a
    priority tier. This is what keeps display order identical run-to-run
    even when an upstream source (the AI, or a dict/set) returns its
    items in a different order each time -- we never trust that order."""
    deduped = _dedupe(items, text_key)
    return sorted(deduped, key=lambda item: (_priority_rank(item), (item.get(text_key) or "").lower()))


def _classify_issue(issue, recommendation=""):
    """Best-effort keyword categorisation for the general content/UX
    issues the AI returns, so they land under the right report card."""
    text = f"{issue} {recommendation}".lower()
    if any(k in text for k in ("alt text", "alt attribute", "accessib", "aria", "contrast",
                                "screen reader", "lang attribute", "keyboard nav")):
        return "accessibility"
    if any(k in text for k in ("seo", "meta description", "title tag", "keyword",
                                "sitemap", "canonical", "heading structure", "h1")):
        return "seo"
    if any(k in text for k in ("security", "ssl", "https", "header", "cookie",
                                "xss", "vulnerab", "csrf", "injection")):
        return "security"
    return "performance"


def _general_issues_by_category(content_analysis):
    buckets = {"seo": [], "security": [], "accessibility": [], "performance": []}
    if not isinstance(content_analysis, dict):
        return buckets
    # Sort by (page_url, issue text) before classifying: the AI can
    # return this array in a different order each call for identical
    # input, so we never rely on its order -- only on its content.
    raw_issues = sorted(
        content_analysis.get("issues", []),
        key=lambda i: (i.get("page_url", ""), i.get("issue", "")),
    )
    for issue in raw_issues:
        cat = _classify_issue(issue.get("issue", ""), issue.get("recommendation", ""))
        severity = issue.get("severity", "medium")
        buckets[cat].append({
            "problem": issue.get("issue", "Issue found"),
            "why_it_matters": _why(severity),
            "priority": severity,
            "_rec": issue.get("recommendation", ""),
        })
    return buckets


def _seo_details(pages, content_analysis, general_issues):
    score = _seo_score(pages)
    no_title = [p["url"] for p in pages if not p.get("title")]
    no_meta = [p["url"] for p in pages if not p.get("meta_description")]

    issues, recs = [], []
    if no_title:
        priority = "high" if pages and len(no_title) > len(pages) / 2 else "medium"
        issues.append({"problem": f"{len(no_title)} of {len(pages)} page(s) are missing a <title> tag.",
                        "why_it_matters": _why(priority), "priority": priority})
        recs.append({"text": "Add a unique, descriptive <title> tag to every page.", "priority": priority})
    if no_meta:
        priority = "medium"
        issues.append({"problem": f"{len(no_meta)} of {len(pages)} page(s) are missing a meta description.",
                        "why_it_matters": _why(priority), "priority": priority})
        recs.append({"text": "Write a unique ~150-160 character meta description for each page.", "priority": priority})

    seo_gaps = content_analysis.get("seo_gaps", []) if isinstance(content_analysis, dict) else []
    for gap in seo_gaps:
        issues.append({"problem": gap, "why_it_matters": _why("medium"), "priority": "medium"})

    for item in general_issues.get("seo", []):
        issues.append({"problem": item["problem"], "why_it_matters": item["why_it_matters"], "priority": item["priority"]})
        if item["_rec"]:
            recs.append({"text": item["_rec"], "priority": item["priority"]})

    if not issues:
        issues.append({"problem": "No major SEO issues detected on the crawled pages.",
                        "why_it_matters": "Solid on-page SEO fundamentals help pages get found in search.",
                        "priority": "low"})
    if not recs:
        recs.append({"text": "Keep monitoring titles, meta descriptions, and heading structure as content changes.",
                      "priority": "low"})

    summary = (f"SEO scored {score}/100. " +
               (f"{len(no_title)} page(s) missing titles and {len(no_meta)} missing meta descriptions out of "
                f"{len(pages)} crawled." if pages else "No pages could be crawled to evaluate SEO."))

    return {"score": score, "summary": summary,
            "issues": _finalize(issues, "problem")[:8],
            "recommendations": _finalize(recs, "text")[:8]}


def _security_details(security_findings, tech_findings, general_issues):
    score = _security_score(security_findings, tech_findings)
    issues, recs = [], []

    missing = security_findings.get("headers", {}).get("missing_headers", [])
    for m in missing:
        issues.append({"problem": f"Missing {m['header']} response header.",
                        "why_it_matters": m.get("risk", _why("medium")), "priority": "medium"})
        recs.append({"text": f"Add the {m['header']} response header.", "priority": "medium"})

    ssl = security_findings.get("ssl", {})
    if not ssl.get("valid", True):
        issues.append({"problem": "SSL/TLS certificate is invalid or could not be verified.",
                        "why_it_matters": "Without a valid certificate, browsers warn visitors the site is "
                                           "insecure and data in transit is not protected.",
                        "priority": "high"})
        recs.append({"text": "Install a valid SSL/TLS certificate (e.g. via Let's Encrypt).", "priority": "high"})
    elif ssl.get("expiring_soon"):
        issues.append({"problem": f"SSL certificate expires soon ({ssl.get('days_until_expiry')} day(s) left).",
                        "why_it_matters": "An expired certificate breaks HTTPS entirely and shows visitors a "
                                           "security warning.",
                        "priority": "medium"})
        recs.append({"text": "Renew the SSL certificate before it expires, ideally with auto-renewal.", "priority": "medium"})

    for issue in security_findings.get("cookies", {}).get("issues", []):
        issues.append({"problem": issue, "why_it_matters": "Cookies without the Secure/HttpOnly flags can be "
                                                             "intercepted or read by client-side scripts.",
                        "priority": "medium"})
        recs.append({"text": "Set the Secure and HttpOnly flags on all session/auth cookies.", "priority": "medium"})

    mixed = security_findings.get("mixed_content_flags", [])
    if mixed:
        issues.append({"problem": f"{len(mixed)} instance(s) of mixed content detected (HTTP resources on an HTTPS page).",
                        "why_it_matters": "Browsers may block mixed content, and it opens a path for "
                                           "man-in-the-middle tampering.",
                        "priority": "medium"})
        recs.append({"text": "Serve all page resources (scripts, images, styles) over HTTPS.", "priority": "medium"})

    for signal in tech_findings.get("outdated_signals", []):
        issues.append({"problem": signal, "why_it_matters": "Outdated software versions are a common, well "
                                                              "documented attack vector.",
                        "priority": "medium"})
        recs.append({"text": "Upgrade or stop exposing outdated server/software versions in response headers.", "priority": "medium"})

    for item in general_issues.get("security", []):
        issues.append({"problem": item["problem"], "why_it_matters": item["why_it_matters"], "priority": item["priority"]})
        if item["_rec"]:
            recs.append({"text": item["_rec"], "priority": item["priority"]})

    if not issues:
        issues.append({"problem": "No major security issues detected by the passive scan.",
                        "why_it_matters": "A clean passive scan is a good sign, though it doesn't replace a full penetration test.",
                        "priority": "low"})
    if not recs:
        recs.append({"text": "Continue monitoring headers, certificates, and dependencies over time.", "priority": "low"})

    summary = f"Security scored {score}/100, based on {len(missing)} missing recommended header(s) and the site's SSL/cookie posture."

    return {"score": score, "summary": summary,
            "issues": _finalize(issues, "problem")[:8],
            "recommendations": _finalize(recs, "text")[:8]}


def _accessibility_details(pages, content_analysis, test_results, general_issues):
    score = _accessibility_score(pages, test_results)
    issues, recs = [], []

    total_images = sum(len(p.get("images", [])) for p in pages)
    missing_alt = sum(sum(1 for i in p.get("images", []) if not i.get("has_alt")) for p in pages)
    if total_images and missing_alt:
        priority = "high" if missing_alt > total_images / 2 else "medium"
        issues.append({"problem": f"{missing_alt} of {total_images} image(s) are missing alt text.",
                        "why_it_matters": "Screen readers rely on alt text to describe images to visually "
                                           "impaired visitors; without it, content is inaccessible to them.",
                        "priority": priority})
        recs.append({"text": "Add descriptive alt text to every meaningful image (empty alt=\"\" for purely decorative ones).",
                      "priority": priority})

    for gap in (content_analysis.get("accessibility_gaps", []) if isinstance(content_analysis, dict) else []):
        issues.append({"problem": gap, "why_it_matters": _why("medium"), "priority": "medium"})

    if isinstance(test_results, dict) and not test_results.get("skipped"):
        summary_t = test_results.get("summary", {})
        missing_lang = summary_t.get("pages_missing_lang_attr", 0)
        if missing_lang:
            issues.append({"problem": f"{missing_lang} page(s) are missing the lang attribute on <html>.",
                            "why_it_matters": "The lang attribute tells assistive technology (and translators) "
                                               "what language to use; without it, screen readers may mispronounce content.",
                            "priority": "medium"})
            recs.append({"text": 'Add lang="en" (or the appropriate language code) to the <html> tag.', "priority": "medium"})

    for item in general_issues.get("accessibility", []):
        issues.append({"problem": item["problem"], "why_it_matters": item["why_it_matters"], "priority": item["priority"]})
        if item["_rec"]:
            recs.append({"text": item["_rec"], "priority": item["priority"]})

    if not issues:
        issues.append({"problem": "No major accessibility issues detected.",
                        "why_it_matters": "Good accessibility widens your audience and is often a legal requirement.",
                        "priority": "low"})
    if not recs:
        recs.append({"text": "Periodically re-test with a screen reader and automated accessibility tooling.", "priority": "low"})

    summary = f"Accessibility scored {score}/100. {missing_alt} of {total_images} images are missing alt text."

    return {"score": score, "summary": summary,
            "issues": _finalize(issues, "problem")[:8],
            "recommendations": _finalize(recs, "text")[:8]}


def _performance_details(pages, crawl_errors, test_results, tech_findings, content_analysis, general_issues):
    score = _technical_health_score(pages, crawl_errors, test_results)
    issues, recs = [], []

    if crawl_errors:
        issues.append({"problem": f"{len(crawl_errors)} page(s) could not be crawled successfully.",
                        "why_it_matters": "Pages that fail to load reliably hurt both user experience and "
                                           "search engine crawlability.",
                        "priority": "high" if len(crawl_errors) > 2 else "medium"})
        recs.append({"text": "Investigate and fix the failing URLs (broken links, timeouts, or server errors).", "priority": "medium"})

    if isinstance(test_results, dict) and not test_results.get("skipped") and not test_results.get("error"):
        summary_t = test_results.get("summary", {})
        pages_tested = test_results.get("pages_tested", 0) or 1
        if summary_t.get("pages_with_errors"):
            issues.append({"problem": f"{summary_t['pages_with_errors']} of {pages_tested} page(s) throw JavaScript console errors.",
                            "why_it_matters": "Console errors often indicate broken functionality that visitors "
                                               "will also experience.",
                            "priority": "medium"})
            recs.append({"text": "Open the browser console on the affected pages and resolve the reported errors.", "priority": "medium"})
        if summary_t.get("pages_with_broken_images"):
            issues.append({"problem": f"{summary_t['pages_with_broken_images']} of {pages_tested} page(s) have broken images.",
                            "why_it_matters": "Broken images look unpolished and can signal deeper content or CDN issues.",
                            "priority": "medium"})
            recs.append({"text": "Fix or replace broken image references.", "priority": "medium"})
    elif isinstance(test_results, dict) and test_results.get("error"):
        issues.append({"problem": "Automated browser tests could not run.",
                        "why_it_matters": "Without this check, some load-time and rendering issues may go undetected.",
                        "priority": "low"})

    for pattern in (content_analysis.get("outdated_patterns", []) if isinstance(content_analysis, dict) else []):
        issues.append({"problem": pattern, "why_it_matters": _why("low"), "priority": "low"})

    for item in general_issues.get("performance", []):
        issues.append({"problem": item["problem"], "why_it_matters": item["why_it_matters"], "priority": item["priority"]})
        if item["_rec"]:
            recs.append({"text": item["_rec"], "priority": item["priority"]})

    if not issues:
        issues.append({"problem": "No major technical/performance issues detected.",
                        "why_it_matters": "A technically healthy site loads reliably and keeps visitors engaged.",
                        "priority": "low"})
    if not recs:
        recs.append({"text": "Re-run this audit periodically as the site changes.", "priority": "low"})

    summary = f"Technical health / performance scored {score}/100, based on crawl reliability and automated browser checks."

    return {"score": score, "summary": summary,
            "issues": _finalize(issues, "problem")[:8],
            "recommendations": _finalize(recs, "text")[:8]}


def _build_recs(content_analysis, security_findings, modernization):
    recs = []

    if isinstance(content_analysis, dict):
        # Sort before taking the top 5: the AI can return `issues` in a
        # different order each call for identical input, so "the first 5"
        # must be chosen by a stable key, not by array position.
        ai_issues = sorted(
            content_analysis.get("issues", []),
            key=lambda i: (_PRIORITY_RANK.get(i.get("severity"), 1), i.get("issue", "")),
        )
        for issue in ai_issues[:5]:
            recs.append({
                "t": issue.get("issue", "Issue found")[:70],
                "b": _severity_to_badge(issue.get("severity", "medium")),
                "d": issue.get("recommendation", ""),
                "a": issue.get("recommendation", "Review and fix")[:60],
            })

    # missing_headers comes from a fixed, literal dict (EXPECTED_HEADERS
    # in analyze.py) iterated in a fixed order -- already deterministic.
    missing_headers = security_findings.get("headers", {}).get("missing_headers", [])
    for m in missing_headers[:4]:
        recs.append({
            "t": f"Add {m['header']} header",
            "b": "security",
            "d": m["risk"],
            "a": f"Set the {m['header']} response header",
        })

    if isinstance(modernization, dict):
        ai_priorities = sorted(
            modernization.get("security_priorities", []),
            key=lambda sp: (_PRIORITY_RANK.get(sp.get("severity"), 1), sp.get("finding", "")),
        )
        for sp in ai_priorities[:4]:
            recs.append({
                "t": sp.get("finding", "Security finding")[:70],
                "b": _severity_to_badge(sp.get("severity", "medium")),
                "d": sp.get("fix", ""),
                "a": sp.get("fix", "")[:60],
            })

    recs = _dedupe(recs, "t")
    recs.sort(key=lambda r: (_PRIORITY_RANK.get(_BADGE_TO_PRIORITY.get(r["b"], "medium"), 1), r["t"]))

    return recs[:10] or [{
        "t": "No major issues detected",
        "b": "enhance",
        "d": "The automated checks did not surface high-priority issues on the crawled pages.",
        "a": "Re-run with more pages crawled for deeper coverage",
    }]


def _build_efficiency(modernization):
    eff = []
    if isinstance(modernization, dict):
        for rec in modernization.get("modernization_recommendations", []):
            if rec.get("effort") == "low":
                eff.append({
                    "t": rec.get("area", "Improvement")[:70],
                    "b": "efficiency",
                    "d": rec.get("recommendation", ""),
                    "a": rec.get("recommendation", "")[:60],
                })
    return eff[:6] or [{
        "t": "No quick efficiency wins flagged",
        "b": "efficiency",
        "d": "Nothing low-effort surfaced in this scan. Higher-effort modernization items may still apply.",
        "a": "See Quick Wins in the full report",
    }]


def _build_ai_suggestions(domain):
    return [
        {
            "ico": "🤖", "cat": "UX", "t": "AI chatbot assistant",
            "d": f"Help visitors find what they need on {domain} without digging through menus.",
            "impl": "Embed a chat widget backed by an LLM using retrieval-augmented generation over your site content.",
        },
        {
            "ico": "🔍", "cat": "Search", "t": "Semantic search",
            "d": "Replace exact keyword search with something that understands intent and synonyms.",
            "impl": "Embed page content as vectors (e.g. with a sentence-embedding model) and retrieve nearest neighbours per query.",
        },
        {
            "ico": "👤", "cat": "Personalisation", "t": "AI content personalisation",
            "d": "Surface the most relevant content to each visitor based on behavior.",
            "impl": "Build a lightweight recommendation layer using session/browsing data, served at request time.",
        },
    ]


_CATEGORY_TITLES = {"seo": "SEO", "security": "Security", "accessibility": "Accessibility", "performance": "Performance"}

_BUSINESS_IMPACT = {
    "seo": "Weak SEO means fewer people find {domain} through search, which directly limits organic traffic and leads.",
    "security": "Security gaps put visitor data and {domain}'s reputation at risk, and can trigger browser warnings that scare off visitors.",
    "accessibility": "Poor accessibility excludes visitors with disabilities and can create legal/compliance exposure for {domain}.",
    "performance": "Technical reliability issues cause frustration and drop-off -- visitors who hit errors rarely come back.",
}


def _build_overall(domain, categories, content_analysis, modernization):
    exec_summary = None
    if isinstance(content_analysis, dict):
        exec_summary = content_analysis.get("summary")
    if not exec_summary:
        overall_score = round(sum(c["score"] for c in categories.values()) / len(categories))
        exec_summary = (f"{domain} scored {overall_score}/100 overall across SEO, security, accessibility, "
                         f"and technical health. See the category breakdowns below for specifics.")

    strengths, weaknesses, business_impact = [], [], []
    for key, cat in categories.items():
        title = _CATEGORY_TITLES[key]
        real_issue_count = sum(1 for i in cat["issues"] if i.get("priority") in ("high", "medium"))
        if cat["score"] >= 75:
            strengths.append(f"{title} is in good shape ({cat['score']}/100) with no major issues found.")
        elif cat["score"] < 55:
            top_issue = cat["issues"][0]["problem"] if cat["issues"] else "multiple issues"
            weaknesses.append(f"{title} needs attention ({cat['score']}/100) -- top issue: {top_issue}")
            business_impact.append(_BUSINESS_IMPACT[key].format(domain=domain))
        elif real_issue_count:
            weaknesses.append(f"{title} is fair ({cat['score']}/100) with room to improve -- {real_issue_count} issue(s) flagged.")

    if not strengths:
        strengths.append("No category scored high enough yet to call out as a standout strength -- "
                          "focus on the priority actions below to build one.")
    if not weaknesses:
        weaknesses.append("No category is currently in poor shape -- keep an eye on the medium-priority items to stay ahead.")
    if not business_impact:
        business_impact.append(f"{domain} is not currently exposed to major risk from the areas scanned; "
                                f"continue to monitor as the site evolves.")

    priority_actions = []
    for key, cat in categories.items():
        for issue, rec in zip(cat["issues"], cat["recommendations"] + [None] * len(cat["issues"])):
            if issue.get("priority") == "high":
                priority_actions.append({
                    "category": _CATEGORY_TITLES[key],
                    "action": (rec["text"] if rec else issue["problem"]),
                    "priority": "high",
                })
    if not priority_actions:
        for key, cat in categories.items():
            for issue, rec in zip(cat["issues"], cat["recommendations"] + [None] * len(cat["issues"])):
                if issue.get("priority") == "medium":
                    priority_actions.append({
                        "category": _CATEGORY_TITLES[key],
                        "action": (rec["text"] if rec else issue["problem"]),
                        "priority": "medium",
                    })
    priority_actions = priority_actions[:8] or [{
        "category": "General", "action": "No urgent action items -- re-run the audit periodically.", "priority": "low",
    }]

    modernization_recs = []
    if isinstance(modernization, dict):
        modernization_recs = modernization.get("modernization_recommendations", [])

    return {
        "executive_summary": exec_summary,
        "strengths": strengths[:6],
        "weaknesses": weaknesses[:6],
        "business_impact": business_impact[:6],
        "ai_suggestions": _build_ai_suggestions(domain),
        "modernization": modernization_recs,
        "priority_actions": priority_actions,
    }


def build_frontend_data(domain, pages, crawl_errors, tech_findings,
                         security_findings, content_analysis,
                         modernization, test_results):
    perf = _technical_health_score(pages, crawl_errors, test_results)
    sec = _security_score(security_findings, tech_findings)
    seo = _seo_score(pages)
    a11y = _accessibility_score(pages, test_results)

    score = round((perf + sec + seo + a11y) / 4)

    general_issues = _general_issues_by_category(content_analysis)
    categories = {
        "seo": _seo_details(pages, content_analysis, general_issues),
        "security": _security_details(security_findings, tech_findings, general_issues),
        "accessibility": _accessibility_details(pages, content_analysis, test_results, general_issues),
        "performance": _performance_details(pages, crawl_errors, test_results, tech_findings, content_analysis, general_issues),
    }

    return {
        "score": score,
        "label": _label(score),
        "metrics": [
            {"l": "Technical health", "v": f"{perf}/100", "s": _status(perf)},
            {"l": "Security", "v": f"{sec}/100", "s": _status(sec)},
            {"l": "SEO", "v": f"{seo}/100", "s": _status(seo)},
            {"l": "Accessibility", "v": f"{a11y}/100", "s": _status(a11y)},
        ],
        "recs": _build_recs(content_analysis, security_findings, modernization),
        "eff": _build_efficiency(modernization),
        "ai": _build_ai_suggestions(domain),
        "categories": categories,
        "overall": _build_overall(domain, categories, content_analysis, modernization),
    }
