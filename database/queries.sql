-- queries.sql



-- =====================================================================
-- CORE QUERIES  (Q1 – Q7)
-- =====================================================================

-- Q1: Top Inventors
-- Who has the most patents?

WITH inv_counts AS (
    SELECT inventor_id,
           COUNT(*) AS patent_count
    FROM   patent_inventor
    GROUP  BY inventor_id
    ORDER  BY patent_count DESC
    LIMIT  20
)
SELECT i.inventor_id, i.name, i.country, c.patent_count
FROM   inv_counts c
JOIN   inventors  i ON c.inventor_id = i.inventor_id
ORDER  BY c.patent_count DESC;

-- Q2: Top Companies
-- Which companies own the most patents?

WITH co_counts AS (
    SELECT company_id,
           COUNT(*) AS patent_count
    FROM   patent_company
    GROUP  BY company_id
    ORDER  BY patent_count DESC
    LIMIT  20
)
SELECT c.company_id, c.name, c.assignee_type, co.patent_count
FROM   co_counts  co
JOIN   companies  c  ON co.company_id = c.company_id
ORDER  BY co.patent_count DESC;

-- Q3: Top Countries
-- Which countries produce the most patents?

WITH country_patent AS (
    SELECT DISTINCT i.country,
                    pi.patent_id
    FROM   patent_inventor pi
    JOIN   inventors       i  ON pi.inventor_id = i.inventor_id
    WHERE  i.country NOT IN ('Unknown', '')
      AND  i.country IS NOT NULL
)
SELECT country,
       COUNT(*) AS patent_count
FROM   country_patent
GROUP  BY country
ORDER  BY patent_count DESC
LIMIT  30;

-- Q4: Trends Over Time
-- How many patents are filed each year? (1976 – 2025 only)

SELECT year,
       COUNT(*) AS patent_count
FROM   patents
WHERE  year BETWEEN 1976 AND 2025
GROUP  BY year
ORDER  BY year ASC;

-- Q5: JOIN Query
-- Combine patents with inventors and companies.
-- Pre-limit patents to 100 rows first to prevent Cartesian explosion

SELECT p.patent_id,
       p.title,
       p.year,
       p.patent_type,
       p.num_claims,
       p.grant_lag_days,
       GROUP_CONCAT(DISTINCT i.name)    AS inventor_names,
       GROUP_CONCAT(DISTINCT i.country) AS inventor_countries,
       GROUP_CONCAT(DISTINCT c.name)    AS company_names
FROM (
    SELECT patent_id, title, year, patent_type, num_claims, grant_lag_days
    FROM   patents
    WHERE  year IS NOT NULL
    ORDER  BY year DESC
    LIMIT  100
) p
LEFT JOIN patent_inventor pi ON p.patent_id   = pi.patent_id
LEFT JOIN inventors       i  ON pi.inventor_id = i.inventor_id
LEFT JOIN patent_company  pc ON p.patent_id   = pc.patent_id
LEFT JOIN companies       c  ON pc.company_id  = c.company_id
GROUP  BY p.patent_id, p.title, p.year,
          p.patent_type, p.num_claims, p.grant_lag_days
ORDER  BY p.year DESC, p.patent_id;

-- Q6: CTE Query (WITH statement)
-- Top 5 inventive countries per decade.
-- De-duplicate at (decade, country, patent_id) first; ROW_NUMBER then
-- limits the final output to 5 countries per decade.
WITH decade_patent AS (
    SELECT DISTINCT
           (p.year / 10) * 10 AS decade,
           i.country,
           pi.patent_id
    FROM   patent_inventor pi
    JOIN   inventors       i  ON pi.inventor_id = i.inventor_id
    JOIN   patents         p  ON pi.patent_id   = p.patent_id
    WHERE  p.year BETWEEN 1976 AND 2025
      AND  i.country NOT IN ('Unknown', '')
),
decade_counts AS (
    SELECT decade,
           country,
           COUNT(*) AS patents_per_decade
    FROM   decade_patent
    GROUP  BY decade, country
),
ranked AS (
    SELECT decade, country, patents_per_decade,
           ROW_NUMBER() OVER (
               PARTITION BY decade
               ORDER BY patents_per_decade DESC
           ) AS rn
    FROM   decade_counts
)
SELECT decade, country, patents_per_decade
FROM   ranked
WHERE  rn <= 5
ORDER  BY decade DESC, patents_per_decade DESC;


-- Q7: Ranking Query - Can be derived from Q1, but demonstrates window functions for ranking.
-- Rank inventors by total patent count using a window function

WITH inventor_counts AS (
    SELECT
        pi.inventor_id,
        i.name,
        i.country,
        COUNT(DISTINCT pi.patent_id) AS patent_count
    FROM patent_inventor pi
    JOIN inventors i
        ON pi.inventor_id = i.inventor_id
    GROUP BY pi.inventor_id, i.name, i.country
),

ranked_inventors AS (
    SELECT
        inventor_id,
        name,
        country,
        patent_count,
        ROW_NUMBER() OVER (
            ORDER BY patent_count DESC
        ) AS rank
    FROM inventor_counts
)

SELECT
    rank,
    inventor_id,
    name,
    country,
    patent_count
FROM ranked_inventors
ORDER BY rank
LIMIT 20;

-- =====================================================================
-- EXTRA-CREDIT: CPC CATEGORY ANALYSIS  (E1 – E5)
-- =====================================================================

-- E1: CPC Section Distribution

SELECT cpc_section,
       COUNT(*)                                                         AS patent_count,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM patent_cpc), 2) AS percentage
FROM   patent_cpc
WHERE  cpc_section IS NOT NULL
GROUP  BY cpc_section
ORDER  BY patent_count DESC;

-- E2: CPC Section Trends Over Time

SELECT p.year,
       pc.cpc_section,
       COUNT(*) AS patent_count
FROM   patent_cpc pc
JOIN   patents    p  ON pc.patent_id = p.patent_id
WHERE  p.year BETWEEN 1976 AND 2025
  AND  pc.cpc_section IS NOT NULL
GROUP  BY p.year, pc.cpc_section
ORDER  BY p.year DESC, patent_count DESC;

-- E3: Top 5 Companies per CPC Section

WITH cpc_co AS (
    SELECT   pc.cpc_section,
             pco.company_id,
             COUNT(*) AS patent_count
    FROM     patent_cpc     pc
    JOIN     patent_company pco ON pc.patent_id = pco.patent_id
    WHERE    pc.cpc_section IS NOT NULL
    GROUP BY pc.cpc_section, pco.company_id
),
ranked AS (
    SELECT cpc_section, company_id, patent_count,
           ROW_NUMBER() OVER (
               PARTITION BY cpc_section
               ORDER BY patent_count DESC
           ) AS rn
    FROM cpc_co
)
SELECT r.cpc_section,
       c.name AS company_name,
       r.patent_count
FROM   ranked    r
JOIN   companies c ON r.company_id = c.company_id
WHERE  r.rn <= 5
ORDER  BY r.cpc_section, r.patent_count DESC;

-- E4: Top 5 Countries per CPC Section

WITH cpc_country_patent AS (
    SELECT DISTINCT pc.cpc_section,
                    i.country,
                    pc.patent_id
    FROM   patent_cpc      pc
    JOIN   patent_inventor pi ON pc.patent_id   = pi.patent_id
    JOIN   inventors       i  ON pi.inventor_id = i.inventor_id
    WHERE  pc.cpc_section IS NOT NULL
      AND  i.country NOT IN ('Unknown', '')
),
counts AS (
    SELECT cpc_section,
           country,
           COUNT(*) AS patent_count
    FROM   cpc_country_patent
    GROUP  BY cpc_section, country
),
ranked AS (
    SELECT cpc_section, country, patent_count,
           ROW_NUMBER() OVER (
               PARTITION BY cpc_section
               ORDER BY patent_count DESC
           ) AS rn
    FROM counts
)
SELECT cpc_section, country, patent_count
FROM   ranked
WHERE  rn <= 5
ORDER  BY cpc_section, patent_count DESC;

-- E5: 5 Most Recent Patents per CPC Section
WITH ranked_patents AS (
    SELECT pc.cpc_section,
           p.patent_id,
           p.title,
           p.year,
           p.filing_date,
           ROW_NUMBER() OVER (
               PARTITION BY pc.cpc_section
               ORDER BY p.year DESC
           ) AS rn
    FROM patent_cpc pc
    JOIN patents    p  ON pc.patent_id = p.patent_id
    WHERE p.year BETWEEN 1976 AND 2025
)
SELECT cpc_section, patent_id, title, year, filing_date
FROM   ranked_patents
WHERE  rn <= 5
ORDER  BY cpc_section, year DESC;


-- =====================================================================
-- ANALYSIS QUERIES: GRANT LAG & CLAIMS  (A1 – A5)  Special focus of the anaysis
-- =====================================================================

-- A1: Grant Lag by CPC Section
SELECT pc.cpc_section,
       COUNT(*)                                      AS patent_count,
       ROUND(AVG(p.grant_lag_days))                 AS avg_grant_lag_days,
       ROUND(AVG(p.grant_lag_days) / 365.25, 2)     AS avg_grant_lag_years,
       MIN(p.grant_lag_days)                         AS min_lag_days,
       MAX(p.grant_lag_days)                         AS max_lag_days
FROM   patents    p
JOIN   patent_cpc pc ON p.patent_id = pc.patent_id
WHERE  p.grant_lag_days > 0
  AND  pc.cpc_section IS NOT NULL
GROUP  BY pc.cpc_section
ORDER  BY avg_grant_lag_days DESC;

-- A2: Grant Lag by Country
WITH country_patent_lag AS (
    SELECT i.country,
           p.patent_id,
           p.grant_lag_days
    FROM   patent_inventor pi
    JOIN   inventors       i  ON pi.inventor_id = i.inventor_id
    JOIN   patents         p  ON pi.patent_id   = p.patent_id
    WHERE  p.grant_lag_days > 0
      AND  i.country NOT IN ('Unknown', '')
    GROUP  BY i.country, p.patent_id, p.grant_lag_days
)
SELECT country,
       COUNT(*)                                  AS patent_count,
       ROUND(AVG(grant_lag_days))               AS avg_grant_lag_days,
       ROUND(AVG(grant_lag_days) / 365.25, 2)   AS avg_grant_lag_years,
       MIN(grant_lag_days)                       AS min_lag_days,
       MAX(grant_lag_days)                       AS max_lag_days
FROM   country_patent_lag
GROUP  BY country
HAVING patent_count >= 500
ORDER  BY patent_count DESC
LIMIT  40;

-- A3: Average Claims per Year
SELECT year,
       COUNT(*)                     AS patent_count,
       ROUND(AVG(num_claims), 2)    AS avg_claims,
       MIN(num_claims)              AS min_claims,
       MAX(num_claims)              AS max_claims
FROM   patents
WHERE  year BETWEEN 1976 AND 2025
  AND  num_claims > 0
GROUP  BY year
ORDER  BY year ASC;

-- A4: Grant Lag Trend Over Time

SELECT year,
       COUNT(*)                                  AS patent_count,
       ROUND(AVG(grant_lag_days))               AS avg_grant_lag_days,
       ROUND(AVG(grant_lag_days) / 365.25, 2)   AS avg_grant_lag_years
FROM   patents
WHERE  year BETWEEN 1976 AND 2025
  AND  grant_lag_days > 0
GROUP  BY year
ORDER  BY year ASC;

-- A5: Average Claims by CPC Section
SELECT pc.cpc_section,
       COUNT(*)                      AS patent_count,
       ROUND(AVG(p.num_claims), 2)   AS avg_claims,
       MAX(p.num_claims)             AS max_claims
FROM   patents    p
JOIN   patent_cpc pc ON p.patent_id = pc.patent_id
WHERE  p.num_claims > 0
  AND  pc.cpc_section IS NOT NULL
GROUP  BY pc.cpc_section
ORDER  BY avg_claims DESC;