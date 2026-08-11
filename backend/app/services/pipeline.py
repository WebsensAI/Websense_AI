"""
app/services/pipeline.py
Runs every stage in order and returns the combined raw results:
crawl -> analyze (tech + security) -> ai_insights -> browser_tests.
This is what app/routes/routes.py calls for POST /api/analyze.
"""
import traceback

from app.services.crawl import crawl_site
from app.services.analyze import detect_technologies, run_security_scan
from app.services.ai_insights import analyze_content_and_ux, analyze_tech_modernization
from app.services.browser_tests import run_tests


def run_pipeline_core(start_url, max_pages=15, skip_tests=False, progress_cb=None):
    def _progress(n, msg):
        print(msg)
        if progress_cb:
            progress_cb(n, msg)

    _progress(1, f"[1/6] Crawling {start_url} (max {max_pages} pages)...")
    try:
        crawl_result = crawl_site(start_url, max_pages=max_pages)
    except Exception as e:
        # A total crawl failure (e.g. DNS resolution error) still leaves us
        # able to report *something* rather than a raw 500 to the frontend.
        print(f"[pipeline] Crawl stage failed unexpectedly: {e}")
        traceback.print_exc()
        crawl_result = {"pages": [], "errors": [{"url": start_url, "error": "Could not crawl this site."}]}
    pages = crawl_result["pages"]
    print(f"      -> {len(pages)} pages crawled, {len(crawl_result['errors'])} errors")

    _progress(2, "[2/6] Detecting technology stack...")
    try:
        tech_findings = detect_technologies(pages)
    except Exception as e:
        print(f"[pipeline] Tech detection failed: {e}")
        traceback.print_exc()
        tech_findings = {"technologies": {}, "header_hints": {}, "outdated_signals": []}

    _progress(3, "[3/6] Running passive security checks...")
    try:
        security_findings = run_security_scan(start_url, pages)
    except Exception as e:
        print(f"[pipeline] Security scan failed: {e}")
        traceback.print_exc()
        security_findings = {"ssl": {"valid": True}, "headers": {"missing_headers": [], "present_headers": {}},
                              "cookies": {"issues": []}, "mixed_content_flags": []}

    _progress(4, "[4/6] AI content & UX analysis...")
    try:
        content_analysis = analyze_content_and_ux(pages)
    except Exception as e:
        print(f"[pipeline] AI content/UX analysis failed unexpectedly: {e}")
        traceback.print_exc()
        content_analysis = {"parse_error": True, "note": "AI service unavailable",
                             "summary": "AI content analysis couldn't be completed for this scan."}

    _progress(5, "[5/6] AI modernization recommendations...")
    try:
        modernization = analyze_tech_modernization(tech_findings, security_findings)
    except Exception as e:
        print(f"[pipeline] AI modernization analysis failed unexpectedly: {e}")
        traceback.print_exc()
        modernization = {"parse_error": True, "note": "AI service unavailable",
                          "modernization_recommendations": [], "security_priorities": []}

    test_results = {"skipped": True}
    if not skip_tests:
        _progress(6, "[6/6] Running automated browser tests...")
        try:
            test_results = run_tests([p["url"] for p in pages])
        except Exception as e:
            print(f"[pipeline] Playwright browser tests failed: {e}")
            traceback.print_exc()
            test_results = {"error": "Automated browser tests could not run.",
                             "note": "Run 'playwright install chromium' if this is a missing-browser error."}
    else:
        _progress(6, "[6/6] Skipping automated tests (--skip-tests)")

    crawl_summary = {
        "pages_crawled": len(pages),
        "crawl_errors": crawl_result["errors"],
        "pages": [{"url": p["url"], "title": p["title"], "word_count": p["word_count"]} for p in pages],
    }

    return {
        "pages": pages,
        "crawl_errors": crawl_result["errors"],
        "crawl_summary": crawl_summary,
        "tech_findings": tech_findings,
        "security_findings": security_findings,
        "content_analysis": content_analysis,
        "modernization": modernization,
        "test_results": test_results,
    }
