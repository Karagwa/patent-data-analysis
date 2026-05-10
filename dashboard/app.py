import json
import re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Paths 
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = BASE_DIR / "patents.db"
REPORT_DIR = next(
    (p for p in [BASE_DIR / "report", BASE_DIR / "reports"]
     if (p / "patent_report.json").exists()),
    BASE_DIR / "report",
)

CPC_NAMES = {
    "A": "Human Necessities",    "B": "Operations & Transport",
    "C": "Chemistry & Metallurgy","D": "Textiles & Paper",
    "E": "Fixed Constructions",  "F": "Mechanical Engineering",
    "G": "Physics",              "H": "Electricity",
    "Y": "Emerging Technologies",
}

# Page config 
st.set_page_config(
    page_title="Patent Intelligence",
    page_icon=":zap:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* Sidebar */
[data-testid="stSidebar"] { background:#0d1117; }
[data-testid="stSidebar"] * { color:#e6edf3; }
[data-testid="stSidebar"] .stRadio label { font-size:0.95rem; }

/* Headings */
h1 { color:#1f77b4; font-size:1.8rem; }
h2 { color:#1f77b4; font-size:1.3rem; }
h3 { color:#333; font-size:1.05rem; margin-bottom:0.2rem; }

/* Metric cards */
[data-testid="metric-container"] {
    background:#f8f9fa; border-radius:8px;
    border-left:4px solid #1f77b4; padding:0.4rem 0.8rem;
}

/* Section dividers */
hr { margin: 1.2rem 0; border-color:#e0e0e0; }

/* Dataframe header */
.stDataFrame thead tr th { background:#1f77b4; color:white; }
</style>
""", unsafe_allow_html=True)


#  Data loaders 
@st.cache_data(ttl=3600, show_spinner=False)
def load_csv(filename: str) -> pd.DataFrame:
    path = REPORT_DIR / filename
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_report_json() -> dict:
    path = REPORT_DIR / "patent_report.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=300, show_spinner=False)
#This needs the database so it may not work on deploymnt due to large database
def search_patents_fts(query: str, limit: int = 200) -> pd.DataFrame:
    """
    Full-text search via FTS5 (Porter stemming).  Falls back to LIKE on
    title-only if FTS5 raises a syntax error from special characters.
    """
    if not DB_PATH.exists() or len(query.strip()) < 2:
        return pd.DataFrame()

    # Strip FTS5 operators to avoid parse errors from raw user input
    clean = re.sub(r'[^\w\s]', ' ', query.strip())
    if not clean.strip():
        return pd.DataFrame()

    fts_sql = """
        SELECT p.patent_id, p.title, p.year, p.patent_type,
               p.num_claims, p.grant_lag_days, p.filing_date, p.patent_date,
               p.abstract
        FROM patents_fts f
        JOIN patents p ON p.rowid = f.rowid
        WHERE patents_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """
    fallback_sql = """
        SELECT patent_id, title, year, patent_type,
               num_claims, grant_lag_days, filing_date, patent_date, abstract
        FROM patents
        WHERE LOWER(title) LIKE ?
        ORDER BY year DESC
        LIMIT ?
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA cache_size=-32768")
        try:
            df = pd.read_sql_query(fts_sql, conn, params=(clean, limit))
        except Exception:
            df = pd.read_sql_query(fallback_sql, conn,
                                   params=(f"%{query.lower()}%", limit))
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


#  Load all CSVs once 
report        = load_report_json()
df_yr         = load_csv("patents_per_year.csv")
df_grant_yr = load_csv("patents_by_grant_year.csv")  
df_inv        = load_csv("top_inventors.csv")
df_inv_rank   = load_csv("top_inventor_rankings.csv")
df_co         = load_csv("top_companies.csv")
df_ctry       = load_csv("top_countries.csv")
df_ctry_trend = load_csv("country_trends.csv")
df_decade     = load_csv("countries_by_decade.csv")
df_cpc_dist   = load_csv("cpc_section_distribution.csv")
df_cpc_trend  = load_csv("cpc_section_trends.csv")
df_cpc_co     = load_csv("top_companies_by_cpc.csv")
df_cpc_ctry   = load_csv("top_countries_by_cpc.csv")
df_cpc_recent = load_csv("recent_patents_by_cpc.csv")
df_lag_cpc    = load_csv("grant_lag_by_cpc.csv")
df_lag_ctry   = load_csv("grant_lag_by_country.csv")
df_lag_trend  = load_csv("grant_lag_trend.csv")
df_claims_yr  = load_csv("claims_per_year.csv")
df_claims_cpc = load_csv("claims_by_cpc.csv")

# Enrich CPC frames with human-readable section names
for _df in [df_cpc_dist, df_cpc_trend, df_cpc_co, df_cpc_ctry,
            df_cpc_recent, df_lag_cpc, df_claims_cpc]:
    if not _df.empty and "cpc_section" in _df.columns:
        _df["cpc_section_name"] = _df["cpc_section"].map(CPC_NAMES).fillna("Other")

# Totals from JSON report (flat schema) 
total_patents   = report.get("total_patents")
total_inventors = report.get("total_inventors")
total_companies = report.get("total_companies")
yr_range        = report.get("year_range", {})

# Fallback from CSV
if total_patents is None and not df_yr.empty:
    total_patents = int(df_yr["patent_count"].sum())

avg_grant_yrs = None
if not df_lag_trend.empty and "avg_grant_lag_days" in df_lag_trend.columns:
    avg_grant_yrs = df_lag_trend["avg_grant_lag_days"].mean() / 365.25

# Global sidebar filters 
st.sidebar.markdown("## :zap: Patent Intelligence")
st.sidebar.markdown("---")

PAGES = {
    ":bar_chart:   Overview":                 "overview",
    ":chart_with_upwards_trend:  Patent Trends":            "trends",
    ":trophy:  Inventors & Companies":    "leaderboard",
    ":earth_africa:  Country Analysis":         "countries",
    ":microscope:  CPC Technology":           "cpc",
    ":stopwatch:  Grant Duration Analytics": "grant",
    ":clipboard:  Claims Analysis":          "claims",
    ":mag:  Patent Search":            "search",
}

page_label = st.sidebar.radio("", list(PAGES.keys()))
page = PAGES[page_label]

st.sidebar.markdown("---")
st.sidebar.markdown("**:calendar:  Year range**")
y_min = int(df_yr["year"].min()) if not df_yr.empty else 1976
y_max = int(df_yr["year"].max()) if not df_yr.empty else 2025
yr_sel = st.sidebar.slider("", y_min, y_max, (y_min, y_max), label_visibility="collapsed")

st.sidebar.markdown("** :globe_with_meridians: Country filter**")
ctry_options = sorted(df_ctry["country"].dropna().unique()) if not df_ctry.empty else []
ctry_sel = st.sidebar.multiselect("", ctry_options, label_visibility="collapsed")


# Shared chart defaults
BOLD = px.colors.qualitative.Bold
CHART_H = dict(height=380, margin=dict(t=30, b=20, l=10, r=10))

def _apply(fig, **kw):
    fig.update_layout(**{**CHART_H, **kw})
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if page == "overview":
    st.markdown("# :bar_chart:   Patent Intelligence Dashboard")
    st.markdown(
        "Global patent analysis from **USPTO PatentsView** — "
        f"{yr_range.get('from', 1976)} to {yr_range.get('to', 2025)}."
    )
    st.markdown("---")

    # ── Key metrics ────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(":page_facing_up: Total Patents",
              f"{int(total_patents):,}" if total_patents else "N/A")
    m2.metric(":man_scientist: Inventors",
              f"{int(total_inventors):,}" if total_inventors else "N/A")
    m3.metric(":office: Companies",
              f"{int(total_companies):,}" if total_companies else "N/A")
    m4.metric(":date: Year Range",
              f"{yr_range.get('from','?')} – {yr_range.get('to','?')}")
    m5.metric(":stopwatch: Avg Grant Time",
              f"{avg_grant_yrs:.1f} yrs" if avg_grant_yrs else "N/A")

    st.markdown("---")

    #  Column 1: trend + CPC donut 
    c_left, c_right = st.columns([2, 3])

    with c_left:
        st.markdown("###:chart_with_upwards_trend: Patent Grants Per Year")
        if not df_yr.empty:
            fdf = df_yr[(df_yr["year"] >= yr_sel[0]) & (df_yr["year"] <= yr_sel[1])]
            fig = px.area(fdf, x="year", y="patent_count",
                          color_discrete_sequence=["#1f77b4"],
                          labels={"year": "Year", "patent_count": "Patents"})
            fig.update_traces(line_color="#1f77b4", fillcolor="rgba(31,119,180,0.12)")
            st.plotly_chart(_apply(fig, height=300, width=400), use_container_width=True)
            st.caption(" Post-2023 decline reflect USPTO reporting lag which is indicated in the visualization in the Grant Duration Analytics page, not fewer filings.")
            st.caption("There is a noticeable dip in patent grants around 2020-2021, likely due to COVID-19 disruptions. However, filings remained strong, suggesting continued innovation. The post-2023 drop is a data artefact from reporting lag, not a real decline in activity.")

    with c_right:
        st.markdown("### :microscope: Patents by Technology (CPC)")
        if not df_cpc_dist.empty:
            fig = px.pie(df_cpc_dist, names="cpc_section_name",
                         values="patent_count", hole=0.45,
                         color_discrete_sequence=BOLD)
            fig.update_traces(textposition="outside", textinfo="label+percent")
            fig.update_layout(height=300, margin=dict(t=10, b=40), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        st.caption("Physics and Electricity are the largest categories which shows the strong focus on electronics which powers the current AI boom.")


    st.markdown("---")

    # Row 2: top inventors / companies / countries 
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("### :1st_place_medal: Top 10 Inventors")
        if not df_inv.empty:
            top = df_inv.head(10).sort_values("patent_count")
            fig = px.bar(top, x="patent_count", y="name", orientation="h",
                         color="patent_count", color_continuous_scale="Blues",
                         labels={"patent_count": "Patents", "name": ""})
            st.plotly_chart(_apply(fig, height=330, coloraxis_showscale=False),
                            use_container_width=True)
            st.caption("Many top inventors are from Japan, reflecting the country's strong patenting culture and focus on electronics. The US also has a significant presence, while South Korea's representation highlights its growing innovation ecosystem.")

    with c2:
        st.markdown("### :office: Top 10 Companies")
        if not df_co.empty:
            top = df_co.head(10).sort_values("patent_count")
            fig = px.bar(top, x="patent_count", y="name", orientation="h",
                         color="patent_count", color_continuous_scale="Oranges",
                         labels={"patent_count": "Patents", "name": ""})
            st.plotly_chart(_apply(fig, height=330, coloraxis_showscale=False),
                            use_container_width=True)
            st.caption("Major tech companies dominate the patent landscape, with strong portfolios in areas like semiconductors, software, and telecommunications.")
            st.caption("Samsung Display Co., Ltd.'s high ranking reflects its focus on display technologies, which are crucial for devices like smartphones and TVs.")
    with c3:
        st.markdown("### :earth_africa: Top 10 Countries")
        if not df_ctry.empty:
            top = df_ctry.head(10).sort_values("patent_count")
            fig = px.bar(top, x="patent_count", y="country", orientation="h",
                         color="patent_count", color_continuous_scale="Greens",
                         labels={"patent_count": "Patents", "country": ""})
            st.plotly_chart(_apply(fig, height=330, coloraxis_showscale=False),
                            use_container_width=True)
            st.caption("The US leads in patent filings, followed by Japan, Germany then China. South Korea's strong showing reflects its focus on technology and innovation spearheaded by Samsung Display Co., Ltd.")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: PATENT TRENDS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "trends":
    st.markdown("#:chart_with_upwards_trend: Patent Trends")
    st.markdown("---")
    
    # ── Filing Year vs Grant Year — reporting lag explainer ───────────────────
    st.markdown("### :bar_chart:  Filing Year vs Grant Year — Understanding the Reporting Lag")
    st.markdown(
        "The apparent **decline in recent years** is not a drop in innovation. "
        "It is a **data artefact**: patents filed in 2022–2024 are still being examined "
        "and have not been granted yet, so they are missing from the grant-year count. "
        "The chart below makes this visible."
    )
 
    # filing year = df_yr (already loaded from patents_per_year.csv, Q4)
    # grant year  = df_grant_yr (loaded from patents_by_grant_year.csv, A6)
    # Both are pre-computed by reports.py — no DB query at dashboard load time.
    df_filing = df_yr.rename(columns={"year": "yr"}) if not df_yr.empty else pd.DataFrame()
    df_grant  = df_grant_yr if not df_grant_yr.empty else pd.DataFrame()
 
    if not df_filing.empty and not df_grant.empty:
        # Apply global year filter
        df_f = df_filing[df_filing["yr"].between(yr_sel[0], yr_sel[1])].copy()
        df_g = df_grant [df_grant ["yr"].between(yr_sel[0], yr_sel[1])].copy()
 
        # Merge to compute the gap (grant < filing in recent years)
        merged = pd.merge(df_f, df_g, on="yr", suffixes=("_filing","_grant"), how="outer")\
                   .sort_values("yr").fillna(0)
 
        fig = go.Figure()
 
        # ── Shaded "unreported zone" between grant and filing ─────────────────
        # Fill from grant line UP to filing line — the gap is the lag
        fig.add_trace(go.Scatter(
            x=pd.concat([merged["yr"], merged["yr"][::-1]]),
            y=pd.concat([merged["patent_count_filing"], merged["patent_count_grant"][::-1]]),
            fill="toself",
            fillcolor="rgba(255,127,14,0.12)",
            line=dict(color="rgba(0,0,0,0)"),
            showlegend=True,
            name="Unreported (filed but not yet granted)",
        ))
 
        # ── Grant year line ────────────────────────────────────────────────────
        fig.add_trace(go.Scatter(
            x=df_g["yr"], y=df_g["patent_count"],
            mode="lines",
            name="Grant year (public record)",
            line=dict(color="#ff7f0e", width=2.5),
        ))
 
        # ── Filing year line ───────────────────────────────────────────────────
        fig.add_trace(go.Scatter(
            x=df_f["yr"], y=df_f["patent_count"],
            mode="lines",
            name="Filing year (actual activity)",
            line=dict(color="#1f77b4", width=2.5),
        ))
 
        # ── Annotate the divergence point ─────────────────────────────────────
        # Find the first year where grant count drops > 10 % below filing count
        _div = merged[(merged["patent_count_grant"] > 0) &
                      (merged["patent_count_grant"] < merged["patent_count_filing"] * 0.90)]
        if not _div.empty:
            div_yr   = 2021
            div_cnt  = int(_div["patent_count_filing"].iloc[0])
            fig.add_vline(
                x=div_yr, line_dash="dot", line_color="#999",
                annotation_text=f"Lag becomes visible (~{div_yr})",
                annotation_position="top right",
                annotation_font_size=11,
            )
 
        # ── Avg lag annotation ─────────────────────────────────────────────────
        if avg_grant_yrs:
            fig.add_annotation(
                x=yr_sel[0] + (yr_sel[1]-yr_sel[0]) * 0.05,
                y=df_f["patent_count"].max() * 0.97,
                text=f"Avg prosecution time: {avg_grant_yrs:.1f} yrs",
                showarrow=False,
                font=dict(size=12, color="#555"),
                bgcolor="rgba(255,255,255,0.7)",
                bordercolor="#ccc",
                borderwidth=1,
            )
 
        fig.update_layout(**{
            **CHART_H,
            "height":420},
            yaxis_title="Number of Patents",
            xaxis_title="Year",
            legend=dict(orientation="h", y=1.08, x=0),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True, key="filing-vs-grant")
 
        # ── Companion gap table ────────────────────────────────────────────────
        with st.expander(":clipboard: Show filing vs grant counts by year"):
            tbl = merged.copy()
            tbl["gap (filing − grant)"] = (
                tbl["patent_count_filing"] - tbl["patent_count_grant"]
            ).astype(int)
            tbl["grant / filing %"] = (
                tbl["patent_count_grant"] / tbl["patent_count_filing"].replace(0, pd.NA) * 100
            ).round(1)
            tbl = tbl.rename(columns={
                "yr": "Year",
                "patent_count_filing": "By Filing Year",
                "patent_count_grant":  "By Grant Year",
            })
            st.dataframe(
                tbl[["Year","By Filing Year","By Grant Year",
                     "gap (filing − grant)","grant / filing %"]].astype(
                    {"Year": int, "By Filing Year": int, "By Grant Year": int}
                ),
                use_container_width=True, height=320,
            )
    else:
        st.info("Could not load filing/grant data — make sure patents.db exists.")
 
    st.markdown("---")
 
    # Annual volume bar
    st.markdown("### Annual Patent Volume (by filing year)")
    if not df_yr.empty:
        fdf = df_yr[(df_yr["year"] >= yr_sel[0]) & (df_yr["year"] <= yr_sel[1])]
        fig = px.bar(fdf, x="year", y="patent_count",
                     color_discrete_sequence=["#1f77b4"],
                     labels={"year": "Year", "patent_count": "Patents"})
        st.plotly_chart(_apply(fig), use_container_width=True, key="filing-year-trend")
        st.caption("Take note of the post-2023 decline, which likely reflects USPTO data lag rather than a real decrease in filings.")
 
    st.markdown("---")

    # Country trends
    col_fil, col_chart = st.columns([1, 3])
    with col_fil:
        st.markdown("### Countries")
        if not df_ctry_trend.empty:
            all_c = sorted(df_ctry_trend["country"].dropna().unique())
            defaults = [c for c in ["US", "JP", "DE", "CN", "KR"] if c in all_c]
            trend_ctry = st.multiselect("Pick countries", all_c, default=defaults)
        else:
            trend_ctry = []

    with col_chart:
        st.markdown("### Patents by Country Over Time")
        if not df_ctry_trend.empty and trend_ctry:
            fdf = df_ctry_trend[
                df_ctry_trend["country"].isin(trend_ctry) &
                df_ctry_trend["year"].between(yr_sel[0], yr_sel[1])
            ]
            fig = px.line(fdf, x="year", y="patents", color="country",
                          markers=False, color_discrete_sequence=BOLD,
                          labels={"year": "Year", "patents": "Patents", "country": "Country"})
            st.plotly_chart(_apply(fig), use_container_width=True)
            st.caption("When we compare the big three (US, JP, CN), we see that the US has a steady growth, Japan shows a plateau and slight decline in recent years, while China exhibits rapid growth, especially post-2010, reflecting its increasing focus on innovation and technology development.")
            st.caption("In 2020, we see a dip for all countries, likely due to COVID-19 disruptions.")
            st.caption("In 2020, we also see China overtake Japan, reflecting its rapid innovation growth and increased patenting activity in recent years.")
        elif df_ctry_trend.empty:
            st.info("country_trends.csv not found — run reports.py first.")
        else:
            st.info("Select at least one country on the left.")

    st.markdown("---")

    # Decade analysis
    st.markdown("### Top Countries by Decade")
    if not df_decade.empty and "decade" in df_decade.columns:
        decades = sorted(df_decade["decade"].dropna().unique(), reverse=True)
        sel_dec = st.select_slider("Decade", [int(d) for d in decades])
        fdf = df_decade[df_decade["decade"] == sel_dec].sort_values(
            "patents_per_decade", ascending=False)
        if not fdf.empty:
            fig = px.bar(fdf, x="country", y="patents_per_decade",
                         color="country", color_discrete_sequence=BOLD,
                         labels={"country": "Country", "patents_per_decade": "Patents"})
            st.plotly_chart(_apply(fig, showlegend=False), use_container_width=True)
            st.caption(f"The chart shows the leading countries in patent filings for the {sel_dec}s. The US consistently leads across decades, with Japan showing strong performance in the late 20th century. China's rise is evident in the 2000s and 2010s, reflecting its rapid growth in innovation and technology development.")
            st.caption("In the 1970s and 1980s, the US and Japan dominated patent filings, reflecting their strong industrial bases and focus on innovation during that period. They were followed by Germany, France, and Great Britain, which shows the dominance of Western countries in the global patent landscape during the late 20th century.")
            st.caption("In the 1990s, we see the US maintaining its lead, while Japan continues to perform strongly. Germany remains in the top ranks, while Great Britain overtakes France. This period reflects France's decline in patent filing due to the end of cold war and the rise of the internet economy which shifted innovation focus towards software and electronics where France had less presence.")
            st.caption("The 2000s show the US still leading, but South Korea and Taiwan's emergence is significant as it enters the top ranks, reflecting its rapid industrial growth and increased focus on innovation. Japan's share declines, while Germany maintains a strong position, and France and Great Britain are not in the top ranks. This marks a shift in the global patent landscape, with Asian countries like South Korea and Taiwan rising due to their focus on technology and manufacturing, while traditional Western leaders like France and Great Britain see a relative decline.")
            st.caption("In the 2010s, the US remains the leader, but China's rapid rise is the most notable change, reflecting its massive investment in R&D and focus on innovation. South Korea maintains a strong position, while Japan's share continues to decline. Germany remains in the top ranks, while France and Great Britain are absent. This decade highlights the significant shift towards Asia in the global patent landscape, driven by China's emergence as a major innovator and South Korea's continued growth in technology sectors.")
            st.caption("Looking at the most recent decade (2020s), the US still leads, China overtakes Japan to become the second largest filer, and South Korea remains strong. Taiwan is back in the top ranks, while Japan's share continues to decline. This reflects the ongoing dominance of the US in patent filings, China's rapid growth and increasing focus on innovation, and the continued strength of South Korea in technology sectors. Japan's decline may be due to various factors including recent economic challenges such as an aging population and a shrinking workforce.")
           
    else:
        st.info("countries_by_decade.csv not found — run reports.py first.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: INVENTORS & COMPANIES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "leaderboard":
    st.markdown("# :trophy: Top Inventors & Companies")
    st.markdown("---")

    tab_inv, tab_co = st.tabs([":man_scientist: Inventors", ":office: Companies"])

    with tab_inv:
        col_chart, col_tbl = st.columns([3, 2])
        with col_chart:
            st.markdown("### Top 20 Inventors")
            if not df_inv.empty:
                fdf = df_inv.copy()
                if ctry_sel and "country" in fdf.columns:
                    fdf = fdf[fdf["country"].isin(ctry_sel)]
                fdf = fdf.head(20).sort_values("patent_count")
                fig = px.bar(fdf, x="patent_count", y="name", orientation="h",
                             color="country", color_discrete_sequence=BOLD,
                             labels={"patent_count": "Patents", "name": "Inventor",
                                     "country": "Country"})
                st.plotly_chart(_apply(fig, height=560), use_container_width=True)
                st.caption("The inventor with most patents is from Japan, followed by Australia then Taiwan. The rest are from the US. This reflects the strong patenting culture in Japan and the US due to the large investments in R&D, as well as the significant contributions from inventors in Australia and Taiwan.")

            else:
                st.info("top_inventors.csv not found — run reports.py first.")

        with col_tbl:
            st.markdown("### Rankings Table")
            if not df_inv_rank.empty:
                fdf = df_inv_rank.copy()
                if ctry_sel and "country" in fdf.columns:
                    fdf = fdf[fdf["country"].isin(ctry_sel)]
                show_cols = [c for c in ["rank","name","country","patent_count"] if c in fdf.columns]
                st.dataframe(fdf[show_cols].rename(columns={"patent_count": "patents"}),
                             use_container_width=True, height=560)

    with tab_co:
        col_chart, col_tbl = st.columns([3, 2])
        with col_chart:
            st.markdown("### Top 20 Companies")
            if not df_co.empty:
                fdf = df_co.head(20).sort_values("patent_count")
                color_col = "assignee_type" if "assignee_type" in fdf.columns else "patent_count"
                fig = px.bar(fdf, x="patent_count", y="name", orientation="h",
                             color=color_col, color_discrete_sequence=BOLD,
                             labels={"patent_count": "Patents", "name": "Company"})
                st.plotly_chart(_apply(fig, height=560), use_container_width=True)
                st.caption("The assignee type in the top 20 is corporations, which reflects the dominance of corporate entities in patent filings. Samsung Display Co., Ltd. leads the rankings, highlighting its focus on display technologies. The presence of other major tech companies in the top ranks underscores their significant investment in R&D and innovation.")
                st.caption("Individual inventors and universities are not present in the top 20, which may be due to the fact that corporate entities often file patents on behalf of their employees and research teams, leading to a concentration of patents under company names rather than individual inventors or academic institutions. There is also a cost barrier to filing patents that may deter individuals and smaller entities from filing as frequently as larger corporations.")
            else:
                st.info("top_companies.csv not found — run reports.py first.")

        with col_tbl:
            st.markdown("### Company Table")
            if not df_co.empty:
                st.dataframe(df_co, use_container_width=True, height=560)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: COUNTRY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "countries":
    st.markdown("# :earth_africa: Country Analysis")
    st.markdown("---")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### Patent Totals by Top 20 Countries")
        if not df_ctry.empty:
            fdf = df_ctry.copy()
            if ctry_sel:
                fdf = fdf[fdf["country"].isin(ctry_sel)]
            fig = px.bar(fdf.head(20).sort_values("patent_count", ascending=False), #Show top 20 countries by total patents
                         x="country", y="patent_count",
                         color="patent_count", color_continuous_scale="Blues",
                         labels={"patent_count": "Patents", "country": "Country"})
            st.plotly_chart(_apply(fig, coloraxis_showscale=False), use_container_width=True)
            st.caption("The US leads by a significant margin, followed by Japan, Germany and China. South Korea's strong showing reflects its focus on technology and innovation spearheaded by Samsung Display Co., Ltd.")

    with col_b:
        st.markdown("### Avg Grant Lag by Top 20 Countries")
        if not df_lag_ctry.empty:
            fdf = df_lag_ctry.copy()
            if ctry_sel:
                fdf = fdf[fdf["country"].isin(ctry_sel)]
            fdf = fdf.head(20).sort_values("avg_grant_lag_days")
            fig = px.bar(fdf, x="avg_grant_lag_days", y="country", orientation="h",
                         color="avg_grant_lag_years", color_continuous_scale="RdYlGn_r",
                         text="avg_grant_lag_years",
                         labels={"avg_grant_lag_days": "Avg Days",
                                 "country": "Country", "avg_grant_lag_years": "Yrs"})
            fig.update_traces(texttemplate="%{text:.1f} yrs", textposition="outside")
            st.plotly_chart(_apply(fig, coloraxis_showscale=False), use_container_width=True)
            st.caption("The average grant lag varies significantly by country, with some countries such as Finland experiencing much longer prosecution times than others. This can be influenced by factors such as the efficiency of the patent office, the complexity of the patent applications, and the backlog of pending applications. Countries with longer grant lags may face challenges in bringing innovations to market quickly, while those with shorter lags may have a competitive advantage in terms of speed to market.")
            st.caption("It's also important to note that the grant lag can also be affected by the strategic behavior of applicants, such as intentionally delaying prosecution to extend the period of uncertainty for competitors. ")
            st.caption("The US, Japan, Taiwan and China have relatively shorter grant lags, which may reflect more efficient patent examination processes or a higher proportion of straightforward applications.  This explains their high patent volumes as seen in the patent overview and patent trends pages.")
        else:
            st.info("grant_lag_by_country.csv not found — run reports.py first.")

    st.markdown("---")
    st.markdown("### Patent Trends by Country Over Time")
    if not df_ctry_trend.empty:
        all_c = sorted(df_ctry_trend["country"].dropna().unique())
        defaults = ctry_sel if ctry_sel else [c for c in ["US","JP","DE","CN","KR","TW","GB"] if c in all_c]
        trend_c = st.multiselect("Select countries", all_c, default=defaults, key="ct_trend")
        fdf = df_ctry_trend[
            df_ctry_trend["country"].isin(trend_c) &
            df_ctry_trend["year"].between(yr_sel[0], yr_sel[1])
        ]
        if not fdf.empty:
            fig = px.line(fdf, x="year", y="patents", color="country",
                          color_discrete_sequence=BOLD,
                          labels={"year": "Year", "patents": "Patents", "country": "Country"})
            st.plotly_chart(_apply(fig, height=420), use_container_width=True)
            st.caption("When we compare the big three (US, JP, CN), we see that the US has a steady growth, Japan shows a plateau and slight decline in recent years, while China exhibits rapid growth, especially post-2010, reflecting its increasing focus on innovation and technology development.")

    st.markdown("---")
    st.markdown("### Leading Countries by CPC Technology Area")
    if not df_cpc_ctry.empty:
        sec_opts = sorted(df_cpc_ctry["cpc_section"].dropna().unique())
        sel_sec = st.selectbox("CPC Section", sec_opts,
                               format_func=lambda x: f"{x} — {CPC_NAMES.get(x, x)}")
        fdf = df_cpc_ctry[df_cpc_ctry["cpc_section"] == sel_sec].sort_values(
            "patent_count", ascending=False)
        if not fdf.empty:
            fig = px.bar(fdf, x="country", y="patent_count",
                         color="patent_count", color_continuous_scale="Teal",
                         title=f"Top Countries — {CPC_NAMES.get(sel_sec, sel_sec)}",
                         labels={"country": "Country", "patent_count": "Patents"})
            st.plotly_chart(_apply(fig, coloraxis_showscale=False), use_container_width=True)
            st.caption(f"This chart shows the leading countries in patent filings for the {CPC_NAMES.get(sel_sec, sel_sec)} technology section. The US leads in most sections, reflecting its overall dominance in patent filings. However, in certain sections such as {CPC_NAMES.get(sel_sec, sel_sec)}, other countries like China, Germany, Japan or South Korea may have a stronger presence, indicating their specialization and focus on innovation in those specific technology areas.")


# PAGE: CPC TECHNOLOGY

elif page == "cpc":
    st.markdown("# :microscope: CPC Technology Section Analysis")
    st.markdown(
        "The Cooperative Patent Classification (CPC) groups patents into 9 technology "
        "sections. Use this page to explore innovation by sector."
    )
    st.markdown("---")

    # Section overview
    col_chart, col_ref = st.columns([3, 1])
    with col_chart:
        st.markdown("### Patent Volume by CPC Section")
        if not df_cpc_dist.empty:
            fig = px.bar(
                df_cpc_dist.sort_values("patent_count", ascending=False),
                x="cpc_section_name", y="patent_count",
                text="percentage", color="cpc_section_name",
                color_discrete_sequence=BOLD,
                labels={"cpc_section_name": "Section", "patent_count": "Patents"})
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(**{**CHART_H, "showlegend": False, "xaxis_tickangle": -20})
            st.plotly_chart(fig, use_container_width=True)
            st.caption("The chart shows the distribution of patents across the 9 CPC sections. The largest sections are Physics (Section G) and Electricity (Section H), which reflects the strong focus on electronics and related technologies in patent filings. The other sections have smaller shares, indicating that while there is innovation across all technology areas, certain sectors like electronics dominate the patent landscape.")
            st.caption("The dominance of the Physics and Electricity sections may be driven by the rapid growth in technologies such as semiconductors, telecommunications, and computing, which are classified under these sections. This is especially relevant in the context of the current AI boom, which relies heavily on advancements in these areas.")

    with col_ref:
        st.markdown("### Section Key")
        for k, v in CPC_NAMES.items():
            st.markdown(f"**{k}** {v}")

    st.markdown("---")

    # CPC trends over time
    st.markdown("### Technology Trends Over Time")
    if not df_cpc_trend.empty:
        sec_list = sorted(df_cpc_trend["cpc_section"].dropna().unique())
        sel_secs = st.multiselect(
            "Filter sections", sec_list, default=list(sec_list),
            format_func=lambda x: f"{x} — {CPC_NAMES.get(x,x)}", key="cpc_trend_sel")
        fdf = df_cpc_trend[
            df_cpc_trend["cpc_section"].isin(sel_secs) &
            df_cpc_trend["year"].between(yr_sel[0], yr_sel[1])
        ]
        if not fdf.empty:
            fig = px.line(fdf, x="year", y="patent_count",
                          color="cpc_section_name", color_discrete_sequence=BOLD,
                          labels={"year": "Year", "patent_count": "Patents",
                                  "cpc_section_name": "Section"})
            st.plotly_chart(_apply(fig, height=420), use_container_width=True)
            st.caption("In the 1970s and 1980s, the largest section was Operation and Transport (Section B), reflecting the focus on mechanical inventions during that period. However, starting in the 1990s, we see a significant rise in the Physics (Section G) and Electricity (Section H) sections, which corresponds with the growth of electronics, computing, and telecommunications technologies. This trend continues into the 2000s and 2010s, with these two sections dominating the patent landscape, especially in recent years with the rise of AI and related technologies. The other sections show more modest growth, indicating that while there is innovation across all technology areas, certain sectors like electronics have become increasingly dominant.")
    else:
        st.info("cpc_section_trends.csv not found — run reports.py first.")

    st.markdown("---")

    # Top companies and countries per section
    

    
    st.markdown("### Top Companies per CPC Section")
    if not df_cpc_co.empty:
            sel = st.selectbox("Section (companies)", sorted(df_cpc_co["cpc_section"].unique()),
                               format_func=lambda x: f"{x} — {CPC_NAMES.get(x,x)}",
                               key="cpc_co_sel")
            fdf = df_cpc_co[df_cpc_co["cpc_section"] == sel].sort_values("patent_count")
            fig = px.bar(fdf, x="patent_count", y="company_name", orientation="h",
                         color="patent_count", color_continuous_scale="Blues",
                         labels={"patent_count": "Patents", "company_name": "Company"})
            st.plotly_chart(_apply(fig, height=300, coloraxis_showscale=False),
                            use_container_width=True)
            st.caption(f"The chart shows the leading companies in patent filings for the {CPC_NAMES.get(sel, sel)} technology section. The top companies may vary by section, reflecting their specialization and focus on innovation in those specific technology areas. For example, in the Electricity (Section H) category, we may see major tech companies like Samsung Display Co., Ltd. leading due to their focus on display technologies, while in the Physics (Section G) category, we see International Business Machines Corporation (IBM) leading due to its focus on artificial intelligence and computing technologies.")

    

    st.markdown("---")

    # Recent patents per section
    st.markdown("### Most Recent Patents by CPC Section")
    if not df_cpc_recent.empty:
        sel = st.selectbox("Section (recent patents)",
                           sorted(df_cpc_recent["cpc_section"].unique()),
                           format_func=lambda x: f"{x} — {CPC_NAMES.get(x,x)}",
                           key="cpc_rec_sel")
        fdf = df_cpc_recent[df_cpc_recent["cpc_section"] == sel]
        cols = [c for c in ["patent_id", "title", "year", "filing_date"] if c in fdf.columns]
        st.dataframe(fdf[cols], use_container_width=True)
    else:
        st.info("recent_patents_by_cpc.csv not found — run reports.py first.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: GRANT DURATION ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "grant":
    st.markdown("# :stopwatch: Patent Grant Duration Analytics")
    st.markdown(
        "**Grant lag** = calendar days from filing date to patent grant. "
        "Longer lag means longer prosecution — more examiner rounds, objections, or complexity."
    )
    st.markdown("---")

    # Summary KPIs
    if not df_lag_trend.empty:
        overall   = df_lag_trend["avg_grant_lag_days"].mean()
        recent5   = df_lag_trend.nlargest(5,  "year")["avg_grant_lag_days"].mean()
        earliest5 = df_lag_trend.nsmallest(5, "year")["avg_grant_lag_days"].mean()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Overall Avg Lag", f"{overall:,.0f} days")
        k2.metric("Avg Years",                f"({overall/365.25:.1f} years)")
        k3.metric("Last 5 yrs avg",  f"{recent5:,.0f} d ({recent5/365.25:.1f} yrs)")
        k4.metric("First 5 yrs avg", f"{earliest5:,.0f} d ({earliest5/365.25:.1f} yrs)")
        st.markdown("---")

    # Grant lag trend over time
    st.markdown("### Grant Lag Trend Over Time (by filing year)")
    if not df_lag_trend.empty:
        fdf = df_lag_trend[df_lag_trend["year"].between(yr_sel[0], yr_sel[1])]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=fdf["year"], y=fdf["avg_grant_lag_days"],
            name="Avg Days", mode="lines+markers",
            line=dict(color="#d62728", width=2),
        ))
        fig.add_trace(go.Scatter(
            x=fdf["year"], y=fdf["avg_grant_lag_years"],
            name="Avg Years", mode="lines", yaxis="y2",
            line=dict(color="#aec7e8", width=1.5, dash="dot"),
        ))
        fig.update_layout(
            **CHART_H,
            yaxis=dict(title="Days to Grant"),
            yaxis2=dict(title="Years to Grant", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.08),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Red solid = days (left axis).  Blue dotted = years (right axis).")
        st.caption("There is a general decline in grant lag over time due to improvements in patent office efficiency due to technological advances and changes in patenting behavior. However, there are fluctuations that may reflect changes in patent law, examination practices, or the complexity of inventions being patented.")
    else:
        st.info("grant_lag_trend.csv not found — run reports.py first.")

    st.markdown("---")

    # Grant lag by CPC and by country (side by side)
    col_cpc, col_ctry = st.columns(2)

    with col_cpc:
        st.markdown("### Grant Lag by Technology (CPC)")
        if not df_lag_cpc.empty:
            fdf = df_lag_cpc.sort_values("avg_grant_lag_days", ascending=True)
            fig = px.bar(fdf, x="avg_grant_lag_days", y="cpc_section_name",
                         orientation="h", text="avg_grant_lag_years",
                         color="avg_grant_lag_years", color_continuous_scale="RdYlGn_r",
                         labels={"avg_grant_lag_days": "Avg Days",
                                 "cpc_section_name": "Section",
                                 "avg_grant_lag_years": "Avg Yrs"})
            fig.update_traces(texttemplate="%{text:.1f} yrs", textposition="outside")
            st.plotly_chart(_apply(fig, coloraxis_showscale=False), use_container_width=True)
            st.caption("Longer lag indicate more complex examination or more objections raised.")
            st.caption("Human neccessities has the largest lag to grant due to more complex examination and the ethical objections raised by examiners and the public.")

            with st.expander(":clipboard: Full Table — Grant Lag by CPC"):
                show = [c for c in ["cpc_section","cpc_section_name","patent_count",
                                    "avg_grant_lag_days","avg_grant_lag_years",
                                    "min_lag_days","max_lag_days"] if c in df_lag_cpc.columns]
                st.dataframe(df_lag_cpc[show].sort_values(
                    "avg_grant_lag_days", ascending=False), use_container_width=True)
                
        else:
            st.info("grant_lag_by_cpc.csv not found — run reports.py first.")

    with col_ctry:
        st.markdown("### Grant Lag by Country")
        if not df_lag_ctry.empty:
            fdf = df_lag_ctry.copy()
            if ctry_sel:
                fdf = fdf[fdf["country"].isin(ctry_sel)]
            fdf = fdf.head(25).sort_values("avg_grant_lag_days", ascending=True)
            fig = px.bar(fdf, x="avg_grant_lag_days", y="country",
                         orientation="h", text="avg_grant_lag_years",
                         color="avg_grant_lag_years", color_continuous_scale="RdYlGn_r",
                         labels={"avg_grant_lag_days": "Avg Days",
                                 "country": "Country",
                                 "avg_grant_lag_years": "Avg Yrs"})
            fig.update_traces(texttemplate="%{text:.1f} yrs", textposition="outside")
            st.plotly_chart(_apply(fig, height=580, coloraxis_showscale=False),
                            use_container_width=True)
            st.caption("""FI - Finland has the largest lag because The Finnish Patent Office (PRH) does full substantive examination before grant. That includes:
novelty check
inventive step review
clarity of claims
technical sufficiency

That alone adds time compared to systems that do lighter review or defer it.""")

            with st.expander(":clipboard: Full Table — Grant Lag by Country"):
                show = [c for c in ["country","patent_count","avg_grant_lag_days",
                                    "avg_grant_lag_years","min_lag_days","max_lag_days"]
                        if c in df_lag_ctry.columns]
                st.dataframe(df_lag_ctry[show], use_container_width=True)
        else:
            st.info("grant_lag_by_country.csv not found — run reports.py first.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: CLAIMS ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "claims":
    st.markdown("# :clipboard: Patent Claims Analysis")
    st.markdown(
        "**Claim count** proxies patent scope and complexity. "
        "More claims ≈ broader protection — and often longer prosecution."
    )
    st.markdown("---")

    col_yr, col_cpc = st.columns(2)

    with col_yr:
        st.markdown("### Avg Claims Per Year")
        if not df_claims_yr.empty:
            fdf = df_claims_yr[df_claims_yr["year"].between(yr_sel[0], yr_sel[1])]
            fig = go.Figure()
            # Shaded min-max band
            if "min_claims" in fdf.columns and "max_claims" in fdf.columns:
                fig.add_trace(go.Scatter(
                    x=pd.concat([fdf["year"], fdf["year"][::-1]]),
                    y=pd.concat([fdf["max_claims"], fdf["min_claims"][::-1]]),
                    fill="toself", fillcolor="rgba(44,160,44,0.08)",
                    line=dict(color="rgba(0,0,0,0)"), showlegend=False,
                ))
            fig.add_trace(go.Scatter(
                x=fdf["year"], y=fdf["avg_claims"],
                name="Avg Claims", mode="lines+markers",
                line=dict(color="#2ca02c", width=2),
            ))
            fig.update_layout(**CHART_H, yaxis_title="Avg Number of Claims")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("The average number of claims per patent has generally increased over time, reflecting a trend towards broader and more complex patent applications. The shaded area represents the range between the minimum and maximum claims, indicating that while some patents have a small number of claims, others can have a very large number, contributing to the overall increase in average claims.")
            st.caption("The higher the number of claims, the broader the protection sought by the patent applicant, which can lead to stronger market exclusivity but also more complex and prolonged prosecution due to increased scrutiny by patent examiners and potential objections from competitors.")

            # Delta metric
            if len(fdf) >= 2:
                first_row = fdf.sort_values("year").iloc[0]
                last_row  = fdf.sort_values("year").iloc[-1]
                d1, d2, d3 = st.columns(3)
                d1.metric(f"Avg Claims ({int(first_row['year'])})",
                          f"{float(first_row['avg_claims']):.1f}")
                d2.metric(f"Avg Claims ({int(last_row['year'])})",
                          f"{float(last_row['avg_claims']):.1f}",
                          delta=f"{float(last_row['avg_claims'])-float(first_row['avg_claims']):+.1f}")
                d3.metric("Patents in latest year",
                          f"{int(last_row['patent_count']):,}")
        else:
            st.info("claims_per_year.csv not found — run reports.py first.")

    with col_cpc:
        st.markdown("### Avg Claims by CPC Section")
        if not df_claims_cpc.empty:
            fdf = df_claims_cpc.sort_values("avg_claims", ascending=True)
            fig = px.bar(fdf, x="avg_claims", y="cpc_section_name",
                         orientation="h", text="avg_claims",
                         color="avg_claims", color_continuous_scale="Greens",
                         labels={"avg_claims": "Avg Claims", "cpc_section_name": "Section"})
            fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
            st.plotly_chart(_apply(fig, coloraxis_showscale=False), use_container_width=True)

            with st.expander(":clipboard: Full Table — Claims by CPC"):
                show = [c for c in ["cpc_section","cpc_section_name",
                                    "patent_count","avg_claims","max_claims"]
                        if c in df_claims_cpc.columns]
                st.dataframe(df_claims_cpc[show].sort_values("avg_claims", ascending=False),
                             use_container_width=True)
                st.caption("Physics and Electricity sections have the highest average claims, which reflects the complexity and breadth of inventions in these technology areas.")
        else:
            st.info("claims_by_cpc.csv not found — run reports.py first.")

    st.markdown("---")

    # Scatter: grant lag vs claims (bubble = patent volume)
    st.markdown("### Grant Lag vs Claims by Technology — bubble = patent volume")
    if not df_lag_cpc.empty and not df_claims_cpc.empty:
        merged = df_lag_cpc.merge(
            df_claims_cpc[["cpc_section","avg_claims"]], on="cpc_section", how="inner")
        if not merged.empty:
            fig = px.scatter(
                merged, x="avg_claims", y="avg_grant_lag_days",
                size="patent_count", color="cpc_section_name", text="cpc_section",
                size_max=70, color_discrete_sequence=BOLD,
                labels={"avg_claims": "Avg Claims",
                        "avg_grant_lag_days": "Avg Grant Lag (days)",
                        "cpc_section_name": "Section",
                        "patent_count": "# Patents"},
            )
            fig.update_traces(textposition="top center")
            fig.update_layout(**{**CHART_H, "height": 460}) # Update layout with height
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Top-right = high claim count AND long prosecution time. "
                "Bubble size proportional to total patents in that section."
            )
            st.caption("Sections with more claims tend to have longer grant lags, indicating that broader and more complex patents. However, there is an exceptions for Human Necessities (Section A) which has a relatively long grant lag despite a lower average claim count, likely due to the ethical and regulatory complexities involved in patenting inventions related to human health and life.")
            st.caption("The Physics and Electricity sections, also have higher average claims and longer grant lags, reflecting the competitive and complex nature of innovation in these technology areas especially with the rise of AI and related technologies. In contrast, sections like Textiles (Section D) and Fixed Constructions (Section E) have lower average claims and shorter grant lags, indicating that patents in these areas may be more straightforward and less complex to prosecute.")
            st.caption("Fixed Constructions (Section E) has the shortest grant lag, which may reflect the more mechanical and less complex nature of inventions in this area, leading to quicker examination and fewer objections from patent examiners.")
    else:
        st.info("Requires both grant_lag_by_cpc.csv and claims_by_cpc.csv — run reports.py first.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: PATENT SEARCH
# ══════════════════════════════════════════════════════════════════════════════
elif page == "search":
    st.markdown("# :mag: Patent Search")
    st.markdown(
        "Full-text search across **9M+ patents** using the FTS5 index "
        "*(Porter stemming: **computing** matches **compute**, **computers**, etc.)*" \
        "" \
        "Doesnt work in the deployed version since the database is not included, but you can run it locally with the full database and FTS index built by `reports.py`. Please heck the provided Dashboard Screenshots for example query and results."

    )
    st.markdown("---")

    col_q, col_lim = st.columns([4, 1])
    with col_q:
        query = st.text_input(
            "Search terms",
            placeholder="e.g.  quantum computing   |   neural network   |   CRISPR gene editing",
        )
    with col_lim:
        limit = st.number_input("Max results", 10, 1000, 200, step=50)

    if query and len(query.strip()) >= 2:
        with st.spinner(f"Searching **{query}** …"):
            results = search_patents_fts(query.strip(), int(limit))

        if results.empty:
            st.warning(f"No patents found for **'{query}'**.")
            st.markdown("**Tips:** Try shorter terms, check spelling, use single concepts.")
        else:
            st.success(f" {len(results):,} results (capped at {limit})")

            # Result KPIs
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Results", f"{len(results):,}")
            if "year" in results.columns and results["year"].notna().any():
                k2.metric("Year Range",
                          f"{int(results['year'].min())} – {int(results['year'].max())}")
            if "num_claims" in results.columns:
                k3.metric("Avg Claims", f"{results['num_claims'].mean():.1f}")
            if "grant_lag_days" in results.columns:
                avg_lag = results["grant_lag_days"].dropna().mean()
                k4.metric("Avg Grant Lag",
                          f"{avg_lag/365.25:.1f} yrs" if pd.notna(avg_lag) else "N/A")

            # Year distribution
            if "year" in results.columns:
                yr_dist = (results.dropna(subset=["year"])["year"]
                           .astype(int).value_counts().sort_index().reset_index())
                yr_dist.columns = ["year", "count"]
                fig = px.bar(yr_dist, x="year", y="count",
                             color_discrete_sequence=["#1f77b4"],
                             labels={"year": "Year", "count": "Matching Patents"},
                             title=f'"{query}" — results by year')
                fig.update_layout(height=260, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)

            # Results table
            disp = [c for c in ["patent_id","title","year","patent_type",
                                 "num_claims","grant_lag_days","filing_date"]
                    if c in results.columns]
            st.dataframe(results[disp], use_container_width=True, height=400)

            # Abstract reader
            with st.expander(":page_facing_up: Read Abstracts (first 10)"):
                for _, row in results.head(10).iterrows():
                    st.markdown(f"**[{row.get('patent_id','')}]**  {row.get('title','')}")
                    st.caption(row.get("abstract", "No abstract available."))
                    st.markdown("---")

            # Download
            st.download_button(
                ":inbox_tray: Download results as CSV",
                results.to_csv(index=False).encode("utf-8"),
                file_name=f"search_{query.replace(' ','_')[:40]}.csv",
                mime="text/csv",
            )

    elif query:
        st.info("Enter at least 2 characters to search.")
    else:
        st.markdown("### :bulb: Example searches")
        ex_cols = st.columns(4)
        for col, ex in zip(ex_cols, ["quantum computing", "CRISPR", "autonomous vehicle",
                                      "machine learning"]):
            col.code(ex)


# ── Footer ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"**Patent Intelligence Dashboard** · Data: USPTO PatentsView · "
    f"Reports directory: `{REPORT_DIR}`"
)