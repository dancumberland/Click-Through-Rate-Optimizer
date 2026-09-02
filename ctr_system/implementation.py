#!/usr/bin/env python3
# ABOUTME: Implementation module for CTR optimization
# ABOUTME: Handles RankMath API updates and experiment creation

import base64
import requests
from typing import Optional, Dict

from .config import WP_SITE_URL, WP_USER, WP_APP_PASSWORD, CMS_BACKEND
from . import database as db
from . import strapi


def get_auth_headers() -> Dict[str, str]:
    """Create Basic Auth headers for WordPress REST API"""
    credentials = f"{WP_USER}:{WP_APP_PASSWORD}"
    token = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }


def get_post_id_from_slug(slug: str) -> Optional[int]:
    """Get the CMS id for a slug, from whichever CMS this site runs."""
    if CMS_BACKEND == "strapi":
        return strapi.get_post_id_from_slug(slug)
    return _wp_get_post_id_from_slug(slug)


def _wp_get_post_id_from_slug(slug: str) -> Optional[int]:
    """Get WordPress post ID from slug"""
    url = f"{WP_SITE_URL}/wp-json/wp/v2/posts?slug={slug}"
    response = requests.get(url)

    if response.status_code == 200:
        posts = response.json()
        if posts:
            return posts[0]['id']
    return None


def get_current_title(post_id: int) -> str:
    """Get the title the site currently serves, from whichever CMS it runs."""
    if CMS_BACKEND == "strapi":
        return strapi.get_current_title(post_id)
    return _wp_get_current_title(post_id)


def _wp_get_current_title(post_id: int) -> str:
    """Get current title (RankMath SEO title or post title)"""
    url = f"{WP_SITE_URL}/wp-json/wp/v2/posts/{post_id}"
    response = requests.get(url, headers=get_auth_headers())

    if response.status_code == 200:
        post = response.json()
        meta = post.get('meta', {})

        # Prefer RankMath title if set
        rm_title = meta.get('rank_math_title', '')
        if rm_title:
            return rm_title

        # Fall back to post title
        return post['title']['rendered']

    return ""


def update_title(post_id: int, new_title: str) -> bool:
    """Write the new title through whichever CMS this site runs."""
    if CMS_BACKEND == "strapi":
        return strapi.update_title(post_id, new_title)
    return update_rankmath_title(post_id, new_title)


def update_rankmath_title(post_id: int, new_title: str) -> bool:
    """Update RankMath meta title via REST API"""
    url = f"{WP_SITE_URL}/wp-json/rank-math-api/v1/update-meta"

    data = {
        "post_id": post_id,
        "rank_math_title": new_title
    }

    response = requests.post(url, headers=get_auth_headers(), json=data)

    if response.status_code != 200:
        print(f"  API Error: {response.status_code} - {response.text[:200]}")
        return False

    return True


def implement_title_change(
    page_url: str,
    page_slug: str,
    new_title: str,
    hypothesis: str,
    idea_type: str,
    pre_ctr: float,
    pre_position: float,
    pre_impressions: int,
    pre_clicks: int,
    pre_start_date: str,
    pre_end_date: str,
    review_id: Optional[int] = None
) -> Optional[int]:
    """Implement a title change and create experiment record"""

    # Get post ID
    post_id = get_post_id_from_slug(page_slug)
    if not post_id:
        print(f"  Could not find post ID for {page_slug}")
        return None

    # Get current title
    old_title = get_current_title(post_id)

    # Write the title through the site's CMS
    success = update_title(post_id, new_title)
    if not success:
        print(f"  Failed to update title for {page_slug}")
        return None

    # Create experiment record
    experiment_id = db.create_experiment(
        page_url=page_url,
        page_slug=page_slug,
        wp_post_id=post_id,
        hypothesis=hypothesis,
        idea_type=idea_type,
        old_title=old_title,
        new_title=new_title,
        pre_ctr=pre_ctr,
        pre_position=pre_position,
        pre_impressions=pre_impressions,
        pre_clicks=pre_clicks,
        pre_start_date=pre_start_date,
        pre_end_date=pre_end_date,
        review_id=review_id
    )

    # Also log to seo_changes for compatibility with existing system.
    # get_connection() is a context manager and the placeholder differs per
    # backend, so the old conn.cursor() / "?" form here crashed on the first
    # successful title change on either database.
    ph = db._placeholder()
    with db.get_connection() as conn:
        cursor = db._get_cursor(conn)
        cursor.execute(f"""
            INSERT INTO seo_changes
            (page_url, wp_post_id, field_changed, old_value, new_value,
             change_reason, gsc_ctr_at_change, gsc_impressions_at_change, gsc_clicks_at_change)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (
            page_url, post_id, 'seo_title' if CMS_BACKEND == 'strapi' else 'rank_math_title',
            old_title, new_title,
            f"CTR experiment: {hypothesis}",
            pre_ctr * 100,  # Store as percentage
            pre_impressions, pre_clicks
        ))
        conn.commit()

    print(f"  ✅ Updated: {old_title[:40]}... → {new_title[:40]}...")
    return experiment_id


def revert_experiment(experiment_id: int) -> bool:
    """Revert an experiment to its original title"""
    ph = db._placeholder()

    with db.get_connection() as conn:
        cursor = db._get_cursor(conn)
        cursor.execute(f"""
            SELECT page_slug, wp_post_id, old_title, new_title
            FROM optimization_experiments
            WHERE id = {ph}
        """, (experiment_id,))
        row = cursor.fetchone()

    if not row:
        print(f"  Experiment {experiment_id} not found")
        return False

    page_slug = row['page_slug']
    post_id = row['wp_post_id']
    old_title = row['old_title']

    # A Strapi revert needs the documentId that pairs with this numeric id, and
    # that pairing is only cached for the length of a run. Re-resolve it from
    # the slug so a revert works in a fresh process.
    if CMS_BACKEND == "strapi":
        post_id = get_post_id_from_slug(page_slug)
        if not post_id:
            print(f"  Could not find {page_slug} in Strapi to revert")
            return False

    # Revert title
    success = update_title(post_id, old_title)
    if not success:
        print(f"  Failed to revert {page_slug}")
        return False

    # Update experiment status
    with db.get_connection() as conn:
        cursor = db._get_cursor(conn)
        cursor.execute(f"""
            UPDATE optimization_experiments
            SET status = 'reverted',
                ended_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (experiment_id,))
        conn.commit()

    print(f"  \u21a9\ufe0f  Reverted {page_slug} to original title")
    return True
