"""
app/services/crawl.py
Crawls a website up to a page limit, collecting page text, links,
images, and basic metadata for downstream analysis.
"""
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def _same_domain(base_url, link):
    return urlparse(base_url).netloc == urlparse(link).netloc


def crawl_site(start_url, max_pages=15, delay=0.5, timeout=10):
    """
    Breadth-first crawl of a site starting at start_url.

    Returns a dict:
    {
        "pages": [ {url, status_code, title, meta_description,
                     text, links, images, headers}, ... ],
        "errors": [ {url, error}, ... ]
    }
    """
    visited = set()
    to_visit = [start_url]
    pages = []
    errors = []

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (AI-Website-Auditor/1.0; +https://example.com/bot)"
    })

    while to_visit and len(pages) < max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException as e:
            errors.append({"url": url, "error": str(e)})
            continue

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_description = meta_desc_tag["content"].strip() if meta_desc_tag and meta_desc_tag.get("content") else ""

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())

        links = set()
        for a in soup.find_all("a", href=True):
            full_url = urljoin(url, a["href"]).split("#")[0]
            if full_url.startswith("http") and _same_domain(start_url, full_url):
                links.add(full_url)
                if full_url not in visited and full_url not in to_visit:
                    to_visit.append(full_url)

        images = []
        for img in soup.find_all("img"):
            images.append({
                "src": urljoin(url, img.get("src", "")),
                "alt": img.get("alt", "").strip(),
                "has_alt": bool(img.get("alt", "").strip())
            })

        pages.append({
            "url": url,
            "status_code": resp.status_code,
            "title": title,
            "meta_description": meta_description,
            "text": text[:8000],
            "word_count": len(text.split()),
            # `links` started life as a set (only used for fast membership
            # checks above) -- sort it before it leaves this function so
            # its order doesn't depend on Python's per-process string hash
            # randomization.
            "links": sorted(links),
            "images": images,
            "response_headers": dict(resp.headers),
        })

        time.sleep(delay)

    # The BFS visiting order above is already deterministic for a given
    # site (it follows document order of <a> tags, and to_visit is a
    # plain FIFO list, not a set/dict). Still, sort the final `pages` and
    # `errors` lists by URL before returning: this is the single choke
    # point every caller reads from, so it guarantees a stable, easy-to-
    # reason-about order for scoring/reporting regardless of BFS timing,
    # and protects against future changes (e.g. concurrent fetching)
    # reintroducing order nondeterminism here.
    pages.sort(key=lambda p: p["url"])
    errors.sort(key=lambda e: e["url"])

    return {"pages": pages, "errors": errors, "pages_crawled": len(pages)}
