import streamlit as st
import pandas as pd
import time
import os

st.set_page_config(page_title="Advanced Slip Ring Monitor", layout="wide")
st.title("⚙️ 1000BASE-T1 Advanced Slip Ring Telemetry")

# --- SIDEBAR CONFIGURATION ---
st.sidebar.title("📋 Loaded Test Profile")
config_placeholder = st.sidebar.empty()

st.sidebar.markdown("---")
st.sidebar.title("🚦 Live Traffic Stats")
traffic_placeholder = st.sidebar.empty()

if os.path.exists("slipring_config.csv"):
    try:
        df_cfg = pd.read_csv("slipring_config.csv")
        config_placeholder.dataframe(df_cfg.set_index("Parameter"), use_container_width=True)
    except Exception:
        pass
# -----------------------------

# --- TOP LIVE METRICS ---
st.markdown("### 🔍 Live Test Status")
col1, col2, col3, col4 = st.columns(4)
iter_placeholder = col1.empty()
status_placeholder = col2.empty()
fcs_placeholder = col3.empty()
drops_placeholder = col4.empty()

# --- PORT 1 & PORT 2 CHARTS ---
st.markdown("---")
col_p1, col_p2 = st.columns(2)

with col_p1:
    st.subheader("🔵 Port 1 Live Speeds (Mbps)")
    p1_speed_chart = st.empty()
    st.subheader("🔵 Port 1 Latency (μs)")
    p1_lat_chart = st.empty()

with col_p2:
    st.subheader("🟢 Port 2 Live Speeds (Mbps)")
    p2_speed_chart = st.empty()
    st.subheader("🟢 Port 2 Latency (μs)")
    p2_lat_chart = st.empty()

# --- ERROR HISTORY ---
st.markdown("---")
st.subheader("💥 Error History (Spikes)")
st.caption("Bar chart of recent transmission errors. Hover to view Iteration and Time.")
error_chart_placeholder = st.empty()

# --- FAILURE LOG ---
st.markdown("---")
st.subheader("⚠️ Recent Failure Log (Last 10 Events)")
log_placeholder = st.empty()

# --- BACKGROUND TELEMETRY LOOP ---
while True:
    try:
        # Read the latest telemetry entry
        df = pd.read_csv("slipring_metrics.csv")
        latest = df.iloc[-1]
        
        # 1. Update Core Live Cards
        iter_placeholder.metric("Current Iteration", int(latest['Iteration']))
        
        current_status = str(latest['Status'])
        if current_status == "PASS":
            status_placeholder.success("✅ PASS")
        else:
            status_placeholder.error(f"❌ {current_status}")
            
        fcs_p1 = int(latest['P1_FCS_Iteration'])
        fcs_p2 = int(latest['P2_FCS_Iteration'])
        fcs_placeholder.metric("FCS Errors (P1 / P2)", f"{fcs_p1} / {fcs_p2}")
        
        drops_p1 = int(latest['P1_Drops_Iteration'])
        drops_p2 = int(latest['P2_Drops_Iteration'])
        drops_placeholder.metric("OutSeq Drops (P1 / P2)", f"{drops_p1} / {drops_p2}")

        # 2. Update Sidebar Traffic Stats (Aggregations)
        total_fcs = df['P1_FCS_Iteration'].sum() + df['P2_FCS_Iteration'].sum()
        total_prbs = df['P1_PRBS_Iteration'].sum() + df['P2_PRBS_Iteration'].sum()
        
        traffic_placeholder.markdown(f"""
        **Total Errors (This Session):**
        * **FCS Errors:** {total_fcs}
        * **PRBS Errors:** {total_prbs}
        
        **Latest Rx Check:**
        * **P1:** {int(latest['P1_Rx_bps'])/1000000:.2f} Mbps
        * **P2:** {int(latest['P2_Rx_bps'])/1000000:.2f} Mbps
        """)
        
        # 3. Chart Data Prep (Last 60 records)
        chart_df = df.tail(60).copy()
        
        # Combine Iteration and Timestamp for the X-Axis label
        if 'Timestamp' in chart_df.columns:
            chart_df['Iter_Time'] = chart_df['Iteration'].astype(str) + " | " + chart_df['Timestamp'].astype(str)
        else:
            chart_df['Iter_Time'] = chart_df['Iteration'].astype(str)
            
        chart_df = chart_df.set_index('Iter_Time')
        
        # Process Speeds (bps -> Mbps)
        chart_df['P1_Tx_Mbps'] = chart_df['P1_Tx_bps'] / 1000000
        chart_df['P1_Rx_Mbps'] = chart_df['P1_Rx_bps'] / 1000000
        chart_df['P2_Tx_Mbps'] = chart_df['P2_Tx_bps'] / 1000000
        chart_df['P2_Rx_Mbps'] = chart_df['P2_Rx_bps'] / 1000000
        
        p1_speed_chart.line_chart(chart_df[['P1_Tx_Mbps', 'P1_Rx_Mbps']])
        p2_speed_chart.line_chart(chart_df[['P2_Tx_Mbps', 'P2_Rx_Mbps']])
        
        # Process Latency (ns -> us)
        chart_df['P1_Lat_us'] = chart_df['P1_MaxLat_ns'] / 1000
        chart_df['P2_Lat_us'] = chart_df['P2_MaxLat_ns'] / 1000
        
        p1_lat_chart.line_chart(chart_df[['P1_Lat_us']])
        p2_lat_chart.line_chart(chart_df[['P2_Lat_us']])
        
        # Process Errors using a Bar Chart for clear visual spikes
        error_cols = ['P1_FCS_Iteration', 'P1_PRBS_Iteration', 'P2_FCS_Iteration', 'P2_PRBS_Iteration']
        error_chart_placeholder.bar_chart(chart_df[error_cols])
        
        # 4. Compile Recent Failure Audit Log
        fail_cols = ['Iteration', 'Timestamp', 'Status', 'P1_Drops_Iteration', 'P1_FCS_Iteration', 'P1_PRBS_Iteration', 'P2_Drops_Iteration', 'P2_FCS_Iteration', 'P2_PRBS_Iteration']
        # Guard in case Timestamp doesn't exist
        actual_cols = [c for c in fail_cols if c in df.columns] 
        
        fail_df = df[df['Status'] != 'PASS'].tail(10)[actual_cols]
        
        if not fail_df.empty:
            log_placeholder.dataframe(fail_df.reset_index(drop=True), use_container_width=True)
        else:
            log_placeholder.info("All parameters nominal. Copper brush contact interface is completely stable! ✨")
            
    except FileNotFoundError:
        st.info("Awaiting file cache pipeline sync...")
    except Exception as e:
        pass
        
    time.sleep(1)