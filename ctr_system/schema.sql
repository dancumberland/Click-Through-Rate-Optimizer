-- ABOUTME: Database schema extension for CTR optimization system
-- ABOUTME: Run against site_crawl.db to add experiment tracking tables

-- Historical record of SEO changes made to pages
CREATE TABLE IF NOT EXISTS seo_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,
    wp_post_id INTEGER,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    field_changed TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    change_reason TEXT,
    gsc_ctr_at_change REAL,
    gsc_impressions_at_change INTEGER,
    gsc_clicks_at_change INTEGER,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_seo_changes_url ON seo_changes(page_url);
CREATE INDEX IF NOT EXISTS idx_seo_changes_date ON seo_changes(changed_at);
CREATE INDEX IF NOT EXISTS idx_seo_changes_post ON seo_changes(wp_post_id);

-- Site-specific CTR expectations by position band
-- Used to calculate "expected CTR" for gap analysis
CREATE TABLE IF NOT EXISTS ctr_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_min REAL NOT NULL,
    position_max REAL NOT NULL,
    expected_ctr REAL NOT NULL,
    sample_size INTEGER,
    last_calculated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Track each optimization experiment with hypothesis and outcome
CREATE TABLE IF NOT EXISTS optimization_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,
    page_slug TEXT,
    wp_post_id INTEGER,

    -- Timing
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    min_evaluation_date DATE,  -- Don't evaluate before this date

    -- The hypothesis (critical for learning)
    hypothesis TEXT NOT NULL,
    idea_type TEXT,  -- 'numbers', 'curiosity', 'question', etc.

    -- What changed
    old_title TEXT,
    new_title TEXT,
    old_description TEXT,
    new_description TEXT,

    -- Pre-change metrics (snapshot at time of change)
    pre_ctr REAL,
    pre_position REAL,
    pre_impressions INTEGER,
    pre_clicks INTEGER,
    pre_measurement_start DATE,
    pre_measurement_end DATE,

    -- Post-change metrics (updated weekly)
    post_ctr REAL,
    post_position REAL,
    post_impressions INTEGER,
    post_clicks INTEGER,
    post_measurement_start DATE,
    post_measurement_end DATE,
    last_measured TIMESTAMP,

    -- Evaluation
    outcome TEXT,  -- 'improved', 'worsened', 'no_change', 'inconclusive', 'pending'
    ctr_change_pct REAL,
    position_change REAL,

    -- Learnings (extracted after evaluation)
    learnings TEXT,

    -- Status
    status TEXT DEFAULT 'active',  -- 'active', 'completed', 'reverted', 'cancelled'

    -- Linking
    review_id INTEGER,
    FOREIGN KEY (review_id) REFERENCES monthly_reviews(id)
);

-- Store all generated title ideas (used and unused)
-- This prevents repeating past experiments
CREATE TABLE IF NOT EXISTS title_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,
    idea_text TEXT NOT NULL,
    char_count INTEGER,
    idea_type TEXT NOT NULL,  -- 'specificity', 'curiosity', 'power_words', 'question', 'how_to', 'list', 'brackets', 'social_proof', 'benefit_first', 'problem_solution'
    hypothesis TEXT,

    -- Generation context
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    generated_for_review_id INTEGER,
    source TEXT DEFAULT 'ai_generated',  -- 'ai_generated', 'competitor_inspired', 'manual'

    -- Usage tracking
    selected BOOLEAN DEFAULT FALSE,
    used_at TIMESTAMP,
    experiment_id INTEGER,

    -- Prevent duplicates
    UNIQUE(page_url, idea_text),
    FOREIGN KEY (experiment_id) REFERENCES optimization_experiments(id),
    FOREIGN KEY (generated_for_review_id) REFERENCES monthly_reviews(id)
);

-- Track monthly review sessions
CREATE TABLE IF NOT EXISTS monthly_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_date DATE NOT NULL,
    review_month TEXT,  -- '2025-01' format for easy grouping

    -- Data range analyzed
    gsc_data_start DATE,
    gsc_data_end DATE,

    -- Stats
    total_pages_analyzed INTEGER,
    pages_eligible INTEGER,  -- Met time/impression thresholds
    opportunities_identified INTEGER,
    experiments_proposed INTEGER,
    experiments_approved INTEGER,
    experiments_started INTEGER,

    -- From previous month's experiments
    experiments_completed INTEGER,
    avg_improvement_pct REAL,
    success_rate REAL,  -- % of experiments that improved

    -- Learnings summary
    top_learnings TEXT,  -- JSON array of key insights

    -- Report
    report_path TEXT,  -- Path to generated markdown report

    -- Status
    status TEXT DEFAULT 'draft',  -- 'draft', 'reviewed', 'implemented', 'completed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Store site-wide learnings extracted from experiments
-- This builds institutional knowledge over time
CREATE TABLE IF NOT EXISTS ctr_learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_type TEXT NOT NULL,  -- 'idea_type_performance', 'content_category', 'general'
    category TEXT,  -- e.g., 'bible', 'purpose', 'career' for content categories
    idea_type TEXT,  -- e.g., 'numbers', 'curiosity'

    insight TEXT NOT NULL,
    supporting_data TEXT,  -- JSON with experiment IDs, stats

    sample_size INTEGER,
    confidence TEXT,  -- 'high', 'medium', 'low'

    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP,

    -- Tracking
    times_applied INTEGER DEFAULT 0,
    still_valid BOOLEAN DEFAULT TRUE
);

-- Snapshot of GSC data for analysis (refreshed monthly)
CREATE TABLE IF NOT EXISTS gsc_page_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,
    page_slug TEXT,

    -- Measurement period
    measurement_start DATE NOT NULL,
    measurement_end DATE NOT NULL,

    -- Metrics
    impressions INTEGER,
    clicks INTEGER,
    ctr REAL,
    position REAL,

    -- Calculated fields
    expected_ctr REAL,  -- Based on position
    ctr_gap REAL,  -- expected - actual (positive = underperforming)
    impact_score REAL,  -- impressions * ctr_gap (prioritization)

    -- Context
    days_since_last_change INTEGER,
    last_change_date DATE,
    eligible_for_optimization BOOLEAN,

    -- Top queries for this page
    top_queries TEXT,  -- JSON array of {query, impressions, clicks, ctr, position}

    -- Timestamps
    pulled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    review_id INTEGER,

    FOREIGN KEY (review_id) REFERENCES monthly_reviews(id)
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_experiments_status ON optimization_experiments(status);
CREATE INDEX IF NOT EXISTS idx_experiments_page ON optimization_experiments(page_url);
CREATE INDEX IF NOT EXISTS idx_ideas_page ON title_ideas(page_url);
CREATE INDEX IF NOT EXISTS idx_ideas_used ON title_ideas(selected, used_at);
CREATE INDEX IF NOT EXISTS idx_gsc_metrics_review ON gsc_page_metrics(review_id);
CREATE INDEX IF NOT EXISTS idx_gsc_metrics_eligible ON gsc_page_metrics(eligible_for_optimization);

-- View: Active experiments needing measurement
CREATE VIEW IF NOT EXISTS v_active_experiments AS
SELECT
    e.*,
    julianday('now') - julianday(e.started_at) as days_active,
    CASE
        WHEN julianday('now') >= julianday(e.min_evaluation_date) THEN 1
        ELSE 0
    END as ready_for_evaluation
FROM optimization_experiments e
WHERE e.status = 'active';

-- Track when pages first appeared in GSC (auto-discovered)
-- Replaces manual registration for determining page eligibility
CREATE TABLE IF NOT EXISTS gsc_page_tracking (
    page_url TEXT PRIMARY KEY,
    page_slug TEXT,

    -- Discovery
    first_seen_date DATE NOT NULL,  -- When page first got impressions in GSC
    first_discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Activity tracking
    last_seen_date DATE,  -- Most recent data from GSC
    last_updated TIMESTAMP,

    -- Status
    status TEXT DEFAULT 'active',  -- 'active', 'inactive', 'excluded'

    -- Metadata
    wp_post_id INTEGER,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_page_tracking_first_seen ON gsc_page_tracking(first_seen_date);
CREATE INDEX IF NOT EXISTS idx_page_tracking_status ON gsc_page_tracking(status);

-- Historical GSC data log (preserves data beyond 16-month window)
-- Stores daily or weekly snapshots for long-term trend analysis
CREATE TABLE IF NOT EXISTS gsc_historical_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,

    -- Date this snapshot represents
    data_date DATE NOT NULL,

    -- GSC metrics
    impressions INTEGER,
    clicks INTEGER,
    ctr REAL,
    position REAL,

    -- Metadata
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Prevent duplicates
    UNIQUE(page_url, data_date)
);
CREATE INDEX IF NOT EXISTS idx_historical_data_url ON gsc_historical_data(page_url);
CREATE INDEX IF NOT EXISTS idx_historical_data_date ON gsc_historical_data(data_date);

-- View: Idea type performance summary
CREATE VIEW IF NOT EXISTS v_idea_type_performance AS
SELECT
    idea_type,
    COUNT(*) as total_experiments,
    SUM(CASE WHEN outcome = 'improved' THEN 1 ELSE 0 END) as improved,
    SUM(CASE WHEN outcome = 'worsened' THEN 1 ELSE 0 END) as worsened,
    SUM(CASE WHEN outcome = 'no_change' THEN 1 ELSE 0 END) as no_change,
    ROUND(AVG(ctr_change_pct), 2) as avg_ctr_change,
    ROUND(100.0 * SUM(CASE WHEN outcome = 'improved' THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
FROM optimization_experiments
WHERE outcome IS NOT NULL AND outcome != 'pending' AND outcome != 'inconclusive'
GROUP BY idea_type;
