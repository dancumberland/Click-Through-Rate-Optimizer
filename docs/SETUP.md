# Setup Guide

## Prerequisites

1. **WordPress Site**:
   - RankMath SEO plugin installed and activated
   - Application password for REST API access

2. **Google Search Console**:
   - Verified property for your domain
   - OAuth2 credentials (see below)

3. **Claude Code**:
   - Active subscription to Claude Code
   - CLI installed globally

## Step 1: Install Dependencies

```bash
# Python dependencies
pip install -r requirements.txt

# Claude CLI
npm install -g @anthropic-ai/claude-code
```

## Step 2: Google Search Console Setup

### Create OAuth2 Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable "Google Search Console API"
4. Go to "Credentials" → "Create Credentials" → "OAuth client ID"
5. Application type: "Desktop app"
6. Download JSON and save as `ClientData/credentials/gsc_oauth.json`

### First-Time Authentication

Run any script that uses GSC (e.g., `python scripts/ctr_orchestrator.py --analyze-only`). A browser will open for OAuth consent. After granting access, a `gsc_token.json` file will be created for future use.

## Step 3: WordPress/RankMath Setup

### Get Application Password

1. WordPress Admin → Users → Profile
2. Scroll to "Application Passwords"
3. Name: "CTR Optimizer"
4. Click "Add New Application Password"
5. Copy the generated password (save for .env)

### Verify RankMath API Access

```bash
curl -u "username:app_password" \
  https://yoursite.com/wp-json/rankmath/v1/
```

Should return RankMath API routes.

## Step 4: Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# WordPress
WP_SITE_URL=https://yoursite.com
WP_USER=your_username
Wordpress_Rest_API_KEY=xxxx xxxx xxxx xxxx xxxx xxxx

# Google Search Console
# For domain property:
GSC_SITE_URL=sc-domain:yoursite.com
# For URL property:
# GSC_SITE_URL=https://yoursite.com/

# Email (optional but recommended)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password
NOTIFICATION_EMAIL=you@example.com
```

## Step 5: Initialize Database

```bash
# First run will create database and tables automatically
python scripts/ctr_orchestrator.py --analyze-only
```

## Step 6: Test the System

```bash
# Full dry run (won't implement changes)
python scripts/ctr_orchestrator.py

# Check generated reports
ls -la CTR_Reports/
```

## Multi-Site Deployment

### Option 1: Separate Installations (Recommended)

```
/sites/
├── themeaningmovement/
│   ├── Click-Through-Rate-Optimizer/  # Git clone
│   ├── .env                           # Site-specific
│   ├── site_crawl.db
│   └── CTR_Reports/
└── dancumberlandlabs/
    ├── Click-Through-Rate-Optimizer/  # Git clone
    ├── .env                           # Site-specific
    ├── site_crawl.db
    └── CTR_Reports/
```

**Pros**: Complete isolation, easy to update (git pull)
**Cons**: Duplicate code (but small footprint)

### Option 2: Shared Codebase, Multiple Configs

```
/tools/Click-Through-Rate-Optimizer/  # One install
/sites/
├── themeaningmovement/
│   ├── .env
│   ├── site_crawl.db
│   └── CTR_Reports/
└── dancumberlandlabs/
    ├── .env
    ├── site_crawl.db
    └── CTR_Reports/
```

Run with explicit config:
```bash
cd /sites/themeaningmovement
python /tools/Click-Through-Rate-Optimizer/scripts/ctr_orchestrator.py
```

**Pros**: Single codebase to maintain
**Cons**: Requires careful path management

### Option 3: Environment Switching

```bash
# Set environment variable
export CTR_SITE=themeaningmovement
python scripts/ctr_orchestrator.py

export CTR_SITE=dancumberlandlabs
python scripts/ctr_orchestrator.py
```

Load different .env files based on `CTR_SITE`:
```python
# In config.py
site = os.getenv('CTR_SITE', 'default')
load_dotenv(f'.env.{site}')
```

## Automation

### Cron Jobs

```cron
# Monthly CTR optimization (1st of month at 9am)
0 9 1 * * cd /path/to/Click-Through-Rate-Optimizer && python scripts/ctr_orchestrator.py

# Weekly GSC data logging (Sundays at midnight)
0 0 * * 0 cd /path/to/Click-Through-Rate-Optimizer && python scripts/log_gsc_data.py --days 7

# Daily experiment evaluation (every day at 8am)
0 8 * * * cd /path/to/Click-Through-Rate-Optimizer && python scripts/ctr_orchestrator.py --evaluate-only
```

### GitHub Actions

See `.github/workflows/ctr-optimization.yml` for automated monthly runs.

## Troubleshooting

### "No module named 'ctr_system'"

Ensure you're running from the project root or add to PYTHONPATH:
```bash
export PYTHONPATH=/path/to/Click-Through-Rate-Optimizer:$PYTHONPATH
```

### "GSC authentication failed"

Delete `gsc_token.json` and re-authenticate.

### "WordPress API returned 401"

Check application password format (should be space-separated groups of 4 characters).

### "No opportunities found"

- Check that GSC has data (requires 16 months of history)
- Lower thresholds in config.py: `MIN_CTR_GAP_PERCENT = 3.0`
- Verify MIN_IMPRESSIONS_FOR_ANALYSIS isn't too high

## Support

For issues, open a GitHub issue or contact Dan Cumberland.
