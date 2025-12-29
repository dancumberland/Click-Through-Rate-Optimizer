#!/usr/bin/env python3
# ABOUTME: Configuration for CTR optimization system
# ABOUTME: Thresholds, paths, and settings for all modules

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from parent directory
# This allows .env to be in the site directory (outside the repo)
load_dotenv(Path.cwd() / '.env')
load_dotenv()  # Also try current directory

# =============================================================================
# PATHS
# =============================================================================

# Default to current working directory for site-specific files
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB_PATH = Path.cwd() / "site_crawl.db"
DEFAULT_REPORTS_DIR = Path.cwd() / "CTR_Reports"

DB_PATH = os.getenv("DB_PATH", str(DEFAULT_DB_PATH))
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(DEFAULT_REPORTS_DIR)))

# Ensure reports directory exists
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# WORDPRESS / RANKMATH API
# =============================================================================

WP_SITE_URL = os.getenv("WP_SITE_URL", "https://themeaningmovement.com")
WP_USER = os.getenv("WP_USER")
WP_APP_PASSWORD = os.getenv("Wordpress_Rest_API_KEY")

# =============================================================================
# GOOGLE SEARCH CONSOLE
# =============================================================================

# GSC API credentials - stored in .env or as JSON file
GSC_CREDENTIALS_FILE = os.getenv("GSC_CREDENTIALS_FILE", str(PROJECT_ROOT / "gsc_credentials.json"))
GSC_SITE_URL = os.getenv("GSC_SITE_URL", "sc-domain:themeaningmovement.com")

# =============================================================================
# CLAUDE CLI (for ideation - uses existing Claude Code subscription)
# =============================================================================

# Model preference (not required - CLI uses your account settings)
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# =============================================================================
# ANALYSIS THRESHOLDS
# =============================================================================

# Minimum impressions to consider a page for analysis
MIN_IMPRESSIONS_FOR_ANALYSIS = 100

# Minimum days since last change before we can optimize again
MIN_DAYS_BETWEEN_CHANGES = 21

# Minimum days before evaluating an experiment
MIN_DAYS_FOR_EVALUATION = 21

# Maximum days to wait before declaring experiment inconclusive
MAX_DAYS_FOR_EVALUATION = 90

# Minimum post-change impressions needed to evaluate
MIN_POST_CHANGE_IMPRESSIONS = 50

# =============================================================================
# CTR BENCHMARKS (default, will be overwritten by calculated values)
# =============================================================================

# Default CTR expectations by position (from industry averages)
# These get replaced with site-specific values after first calculation
DEFAULT_CTR_BENCHMARKS = [
    {"position_min": 1.0, "position_max": 1.5, "expected_ctr": 0.30},
    {"position_min": 1.5, "position_max": 2.5, "expected_ctr": 0.18},
    {"position_min": 2.5, "position_max": 3.5, "expected_ctr": 0.11},
    {"position_min": 3.5, "position_max": 5.5, "expected_ctr": 0.07},
    {"position_min": 5.5, "position_max": 10.5, "expected_ctr": 0.035},
    {"position_min": 10.5, "position_max": 20.5, "expected_ctr": 0.015},
    {"position_min": 20.5, "position_max": 100.0, "expected_ctr": 0.005},
]

# =============================================================================
# OPTIMIZATION LIMITS
# =============================================================================

# CTR-gap based selection (optimize pages that need it most)
# A page is eligible if it meets ALL of these criteria:
MIN_CTR_GAP_PERCENT = 5.0   # Must be underperforming expected CTR by at least 5%
MIN_IMPACT_SCORE = 5.0      # impact_score = impressions * ctr_gap (must be >= 5.0)

# Safety limit (prevent over-optimization if site has many underperforming pages)
MAX_EXPERIMENTS_PER_MONTH = 50

# Maximum title length
MAX_TITLE_LENGTH = 60

# Number of title ideas to generate per page
IDEAS_PER_PAGE = 10

# =============================================================================
# IDEA TYPES (psychological triggers)
# =============================================================================

IDEA_TYPES = [
    {
        "type": "specificity",
        "description": "Add specific numbers, dates, or details",
        "example": "7 Proven Ways to Find Your Purpose in 2025"
    },
    {
        "type": "curiosity",
        "description": "Create intrigue without clickbait",
        "example": "The Hidden Truth About Finding Your Purpose"
    },
    {
        "type": "power_words",
        "description": "Use emotional triggers (ultimate, essential, proven)",
        "example": "The Ultimate Guide to Discovering Your Life Purpose"
    },
    {
        "type": "question",
        "description": "Mirror how people search",
        "example": "What Is My Purpose? A Complete Guide to Finding Out"
    },
    {
        "type": "how_to",
        "description": "Instructional framing",
        "example": "How to Find Your Purpose When You Feel Lost"
    },
    {
        "type": "list",
        "description": "Numbers at the beginning",
        "example": "15 Signs You've Found Your True Purpose"
    },
    {
        "type": "brackets",
        "description": "Bracket additions for context",
        "example": "Finding Your Purpose [Complete 2025 Guide]"
    },
    {
        "type": "social_proof",
        "description": "Imply popularity or authority",
        "example": "Why Thousands Are Rethinking Their Life Purpose"
    },
    {
        "type": "benefit_first",
        "description": "Lead with what reader gets",
        "example": "Find Clarity and Direction: Your Purpose Guide"
    },
    {
        "type": "problem_solution",
        "description": "Address pain point directly",
        "example": "Feeling Lost? Here's How to Find Your Purpose"
    },
]

# =============================================================================
# NOTIFICATIONS
# =============================================================================

# Slack webhook URL (optional)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# Email settings (optional)
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL")

# =============================================================================
# OUTCOME THRESHOLDS
# =============================================================================

# CTR change thresholds for outcome determination
IMPROVEMENT_THRESHOLD = 0.05  # 5% improvement = "improved"
WORSENED_THRESHOLD = -0.05   # 5% decline = "worsened"
# Between these = "no_change"

# Position change threshold to flag position-confounded results
POSITION_CHANGE_THRESHOLD = 2.0  # Flag if position changed by more than 2


def validate_config():
    """Check that required configuration is present"""
    import shutil

    errors = []

    if not WP_USER:
        errors.append("WP_USER not set in .env")
    if not WP_APP_PASSWORD:
        errors.append("Wordpress_Rest_API_KEY not set in .env")
    if not shutil.which("claude"):
        errors.append("Claude CLI not found. Install Claude Code: npm install -g @anthropic-ai/claude-code")

    if errors:
        print("Configuration errors:")
        for e in errors:
            print(f"  - {e}")
        return False
    return True
