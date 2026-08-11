"""
app/services/ai_insights.py
Uses the Groq API (free tier) to turn raw crawl/security/tech data into
human-readable analysis: content & UX critique, modernization
recommendations, and a final synthesized report.

IMPORTANT (determinism): everything returned from this module is TEXT/
EXPLANATION ONLY -- issue descriptions, summaries, recommendation wording.
None of it is allowed to feed into a numeric score. See the comment at
the top of app/services/scoring.py for why, and don't reintroduce
`len(content_analysis["..."])`-style deductions there.
"""
import json
import traceback

from groq import Groq

from app.config import Config

MODEL = "llama-3.3-70b-versatile"

client = Groq(api_key=Config.GROQ_API_KEY) if Config.GROQ_API_KEY else None


class AIUnavailableError(Exception):
    """Raised (and caught by the callers below) when the Groq API call
    itself fails -- network issue, rate limit, bad key, etc. Callers
    turn this into a graceful fallback instead of crashing the pipeline."""


def _ask_ai(system, user_prompt, max_tokens=2000):
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=max_tokens,
            # temperature=0 + a fixed seed make the model's sampling as
            # deterministic as the provider allows -- this reduces
            # run-to-run wording/ordering drift in the AI's text, but it
            # is a *best-effort* setting, not a guarantee: LLM inference
            # can still vary slightly between calls (batching, floating
            # point non-associativity on the provider's GPUs, etc), and
            # Groq's `seed` support is itself best-effort. This is exactly
            # why numeric scoring must never depend on AI output (see
            # scoring.py) -- these settings only make the *text* more
            # stable, they can't make it perfectly reproducible.
            temperature=0,
            seed=42,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content
    except Exception as e:
        # Technical detail stays server-side; callers surface a friendly note instead.
        print(f"[ai_insights] Groq API call failed: {e}")
        traceback.print_exc()
        raise AIUnavailableError(str(e)) from e


def analyze_content_and_ux(pages):
    condensed = [
        {
            "url": p["url"],
            "title": p["title"],
            "meta_description": p["meta_description"],
            "word_count": p["word_count"],
            "images_missing_alt": sum(1 for i in p["images"] if not i["has_alt"]),
            "total_images": len(p["images"]),
            "text_excerpt": p["text"][:1500],
        }
        for p in pages
    ]

    system = (
        "You are a senior UX/content auditor. You review website page data "
        "and identify concrete, prioritized issues around clarity, SEO "
        "fundamentals, accessibility, and outdated design/copy patterns. "
        "Be specific and reference actual page URLs. Output valid JSON only."
    )
    user_prompt = f"""
Here is crawled page data (JSON): {json.dumps(condensed, indent=2)}

Analyze it and return ONLY a JSON object with this shape:
{{
  "summary": "2-3 sentence overall impression",
  "issues": [
    {{"page_url": "...", "issue": "...", "severity": "high|medium|low", "recommendation": "..."}}
  ],
  "seo_gaps": ["..."],
  "accessibility_gaps": ["..."],
  "outdated_patterns": ["..."]
}}
No markdown, no commentary outside the JSON.
"""
    if not client:
        return {"raw_output": None, "parse_error": True, "note": "GROQ_API_KEY not set",
                "summary": "AI content analysis is unavailable right now (no API key configured)."}
    try:
        raw = _ask_ai(system, user_prompt, max_tokens=3000)
    except AIUnavailableError:
        return {"raw_output": None, "parse_error": True, "note": "AI service unavailable",
                "summary": "AI content analysis couldn't be completed for this scan. "
                            "Other results below are still accurate."}
    return _safe_json(raw)


def analyze_tech_modernization(tech_findings, security_findings):
    system = (
        "You are a web infrastructure consultant. Given detected "
        "technologies and security scan results, recommend modernization "
        "steps: what to upgrade, why it matters, effort estimate "
        "(low/medium/high), and risk of not acting. Output valid JSON only."
    )
    user_prompt = f"""
Detected technologies: {json.dumps(tech_findings, indent=2)}
Security scan findings: {json.dumps(security_findings, indent=2, default=str)}

Return ONLY a JSON object:
{{
  "modernization_recommendations": [
    {{"area": "...", "current_state": "...", "recommendation": "...",
      "effort": "low|medium|high", "risk_if_ignored": "..."}}
  ],
  "security_priorities": [
    {{"finding": "...", "severity": "high|medium|low", "fix": "..."}}
  ]
}}
No markdown, no commentary outside the JSON.
"""
    if not client:
        return {"raw_output": None, "parse_error": True, "note": "GROQ_API_KEY not set"}
    try:
        raw = _ask_ai(system, user_prompt, max_tokens=2500)
    except AIUnavailableError:
        return {"raw_output": None, "parse_error": True, "note": "AI service unavailable",
                "modernization_recommendations": [], "security_priorities": []}
    return _safe_json(raw)


def synthesize_final_report(crawl_summary, tech_findings, security_findings,
                             content_analysis, modernization, test_results):
    system = (
        "You are a consulting lead producing a final client-ready website "
        "audit report. Combine all inputs into a clear, prioritized action "
        "plan. Use markdown with headers. Be concise but concrete. Group "
        "recommendations into Quick Wins (low effort) and Strategic "
        "Investments (higher effort, higher impact)."
    )
    user_prompt = f"""
CRAWL SUMMARY: {json.dumps(crawl_summary, indent=2)}
TECH STACK FINDINGS: {json.dumps(tech_findings, indent=2)}
SECURITY FINDINGS: {json.dumps(security_findings, indent=2, default=str)}
CONTENT/UX ANALYSIS: {json.dumps(content_analysis, indent=2)}
MODERNIZATION RECOMMENDATIONS: {json.dumps(modernization, indent=2)}
AUTOMATED TEST RESULTS: {json.dumps(test_results, indent=2)}

Write the final markdown report with these sections:
# Website Audit Report
## Executive Summary
## Security Findings
## Technology & Modernization
## Content & UX
## Automated Test Results
## Quick Wins (do this week)
## Strategic Investments (plan this quarter)
"""
    if not client:
        return "AI report unavailable: GROQ_API_KEY not set."
    try:
        return _ask_ai(system, user_prompt, max_tokens=4000)
    except AIUnavailableError:
        return "The AI-written summary couldn't be generated for this scan, but the structured results above are accurate."


def _safe_json(raw_text):
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"raw_output": raw_text, "parse_error": True}
