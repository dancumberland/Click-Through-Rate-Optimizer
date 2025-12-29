#!/usr/bin/env python3
# ABOUTME: Database operations for CTR optimization system
# ABOUTME: Handles all SQLite interactions for experiments, ideas, and metrics

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from .config import DB_PATH, MIN_DAYS_BETWEEN_CHANGES, MIN_DAYS_FOR_EVALUATION


def get_connection():
    """Get database connection with row factory for dict-like access"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================================
# SEO CHANGES (from existing schema)
# =============================================================================

def get_last_change_date(page_url: str) -> Optional[datetime]:
    """Get the date of the most recent SEO change for a page"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT MAX(changed_at) as last_change
        FROM seo_changes
        WHERE page_url = ?
    """, (page_url,))

    row = cursor.fetchone()
    conn.close()

    if row and row['last_change']:
        return datetime.fromisoformat(row['last_change'])
    return None


def get_days_since_last_change(page_url: str) -> Optional[int]:
    """Get number of days since last change, or None if never changed"""
    last_change = get_last_change_date(page_url)
    if last_change is None:
        return None
    return (datetime.now() - last_change).days


def can_optimize_page(page_url: str) -> bool:
    """Check if enough time has passed since last change"""
    days = get_days_since_last_change(page_url)
    if days is None:
        return True  # Never optimized
    return days >= MIN_DAYS_BETWEEN_CHANGES


# =============================================================================
# PAGE TRACKING (first-seen dates from GSC)
# =============================================================================

def get_page_first_seen(page_url: str) -> Optional[str]:
    """Get the first-seen date for a page from tracking table"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT first_seen_date
        FROM gsc_page_tracking
        WHERE page_url = ?
    """, (page_url,))

    row = cursor.fetchone()
    conn.close()

    return row['first_seen_date'] if row else None


def track_page_first_seen(page_url: str, page_slug: str, first_seen_date: str, wp_post_id: Optional[int] = None):
    """Record when a page first appeared in GSC"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO gsc_page_tracking (
            page_url, page_slug, first_seen_date, wp_post_id,
            last_seen_date, last_updated
        ) VALUES (?, ?, ?, ?, date('now'), datetime('now'))
    """, (page_url, page_slug, first_seen_date, wp_post_id))

    conn.commit()
    conn.close()


def update_page_last_seen(page_url: str, last_seen_date: str):
    """Update the last-seen date for a page"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE gsc_page_tracking
        SET last_seen_date = ?, last_updated = datetime('now')
        WHERE page_url = ?
    """, (last_seen_date, page_url))

    conn.commit()
    conn.close()


def get_days_since_first_seen(page_url: str) -> Optional[int]:
    """Get number of days since page first appeared in GSC"""
    first_seen = get_page_first_seen(page_url)
    if not first_seen:
        return None

    from datetime import datetime
    first_date = datetime.strptime(first_seen, '%Y-%m-%d')
    days = (datetime.now() - first_date).days
    return days


def is_page_old_enough_for_optimization(page_url: str, min_days: int = 30) -> bool:
    """
    Check if page has been in GSC long enough to optimize.

    Uses first-seen date from GSC rather than publish date.
    Returns True if:
    - Page has been seen in GSC for at least min_days
    - OR page is not tracked yet (allows discovery in monthly review)
    """
    days = get_days_since_first_seen(page_url)
    if days is None:
        return True  # Not tracked yet, will be discovered
    return days >= min_days


# =============================================================================
# HISTORICAL DATA LOGGING
# =============================================================================

def log_historical_gsc_data(page_url: str, data_date: str, impressions: int, clicks: int, ctr: float, position: float):
    """Log historical GSC data for long-term preservation"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO gsc_historical_data (
            page_url, data_date, impressions, clicks, ctr, position
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (page_url, data_date, impressions, clicks, ctr, position))

    conn.commit()
    conn.close()


def get_historical_data(page_url: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
    """Get historical GSC data for a page"""
    conn = get_connection()
    cursor = conn.cursor()

    if start_date and end_date:
        cursor.execute("""
            SELECT data_date, impressions, clicks, ctr, position
            FROM gsc_historical_data
            WHERE page_url = ? AND data_date BETWEEN ? AND ?
            ORDER BY data_date
        """, (page_url, start_date, end_date))
    else:
        cursor.execute("""
            SELECT data_date, impressions, clicks, ctr, position
            FROM gsc_historical_data
            WHERE page_url = ?
            ORDER BY data_date
        """, (page_url,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


# =============================================================================
# BENCHMARKS
# =============================================================================

def get_benchmarks() -> List[Dict]:
    """Get CTR benchmarks by position band"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT position_min, position_max, expected_ctr, sample_size
        FROM ctr_benchmarks
        ORDER BY position_min
    """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def update_benchmarks(benchmarks: List[Dict]):
    """Update CTR benchmarks (replace all)"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM ctr_benchmarks")

    for b in benchmarks:
        cursor.execute("""
            INSERT INTO ctr_benchmarks (position_min, position_max, expected_ctr, sample_size)
            VALUES (?, ?, ?, ?)
        """, (b['position_min'], b['position_max'], b['expected_ctr'], b.get('sample_size', 0)))

    conn.commit()
    conn.close()


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

    # If position is beyond all benchmarks, use the last one
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
    conn = get_connection()
    cursor = conn.cursor()

    min_eval_date = (datetime.now() + timedelta(days=MIN_DAYS_FOR_EVALUATION)).date()

    cursor.execute("""
        INSERT INTO optimization_experiments (
            page_url, page_slug, wp_post_id,
            hypothesis, idea_type,
            old_title, new_title,
            pre_ctr, pre_position, pre_impressions, pre_clicks,
            pre_measurement_start, pre_measurement_end,
            min_evaluation_date, outcome, status, review_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'active', ?)
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
    conn.close()

    return experiment_id


def get_active_experiments() -> List[Dict]:
    """Get all active experiments"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *,
            julianday('now') - julianday(started_at) as days_active,
            CASE WHEN date('now') >= min_evaluation_date THEN 1 ELSE 0 END as ready_for_evaluation
        FROM optimization_experiments
        WHERE status = 'active'
        ORDER BY started_at DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_experiments_ready_for_evaluation() -> List[Dict]:
    """Get experiments ready to be evaluated"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM optimization_experiments
        WHERE status = 'active'
          AND date('now') >= min_evaluation_date
          AND post_impressions >= 50
        ORDER BY started_at
    """)

    rows = cursor.fetchall()
    conn.close()

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
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE optimization_experiments
        SET post_ctr = ?,
            post_position = ?,
            post_impressions = ?,
            post_clicks = ?,
            post_measurement_start = ?,
            post_measurement_end = ?,
            last_measured = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        post_ctr, post_position, post_impressions, post_clicks,
        post_start_date, post_end_date, experiment_id
    ))

    conn.commit()
    conn.close()


def complete_experiment(
    experiment_id: int,
    outcome: str,
    ctr_change_pct: float,
    position_change: float,
    learnings: str
):
    """Mark experiment as completed with outcome"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE optimization_experiments
        SET status = 'completed',
            ended_at = CURRENT_TIMESTAMP,
            outcome = ?,
            ctr_change_pct = ?,
            position_change = ?,
            learnings = ?
        WHERE id = ?
    """, (outcome, ctr_change_pct, position_change, learnings, experiment_id))

    conn.commit()
    conn.close()


def get_experiment_history(page_url: str) -> List[Dict]:
    """Get all experiments for a specific page"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM optimization_experiments
        WHERE page_url = ?
        ORDER BY started_at DESC
    """, (page_url,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


# =============================================================================
# TITLE IDEAS
# =============================================================================

def store_title_ideas(
    page_url: str,
    ideas: List[Dict],
    review_id: Optional[int] = None
):
    """Store generated title ideas for a page"""
    conn = get_connection()
    cursor = conn.cursor()

    for idea in ideas:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO title_ideas (
                    page_url, idea_text, char_count, idea_type, hypothesis,
                    generated_for_review_id, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                page_url,
                idea['text'],
                len(idea['text']),
                idea['type'],
                idea.get('hypothesis', ''),
                review_id,
                idea.get('source', 'ai_generated')
            ))
        except sqlite3.IntegrityError:
            # Duplicate - skip
            pass

    conn.commit()
    conn.close()


def mark_idea_used(idea_id: int, experiment_id: int):
    """Mark an idea as used in an experiment"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE title_ideas
        SET selected = TRUE,
            used_at = CURRENT_TIMESTAMP,
            experiment_id = ?
        WHERE id = ?
    """, (experiment_id, idea_id))

    conn.commit()
    conn.close()


def get_past_ideas(page_url: str) -> List[Dict]:
    """Get all past ideas for a page (to avoid duplicates)"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT idea_text, idea_type, selected, used_at
        FROM title_ideas
        WHERE page_url = ?
    """, (page_url,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_unused_ideas(page_url: str) -> List[Dict]:
    """Get generated but unused ideas for a page"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM title_ideas
        WHERE page_url = ? AND selected = FALSE
        ORDER BY generated_at DESC
    """, (page_url,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


# =============================================================================
# MONTHLY REVIEWS
# =============================================================================

def create_monthly_review(
    review_date: datetime,
    gsc_start: str,
    gsc_end: str
) -> int:
    """Create a new monthly review record"""
    conn = get_connection()
    cursor = conn.cursor()

    review_month = review_date.strftime('%Y-%m')

    cursor.execute("""
        INSERT INTO monthly_reviews (
            review_date, review_month,
            gsc_data_start, gsc_data_end,
            status
        ) VALUES (?, ?, ?, ?, 'draft')
    """, (review_date.date(), review_month, gsc_start, gsc_end))

    review_id = cursor.lastrowid
    conn.commit()
    conn.close()

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
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE monthly_reviews
        SET total_pages_analyzed = ?,
            pages_eligible = ?,
            opportunities_identified = ?,
            experiments_proposed = ?,
            experiments_started = ?
        WHERE id = ?
    """, (total_pages, pages_eligible, opportunities, experiments_proposed, experiments_started, review_id))

    conn.commit()
    conn.close()


def complete_monthly_review(review_id: int, report_path: str):
    """Mark monthly review as completed"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE monthly_reviews
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            report_path = ?
        WHERE id = ?
    """, (report_path, review_id))

    conn.commit()
    conn.close()


def get_latest_review() -> Optional[Dict]:
    """Get the most recent monthly review"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM monthly_reviews
        ORDER BY review_date DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    conn.close()

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
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO ctr_learnings (
            learning_type, category, idea_type, insight,
            supporting_data, sample_size, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        learning_type, category, idea_type, insight,
        json.dumps(supporting_data) if supporting_data else None,
        sample_size, confidence
    ))

    conn.commit()
    conn.close()


def get_learnings(idea_type: Optional[str] = None) -> List[Dict]:
    """Get learnings, optionally filtered by idea type"""
    conn = get_connection()
    cursor = conn.cursor()

    if idea_type:
        cursor.execute("""
            SELECT * FROM ctr_learnings
            WHERE (idea_type = ? OR idea_type IS NULL)
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
    conn.close()

    return [dict(row) for row in rows]


def get_idea_type_performance() -> List[Dict]:
    """Get performance summary by idea type"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM v_idea_type_performance
        ORDER BY success_rate DESC
    """)

    rows = cursor.fetchall()
    conn.close()

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
    conn = get_connection()
    cursor = conn.cursor()

    ctr_gap = expected_ctr - ctr
    impact_score = impressions * max(ctr_gap, 0)

    days_since = get_days_since_last_change(page_url)
    last_change = get_last_change_date(page_url)
    eligible = can_optimize_page(page_url)

    cursor.execute("""
        INSERT INTO gsc_page_metrics (
            page_url, page_slug,
            measurement_start, measurement_end,
            impressions, clicks, ctr, position,
            expected_ctr, ctr_gap, impact_score,
            days_since_last_change, last_change_date, eligible_for_optimization,
            top_queries, review_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        page_url, page_slug,
        start_date, end_date,
        impressions, clicks, ctr, position,
        expected_ctr, ctr_gap, impact_score,
        days_since, last_change.date() if last_change else None, eligible,
        json.dumps(top_queries), review_id
    ))

    conn.commit()
    conn.close()


def get_optimization_opportunities(
    review_id: int,
    min_ctr_gap_percent: float = 15.0,
    min_impact_score: float = 5.0,
    max_results: int = 50
) -> List[Dict]:
    """
    Get optimization opportunities from a review based on CTR gap thresholds.

    Args:
        review_id: The monthly review ID
        min_ctr_gap_percent: Minimum CTR gap as percentage (e.g., 15.0 means 15% below expected)
        min_impact_score: Minimum impact score (impressions * ctr_gap)
        max_results: Safety limit on number of results

    Returns:
        List of pages meeting the thresholds, ordered by impact score
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Convert percentage to decimal for comparison with ctr_gap
    min_ctr_gap = min_ctr_gap_percent / 100.0

    cursor.execute("""
        SELECT *
        FROM gsc_page_metrics
        WHERE review_id = ?
          AND eligible_for_optimization = TRUE
          AND ctr_gap >= ?
          AND impact_score >= ?
        ORDER BY impact_score DESC
        LIMIT ?
    """, (review_id, min_ctr_gap, min_impact_score, max_results))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_page_ctr_history(page_url: str, months: int = 6) -> List[Dict]:
    """Get historical CTR progression for a page across monthly reviews"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            mr.review_month,
            gpm.ctr,
            gpm.position,
            gpm.impressions,
            gpm.clicks
        FROM gsc_page_metrics gpm
        JOIN monthly_reviews mr ON gpm.review_id = mr.id
        WHERE gpm.page_url = ?
        ORDER BY mr.review_date DESC
        LIMIT ?
    """, (page_url, months))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def format_ctr_progression(page_url: str, months: int = 3) -> str:
    """
    Format historical CTR as a progression string like "Nov 6% → Dec 9% → Jan 10%"
    Returns most recent `months` in chronological order
    """
    history = get_page_ctr_history(page_url, months)

    if not history:
        return "No history"

    # Reverse to show oldest first (chronological)
    history = list(reversed(history))

    # Format as "MonthName CTR%"
    progression = []
    for h in history:
        month_abbr = datetime.strptime(h['review_month'], '%Y-%m').strftime('%b')
        ctr_pct = int(h['ctr'] * 100)  # Convert to whole percentage
        progression.append(f"{month_abbr} {ctr_pct}%")

    return " → ".join(progression)
