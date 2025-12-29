#!/usr/bin/env python3
# ABOUTME: Gap analysis and benchmark calculation for CTR system
# ABOUTME: Identifies underperforming pages with position-adjusted CTR expectations

from datetime import datetime
from typing import List, Dict, Optional

from .config import (
    DEFAULT_CTR_BENCHMARKS,
    MIN_IMPRESSIONS_FOR_ANALYSIS,
    MIN_CTR_GAP_PERCENT,
    MIN_IMPACT_SCORE,
    MAX_EXPERIMENTS_PER_MONTH
)
from . import database as db
from .gsc_client import get_gsc_client


def refresh_benchmarks(days: int = 90) -> List[Dict]:
    """Calculate and store site-specific CTR benchmarks"""
    print("Calculating site-specific CTR benchmarks...")

    client = get_gsc_client()
    start_date, end_date = client.get_valid_date_range(max_days=days)

    benchmarks = client.calculate_position_benchmarks(
        start_date, end_date,
        min_impressions=MIN_IMPRESSIONS_FOR_ANALYSIS
    )

    if benchmarks:
        db.update_benchmarks(benchmarks)
        print(f"  Updated {len(benchmarks)} position bands")
        for b in benchmarks:
            print(f"    Position {b['position_min']:.1f}-{b['position_max']:.1f}: "
                  f"{b['expected_ctr']*100:.2f}% CTR ({b['sample_size']} pages)")
    else:
        print("  No data available, using defaults")
        db.update_benchmarks(DEFAULT_CTR_BENCHMARKS)

    return benchmarks


def analyze_all_pages(review_id: int, days: int = 90) -> List[Dict]:
    """Analyze all pages and store metrics with gap analysis"""
    print("Analyzing all pages for CTR opportunities...")

    client = get_gsc_client()
    start_date, end_date = client.get_valid_date_range(max_days=days)

    pages = client.get_all_pages(start_date, end_date, MIN_IMPRESSIONS_FOR_ANALYSIS)
    print(f"  Found {len(pages)} pages with {MIN_IMPRESSIONS_FOR_ANALYSIS}+ impressions")

    # Auto-track first-seen dates for new pages
    print("  Auto-tracking first-seen dates from GSC...")
    new_pages_tracked = 0
    for page in pages:
        page_url = page['page_url']

        # Check if we've tracked this page before
        if db.get_page_first_seen(page_url) is None:
            # New page - find when it first appeared in GSC
            first_seen = client.get_page_first_seen_date(page_url)
            if first_seen:
                db.track_page_first_seen(
                    page_url=page_url,
                    page_slug=page['page_slug'],
                    first_seen_date=first_seen
                )
                new_pages_tracked += 1

        # Update last-seen date
        db.update_page_last_seen(page_url, end_date)

    if new_pages_tracked > 0:
        print(f"    Tracked {new_pages_tracked} new pages from GSC")

    # Analyze each page
    results = []
    for i, page in enumerate(pages):
        page_url = page['page_url']
        page_slug = page['page_slug']

        # Get time-adjusted metrics if page was recently changed
        last_change = db.get_last_change_date(page_url)
        if last_change:
            # Get metrics only from after the change
            date_range = client.get_valid_date_range(last_change)

            # If change is too recent (no valid data yet), skip this page
            if date_range is None:
                continue

            adj_start, adj_end = date_range
            adj_metrics = client.get_page_metrics(page_url, adj_start, adj_end)

            if adj_metrics and adj_metrics['impressions'] >= MIN_IMPRESSIONS_FOR_ANALYSIS:
                page = adj_metrics
                page['page_slug'] = page_slug
                start_date = adj_start
                end_date = adj_end
            # If not enough post-change data, skip this page
            elif adj_metrics:
                continue

        # Calculate expected CTR based on position
        expected_ctr = db.get_expected_ctr(page['position'])

        # Get top queries
        queries = client.get_queries_for_page(page_url, start_date, end_date)

        # Store in database
        db.store_gsc_metrics(
            page_url=page_url,
            page_slug=page_slug,
            start_date=start_date,
            end_date=end_date,
            impressions=page['impressions'],
            clicks=page['clicks'],
            ctr=page['ctr'],
            position=page['position'],
            expected_ctr=expected_ctr,
            top_queries=queries[:10],  # Store top 10 queries
            review_id=review_id
        )

        # Add to results
        page['expected_ctr'] = expected_ctr
        page['ctr_gap'] = expected_ctr - page['ctr']
        page['impact_score'] = page['impressions'] * max(page['ctr_gap'], 0)
        page['top_queries'] = queries

        # Check eligibility: old enough AND enough time since last change
        page['eligible'] = (
            db.is_page_old_enough_for_optimization(page_url, min_days=30) and
            db.can_optimize_page(page_url)
        )
        results.append(page)

        if (i + 1) % 50 == 0:
            print(f"    Processed {i + 1}/{len(pages)} pages...")

    print(f"  Analysis complete: {len(results)} pages processed")
    return results


def get_top_opportunities(review_id: int) -> List[Dict]:
    """
    Get optimization opportunities that meet CTR gap thresholds.

    Uses threshold-based selection instead of a fixed limit:
    - Pages must be underperforming by at least MIN_CTR_GAP_PERCENT
    - Pages must have impact score >= MIN_IMPACT_SCORE
    - Returns ALL pages meeting criteria, up to MAX_EXPERIMENTS_PER_MONTH safety limit

    This means: if 40 pages need optimization, optimize all 40 (vs old behavior of only 20)
    """
    opportunities = db.get_optimization_opportunities(
        review_id=review_id,
        min_ctr_gap_percent=MIN_CTR_GAP_PERCENT,
        min_impact_score=MIN_IMPACT_SCORE,
        max_results=MAX_EXPERIMENTS_PER_MONTH
    )

    # Enrich with additional calculated fields
    results = []
    for opp in opportunities:
        results.append({
            'page_url': opp['page_url'],
            'page_slug': opp['page_slug'],
            'impressions': opp['impressions'],
            'clicks': opp['clicks'],
            'current_ctr': opp['ctr'],
            'expected_ctr': opp['expected_ctr'],
            'ctr_gap': opp['ctr_gap'],
            'ctr_gap_pct': (opp['ctr_gap'] / opp['expected_ctr'] * 100) if opp['expected_ctr'] > 0 else 0,
            'position': opp['position'],
            'impact_score': opp['impact_score'],
            'days_since_change': opp['days_since_last_change'],
            'top_queries': opp['top_queries'],
            'eligible': opp['eligible_for_optimization']
        })

    return results


def calculate_potential_impact(opportunities: List[Dict]) -> Dict:
    """Calculate the total potential impact of optimizing these pages"""
    total_impressions = sum(o['impressions'] for o in opportunities)
    current_clicks = sum(o['clicks'] for o in opportunities)

    # Estimate potential clicks if we hit expected CTR
    potential_clicks = sum(
        o['impressions'] * o['expected_ctr']
        for o in opportunities
    )

    potential_gain = potential_clicks - current_clicks

    return {
        'pages_count': len(opportunities),
        'total_impressions': total_impressions,
        'current_clicks': current_clicks,
        'potential_clicks': int(potential_clicks),
        'potential_gain': int(potential_gain),
        'potential_improvement_pct': (potential_gain / current_clicks * 100) if current_clicks > 0 else 0
    }


def get_page_context(page_url: str) -> Dict:
    """Get full context for a page including history and queries"""
    from .gsc_client import get_gsc_client

    client = get_gsc_client()

    # Get experiment history
    history = db.get_experiment_history(page_url)

    # Get past ideas
    past_ideas = db.get_past_ideas(page_url)

    # Get learnings that might apply
    learnings = db.get_learnings()

    # Get idea type performance for this site
    idea_performance = db.get_idea_type_performance()

    return {
        'page_url': page_url,
        'experiment_history': history,
        'past_ideas': past_ideas,
        'site_learnings': learnings,
        'idea_type_performance': idea_performance
    }


def generate_analysis_summary(opportunities: List[Dict]) -> str:
    """Generate a text summary of the analysis"""
    if not opportunities:
        return "No optimization opportunities found."

    impact = calculate_potential_impact(opportunities)

    lines = [
        "## CTR Gap Analysis Summary",
        "",
        f"**Pages analyzed with opportunities:** {impact['pages_count']}",
        f"**Total impressions:** {impact['total_impressions']:,}",
        f"**Current clicks:** {impact['current_clicks']:,}",
        f"**Potential clicks:** {impact['potential_clicks']:,}",
        f"**Potential gain:** +{impact['potential_gain']:,} clicks ({impact['potential_improvement_pct']:.1f}%)",
        "",
        "### Top Opportunities",
        ""
    ]

    for i, opp in enumerate(opportunities[:10], 1):
        lines.append(f"**{i}. {opp['page_slug']}**")
        lines.append(f"   - CTR: {opp['current_ctr']*100:.2f}% (expected {opp['expected_ctr']*100:.2f}%)")
        lines.append(f"   - Gap: -{opp['ctr_gap_pct']:.1f}%")
        lines.append(f"   - Position: {opp['position']:.1f}")
        lines.append(f"   - Impressions: {opp['impressions']:,}")
        if opp['days_since_change'] is not None:
            lines.append(f"   - Days since last change: {opp['days_since_change']}")
        lines.append("")

    return "\n".join(lines)
