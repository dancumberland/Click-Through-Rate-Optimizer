#!/usr/bin/env python3
# ABOUTME: Database operations for CTR optimization system
# ABOUTME: Supports both SQLite (local dev) and PostgreSQL via Supabase (CI/production)

import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from .config import DB_PATH, MIN_DAYS_BETWEEN_CHANGES, MIN_DAYS_FOR_EVALUATION

# Detect database backend
DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
else:
    import sqlite3


@contextmanager
def get_connection():
    """Get database connection - PostgreSQL if SUPABASE_DATABASE_URL is set, else SQLite"""
    if USE_POSTGRES:
        # Force IPv4 for GitHub Actions compatibility
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(DATABASE_URL)
        hostname = parsed.hostname

        try:
            addr_info = socket.getaddrinfo(hostname, parsed.port or 5432, socket.AF_INET)
            if addr_info:
                ipv4_addr = addr_info[0][4][0]
                conn = psycopg2.connect(DATABASE_URL, hostaddr=ipv4_addr)
            else:
                conn = psycopg2.connect(DATABASE_URL)
        except (socket.gaierror, IndexError):
            conn = psycopg2.connect(DATABASE_URL)

        try:
            yield conn
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def _get_cursor(conn):
    """Get appropriate cursor for the database backend"""
    if USE_POSTGRES:
        return conn.cursor(cursor_factory=RealDictCursor)
    return conn.cursor()


def _placeholder():
    """Return the correct placeholder for the database backend"""
    return "%s" if USE_POSTGRES else "?"


def _row_to_dict(row):
    """Convert a row to a dictionary"""
    if row is None:
        return None
    if USE_POSTGRES:
        return dict(row)
    return dict(row)


# =============================================================================
# SEO CHANGES
# =============================================================================

def get_last_change_date(page_url: str) -> Optional[datetime]:
    """Get the date of the most recent SEO change for a page"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            SELECT MAX(changed_at) as last_change
            FROM seo_changes
            WHERE page_url = {ph}
        """, (page_url,))
        row = cursor.fetchone()

    if row:
        last_change = row['last_change'] if USE_POSTGRES else row[0]
        if last_change:
            if isinstance(last_change, str):
                return datetime.fromisoformat(last_change.replace('Z', '+00:00'))
            return last_change
    return None


def get_days_since_last_change(page_url: str) -> Optional[int]:
    """Get number of days since last change, or None if never changed"""
    last_change = get_last_change_date(page_url)
    if last_change is None:
        return None
    if last_change.tzinfo is not None:
        last_change = last_change.replace(tzinfo=None)
    return (datetime.now() - last_change).days


def can_optimize_page(page_url: str) -> bool:
    """Check if enough time has passed since last change"""
    days = get_days_since_last_change(page_url)
    if days is None:
        return True  # Never optimized
    return days >= MIN_DAYS_BETWEEN_CHANGES


def record_seo_change(
    page_url: str,
    field_changed: str,
    old_value: str,
    new_value: str,
    change_reason: str = None,
    wp_post_id: int = None,
    gsc_ctr: float = None,
    gsc_impressions: int = None,
    gsc_clicks: int = None,
    notes: str = None,
):
    """Record an SEO change made to a page"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            INSERT INTO seo_changes (
                page_url, wp_post_id, field_changed, old_value, new_value,
                change_reason, gsc_ctr_at_change, gsc_impressions_at_change,
                gsc_clicks_at_change, notes
            ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (
            page_url, wp_post_id, field_changed, old_value, new_value,
            change_reason, gsc_ctr, gsc_impressions, gsc_clicks, notes
        ))
        conn.commit()


# =============================================================================
# PAGE TRACKING
# =============================================================================

def get_page_first_seen(page_url: str) -> Optional[str]:
    """Get the first-seen date for a page from tracking table"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            SELECT first_seen_date
            FROM gsc_page_tracking
            WHERE page_url = {ph}
        """, (page_url,))
        row = cursor.fetchone()

    if row:
        val = row['first_seen_date'] if USE_POSTGRES else row[0]
        return str(val) if val else None
    return None


def track_page_first_seen(page_url: str, page_slug: str, first_seen_date: str, wp_post_id: Optional[int] = None):
    """Record when a page first appeared in GSC"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(f"""
                INSERT INTO gsc_page_tracking (
                    page_url, page_slug, first_seen_date, wp_post_id,
                    last_seen_date, last_updated
                ) VALUES ({ph}, {ph}, {ph}, {ph}, CURRENT_DATE, CURRENT_TIMESTAMP)
                ON CONFLICT (page_url) DO UPDATE SET
                    last_seen_date = CURRENT_DATE,
                    last_updated = CURRENT_TIMESTAMP
            """, (page_url, page_slug, first_seen_date, wp_post_id))
        else:
            cursor.execute(f"""
                INSERT OR REPLACE INTO gsc_page_tracking (
                    page_url, page_slug, first_seen_date, wp_post_id,
                    last_seen_date, last_updated
                ) VALUES ({ph}, {ph}, {ph}, {ph}, date('now'), datetime('now'))
            """, (page_url, page_slug, first_seen_date, wp_post_id))
        conn.commit()


def update_page_last_seen(page_url: str, last_seen_date: str):
    """Update the last-seen date for a page"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(f"""
                UPDATE gsc_page_tracking
                SET last_seen_date = {ph}, last_updated = CURRENT_TIMESTAMP
                WHERE page_url = {ph}
            """, (last_seen_date, page_url))
        else:
            cursor.execute(f"""
                UPDATE gsc_page_tracking
                SET last_seen_date = {ph}, last_updated = datetime('now')
                WHERE page_url = {ph}
            """, (last_seen_date, page_url))
        conn.commit()


def get_days_since_first_seen(page_url: str) -> Optional[int]:
    """Get number of days since page first appeared in GSC"""
    first_seen = get_page_first_seen(page_url)
    if not first_seen:
        return None
    first_date = datetime.strptime(first_seen, '%Y-%m-%d')
    return (datetime.now() - first_date).days


def is_page_old_enough_for_optimization(page_url: str, min_days: int = 30) -> bool:
    """Check if page has been in GSC long enough to optimize"""
    days = get_days_since_first_seen(page_url)
    if days is None:
        return True  # Not tracked yet, will be discovered
    return days >= min_days


# =============================================================================
# HISTORICAL DATA LOGGING
# =============================================================================

def log_historical_gsc_data(page_url: str, data_date: str, impressions: int, clicks: int, ctr: float, position: float):
    """Log historical GSC data for long-term preservation"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(f"""
                INSERT INTO gsc_historical_data (
                    page_url, data_date, impressions, clicks, ctr, position
                ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (page_url, data_date) DO UPDATE SET
                    impressions = EXCLUDED.impressions,
                    clicks = EXCLUDED.clicks,
                    ctr = EXCLUDED.ctr,
                    position = EXCLUDED.position,
                    logged_at = CURRENT_TIMESTAMP
            """, (page_url, data_date, impressions, clicks, ctr, position))
        else:
            cursor.execute(f"""
                INSERT OR IGNORE INTO gsc_historical_data (
                    page_url, data_date, impressions, clicks, ctr, position
                ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """, (page_url, data_date, impressions, clicks, ctr, position))
        conn.commit()


def get_historical_data(page_url: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
    """Get historical GSC data for a page"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if start_date and end_date:
            cursor.execute(f"""
                SELECT data_date, impressions, clicks, ctr, position
                FROM gsc_historical_data
                WHERE page_url = {ph} AND data_date BETWEEN {ph} AND {ph}
                ORDER BY data_date
            """, (page_url, start_date, end_date))
        else:
            cursor.execute(f"""
                SELECT data_date, impressions, clicks, ctr, position
                FROM gsc_historical_data
                WHERE page_url = {ph}
                ORDER BY data_date
            """, (page_url,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


# =============================================================================
# BENCHMARKS
# =============================================================================

def get_benchmarks() -> List[Dict]:
    """Get CTR benchmarks by position band"""
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute("""
            SELECT position_min, position_max, expected_ctr, sample_size
            FROM ctr_benchmarks
            ORDER BY position_min
        """)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def update_benchmarks(benchmarks: List[Dict]):
    """Update CTR benchmarks (replace all)"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute("DELETE FROM ctr_benchmarks")
        for b in benchmarks:
            cursor.execute(f"""
                INSERT INTO ctr_benchmarks (position_min, position_max, expected_ctr, sample_size)
                VALUES ({ph}, {ph}, {ph}, {ph})
            """, (b['position_min'], b['position_max'], b['expected_ctr'], b.get('sample_size', 0)))
        conn.commit()


def get_expected_ctr(position: float) -> float:
    """Get expected CTR for a given position"""
    benchmarks = get_benchmarks()
    if not benchmarks:
        # Fallback to rough estimate
        if position <= 1.5:
            return 0.30
        elif position <= 3:
            return 0.15
        elif position <= 5:
            return 0.08
        elif position <= 10:
            return 0.04
        else:
            return 0.01

    for b in benchmarks:
        if b['position_min'] <= position < b['position_max']:
            return b['expected_ctr']
    return benchmarks[-1]['expected_ctr']


# =============================================================================
# EXPERIMENTS
# =============================================================================

def create_experiment(
    page_url: str,
    page_slug: str,
    wp_post_id: int,
    hypothesis: str,
    idea_type: str,
    old_title: str,
    new_title: str,
    pre_ctr: float,
    pre_position: float,
    pre_impressions: int,
    pre_clicks: int,
    pre_start_date: str,
    pre_end_date: str,
    review_id: Optional[int] = None
) -> int:
    """Create a new optimization experiment"""
    ph = _placeholder()
    min_eval_date = (datetime.now() + timedelta(days=MIN_DAYS_FOR_EVALUATION)).date()

    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(f"""
                INSERT INTO optimization_experiments (
                    page_url, page_slug, wp_post_id,
                    hypothesis, idea_type,
                    old_title, new_title,
                    pre_ctr, pre_position, pre_impressions, pre_clicks,
                    pre_measurement_start, pre_measurement_end,
                    min_evaluation_date, outcome, status, review_id
                ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 'pending', 'active', {ph})
                RETURNING id
            """, (
                page_url, page_slug, wp_post_id,
                hypothesis, idea_type,
                old_title, new_title,
                pre_ctr, pre_position, pre_impressions, pre_clicks,
                pre_start_date, pre_end_date,
                min_eval_date, review_id
            ))
            experiment_id = cursor.fetchone()['id']
        else:
            cursor.execute(f"""
                INSERT INTO optimization_experiments (
                    page_url, page_slug, wp_post_id,
                    hypothesis, idea_type,
                    old_title, new_title,
                    pre_ctr, pre_position, pre_impressions, pre_clicks,
                    pre_measurement_start, pre_measurement_end,
                    min_evaluation_date, outcome, status, review_id
                ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 'pending', 'active', {ph})
            """, (
                page_url, page_slug, wp_post_id,
                hypothesis, idea_type,
                old_title, new_title,
                pre_ctr, pre_position, pre_impressions, pre_clicks,
                pre_start_date, pre_end_date,
                min_eval_date, review_id
            ))
            experiment_id = cursor.lastrowid
        conn.commit()
    return experiment_id


def get_active_experiments() -> List[Dict]:
    """Get all active experiments"""
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute("""
                SELECT *,
                    EXTRACT(DAY FROM (CURRENT_TIMESTAMP - started_at)) as days_active,
                    CASE WHEN CURRENT_DATE >= min_evaluation_date THEN 1 ELSE 0 END as ready_for_evaluation
                FROM optimization_experiments
                WHERE status = 'active'
                ORDER BY started_at DESC
            """)
        else:
            cursor.execute("""
                SELECT *,
                    julianday('now') - julianday(started_at) as days_active,
                    CASE WHEN date('now') >= min_evaluation_date THEN 1 ELSE 0 END as ready_for_evaluation
                FROM optimization_experiments
                WHERE status = 'active'
                ORDER BY started_at DESC
            """)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_experiments_ready_for_evaluation() -> List[Dict]:
    """Get experiments ready to be evaluated"""
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute("""
                SELECT *
                FROM optimization_experiments
                WHERE status = 'active'
                  AND CURRENT_DATE >= min_evaluation_date
                  AND post_impressions >= 50
                ORDER BY started_at
            """)
        else:
            cursor.execute("""
                SELECT *
                FROM optimization_experiments
                WHERE status = 'active'
                  AND date('now') >= min_evaluation_date
                  AND post_impressions >= 50
                ORDER BY started_at
            """)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def update_experiment_metrics(
    experiment_id: int,
    post_ctr: float,
    post_position: float,
    post_impressions: int,
    post_clicks: int,
    post_start_date: str,
    post_end_date: str
):
    """Update post-change metrics for an experiment"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            UPDATE optimization_experiments
            SET post_ctr = {ph},
                post_position = {ph},
                post_impressions = {ph},
                post_clicks = {ph},
                post_measurement_start = {ph},
                post_measurement_end = {ph},
                last_measured = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (
            post_ctr, post_position, post_impressions, post_clicks,
            post_start_date, post_end_date, experiment_id
        ))
        conn.commit()


def complete_experiment(
    experiment_id: int,
    outcome: str,
    ctr_change_pct: float,
    position_change: float,
    learnings: str
):
    """Mark experiment as completed with outcome"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            UPDATE optimization_experiments
            SET status = 'completed',
                ended_at = CURRENT_TIMESTAMP,
                outcome = {ph},
                ctr_change_pct = {ph},
                position_change = {ph},
                learnings = {ph}
            WHERE id = {ph}
        """, (outcome, ctr_change_pct, position_change, learnings, experiment_id))
        conn.commit()


def get_experiment_history(page_url: str) -> List[Dict]:
    """Get all experiments for a specific page"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            SELECT *
            FROM optimization_experiments
            WHERE page_url = {ph}
            ORDER BY started_at DESC
        """, (page_url,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


# =============================================================================
# TITLE IDEAS
# =============================================================================

def store_title_ideas(page_url: str, ideas: List[Dict], review_id: Optional[int] = None):
    """Store generated title ideas for a page"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        for idea in ideas:
            try:
                if USE_POSTGRES:
                    cursor.execute(f"""
                        INSERT INTO title_ideas (
                            page_url, idea_text, char_count, idea_type, hypothesis,
                            generated_for_review_id, source
                        ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                        ON CONFLICT (page_url, idea_text) DO NOTHING
                    """, (
                        page_url,
                        idea['text'],
                        len(idea['text']),
                        idea['type'],
                        idea.get('hypothesis', ''),
                        review_id,
                        idea.get('source', 'ai_generated')
                    ))
                else:
                    cursor.execute(f"""
                        INSERT OR IGNORE INTO title_ideas (
                            page_url, idea_text, char_count, idea_type, hypothesis,
                            generated_for_review_id, source
                        ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    """, (
                        page_url,
                        idea['text'],
                        len(idea['text']),
                        idea['type'],
                        idea.get('hypothesis', ''),
                        review_id,
                        idea.get('source', 'ai_generated')
                    ))
            except Exception:
                pass  # Skip duplicates
        conn.commit()


def mark_idea_used(idea_id: int, experiment_id: int):
    """Mark an idea as used in an experiment"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            UPDATE title_ideas
            SET selected = TRUE,
                used_at = CURRENT_TIMESTAMP,
                experiment_id = {ph}
            WHERE id = {ph}
        """, (experiment_id, idea_id))
        conn.commit()


def get_past_ideas(page_url: str) -> List[Dict]:
    """Get all past ideas for a page (to avoid duplicates)"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            SELECT idea_text, idea_type, selected, used_at
            FROM title_ideas
            WHERE page_url = {ph}
        """, (page_url,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_unused_ideas(page_url: str) -> List[Dict]:
    """Get generated but unused ideas for a page"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            SELECT *
            FROM title_ideas
            WHERE page_url = {ph} AND selected = FALSE
            ORDER BY generated_at DESC
        """, (page_url,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


# =============================================================================
# MONTHLY REVIEWS
# =============================================================================

def create_monthly_review(review_date: datetime, gsc_start: str, gsc_end: str) -> int:
    """Create a new monthly review record"""
    ph = _placeholder()
    review_month = review_date.strftime('%Y-%m')

    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(f"""
                INSERT INTO monthly_reviews (
                    review_date, review_month,
                    gsc_data_start, gsc_data_end,
                    status
                ) VALUES ({ph}, {ph}, {ph}, {ph}, 'draft')
                RETURNING id
            """, (review_date.date(), review_month, gsc_start, gsc_end))
            review_id = cursor.fetchone()['id']
        else:
            cursor.execute(f"""
                INSERT INTO monthly_reviews (
                    review_date, review_month,
                    gsc_data_start, gsc_data_end,
                    status
                ) VALUES ({ph}, {ph}, {ph}, {ph}, 'draft')
            """, (review_date.date(), review_month, gsc_start, gsc_end))
            review_id = cursor.lastrowid
        conn.commit()
    return review_id


def update_review_stats(
    review_id: int,
    total_pages: int,
    pages_eligible: int,
    opportunities: int,
    experiments_proposed: int,
    experiments_started: int
):
    """Update review statistics"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            UPDATE monthly_reviews
            SET total_pages_analyzed = {ph},
                pages_eligible = {ph},
                opportunities_identified = {ph},
                experiments_proposed = {ph},
                experiments_started = {ph}
            WHERE id = {ph}
        """, (total_pages, pages_eligible, opportunities, experiments_proposed, experiments_started, review_id))
        conn.commit()


def complete_monthly_review(review_id: int, report_path: str):
    """Mark monthly review as completed"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            UPDATE monthly_reviews
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                report_path = {ph}
            WHERE id = {ph}
        """, (report_path, review_id))
        conn.commit()


def get_latest_review() -> Optional[Dict]:
    """Get the most recent monthly review"""
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute("""
            SELECT *
            FROM monthly_reviews
            ORDER BY review_date DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
    return dict(row) if row else None


# =============================================================================
# LEARNINGS
# =============================================================================

def store_learning(
    learning_type: str,
    insight: str,
    category: Optional[str] = None,
    idea_type: Optional[str] = None,
    supporting_data: Optional[Dict] = None,
    sample_size: int = 0,
    confidence: str = 'medium'
):
    """Store a learning/insight from experiments"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            INSERT INTO ctr_learnings (
                learning_type, category, idea_type, insight,
                supporting_data, sample_size, confidence
            ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (
            learning_type, category, idea_type, insight,
            json.dumps(supporting_data) if supporting_data else None,
            sample_size, confidence
        ))
        conn.commit()


def get_learnings(idea_type: Optional[str] = None) -> List[Dict]:
    """Get learnings, optionally filtered by idea type"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if idea_type:
            cursor.execute(f"""
                SELECT * FROM ctr_learnings
                WHERE (idea_type = {ph} OR idea_type IS NULL)
                  AND still_valid = TRUE
                ORDER BY confidence DESC, sample_size DESC
            """, (idea_type,))
        else:
            cursor.execute("""
                SELECT * FROM ctr_learnings
                WHERE still_valid = TRUE
                ORDER BY confidence DESC, sample_size DESC
            """)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_idea_type_performance() -> List[Dict]:
    """Get performance summary by idea type"""
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute("""
                SELECT
                    idea_type,
                    COUNT(*) as total_experiments,
                    SUM(CASE WHEN outcome = 'improved' THEN 1 ELSE 0 END) as improved,
                    SUM(CASE WHEN outcome = 'worsened' THEN 1 ELSE 0 END) as worsened,
                    SUM(CASE WHEN outcome = 'no_change' THEN 1 ELSE 0 END) as no_change,
                    ROUND(AVG(ctr_change_pct)::numeric, 2) as avg_ctr_change,
                    ROUND((100.0 * SUM(CASE WHEN outcome = 'improved' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0))::numeric, 1) as success_rate
                FROM optimization_experiments
                WHERE outcome IS NOT NULL AND outcome NOT IN ('pending', 'inconclusive')
                GROUP BY idea_type
                ORDER BY success_rate DESC NULLS LAST
            """)
        else:
            cursor.execute("""
                SELECT * FROM v_idea_type_performance
                ORDER BY success_rate DESC
            """)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


# =============================================================================
# GSC PAGE METRICS
# =============================================================================

def store_gsc_metrics(
    page_url: str,
    page_slug: str,
    start_date: str,
    end_date: str,
    impressions: int,
    clicks: int,
    ctr: float,
    position: float,
    expected_ctr: float,
    top_queries: List[Dict],
    review_id: int
):
    """Store GSC metrics snapshot for analysis"""
    ph = _placeholder()
    ctr_gap = expected_ctr - ctr
    impact_score = impressions * max(ctr_gap, 0)

    days_since = get_days_since_last_change(page_url)
    last_change = get_last_change_date(page_url)
    eligible = can_optimize_page(page_url)

    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            INSERT INTO gsc_page_metrics (
                page_url, page_slug,
                measurement_start, measurement_end,
                impressions, clicks, ctr, position,
                expected_ctr, ctr_gap, impact_score,
                days_since_last_change, last_change_date, eligible_for_optimization,
                top_queries, review_id
            ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (
            page_url, page_slug,
            start_date, end_date,
            impressions, clicks, ctr, position,
            expected_ctr, ctr_gap, impact_score,
            days_since, last_change.date() if last_change else None, eligible,
            json.dumps(top_queries), review_id
        ))
        conn.commit()


def get_optimization_opportunities(
    review_id: int,
    min_ctr_gap_percent: float = 15.0,
    min_impact_score: float = 5.0,
    max_results: int = 50
) -> List[Dict]:
    """Get optimization opportunities from a review based on CTR gap thresholds"""
    ph = _placeholder()
    min_ctr_gap = min_ctr_gap_percent / 100.0

    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            SELECT *
            FROM gsc_page_metrics
            WHERE review_id = {ph}
              AND eligible_for_optimization = TRUE
              AND ctr_gap >= {ph}
              AND impact_score >= {ph}
            ORDER BY impact_score DESC
            LIMIT {ph}
        """, (review_id, min_ctr_gap, min_impact_score, max_results))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_page_ctr_history(page_url: str, months: int = 6) -> List[Dict]:
    """Get historical CTR progression for a page across monthly reviews"""
    ph = _placeholder()
    with get_connection() as conn:
        cursor = _get_cursor(conn)
        cursor.execute(f"""
            SELECT
                mr.review_month,
                gpm.ctr,
                gpm.position,
                gpm.impressions,
                gpm.clicks
            FROM gsc_page_metrics gpm
            JOIN monthly_reviews mr ON gpm.review_id = mr.id
            WHERE gpm.page_url = {ph}
            ORDER BY mr.review_date DESC
            LIMIT {ph}
        """, (page_url, months))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def format_ctr_progression(page_url: str, months: int = 3) -> str:
    """Format historical CTR as a progression string"""
    history = get_page_ctr_history(page_url, months)
    if not history:
        return "No history"

    history = list(reversed(history))
    progression = []
    for h in history:
        month_abbr = datetime.strptime(h['review_month'], '%Y-%m').strftime('%b')
        ctr_pct = int(h['ctr'] * 100)
        progression.append(f"{month_abbr} {ctr_pct}%")
    return " → ".join(progression)
