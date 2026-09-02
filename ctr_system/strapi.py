#!/usr/bin/env python3
# ABOUTME: Strapi CMS backend for CTR title changes (dancumberlandlabs.com)
# ABOUTME: Mirrors the WordPress/RankMath calls the optimizer already makes

"""Write approved titles into Strapi.

The optimizer was built against WordPress and RankMath, which is what The
Meaning Movement runs. Dan Cumberland Labs runs Strapi, so every DCL page the
monthly review picked failed with "Could not find post ID" and no title was
ever changed. This module is the missing half.

It is a port of Operations/Tools/retitle_published.py in the DCL content repo,
which has been doing exactly this write by hand. The field rules are narrower
here than they are there, and deliberately so: a CTR experiment writes

    seo_title  the meta title, which is what Google shows in the result

and nothing else. The hand tool also rewrites the H1 and the cover alt text,
because it is syncing an approved title across the whole article. An
experiment is not that. Changing the H1 edits what a reader sees on the page
to test what a searcher sees before clicking, which confounds the measurement
and makes a revert visible to readers. Title, slug, body and alt text stay put.

The site is a static build, so a write here is invisible until the CMS webhook
rebuilds dancumberlandlabs.com.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

STRAPI_URL = os.getenv("STRAPI_URL", "https://cms.dancumberlandlabs.com")
STRAPI_TOKEN = os.getenv("STRAPI_API_TOKEN", "")

# The only field a CTR experiment is allowed to write. Anything outside this
# set is a bug, not a judgment call -- see the module docstring.
WRITABLE = ("seo_title",)

# Strapi has two identifiers per entry: a numeric `id` and a string
# `documentId`. The experiments table stores an integer, and the REST write
# needs the string, so we remember the pairing for the length of the run
# rather than widening the schema for a second CMS.
_DOCUMENT_IDS: Dict[int, str] = {}


class StrapiError(Exception):
    """The Strapi read or write could not be completed."""


def _headers() -> dict:
    if not STRAPI_TOKEN:
        raise StrapiError(
            "STRAPI_API_TOKEN is not set. On the VPS it lives in "
            "~/site-uptime/.strapi-token; in CI it comes from the "
            "STRAPI_API_TOKEN repository secret."
        )
    return {"Authorization": "Bearer " + STRAPI_TOKEN,
            "Content-Type": "application/json"}


def _request(method: str, url: str, payload=None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise StrapiError("Strapi returned %s for %s\n%s" % (exc.code, url, body))
    except urllib.error.URLError as exc:
        raise StrapiError("Could not reach Strapi at %s: %s" % (STRAPI_URL, exc))


def fetch_by_slug(slug: str) -> Optional[dict]:
    """Look an article up by slug, tolerating the pipeline's blog- prefix."""
    candidates = [slug]
    if slug.startswith("blog-"):
        candidates.append(slug[len("blog-"):])
    else:
        candidates.append("blog-" + slug)

    for candidate in candidates:
        query = urllib.parse.urlencode({"filters[slug][$eq]": candidate})
        found = _request("GET", "%s/api/articles?%s" % (STRAPI_URL, query)).get("data") or []
        if found:
            return found[0]
    return None


def get_post_id_from_slug(slug: str) -> Optional[int]:
    """Return the numeric Strapi id, remembering its documentId for the write."""
    try:
        article = fetch_by_slug(slug)
    except StrapiError as exc:
        print("  Strapi lookup failed for %s: %s" % (slug, exc))
        return None
    if not article:
        return None

    numeric_id = article.get("id")
    document_id = article.get("documentId")
    if numeric_id is None or not document_id:
        return None

    _DOCUMENT_IDS[numeric_id] = document_id
    return numeric_id


def get_current_title(post_id: int) -> str:
    """Return the SEO title the site currently serves, falling back to the H1."""
    document_id = _DOCUMENT_IDS.get(post_id)
    if not document_id:
        return ""
    article = _request("GET", "%s/api/articles/%s" % (STRAPI_URL, document_id)).get("data") or {}
    return article.get("seo_title") or article.get("title") or ""


def plan_retitle(article: dict, new_title: str) -> dict:
    """Return the fields that actually change.

    An empty dict means the article already carries this title, which makes the
    update a no-op rather than a pointless write.
    """
    new_title = (new_title or "").strip()
    if not new_title:
        raise StrapiError("Refusing to set an empty title.")

    if article.get("seo_title") == new_title:
        return {}
    return {"seo_title": new_title}


def update_title(post_id: int, new_title: str) -> bool:
    """Write the title. Mirrors update_rankmath_title's contract."""
    document_id = _DOCUMENT_IDS.get(post_id)
    if not document_id:
        print("  No Strapi documentId cached for id %s" % post_id)
        return False

    try:
        article = (_request("GET", "%s/api/articles/%s" % (STRAPI_URL, document_id))
                   .get("data") or {})
        plan = plan_retitle(article, new_title)
        if not plan:
            return True
        _request("PUT", "%s/api/articles/%s" % (STRAPI_URL, document_id), {"data": plan})
    except StrapiError as exc:
        print("  Strapi write failed: %s" % exc)
        return False

    return True


def trigger_site_rebuild() -> bool:
    """Kick a Cloudflare Pages build so the new titles actually reach the site.

    dancumberlandlabs.com is a static Astro build that fetches from Strapi at
    build time, so a write here changes nothing a searcher can see until a build
    runs. Nothing else in this tool did that: the first live run's title changes
    sat in the CMS and only went live because the nightly article publisher
    happened to POST the same hook. In a month with no publishing they would have
    sat there indefinitely and the experiment would have measured no change.
    Found 2026-09-02.
    """
    hook_url = os.getenv("CLOUDFLARE_DEPLOY_HOOK_URL", "").strip()
    if not hook_url:
        print("  CLOUDFLARE_DEPLOY_HOOK_URL not set, skipping site rebuild")
        print("  Title changes stay invisible until the site is rebuilt.")
        return False

    req = urllib.request.Request(hook_url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            # Cloudflare deduped us onto a build that is already queued.
            print("  Cloudflare deploy already queued (HTTP 304)")
            return True
        print("  Site rebuild failed: HTTP %s" % exc.code)
        return False
    except Exception as exc:
        print("  Site rebuild failed: %s" % exc)
        return False

    print("  Site rebuild queued (HTTP %s)" % code)
    return True
