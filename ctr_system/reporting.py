#!/usr/bin/env python3
# ABOUTME: Report generation for CTR optimization system
# ABOUTME: Creates markdown reports for monthly reviews and experiment results

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .config import REPORTS_DIR
from . import database as db
from .measurement import get_experiment_summary


def generate_monthly_report(
    review_id: int,
    opportunities: List[Dict],
    experiments_started: List[Dict],
    completed_experiments: List[Dict],
    alerts: List[Dict]
) -> str:
    """Generate comprehensive monthly report"""

    review = db.get_latest_review()
    review_date = datetime.now().strftime('%Y-%m-%d')
    review_month = datetime.now().strftime('%B %Y')

    # Get experiment summary
    summary = get_experiment_summary()

    # Get idea type performance
    idea_performance = db.get_idea_type_performance()

    lines = [
        f"# CTR Monthly Review - {review_month}",
        "",
        f"**Generated:** {review_date}",
        f"**Review ID:** {review_id}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
    ]

    # Summary stats
    lines.extend([
        f"- **Pages Analyzed:** {review.get('total_pages_analyzed', 'N/A') if review else 'N/A'}",
        f"- **Eligible for Optimization:** {review.get('pages_eligible', 'N/A') if review else 'N/A'}",
        f"- **New Experiments Started:** {len(experiments_started)}",
        f"- **Experiments Completed:** {len(completed_experiments)}",
        f"- **Active Experiments:** {summary.get('active', 0)}",
        f"- **Overall Success Rate:** {summary.get('success_rate', 0):.1f}%",
        "",
    ])

    # Alerts section
    if alerts:
        lines.extend([
            "## ⚠️ Alerts",
            "",
        ])
        for alert in alerts:
            lines.append(f"- {alert['message']}")
        lines.append("")

    # Completed experiments section
    if completed_experiments:
        lines.extend([
            "## Completed Experiments",
            "",
            "| Page | Old Title | New Title | CTR Change | Outcome |",
            "|------|-----------|-----------|------------|---------|",
        ])

        for exp in completed_experiments:
            old = (exp.get('old_title', '')[:30] + '...') if len(exp.get('old_title', '')) > 30 else exp.get('old_title', '')
            new = (exp.get('new_title', '')[:30] + '...') if len(exp.get('new_title', '')) > 30 else exp.get('new_title', '')
            change = f"{exp.get('ctr_change_pct', 0):+.1f}%"
            outcome_emoji = {'improved': '✅', 'worsened': '❌', 'no_change': '➖'}.get(exp.get('outcome', ''), '❓')

            lines.append(f"| {exp.get('page_slug', '')} | {old} | {new} | {change} | {outcome_emoji} {exp.get('outcome', '')} |")

        lines.append("")

        # Learnings from completed experiments
        lines.extend([
            "### Key Learnings",
            "",
        ])
        for exp in completed_experiments:
            if exp.get('learnings'):
                lines.append(f"- {exp['learnings']}")
        lines.append("")

    # New experiments section
    if experiments_started:
        lines.extend([
            "## New Experiments Started",
            "",
            "| Page | New Title | Idea Type | Hypothesis |",
            "|------|-----------|-----------|------------|",
        ])

        for exp in experiments_started:
            title = (exp.get('new_title', '')[:40] + '...') if len(exp.get('new_title', '')) > 40 else exp.get('new_title', '')
            hypothesis = (exp.get('hypothesis', '')[:50] + '...') if len(exp.get('hypothesis', '')) > 50 else exp.get('hypothesis', '')

            lines.append(f"| {exp.get('page_slug', '')} | {title} | {exp.get('idea_type', '')} | {hypothesis} |")

        lines.append("")

    # Opportunities not acted on
    if opportunities:
        lines.extend([
            "## Top Opportunities Identified",
            "",
        ])

        for i, opp in enumerate(opportunities[:10], 1):
            lines.extend([
                f"### {i}. {opp.get('page_slug', '')}",
                "",
                f"- **Current CTR:** {opp.get('current_ctr', 0)*100:.2f}%",
                f"- **Expected CTR:** {opp.get('expected_ctr', 0)*100:.2f}%",
                f"- **Gap:** -{opp.get('ctr_gap_pct', 0):.1f}%",
                f"- **Position:** {opp.get('position', 0):.1f}",
                f"- **Impressions:** {opp.get('impressions', 0):,}",
                "",
            ])

            # Top queries
            queries = opp.get('top_queries', [])
            if queries:
                if isinstance(queries, str):
                    queries = json.loads(queries)
                lines.append("**Top Queries:**")
                for q in queries[:5]:
                    lines.append(f"  - \"{q.get('query', '')}\" ({q.get('impressions', 0):,} imp)")
                lines.append("")

    # Idea type performance
    if idea_performance:
        lines.extend([
            "## Idea Type Performance",
            "",
            "| Type | Experiments | Success Rate | Avg CTR Change |",
            "|------|-------------|--------------|----------------|",
        ])

        for perf in idea_performance:
            lines.append(
                f"| {perf['idea_type']} | {perf['total_experiments']} | "
                f"{perf['success_rate']:.0f}% | {perf['avg_ctr_change']:+.1f}% |"
            )

        lines.append("")

    # Footer
    lines.extend([
        "---",
        "",
        f"*Report generated automatically by CTR Optimization System*",
        f"*Next review scheduled: 1st of next month*",
    ])

    return "\n".join(lines)


def save_report(report_content: str, review_id: int) -> str:
    """Save report to file and update database"""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"ctr_review_{datetime.now().strftime('%Y%m')}.md"
    filepath = REPORTS_DIR / filename

    with open(filepath, 'w') as f:
        f.write(report_content)

    # Update review record with report path
    db.complete_monthly_review(review_id, str(filepath))

    return str(filepath)


def generate_weekly_status(
    active_experiments: List[Dict],
    alerts: List[Dict]
) -> str:
    """Generate weekly status update"""

    lines = [
        f"# CTR Weekly Status - {datetime.now().strftime('%Y-%m-%d')}",
        "",
    ]

    # Alerts first
    if alerts:
        lines.extend([
            "## Alerts",
            "",
        ])
        for alert in alerts:
            lines.append(f"- {alert['message']}")
        lines.append("")

    # Active experiments
    lines.extend([
        "## Active Experiments",
        "",
        f"**Total Active:** {len(active_experiments)}",
        "",
    ])

    if active_experiments:
        lines.extend([
            "| Page | Days Active | Pre CTR | Post CTR | Change |",
            "|------|-------------|---------|----------|--------|",
        ])

        for exp in active_experiments:
            pre = exp.get('pre_ctr', 0) * 100
            post = exp.get('post_ctr')
            if post is not None:
                post_str = f"{post*100:.2f}%"
                change = ((post - exp.get('pre_ctr', 0)) / exp.get('pre_ctr', 1)) * 100
                change_str = f"{change:+.1f}%"
            else:
                post_str = "pending"
                change_str = "-"

            lines.append(
                f"| {exp.get('page_slug', '')} | {exp.get('days_active', 0):.0f} | "
                f"{pre:.2f}% | {post_str} | {change_str} |"
            )

        lines.append("")

    # Summary
    summary = get_experiment_summary()
    lines.extend([
        "## Overall Stats",
        "",
        f"- **Total Completed:** {summary.get('completed', 0)}",
        f"- **Success Rate:** {summary.get('success_rate', 0):.1f}%",
        "",
    ])

    return "\n".join(lines)
