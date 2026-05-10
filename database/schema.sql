DROP TABLE IF EXISTS patents_fts;          -- FTS5 virtual table first
DROP TRIGGER IF EXISTS patents_fts_ai;     -- FTS triggers before base tables
DROP TRIGGER IF EXISTS patents_fts_ad;     -- to avoid foreign key issues during drop
DROP TRIGGER IF EXISTS patents_fts_au;     -- (these will be recreated automatically when the tables are re-created)

DROP TABLE IF EXISTS patent_assignee;
DROP TABLE IF EXISTS patent_inventor;
DROP TABLE IF EXISTS patent_company;
DROP TABLE IF EXISTS patent_cpc;
DROP TABLE IF EXISTS cpc_section_agg;
DROP TABLE IF EXISTS patents;
DROP TABLE IF EXISTS inventors;
DROP TABLE IF EXISTS companies;
DROP TABLE IF EXISTS assignees;
DROP TABLE IF EXISTS locations;

DROP VIEW  IF EXISTS patent_relationships;
DROP VIEW  IF EXISTS patent_full;


-- =====================================================================
-- CORE TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS patents (
    patent_id       TEXT    PRIMARY KEY,
    title           TEXT,
    abstract        TEXT,
    
    filing_date     TEXT,
    patent_date     TEXT,
    -- Integer years derived from the validated date columns
    year            INTEGER,            -- filing year  (for trend queries)
    patent_year     INTEGER,            -- grant year
    -- Classification / metadata
    patent_type     TEXT,               -- "utility", "design", "plant", etc.
    num_claims      INTEGER,            -- number of patent claims
    grant_lag_days  INTEGER             -- days from filing to grant (NULL if either date missing)
);


CREATE TABLE IF NOT EXISTS inventors (
    inventor_id TEXT PRIMARY KEY,
    name        TEXT,
    country     TEXT                    -- ISO-2 country code or 'Unknown'
);


-- companies holds both organisations and named individuals (assignees).
-- assignee_type = 'organisation' | 'individual'
CREATE TABLE IF NOT EXISTS companies (
    company_id    TEXT PRIMARY KEY,
    name          TEXT,
    assignee_type TEXT
);


-- =====================================================================
-- RELATIONSHIP TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS patent_inventor (
    patent_id   TEXT,
    inventor_id TEXT,
    PRIMARY KEY (patent_id, inventor_id),
    FOREIGN KEY (patent_id)   REFERENCES patents(patent_id),
    FOREIGN KEY (inventor_id) REFERENCES inventors(inventor_id)
);

CREATE TABLE IF NOT EXISTS patent_company (
    patent_id  TEXT,
    company_id TEXT,
    PRIMARY KEY (patent_id, company_id),
    FOREIGN KEY (patent_id)  REFERENCES patents(patent_id),
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
);

-- CPC classification (one row per patent × section)
CREATE TABLE IF NOT EXISTS patent_cpc (
    patent_id   TEXT,
    cpc_section TEXT,   -- single letter: A-H, Y
    cpc_class   TEXT,   -- reserved / NULL in current export
    cpc_subclass TEXT,
    cpc_group   TEXT,
    cpc_type    TEXT,
    PRIMARY KEY (patent_id, cpc_section),
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id)
);

-- Cached JSON array of CPC sections per patent for fast analytics reads
CREATE TABLE IF NOT EXISTS cpc_section_agg (
    patent_id    TEXT PRIMARY KEY,
    cpc_sections TEXT,              -- e.g. '["G","H"]'
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id)
);



-- FTS5 FULL-TEXT SEARCH

CREATE VIRTUAL TABLE IF NOT EXISTS patents_fts USING fts5 (
    patent_id  UNINDEXED,
    title,
    abstract,
    content    = 'patents',
    content_rowid = 'rowid',
    tokenize   = 'porter ascii'   -- porter stemming: "compute" matches "computing"
);

-- Keep FTS in sync with future single-row inserts / deletes / updates

CREATE TRIGGER IF NOT EXISTS patents_fts_ai
    AFTER INSERT ON patents BEGIN
        INSERT INTO patents_fts(rowid, patent_id, title, abstract)
        VALUES (new.rowid, new.patent_id, new.title, new.abstract);
    END;

CREATE TRIGGER IF NOT EXISTS patents_fts_ad
    AFTER DELETE ON patents BEGIN
        INSERT INTO patents_fts(patents_fts, rowid, patent_id, title, abstract)
        VALUES ('delete', old.rowid, old.patent_id, old.title, old.abstract);
    END;

CREATE TRIGGER IF NOT EXISTS patents_fts_au
    AFTER UPDATE ON patents BEGIN
        INSERT INTO patents_fts(patents_fts, rowid, patent_id, title, abstract)
        VALUES ('delete', old.rowid, old.patent_id, old.title, old.abstract);
        INSERT INTO patents_fts(rowid, patent_id, title, abstract)
        VALUES (new.rowid, new.patent_id, new.title, new.abstract);
    END;


-- =====================================================================
-- INDEXES
-- Convention: idx_<table>_<column(s)>
-- =====================================================================

--  patents 
-- Primary key index is automatic; add covering / filter indexes below.

-- Trend / date-range queries 
-- Indexing the filing year (year) .
CREATE INDEX IF NOT EXISTS idx_patents_year
    ON patents (year);

-- Indexing for the grant year (patent_year) allows for efficient queries 
CREATE INDEX IF NOT EXISTS idx_patents_patent_year
    ON patents (patent_year);

-- Date-range queries using string comparison (ISO dates sort correctly)
CREATE INDEX IF NOT EXISTS idx_patents_filing_date
    ON patents (filing_date);

CREATE INDEX IF NOT EXISTS idx_patents_patent_date
    ON patents (patent_date);

-- Filter by type (utility / design / plant)
CREATE INDEX IF NOT EXISTS idx_patents_type
    ON patents (patent_type);

-- Compound: year + type — common in analytics dashboards
CREATE INDEX IF NOT EXISTS idx_patents_year_type
    ON patents (year, patent_type);

-- Claims analysis / sorting
CREATE INDEX IF NOT EXISTS idx_patents_num_claims
    ON patents (num_claims);

-- Grant-lag analysis
CREATE INDEX IF NOT EXISTS idx_patents_grant_lag
    ON patents (grant_lag_days);

-- LIKE-prefix search on title when FTS is not used
-- e.g. WHERE title LIKE 'Neural%'
CREATE INDEX IF NOT EXISTS idx_patents_title
    ON patents (title);


-- inventors 
-- Name search (LIKE prefix or exact)
CREATE INDEX IF NOT EXISTS idx_inventors_name
    ON inventors (name);

-- Geographic filter / aggregation
CREATE INDEX IF NOT EXISTS idx_inventors_country
    ON inventors (country);

-- Compound: country + name (covers both single-column queries too)
CREATE INDEX IF NOT EXISTS idx_inventors_country_name
    ON inventors (country, name);


--  companies 
CREATE INDEX IF NOT EXISTS idx_companies_name
    ON companies (name);

CREATE INDEX IF NOT EXISTS idx_companies_type
    ON companies (assignee_type);

CREATE INDEX IF NOT EXISTS idx_companies_type_name
    ON companies (assignee_type, name);


--  patent_inventor 
-- PK covers (patent_id, inventor_id); add reverse for inventor→patents
CREATE INDEX IF NOT EXISTS idx_pi_inventor_id
    ON patent_inventor (inventor_id);

CREATE INDEX IF NOT EXISTS idx_pi_patent_id
    ON patent_inventor (patent_id);


--  patent_company 
CREATE INDEX IF NOT EXISTS idx_pc_company_id
    ON patent_company (company_id);

CREATE INDEX IF NOT EXISTS idx_pc_patent_id
    ON patent_company (patent_id);


--  patent_cpc 
-- PK covers (patent_id, cpc_section); 
CREATE INDEX IF NOT EXISTS idx_cpc_section
    ON patent_cpc (cpc_section);

CREATE INDEX IF NOT EXISTS idx_cpc_patent_id
    ON patent_cpc (patent_id);



-- VIEWS
-- Used for convenience and performance in common queries, especially for the dashboard.

-- Convenience view: full patent record with CPC sections JSON-array
CREATE VIEW IF NOT EXISTS patent_full AS
SELECT
    p.patent_id,
    p.title,
    p.abstract,
    p.filing_date,
    p.patent_date,
    p.year,
    p.patent_year,
    p.patent_type,
    p.num_claims,
    p.grant_lag_days,
    a.cpc_sections
FROM patents p
LEFT JOIN cpc_section_agg a ON p.patent_id = a.patent_id;


-- Convenience view: patent ↔ inventor ↔ company relationships
CREATE VIEW IF NOT EXISTS patent_relationships AS
SELECT
    pi.patent_id,
    pi.inventor_id,
    pc.company_id
FROM patent_inventor pi
LEFT JOIN patent_company pc ON pi.patent_id = pc.patent_id;