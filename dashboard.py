import streamlit as st
import pandas as pd
import time
import os

st.set_page_config(page_title="Advanced Slip Ring Monitor", layout="wide")
st.title("⚙️ 1000BASE-T1 Advanced Slip Ring Telemetry")

# --- SIDEBAR CONFIGURATION ---
st.sidebar.title("📋 Loaded Test Profile")
config_placeholder = st.sidebar.empty()

if os.path.exists("slipring_config.csv"):
    try:
        df_cfg = pd.read_csv("slipring_config.csv")
        config_placeholder.dataframe(df_cfg.set_index("Parameter"), use_container_width=True)
    except Exception:
        pass
# -----------------------------

# Primary Metrics Grid
col1, col2, col3, col4 = st.columns(4)
iter_placeholder = col1.empty()
status_placeholder = col2.empty()
fcs_placeholder = col3.empty()
drops_placeholder = col4.empty()

# Secondary Physical Layer Grid
st.markdown("### 🔍 Live Physical Layer Integrity Indicators")
subcol1, subcol2, subcol3 = st.columns(3)
lat_placeholder = subcol1.empty()
jit_placeholder = subcol2.empty()
prbs_placeholder = subcol3.empty()

st.markdown("---")
st.subheader("📊 Live Port Speeds (Mbps)")
speed_chart_placeholder = st.empty()

st.markdown("---")
st.subheader("💥 Live Transmission Errors & Spikes")
error_chart_placeholder = st.empty()

st.markdown("---")
st.subheader("⚠️ Recent Failure Log (Last 10 Events)")
log_placeholder = st.empty()

while True:
    try:
        # Read the latest telemetry entry from the shared CSV file
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
        fcs_placeholder.metric("FCS Errors (P1 / P2 This Iter)", f"{fcs_p1} / {fcs_p2}")
        
        drops_p1 = int(latest['P1_Drops_Iteration'])
        drops_p2 = int(latest['P2_Drops_Iteration'])
        drops_placeholder.metric("OutSeq Drops (P1 / P2 This Iter)", f"{drops_p1} / {drops_p2}")
        
        # 2. Guard and Scale Latency Metrics (Nanoseconds -> Microseconds)
        p1_rx_live = int(latest['P1_Rx_bps'])
        p2_rx_live = int(latest['P2_Rx_bps'])
        
        p1_lat_text = f"{float(latest['P1_MaxLat_ns']) / 1000:.1f} μs" if p1_rx_live > 0 else "N/A (No Rx)"
        p2_lat_text = f"{float(latest['P2_MaxLat_ns']) / 1000:.1f} μs" if p2_rx_live > 0 else "N/A (No Rx)"
        lat_placeholder.metric("Worst-Case Latency (P1 / P2)", f"{p1_lat_text} / {p2_lat_text}")
        
        p1_jit_text = f"{float(latest['P1_Jitter_ns']) / 1000:.1f} μs" if p1_rx_live > 0 else "N/A (No Rx)"
        p2_jit_text = f"{float(latest['P2_Jitter_ns']) / 1000:.1f} μs" if p2_rx_live > 0 else "N/A (No Rx)"
        jit_placeholder.metric("Latency Jitter Spread", f"{p1_jit_text} / {p2_jit_text}")
        
        prbs_p1 = int(latest['P1_PRBS_Iteration'])
        prbs_p2 = int(latest['P2_PRBS_Iteration'])
        prbs_placeholder.metric("PRBS Payload Bit Errors", f"{prbs_p1} / {prbs_p2}")
        
        # 3. Process & Graph Throughput Speeds (bps -> Mbps)
        chart_df = df.tail(60).copy()
        chart_df['P1_Tx_Mbps'] = chart_df['P1_Tx_bps'] / 1000000
        chart_df['P1_Rx_Mbps'] = chart_df['P1_Rx_bps'] / 1000000
        chart_df['P2_Tx_Mbps'] = chart_df['P2_Tx_bps'] / 1000000
        chart_df['P2_Rx_Mbps'] = chart_df['P2_Rx_bps'] / 1000000
        
        speed_data = chart_df[['Iteration', 'P1_Tx_Mbps', 'P1_Rx_Mbps', 'P2_Tx_Mbps', 'P2_Rx_Mbps']].set_index('Iteration')
        speed_chart_placeholder.line_chart(speed_data)
        
        # 4. Process & Graph Error Spikes
        error_cols = ['P1_Drops_Iteration', 'P1_FCS_Iteration', 'P1_PRBS_Iteration', 'P2_Drops_Iteration', 'P2_FCS_Iteration', 'P2_PRBS_Iteration']
        error_data = chart_df[['Iteration'] + error_cols].set_index('Iteration')
        error_chart_placeholder.line_chart(error_data)
        
        # 5. Compile Recent Failure Audit Log
        fail_cols = ['Iteration', 'Timestamp', 'Status', 'P1_Drops_Iteration', 'P1_FCS_Iteration', 'P1_PRBS_Iteration', 'P2_Drops_Iteration', 'P2_FCS_Iteration', 'P2_PRBS_Iteration']
        fail_df = df[df['Status'] != 'PASS'].tail(10)[fail_cols]
        
        if not fail_df.empty:
            log_placeholder.dataframe(fail_df.reset_index(drop=True), use_container_width=True)
        else:
            log_placeholder.info("All parameters nominal. Copper brush contact interface is completely stable! ✨")
            
    except FileNotFoundError:
        st.info("Awaiting file cache pipeline sync...")
    except Exception as e:
        pass
        
    time.sleep(1)