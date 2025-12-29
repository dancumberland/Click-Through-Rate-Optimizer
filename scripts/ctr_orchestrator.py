#!/usr/bin/env python3
# ABOUTME: Main orchestrator for CTR optimization system
# ABOUTME: Runs monthly reviews, weekly measurements, and automated optimizations

import argparse
import sys
import json
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ctr_system.config import (
    validate_config,
    MIN_CTR_GAP_PERCENT,
    MIN_IMPACT_SCORE,
    MAX_EXPERIMENTS_PER_MONTH,
    REPORTS_DIR
)
from ctr_system import database as db
from ctr_system.gsc_client import get_gsc_client
from ctr_system.analysis import (
    refresh_benchmarks,
    analyze_all_pages,
    get_top_opportunities,
    calculate_potential_impact,
    generate_analysis_summary
)
from ctr_system.ideation import generate_and_select
from ctr_system.implementation import implement_title_change, get_current_title, get_post_id_from_slug
from ctr_system.measurement import (
    update_all_active_experiments,
    evaluate_ready_experiments,
    check_for_significant_changes,
    get_experiment_summary
)
from ctr_system.reporting import (
    generate_monthly_report,
    save_report,
    generate_weekly_status
)
from ctr_system.notifications import (
    notify_monthly_review_complete,
    notify_weekly_status,
    notify_alert,
    send_monthly_report_email
)


def run_monthly_review(dry_run: bool = False):
    """Run the full monthly review process"""
    print("=" * 60)
    print("CTR MONTHLY REVIEW")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 60)
    print()

    if not validate_config():
        print("Configuration validation failed. Exiting.")
        return False

    # Initialize GSC client
    print("Connecting to Google Search Console...")
    client = get_gsc_client()
    start_date, end_date = client.get_valid_date_range()
    print(f"  Data range: {start_date} to {end_date}")
    print()

    # Create review record
    review_id = db.create_monthly_review(datetime.now(), start_date, end_date)
    print(f"Created review record: #{review_id}")
    print()

    # Step 1: Refresh benchmarks
    print("STEP 1: Refreshing CTR benchmarks...")
    refresh_benchmarks()
    print()

    # Step 2: Analyze all pages
    print("STEP 2: Analyzing all pages...")
    all_pages = analyze_all_pages(review_id)
    print()

    # Step 3: Get opportunities meeting CTR gap thresholds
    print("STEP 3: Identifying optimization opportunities...")
    print(f"  Thresholds: CTR gap ≥{MIN_CTR_GAP_PERCENT}%, Impact score ≥{MIN_IMPACT_SCORE}")
    opportunities = get_top_opportunities(review_id)
    print(f"  Found {len(opportunities)} pages meeting criteria")

    impact = calculate_potential_impact(opportunities)
    print(f"  Potential impact: +{impact['potential_gain']:,} clicks")
    print()

    # Step 4: Evaluate any completed experiments from previous month
    print("STEP 4: Evaluating completed experiments...")
    completed = evaluate_ready_experiments()
    print(f"  Completed {len(completed)} experiments")
    print()

    # Step 5: Generate ideas and implement for ALL opportunities meeting criteria
    num_to_optimize = len(opportunities)
    print(f"STEP 5: Optimizing {num_to_optimize} pages meeting criteria...")
    if num_to_optimize == MAX_EXPERIMENTS_PER_MONTH:
        print(f"  ⚠️  Hit safety limit of {MAX_EXPERIMENTS_PER_MONTH} - consider raising thresholds")
    experiments_started = []

    for i, opp in enumerate(opportunities, 1):
        page_url = opp['page_url']
        page_slug = opp['page_slug']

        print(f"\n[{i}/{num_to_optimize}] {page_slug}")
        print(f"  Current CTR: {opp['current_ctr']*100:.2f}% (expected {opp['expected_ctr']*100:.2f}%)")
        print(f"  Gap: {opp['ctr_gap_pct']:.1f}%, Impact: {opp['impact_score']:.1f}")

        try:
            # Get current title
            post_id = get_post_id_from_slug(page_slug)
            if not post_id:
                print(f"  ⚠️ Could not find post ID, skipping")
                continue

            current_title = get_current_title(post_id)
            print(f"  Current title: {current_title[:50]}...")

            # Get queries
            queries = opp.get('top_queries', [])
            if isinstance(queries, str):
                queries = json.loads(queries)

            # Generate and select best idea
            print(f"  Generating title ideas...")
            result = generate_and_select(
                page_url=page_url,
                page_slug=page_slug,
                current_title=current_title,
                current_ctr=opp['current_ctr'],
                expected_ctr=opp['expected_ctr'],
                position=opp['position'],
                top_queries=queries,
                review_id=review_id
            )

            selected = result['selected']
            print(f"  Selected: {selected['text']} [{selected['type']}]")
            print(f"  Hypothesis: {selected['hypothesis']}")

            if dry_run:
                print(f"  [DRY RUN] Would update title")
                experiments_started.append({
                    'page_slug': page_slug,
                    'old_title': current_title,
                    'new_title': selected['text'],
                    'idea_type': selected['type'],
                    'hypothesis': selected['hypothesis']
                })
            else:
                # Implement the change
                experiment_id = implement_title_change(
                    page_url=page_url,
                    page_slug=page_slug,
                    new_title=selected['text'],
                    hypothesis=selected['hypothesis'],
                    idea_type=selected['type'],
                    pre_ctr=opp['current_ctr'],
                    pre_position=opp['position'],
                    pre_impressions=opp['impressions'],
                    pre_clicks=opp['clicks'],
                    pre_start_date=start_date,
                    pre_end_date=end_date,
                    review_id=review_id
                )

                if experiment_id:
                    experiments_started.append({
                        'id': experiment_id,
                        'page_slug': page_slug,
                        'old_title': current_title,
                        'new_title': selected['text'],
                        'idea_type': selected['type'],
                        'hypothesis': selected['hypothesis']
                    })

        except Exception as e:
            print(f"  ❌ Error: {e}")
            continue

    print()

    # Step 6: Update review stats
    eligible_count = len([o for o in opportunities if o.get('eligible', True)])
    db.update_review_stats(
        review_id=review_id,
        total_pages=len(all_pages),
        pages_eligible=eligible_count,
        opportunities=len(opportunities),
        experiments_proposed=len(opportunities),
        experiments_started=len(experiments_started)
    )

    # Step 7: Check for alerts
    print("STEP 6: Checking for alerts...")
    alerts = check_for_significant_changes()
    if alerts:
        print(f"  Found {len(alerts)} alerts")
        for alert in alerts:
            print(f"    {alert['message']}")
            if not dry_run:
                notify_alert(alert)
    else:
        print("  No alerts")
    print()

    # Step 8: Generate report
    print("STEP 7: Generating report...")
    report_content = generate_monthly_report(
        review_id=review_id,
        opportunities=opportunities,
        experiments_started=experiments_started,
        completed_experiments=completed,
        alerts=alerts
    )

    if not dry_run:
        report_path = save_report(report_content, review_id)
        print(f"  Report saved to: {report_path}")
    else:
        report_path = "[DRY RUN - not saved]"
        print("  [DRY RUN] Report not saved")

    # Print report to console
    print()
    print("=" * 60)
    print("REPORT PREVIEW")
    print("=" * 60)
    print(report_content[:2000])
    if len(report_content) > 2000:
        print("... [truncated]")
    print()

    # Step 9: Send notifications
    if not dry_run:
        print("STEP 8: Sending notifications...")
        summary = get_experiment_summary()
        notify_monthly_review_complete(
            experiments_started=len(experiments_started),
            experiments_completed=len(completed),
            success_rate=summary.get('success_rate', 0),
            report_path=report_path
        )

        # Send detailed email report
        print("Sending detailed email report...")
        email_sent = send_monthly_report_email(
            experiments_started=experiments_started,
            completed_experiments=completed,
            success_rate=summary.get('success_rate', 0),
            report_path=report_path
        )
        if email_sent:
            print("  ✓ Email report sent")
        else:
            print("  ⚠️ Email not sent (check SMTP configuration)")
    print()

    # Summary
    print("=" * 60)
    print("MONTHLY REVIEW COMPLETE")
    print("=" * 60)
    print(f"  Pages analyzed: {len(all_pages)}")
    print(f"  Opportunities found: {len(opportunities)}")
    print(f"  Experiments started: {len(experiments_started)}")
    print(f"  Experiments completed: {len(completed)}")
    print(f"  Report: {report_path}")
    print()

    return True


def run_weekly_measurement(dry_run: bool = False):
    """Run weekly measurement update"""
    print("=" * 60)
    print("CTR WEEKLY MEASUREMENT")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print()

    # Update all active experiments
    print("Updating active experiment metrics...")
    active = update_all_active_experiments()
    print(f"  Updated {len(active)} experiments")
    print()

    # Evaluate any ready experiments
    print("Evaluating ready experiments...")
    completed = evaluate_ready_experiments()
    print(f"  Completed {len(completed)} experiments")
    print()

    # Check for alerts
    print("Checking for significant changes...")
    alerts = check_for_significant_changes()
    if alerts:
        print(f"  Found {len(alerts)} alerts:")
        for alert in alerts:
            print(f"    {alert['message']}")
            if not dry_run:
                notify_alert(alert)
    else:
        print("  No alerts")
    print()

    # Generate status
    status = generate_weekly_status(active, alerts)

    print("=" * 60)
    print("STATUS")
    print("=" * 60)
    print(status)
    print()

    # Send notification
    if not dry_run:
        notify_weekly_status(len(active), alerts)

    print("Weekly measurement complete.")
    return True


def show_status():
    """Show current system status"""
    print("=" * 60)
    print("CTR SYSTEM STATUS")
    print("=" * 60)
    print()

    summary = get_experiment_summary()

    print(f"Active Experiments: {summary.get('active', 0)}")
    print(f"Total Completed: {summary.get('completed', 0)}")
    print(f"Success Rate: {summary.get('success_rate', 0):.1f}%")
    print()

    outcomes = summary.get('outcomes', {})
    if outcomes:
        print("Outcomes breakdown:")
        for outcome, data in outcomes.items():
            print(f"  {outcome}: {data['count']} (avg {data['avg_change']:+.1f}%)")
    print()

    # Show active experiments
    active = db.get_active_experiments()
    if active:
        print("Active Experiments:")
        for exp in active[:10]:
            days = exp.get('days_active', 0)
            ready = "✓" if exp.get('ready_for_evaluation') else ""
            print(f"  {exp['page_slug']} ({days:.0f} days) {ready}")
    print()

    # Show idea type performance
    perf = db.get_idea_type_performance()
    if perf:
        print("Idea Type Performance:")
        for p in perf:
            print(f"  {p['idea_type']}: {p['success_rate']:.0f}% success ({p['total_experiments']} exp)")
    print()


def main():
    parser = argparse.ArgumentParser(description='CTR Optimization System')
    parser.add_argument('mode', choices=['monthly', 'weekly', 'status'],
                       help='Operation mode')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run without making changes')

    args = parser.parse_args()

    if args.mode == 'monthly':
        run_monthly_review(dry_run=args.dry_run)
    elif args.mode == 'weekly':
        run_weekly_measurement(dry_run=args.dry_run)
    elif args.mode == 'status':
        show_status()


if __name__ == '__main__':
    main()
