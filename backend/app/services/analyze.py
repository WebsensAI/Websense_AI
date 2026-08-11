"""
app/services/analyze.py
Deterministic (non-AI) analysis of a crawled site:
  - detect_technologies()   : lightweight tech-stack fingerprinting
  - run_security_scan()      : passive security posture checks

Merged from the original tech_detect.py + security_scan.py into one
"analyze" stage, matching the crawl -> analyze -> ai_insights pipeline.
"""
import re
import ssl
import socket
from datetime import datetime
from urllib.parse import urlparse

import requests

# ---------------------------------------------------------------------
# Technology detection
# ---------------------------------------------------------------------

SIGNATURES = {
    "WordPress": [r"wp-content", r"wp-includes", r'name="generator" content="WordPress'],
    "Shopify": [r"cdn\.shopify\.com", r"Shopify\.theme"],
    "Wix": [r"wix\.com", r"wixstatic\.com"],
    "Squarespace": [r"squarespace\.com", r"static1\.squarespace"],
    "Webflow": [r"webflow\.com", r"data-wf-page"],
    "React": [r"react-dom", r"data-reactroot", r"__REACT_DEVTOOLS"],
    "Vue.js": [r"vue\.js", r"__VUE__", r"data-v-"],
    "Angular": [r"ng-app", r"ng-version", r"angular\.js"],
    "jQuery": [r"jquery(\.min)?\.js"],
    "Bootstrap": [r"bootstrap(\.min)?\.css"],
    "Next.js": [r"__NEXT_DATA__", r"_next/static"],
    "Drupal": [r"Drupal\.settings", r"/sites/default/files"],
    "Cloudflare": [r"cloudflare"],
    "Google Analytics": [r"google-analytics\.com", r"gtag\("],
    "Google Tag Manager": [r"googletagmanager\.com"],
}

HEADER_HINTS = {
    "server": "Server",
    "x-powered-by": "X-Powered-By",
    "x-generator": "X-Generator",
}


def detect_technologies(pages):
    findings = {}
    header_hints = {}
    outdated_signals = []

    for page in pages:
        text_blob = page.get("text", "") + str(page.get("response_headers", {}))

        for tech, patterns in SIGNATURES.items():
            if tech in findings:
                continue
            for pat in patterns:
                if re.search(pat, text_blob, re.IGNORECASE):
                    findings[tech] = f"Detected via pattern match on {page['url']}"
                    break

        headers = page.get("response_headers", {})
        for hkey, label in HEADER_HINTS.items():
            for actual_key, value in headers.items():
                if actual_key.lower() == hkey:
                    header_hints[label] = value

        headers_lower = {k.lower(): v for k, v in headers.items()}
        server = headers_lower.get("server", "")
        if re.search(r"Apache/1\.|Apache/2\.[0-2]\.", server):
            outdated_signals.append(f"Old Apache version exposed in headers: {server}")
        if re.search(r"PHP/5\.", str(headers_lower)):
            outdated_signals.append("Server exposes PHP 5.x (end-of-life since 2019)")
        if "x-powered-by" in headers_lower and "php/5" in headers_lower["x-powered-by"].lower():
            outdated_signals.append(f"X-Powered-By reveals outdated PHP: {headers_lower['x-powered-by']}")

    return {
        # Plain dicts already preserve insertion order in Python 3.7+, but
        # that insertion order follows crawl order -- sort by key so the
        # output doesn't shift if crawl order ever changes upstream.
        "technologies": dict(sorted(findings.items())),
        "header_hints": dict(sorted(header_hints.items())),
        # `set(...)` dedupes, but iterating a set of strings is ordered by
        # Python's (randomized-per-process) string hash, not insertion
        # order -- two runs of the app could print the exact same signals
        # in a different order. `sorted(set(...))` dedupes AND gives a
        # fixed, reproducible order.
        "outdated_signals": sorted(set(outdated_signals)),
    }


# ---------------------------------------------------------------------
# Security scanning (passive only)
# ---------------------------------------------------------------------

EXPECTED_HEADERS = {
    "Strict-Transport-Security": "Enforces HTTPS; missing means downgrade attacks are possible.",
    "Content-Security-Policy": "Mitigates XSS and data injection attacks.",
    "X-Content-Type-Options": "Prevents MIME-sniffing attacks.",
    "X-Frame-Options": "Mitigates clickjacking.",
    "Referrer-Policy": "Controls how much referrer info leaks to other sites.",
    "Permissions-Policy": "Restricts access to browser features (camera, mic, etc).",
}


def check_ssl_cert(hostname, port=443, timeout=10):
    """
    Note on determinism: `days_until_expiry`/`expiring_soon` below are
    computed against `datetime.utcnow()` at call time. This is *correct*
    time-varying ground truth (a certificate really does have fewer days
    left tomorrow than today), not a bug -- it's intentionally excluded
    from the "must be identical every time" guarantee. In practice this
    only changes the score if two scans of the same site happen to
    straddle the exact 30-day expiry boundary, which is expected
    behavior, not nondeterminism.
    """
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                days_left = (not_after - datetime.utcnow()).days
                return {
                    "valid": True,
                    "issuer": dict(x[0] for x in cert.get("issuer", [])),
                    "expires": cert["notAfter"],
                    "days_until_expiry": days_left,
                    "expiring_soon": days_left < 30,
                }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def check_security_headers(url, timeout=10):
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        return {"error": str(e)}

    headers = {k: v for k, v in resp.headers.items()}
    missing = []
    present = {}
    for header, explanation in EXPECTED_HEADERS.items():
        if header in headers:
            present[header] = headers[header]
        else:
            missing.append({"header": header, "risk": explanation})

    return {
        "present_headers": present,
        "missing_headers": missing,
        "server_header_exposed": headers.get("Server", None),
    }


def check_cookies(url, timeout=10):
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        return {"error": str(e)}

    issues = []
    cookies_info = []
    for cookie in resp.cookies:
        flags = {
            "secure": cookie.secure,
            "httponly": "httponly" in [k.lower() for k in cookie._rest.keys()] if hasattr(cookie, "_rest") else False,
        }
        cookies_info.append({"name": cookie.name, "flags": flags})
        if not cookie.secure:
            issues.append(f"Cookie '{cookie.name}' missing Secure flag")
    return {"cookies": cookies_info, "issues": issues}


def check_mixed_content(page_text, page_url):
    if not page_url.startswith("https"):
        return []
    issues = []
    if "http://" in page_text:
        issues.append(f"Possible mixed content (http:// reference) found on {page_url}")
    return issues


def run_security_scan(start_url, crawled_pages):
    hostname = urlparse(start_url).netloc

    result = {
        "ssl": check_ssl_cert(hostname),
        "headers": check_security_headers(start_url),
        "cookies": check_cookies(start_url),
        "mixed_content_flags": [],
    }

    for page in crawled_pages:
        result["mixed_content_flags"].extend(
            check_mixed_content(page.get("text", ""), page.get("url", ""))
        )

    return result
