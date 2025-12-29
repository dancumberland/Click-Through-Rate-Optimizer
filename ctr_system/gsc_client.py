#!/usr/bin/env python3
# ABOUTME: Google Search Console API client for CTR system
# ABOUTME: Supports per-page date filtering and query-level analysis

import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .config import WP_SITE_URL, MIN_IMPRESSIONS_FOR_ANALYSIS

# GSC Configuration
SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

# Get GSC settings from environment via config
import os
from dotenv import load_dotenv
load_dotenv()

SITE_URL = os.getenv('GSC_SITE_URL', 'sc-domain:example.com')
CREDENTIALS_FILE = Path(os.getenv('GSC_CREDENTIALS_FILE', str(Path(__file__).parent.parent / 'gsc_oauth.json')))
TOKEN_FILE = Path(os.getenv('GSC_TOKEN_FILE', str(Path(__file__).parent.parent / 'gsc_token.json')))


class GSCClient:
    """Google Search Console API client"""

    def __init__(self):
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Handle OAuth2 authentication"""
        creds = None

        if TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

        self.service = build('searchconsole', 'v1', credentials=creds)

    def _query(self, request_body: Dict) -> List[Dict]:
        """Execute a GSC query"""
        response = self.service.searchanalytics().query(
            siteUrl=SITE_URL,
            body=request_body
        ).execute()
        return response.get('rows', [])

    def get_all_pages(
        self,
        start_date: str,
        end_date: str,
        min_impressions: int = MIN_IMPRESSIONS_FOR_ANALYSIS
    ) -> List[Dict]:
        """Get all pages with their metrics"""
        request = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': ['page'],
            'rowLimit': 25000,
            'startRow': 0
        }

        rows = self._query(request)

        # Filter and format
        results = []
        for row in rows:
            impressions = row.get('impressions', 0)
            if impressions >= min_impressions:
                page_url = row['keys'][0]
                results.append({
                    'page_url': page_url,
                    'page_slug': self._url_to_slug(page_url),
                    'impressions': impressions,
                    'clicks': row.get('clicks', 0),
                    'ctr': row.get('ctr', 0),
                    'position': row.get('position', 0)
                })

        return results

    def get_page_metrics(
        self,
        page_url: str,
        start_date: str,
        end_date: str
    ) -> Optional[Dict]:
        """Get metrics for a specific page in a date range"""
        request = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': ['page'],
            'dimensionFilterGroups': [{
                'filters': [{
                    'dimension': 'page',
                    'operator': 'equals',
                    'expression': page_url
                }]
            }],
            'rowLimit': 1
        }

        rows = self._query(request)

        if rows:
            row = rows[0]
            return {
                'page_url': page_url,
                'impressions': row.get('impressions', 0),
                'clicks': row.get('clicks', 0),
                'ctr': row.get('ctr', 0),
                'position': row.get('position', 0)
            }
        return None

    def get_queries_for_page(
        self,
        page_url: str,
        start_date: str,
        end_date: str,
        limit: int = 20
    ) -> List[Dict]:
        """Get top queries driving traffic to a specific page"""
        request = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': ['query'],
            'dimensionFilterGroups': [{
                'filters': [{
                    'dimension': 'page',
                    'operator': 'equals',
                    'expression': page_url
                }]
            }],
            'rowLimit': limit
        }

        rows = self._query(request)

        results = []
        for row in rows:
            results.append({
                'query': row['keys'][0],
                'impressions': row.get('impressions', 0),
                'clicks': row.get('clicks', 0),
                'ctr': row.get('ctr', 0),
                'position': row.get('position', 0)
            })

        return results

    def get_page_with_queries(
        self,
        page_url: str,
        start_date: str,
        end_date: str
    ) -> Optional[Dict]:
        """Get page metrics with top queries"""
        page_data = self.get_page_metrics(page_url, start_date, end_date)
        if not page_data:
            return None

        queries = self.get_queries_for_page(page_url, start_date, end_date)
        page_data['top_queries'] = queries

        return page_data

    def calculate_position_benchmarks(
        self,
        start_date: str,
        end_date: str,
        min_impressions: int = 100
    ) -> List[Dict]:
        """Calculate site-specific CTR benchmarks by position"""
        pages = self.get_all_pages(start_date, end_date, min_impressions)

        # Group by position bands
        position_bands = [
            (1.0, 1.5),
            (1.5, 2.5),
            (2.5, 3.5),
            (3.5, 5.5),
            (5.5, 10.5),
            (10.5, 20.5),
            (20.5, 100.0)
        ]

        benchmarks = []
        for min_pos, max_pos in position_bands:
            band_pages = [
                p for p in pages
                if min_pos <= p['position'] < max_pos
            ]

            if band_pages:
                # Use weighted average CTR
                total_impressions = sum(p['impressions'] for p in band_pages)
                total_clicks = sum(p['clicks'] for p in band_pages)

                if total_impressions > 0:
                    weighted_ctr = total_clicks / total_impressions
                else:
                    weighted_ctr = 0

                benchmarks.append({
                    'position_min': min_pos,
                    'position_max': max_pos,
                    'expected_ctr': weighted_ctr,
                    'sample_size': len(band_pages)
                })

        return benchmarks

    def get_valid_date_range(
        self,
        last_change_date: Optional[datetime] = None,
        max_days: int = 90
    ) -> Optional[Tuple[str, str]]:
        """Get valid date range for measurement (accounting for GSC delay)

        Returns None if the change is too recent to have valid data.
        """
        # GSC data has ~3 day delay
        end_date = datetime.now() - timedelta(days=3)

        if last_change_date:
            # Start from day after change
            start_date = last_change_date + timedelta(days=1)

            # If change is too recent (start_date >= end_date), no valid data yet
            if start_date >= end_date:
                return None

            # Don't go back further than max_days
            earliest = end_date - timedelta(days=max_days)
            if start_date < earliest:
                start_date = earliest
        else:
            # No changes, use last max_days
            start_date = end_date - timedelta(days=max_days)

        return (
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )

    def get_page_first_seen_date(self, page_url: str) -> Optional[str]:
        """
        Find when a page first appeared in GSC (got first impressions).

        Queries backwards in monthly chunks from today to 16 months ago
        to find the earliest date where the page had impressions > 0.

        Returns:
            Date string in 'YYYY-MM-DD' format, or None if page not found in GSC data
        """
        # GSC keeps data for ~16 months
        max_lookback_days = 16 * 30
        end_date = datetime.now() - timedelta(days=3)  # Account for GSC delay

        # Query backwards in 30-day chunks
        chunk_days = 30
        current_end = end_date

        earliest_seen = None

        for _ in range(max_lookback_days // chunk_days):
            current_start = current_end - timedelta(days=chunk_days)

            # Get metrics for this chunk
            metrics = self.get_page_metrics(
                page_url,
                current_start.strftime('%Y-%m-%d'),
                current_end.strftime('%Y-%m-%d')
            )

            if metrics and metrics['impressions'] > 0:
                # Page has data in this chunk, keep looking backwards
                earliest_seen = current_end.strftime('%Y-%m-%d')
                current_end = current_start
            else:
                # No data in this chunk, we've gone too far back
                break

        return earliest_seen

    def _url_to_slug(self, url: str) -> str:
        """Extract slug from full URL"""
        # Remove site URL prefix
        slug = url.replace(SITE_URL, '').replace('https://themeaningmovement.com/', '')
        # Remove trailing slash
        slug = slug.rstrip('/')
        return slug


def get_gsc_client() -> GSCClient:
    """Factory function to get GSC client instance"""
    return GSCClient()
