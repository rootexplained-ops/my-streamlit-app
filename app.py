import streamlit as st
import pandas as pd
import oracledb
# Enable thick mode for advanced connection features
oracledb.init_oracle_client()

# 1. Configuration
QUERIES = {
    "Status": """
        SELECT 
            d.name, 
            i.instance_name, 
            i.status,
            EXTRACT(DAY FROM (SYSTIMESTAMP - CAST(i.startup_time AS TIMESTAMP))) || 'd ' ||
            EXTRACT(HOUR FROM (SYSTIMESTAMP - CAST(i.startup_time AS TIMESTAMP))) || 'h' 
            AS precise_uptime
        FROM v$database d, v$instance i
    """,
    "Blocking": """
        SELECT sid, blocking_session, wait_class, seconds_in_wait 
        FROM v$session WHERE blocking_session IS NOT NULL
    """,
    "Backups": """
        SELECT status, start_time, end_time FROM v$rman_status 
        WHERE operation = 'BACKUP' AND object_type = 'DB FULL'
        ORDER BY start_time DESC FETCH FIRST 5 ROWS ONLY
    """,
    "Long_Running": """
        SELECT sid, serial#, username, osuser, program, 
               last_call_et AS duration_sec, sql_id
        FROM v$session 
        WHERE status = 'ACTIVE' 
          AND type = 'USER'
          AND last_call_et > 600  -- Running for more than 10 minutes
        ORDER BY last_call_et DESC
    """,
    
    "Inactive_Sessions": """
        SELECT sid, serial#, username, status, last_call_et/3600 AS idle_hours, 
               program, machine
        FROM v$session 
        WHERE status = 'INACTIVE' 
          AND type = 'USER'
          AND last_call_et > 3600 -- Idle for more than 1 hour
        ORDER BY last_call_et DESC
    """,
    "Tablespaces": """
        SELECT tablespace_name, 
               round(used_space * 8192 / 1024 / 1024 /1024, 2) as used_gb,
               round(tablespace_size * 8192 / 1024 / 1024 /1024, 2) as max_gb,
               round(used_percent, 2) as pct_used
        FROM dba_tablespace_usage_metrics
        ORDER BY used_percent DESC
    """,
    
    "Invalid_Objects": """
        SELECT owner, object_type, object_name, status
        FROM dba_objects
        WHERE status = 'INVALID'
        ORDER BY owner, object_type
    """
}

st.markdown(
    """
    <style>
    .stApp [data-testid="stHeader"] {
        padding-top: 10px; /* Reduce space above header */
        padding-bottom: 10px; /* Reduce space below header */
    }
    .stApp [data-testid="stMarkdownContainer"] h1 {
        margin-top: 0rem;    /* Remove top margin of the H1 tag */
        margin-bottom: 0rem; /* Remove bottom margin of the H1 tag */
        padding-top: 0rem;
        padding-bottom: 0rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.set_page_config(page_title="Oracle Health 2026", layout="wide")
st.title("🛡️ Database Health Monitor") 



# Initialize Connection
conn = st.connection("sql")

# 2. Fragment for Live Refresh (Every 60 seconds)
@st.fragment(run_every="60s")
def render_dashboard():
    # Helper to fetch and normalize column names to lowercase
    def get_data(key):
        df = conn.query(QUERIES[key], ttl=0) # ttl=0 ensures fresh data inside fragment
        df.columns = [c.lower() for c in df.columns]
        return df

    # Data Retrieval
    status_df = get_data("Status")
    blocking_df = get_data("Blocking")
    backups_df = get_data("Backups")
    long_run_df = get_data("Long_Running")
    inactive_df = get_data("Inactive_Sessions")
    ts_df = get_data("Tablespaces")
    invalid_df = get_data("Invalid_Objects")

    # 3. Metrics Row
    if not status_df.empty:
        c1, c2, c3 = st.columns(3)
        # Using lowercase keys because of our normalization helper
        c1.metric("Database", status_df['name'].iloc[0])
        
        db_status = status_df['status'].iloc[0]
        c2.metric("Status", db_status, 
                  delta="Healthy" if db_status == 'OPEN' else "Check Instance",
                  delta_color="normal" if db_status == 'OPEN' else "inverse")
        
        c3.metric("Precise Uptime", status_df['precise_uptime'].iloc[0])
    
    st.divider()

    # 4. Interactive Tabs
    t1, t2, t3, t4, t5, t6 = st.tabs([
        "🔴 Blocking", "💾 Backups", "⏳ Long Running", 
        "💤 Inactive", "📊 Tablespaces", "❌ Invalid Objects"
    ])

    
    with t1:
        if blocking_df.empty:
            st.success("No blocking sessions detected.")
        else:
            st.warning(f"Detected {len(blocking_df)} blocking sessions!")
            st.dataframe(blocking_df, use_container_width=True)

    with t2:
        if not backups_df.empty:
            st.dataframe(backups_df, use_container_width=True)
        else:
            st.info("No recent backup history found.")
    
    with t3:
        st.subheader("Active Sessions > 10 Minutes")
        if long_run_df.empty:
            st.success("No long-running active sessions.")
        else:
            st.warning(f"Found {len(long_run_df)} sessions running for a long time.")
            st.dataframe(long_run_df, use_container_width=True)

    with t4:
        st.subheader("Inactive Sessions > 1 Hour")
        if inactive_df.empty:
            st.success("No excessively idle sessions.")
        else:
            st.info(f"Monitoring {len(inactive_df)} inactive sessions.")
            st.dataframe(inactive_df, use_container_width=True)

    with t5:
        st.subheader("Tablespace Utilization")
        # Apply number formatting here
        st.dataframe(
          ts_df.style
            .highlight_between(
                subset=['pct_used'], left=85, right=100, color='#ff4b4b44'
            )
            .format({
                # Format pct_used to exactly 2 decimal places in the display
                'pct_used': "{:.2f}",
                # You can also format the MB columns for better readability
                'used_gb': "{:,.2f}", 
                'max_gb': "{:,.2f}"
            }),
        use_container_width=True
    )

    with t6:
        st.subheader("Broken Database Objects")
        if invalid_df.empty:
            st.success("All schema objects are VALID.")
        else:
            st.error(f"Found {len(invalid_df)} invalid objects!")
            st.dataframe(invalid_df, use_container_width=True)
            st.info("💡 Run 'utlrp.sql' as SYS to recompile these objects.")

# Execute the fragment

render_dashboard()

