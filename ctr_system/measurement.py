#!/usr/bin/env python3
# ABOUTME: Measurement and evaluation module for CTR experiments
# ABOUTME: Updates metrics, determines outcomes, extracts learnings

from datetime import datetime, timedelta
from typing import List, Dict, Optional

from .config import (
    IMPROVEMENT_THRESHOLD,
    WORSENED_THRESHOLD,
    POSITION_CHANGE_THRESHOLD,
    MIN_POST_CHANGE_IMPRESSIONS,
    MAX_DAYS_FOR_EVALUATION
)
from . import database as db
from .gsc_client import get_gsc_client


def update_experiment_metrics(experiment: Dict) -> Dict:
    """Update post-change metrics for an experiment"""
    client = get_gsc_client()

    page_url = experiment['page_url']
    started_at = datetime.fromisoformat(experiment['started_at'])

    # Get metrics from day after change to now
    start_date, end_date = client.get_valid_date_range(started_at)

    metrics = client.get_page_metrics(page_url, start_date, end_date)

    if metrics:
        db.update_experiment_metrics(
            experiment_id=experiment['id'],
            post_ctr=metrics['ctr'],
            post_position=metrics['position'],
            post_impressions=metrics['impressions'],
            post_clicks=metrics['clicks'],
            post_start_date=start_date,
            post_end_date=end_date
        )

        return {
            **experiment,
            'post_ctr': metrics['ctr'],
            'post_position': metrics['position'],
            'post_impressions': metrics['impressions'],
            'post_clicks': metrics['clicks']
        }

    return experiment


def evaluate_experiment(experiment: Dict) -> Dict:
    """Evaluate an experiment and determine outcome"""

    # Check if we have enough data
    if experiment.get('post_impressions', 0) < MIN_POST_CHANGE_IMPRESSIONS:
        return {
            'outcome': 'inconclusive',
            'reason': f"Insufficient impressions ({experiment.get('post_impressions', 0)} < {MIN_POST_CHANGE_IMPRESSIONS})"
        }

    pre_ctr = experiment.get('pre_ctr', 0)
    post_ctr = experiment.get('post_ctr', 0)
    pre_position = experiment.get('pre_position', 0)
    post_position = experiment.get('post_position', 0)

    # Calculate changes
    if pre_ctr > 0:
        ctr_change_pct = (post_ctr - pre_ctr) / pre_ctr
    else:
        ctr_change_pct = 1.0 if post_ctr > 0 else 0

    position_change = post_position - pre_position  # Negative = improved

    # Determine outcome
    position_confounded = abs(position_change) > POSITION_CHANGE_THRESHOLD

    if ctr_change_pct >= IMPROVEMENT_THRESHOLD:
        outcome = 'improved'
        if position_confounded and position_change < 0:
            reason = f"CTR improved {ctr_change_pct*100:+.1f}% (position also improved by {abs(position_change):.1f})"
        else:
            reason = f"CTR improved {ctr_change_pct*100:+.1f}%"
    elif ctr_change_pct <= WORSENED_THRESHOLD:
        outcome = 'worsened'
        if position_confounded and position_change > 0:
            reason = f"CTR declined {ctr_change_pct*100:.1f}% (position also declined by {position_change:.1f})"
        else:
            reason = f"CTR declined {ctr_change_pct*100:.1f}%"
    else:
        outcome = 'no_change'
        reason = f"CTR change {ctr_change_pct*100:+.1f}% within noise threshold"

    # Generate learnings
    learnings = generate_learnings(experiment, outcome, ctr_change_pct, position_change)

    return {
        'outcome': outcome,
        'ctr_change_pct': ctr_change_pct * 100,
        'position_change': position_change,
        'reason': reason,
        'learnings': learnings,
        'position_confounded': position_confounded
    }


def generate_learnings(
    experiment: Dict,
    outcome: str,
    ctr_change_pct: float,
    position_change: float
) -> str:
    """Generate learnings from an experiment outcome"""

    idea_type = experiment.get('idea_type', 'unknown')
    hypothesis = experiment.get('hypothesis', '')

    if outcome == 'improved':
        learning = f"✅ {idea_type.upper()} worked: {hypothesis} "
        learning += f"(CTR {ctr_change_pct*100:+.1f}%)"
    elif outcome == 'worsened':
        learning = f"❌ {idea_type.upper()} failed: {hypothesis} "
        learning += f"(CTR {ctr_change_pct*100:.1f}%)"
    else:
        learning = f"➖ {idea_type.upper()} neutral: {hypothesis}"

    if abs(position_change) > POSITION_CHANGE_THRESHOLD:
        learning += f" [Position changed by {position_change:+.1f}]"

    return learning


def update_all_active_experiments() -> List[Dict]:
    """Update metrics for all active experiments"""
    print("Updating metrics for active experiments...")

    experiments = db.get_active_experiments()
    print(f"  Found {len(experiments)} active experiments")

    results = []
    for exp in experiments:
        print(f"  Updating: {exp['page_slug']}...")
        updated = update_experiment_metrics(exp)
        results.append(updated)

    return results


def evaluate_ready_experiments() -> List[Dict]:
    """Evaluate experiments that are ready for evaluation"""
    print("Evaluating ready experiments...")

    experiments = db.get_experiments_ready_for_evaluation()
    print(f"  Found {len(experiments)} experiments ready for evaluation")

    results = []
    for exp in experiments:
        print(f"  Evaluating: {exp['page_slug']}...")

        evaluation = evaluate_experiment(exp)

        # Complete the experiment in database
        db.complete_experiment(
            experiment_id=exp['id'],
            outcome=evaluation['outcome'],
            ctr_change_pct=evaluation['ctr_change_pct'],
            position_change=evaluation['position_change'],
            learnings=evaluation['learnings']
        )

        results.append({
            **exp,
            **evaluation
        })

        print(f"    → {evaluation['outcome']}: {evaluation['reason']}")

    return results


def check_for_significant_changes() -> List[Dict]:
    """Check active experiments for significant changes that need attention"""
    experiments = db.get_active_experiments()

    alerts = []
    for exp in experiments:
        if exp.get('post_ctr') is None:
            continue

        pre_ctr = exp.get('pre_ctr', 0)
        post_ctr = exp.get('post_ctr', 0)

        if pre_ctr > 0:
            change_pct = (post_ctr - pre_ctr) / pre_ctr
        else:
            change_pct = 0

        # Alert on significant decline
        if change_pct < -0.20:  # 20% decline
            alerts.append({
                'type': 'decline',
                'experiment': exp,
                'change_pct': change_pct * 100,
                'message': f"⚠️ {exp['page_slug']} CTR down {change_pct*100:.1f}%"
            })

        # Alert on significant improvement
        if change_pct > 0.30:  # 30% improvement
            alerts.append({
                'type': 'success',
                'experiment': exp,
                'change_pct': change_pct * 100,
                'message': f"🎉 {exp['page_slug']} CTR up {change_pct*100:+.1f}%"
            })

    return alerts


def get_experiment_summary() -> Dict:
    """Get summary of all experiments"""
    conn = db.get_connection()
    cursor = conn.cursor()

    # Active experiments
    cursor.execute("SELECT COUNT(*) as cnt FROM optimization_experiments WHERE status = 'active'")
    active = cursor.fetchone()['cnt']

    # Completed experiments by outcome
    cursor.execute("""
        SELECT outcome, COUNT(*) as cnt, AVG(ctr_change_pct) as avg_change
        FROM optimization_experiments
        WHERE status = 'completed' AND outcome IS NOT NULL
        GROUP BY outcome
    """)
    outcomes = {row['outcome']: {'count': row['cnt'], 'avg_change': row['avg_change']}
                for row in cursor.fetchall()}

    # Overall success rate
    total_completed = sum(o['count'] for o in outcomes.values())
    improved = outcomes.get('improved', {}).get('count', 0)
    success_rate = (improved / total_completed * 100) if total_completed > 0 else 0

    conn.close()

    return {
        'active': active,
        'completed': total_completed,
        'outcomes': outcomes,
        'success_rate': success_rate
    }
