"""
app/services/browser_tests.py
Automated functional + basic accessibility checks using Playwright.
Run `playwright install chromium` once before first use.

Determinism note: this is the one stage of the pipeline that talks to a
live, real website through a real browser, so it can never be made
*perfectly* deterministic -- a site's own third-party scripts, ads, or
A/B tests can genuinely behave differently between two visits, and
that's outside this code's control. What IS this code's responsibility
(and what was previously buggy) is: not leaking event listeners between
pages, and giving the page a fixed, deterministic settle time before
reading results, instead of racing whatever console messages happened
to arrive before `networkidle` resolved.
"""
from playwright.sync_api import sync_playwright

# Fixed grace period after a page reports "networkidle" before we read
# console errors / evaluate the DOM. `networkidle` only guarantees no
# network activity for 500ms -- it does NOT guarantee every console
# message a page will ever emit has already fired. Without this wait,
# whether a late console error gets counted becomes a race, which is a
# real source of the score flipping between runs of the same page.
SETTLE_MS = 500


def run_tests(urls, max_pages=10, timeout_ms=15000):
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        for url in sorted(urls[:max_pages]):
            page_result = {
                "url": url,
                "load_success": False,
                "console_errors": [],
                "broken_images": [],
                "missing_alt_count": 0,
                "has_lang_attr": False,
                "has_title": False,
            }

            console_errors = []

            def _on_console(msg, _errors=console_errors):
                if msg.type == "error":
                    _errors.append(msg.text)

            page.on("console", _on_console)

            try:
                response = page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                page_result["load_success"] = response is not None and response.status < 400
                page_result["status_code"] = response.status if response else None

                # Give any late console messages a fixed window to arrive
                # before we read `console_errors` below, instead of
                # reading it immediately (a race).
                page.wait_for_timeout(SETTLE_MS)

                page_result["has_title"] = bool(page.title())
                page_result["has_lang_attr"] = bool(page.get_attribute("html", "lang"))

                broken = page.evaluate("""
                    () => Array.from(document.images)
                        .filter(img => !img.complete || img.naturalWidth === 0)
                        .map(img => img.src)
                """)
                page_result["broken_images"] = sorted(set(broken))

                missing_alt = page.evaluate("""
                    () => Array.from(document.images)
                        .filter(img => !img.alt || img.alt.trim() === '').length
                """)
                page_result["missing_alt_count"] = missing_alt

            except Exception as e:
                page_result["error"] = str(e)
            finally:
                # Must remove this page's listener before moving to the
                # next URL -- otherwise every previous page's listener
                # stays attached (and keeps firing) for the rest of the
                # run, which is wasted work and a latent source of bugs
                # even though it happened not to corrupt already-copied
                # results here.
                page.remove_listener("console", _on_console)

            # De-duped, sorted copy -- a page can legitimately emit the
            # exact same console error multiple times (e.g. a failed
            # fetch retried), and we don't want that repeat count to be
            # timing-dependent on how many happened to fire before the
            # settle window closed.
            page_result["console_errors"] = sorted(set(console_errors))[:10]
            results.append(page_result)

        browser.close()

    return {
        "pages_tested": len(results),
        "results": results,
        "summary": {
            "pages_with_errors": sum(1 for r in results if r["console_errors"]),
            "pages_with_broken_images": sum(1 for r in results if r["broken_images"]),
            "pages_missing_lang_attr": sum(1 for r in results if not r["has_lang_attr"]),
        }
    }
