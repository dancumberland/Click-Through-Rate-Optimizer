# Click-Through-Rate Optimizer

AI-powered CTR optimization system for WordPress sites using Google Search Console data.

## What It Does

This system automatically:
- **Discovers** underperforming pages from Google Search Console
- **Analyzes** CTR gaps based on position-adjusted benchmarks
- **Generates** AI-powered title improvements using Claude
- **Implements** changes via WordPress/RankMath API
- **Measures** results and learns from outcomes
- **Reports** monthly progress via email

## How It Works

1. **Monthly Analysis**: Queries GSC for all pages, calculates expected CTR by position
2. **Gap Detection**: Finds pages underperforming by 5%+ with sufficient impact
3. **AI Ideation**: Generates 10 title variations per page using historical learnings
4. **Implementation**: Publishes best title via RankMath API
5. **Measurement**: Tracks results over 21-90 days
6. **Learning**: Stores outcomes to improve future recommendations

## Key Features

- **Threshold-Based**: Optimizes ALL pages meeting criteria (not fixed limits)
- **Position-Adjusted**: Benchmarks based on actual SERP position
- **Historical Tracking**: Preserves GSC data beyond 16-month window
- **Automatic Discovery**: No manual page registration needed
- **Self-Improving**: Learns which title types work best for your site

## Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/Click-Through-Rate-Optimizer.git
cd Click-Through-Rate-Optimizer

# Install dependencies
pip install -r requirements.txt

# Install Claude CLI (for AI ideation)
npm install -g @anthropic-ai/claude-code

# Set up configuration
cp .env.example .env
# Edit .env with your site details
```

## Configuration

See [docs/SETUP.md](docs/SETUP.md) for detailed setup instructions.

Required:
- WordPress site with RankMath SEO plugin
- Google Search Console property
- Claude Code subscription (for AI ideation)

## Usage

```bash
# Run monthly CTR optimization review
python scripts/ctr_orchestrator.py

# Log historical GSC data (run weekly via cron)
python scripts/log_gsc_data.py --days 7

# Evaluate ongoing experiments
python scripts/ctr_orchestrator.py --evaluate-only
```

## Project Structure

```
ctr_system/          # Core modules
├── config.py        # Configuration and thresholds
├── database.py      # SQLite database operations
├── gsc_client.py    # Google Search Console API
├── analysis.py      # CTR gap analysis
├── ideation.py      # AI-powered title generation
├── implementation.py # WordPress/RankMath API
├── measurement.py   # Experiment evaluation
├── notifications.py # Email/Slack reporting
└── schema.sql       # Database schema

scripts/             # Executable scripts
├── ctr_orchestrator.py  # Main monthly workflow
└── log_gsc_data.py      # Historical data logger
```

## Database

Uses SQLite with tables for:
- `monthly_reviews` - Review tracking
- `gsc_page_metrics` - Page performance snapshots
- `ctr_experiments` - A/B test tracking
- `ctr_benchmarks` - Position-based expectations
- `gsc_page_tracking` - Page discovery dates
- `gsc_historical_data` - Long-term data preservation
- `seo_changes` - Change history for publishing pipeline integration

## Multi-Site Usage

Each site gets its own:
- `.env` file (site-specific config)
- `site_crawl.db` (isolated data)
- `CTR_Reports/` directory (reports)

See docs/SETUP.md for multi-site deployment strategies.

## License

MIT

## Credits

Built by Dan Cumberland for [The Meaning Movement](https://themeaningmovement.com)
