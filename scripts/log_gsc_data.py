#!/usr/bin/env python3
# ABOUTME: GSC data logger - preserves historical data beyond 16-month window
# ABOUTME: Run weekly/daily via cron or GitHub Actions to build long-term dataset

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ctr_system.config import MIN_IMPRESSIONS_FOR_ANALYSIS
from ctr_system.gsc_client import get_gsc_client
from ctr_system import database as db


def log_current_gsc_data(days: int = 7):
    """
    Log GSC data for all pages from the last N days.

    Args:
        days: Number of days to look back (default: 7 for weekly logging)
    """
    print(f"Logging GSC data from last {days} days...")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    client = get_gsc_client()

    # Get date range (accounting for GSC delay)
    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)

    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    print(f"Fetching data from {start_str} to {end_str}...")

    # Get all pages with impressions
    pages = client.get_all_pages(start_str, end_str, min_impressions=1)
    print(f"Found {len(pages)} pages with impressions")

    # Log data for each page
    logged_count = 0
    for i, page in enumerate(pages):
        page_url = page['page_url']

        # Log this data point
        db.log_historical_gsc_data(
            page_url=page_url,
            data_date=end_str,  # Use end date as the snapshot date
            impressions=page['impressions'],
            clicks=page['clicks'],
            ctr=page['ctr'],
            position=page['position']
        )

        logged_count += 1

        if (i + 1) % 100 == 0:
            print(f"  Logged {i + 1}/{len(pages)} pages...")

    print()
    print(f"✓ Logged {logged_count} pages to historical data")
    print(f"  Database now contains data spanning beyond GSC's 16-month window")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Log GSC historical data')
    parser.add_argument('--days', type=int, default=7,
                       help='Number of days to aggregate (default: 7)')

    args = parser.parse_args()

    log_current_gsc_data(days=args.days)


if __name__ == '__main__':
    main()
