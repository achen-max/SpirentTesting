import time
import sys
import os
from StcPython import StcPython

# --- HELPER FUNCTION FOR LOGGING ---
# Telegraf reads STDOUT. All regular text must go to STDERR.
def log(msg):
    print(msg, file=sys.stderr, flush=True)

# --- CONFIGURATION ---
CHASSIS_IP = "192.168.0.100" 
PORT1_LOC = f"//{CHASSIS_IP}/1/1" 
PORT2_LOC = f"//{CHASSIS_IP}/1/2" 

TCC_FILE = "tcc_configs/slipring_continuous.tcc" 

# --- THRESHOLDS ---
THRESH_MAX_LATENCY_NS = 5000000   
THRESH_JITTER_NS = 1000000        
THRESH_PRBS_ERRORS = 0            
THRESH_SPEED_BPS = 980000000      

VERBOSE = True 
# ---------------------

stc = StcPython()

log("Loading Configuration...")
stc.perform("LoadFromDatabaseCommand", DatabaseConnectionString=TCC_FILE)

log(f"Connecting to Chassis {CHASSIS_IP}...")
stc.connect(CHASSIS_IP)

log("Reserving Ports and Mapping...")
stc.reserve([PORT1_LOC, PORT2_LOC])
stc.perform("SetupPortMappingsCommand")
stc.apply()

project = stc.get("system1", "children-Project")

stc.perform('ResultsSubscribe', Parent=project, ConfigType='Generator', ResultType='GeneratorPortResults')
stc.perform('ResultsSubscribe', Parent=project, ConfigType='Analyzer', ResultType='AnalyzerPortResults')

ports = stc.get(project, "children-Port").split()
port1_handle = [p for p in ports if stc.get(p, 'Location') == PORT1_LOC][0]
port2_handle = [p for p in ports if stc.get(p, 'Location') == PORT2_LOC][0]

gen1 = stc.get(port1_handle, "children-Generator")
gen2 = stc.get(port2_handle, "children-Generator")
analyzer1 = stc.get(port1_handle, "children-Analyzer")
analyzer2 = stc.get(port2_handle, "children-Analyzer")

tx1_res = stc.get(gen1, "children-GeneratorPortResults") if gen1 else None
tx2_res = stc.get(gen2, "children-GeneratorPortResults") if gen2 else None
rx1_res = stc.get(analyzer1, "children-AnalyzerPortResults") if analyzer1 else None
rx2_res = stc.get(analyzer2, "children-AnalyzerPortResults") if analyzer2 else None

log("\n==================================================")
log("VERIFYING LOADED TRAFFIC PATTERNS FROM TCC FILE")
log("==================================================")
streamblocks = stc.get(port1_handle, "children-StreamBlock").split() + stc.get(port2_handle, "children-StreamBlock").split()

for sb in streamblocks:
    if sb:
        sb_name = stc.get(sb, "Name")
        len_mode = stc.get(sb, "FrameLengthMode")
        
        try:
            if len_mode == "FIXED":
                frame_size = stc.get(sb, "FixedFrameLength")
                size_str = f"{frame_size} Bytes"
            else:
                min_len = stc.get(sb, "MinFrameLength")
                max_len = stc.get(sb, "MaxFrameLength")
                size_str = f"{min_len}-{max_len} Bytes"
        except Exception as e:
            size_str = f"Unknown ({e})"
            
        log(f"Stream Block: '{sb_name}' | Mode: {len_mode} | Size: {size_str}")

for i, gen_handle in enumerate([gen1, gen2], start=1):
    if gen_handle:
        gen_config_list = stc.get(gen_handle, "children-GeneratorConfig").split()
        if gen_config_list:
            g_cfg = gen_config_list[0]
            try:
                dur_mode = stc.get(g_cfg, "DurationMode")
                load = stc.get(g_cfg, "FixedLoad")
                load_unit = stc.get(g_cfg, "LoadUnit")
                dur_val = stc.get(g_cfg, "Duration") if dur_mode != "CONTINUOUS" else "N/A"
                
                try:
                    frame_count = stc.get(g_cfg, "BurstSize")
                except Exception:
                    frame_count = "N/A"
                
                log(f"Port {i} Generator: {dur_mode} | Load: {load} {load_unit} | Duration: {dur_val} | Frame Count: {frame_count}")
            except Exception as e:
                log(f"Port {i} Generator Config Error: {e}")

log("==================================================\n")

generators = " ".join(filter(None, [gen1, gen2]))
analyzers = " ".join(filter(None, [analyzer1, analyzer2]))

log("Starting Analyzers...")
stc.perform("AnalyzerStartCommand", analyzerList=analyzers)
log("Starting Generators...")
stc.perform("GeneratorStartCommand", generatorList=generators)
log("Traffic Started. Entering Test Loop...")

iteration = 0
prev_fcs1, prev_fcs2 = 0, 0
prev_drops1, prev_drops2 = 0, 0
prev_prbs1, prev_prbs2 = 0, 0

try:
    while True:
        iteration += 1
        time.sleep(1) 
        
        p1_online = stc.get(port1_handle, 'Online').lower() == 'true'
        p2_online = stc.get(port2_handle, 'Online').lower() == 'true'
        
        # --- READ PORT 1 ---
        p1_tx = int(stc.get(tx1_res, 'GeneratorBitRate')) if tx1_res else 0
        p1_rx = int(stc.get(rx1_res, 'L1BitRate')) if rx1_res else 0
        
        cumul_drops1 = int(stc.get(rx1_res, 'OutSeqFrameCount')) if rx1_res else 0
        p1_drops_iter = cumul_drops1 - prev_drops1
        prev_drops1 = cumul_drops1
        
        cumul_fcs1 = int(stc.get(rx1_res, 'FcsErrorFrameCount')) if rx1_res else 0
        p1_fcs_iter = cumul_fcs1 - prev_fcs1
        prev_fcs1 = cumul_fcs1
        
        p1_max_lat = int(stc.get(rx1_res, 'MaxLatency')) if rx1_res else 0
        p1_min_lat = int(stc.get(rx1_res, 'MinLatency')) if rx1_res else 0
        p1_jitter = max(0, p1_max_lat - p1_min_lat)
        
        cumul_prbs1 = int(stc.get(rx1_res, 'PrbsBitErrorCount')) if rx1_res else 0
        p1_prbs_iter = cumul_prbs1 - prev_prbs1
        prev_prbs1 = cumul_prbs1
        
        # --- READ PORT 2 ---
        p2_tx = int(stc.get(tx2_res, 'GeneratorBitRate')) if tx2_res else 0
        p2_rx = int(stc.get(rx2_res, 'L1BitRate')) if rx2_res else 0
        
        cumul_drops2 = int(stc.get(rx2_res, 'OutSeqFrameCount')) if rx2_res else 0
        p2_drops_iter = cumul_drops2 - prev_drops2
        prev_drops2 = cumul_drops2
        
        cumul_fcs2 = int(stc.get(rx2_res, 'FcsErrorFrameCount')) if rx2_res else 0
        p2_fcs_iter = cumul_fcs2 - prev_fcs2
        prev_fcs2 = cumul_fcs2
        
        p2_max_lat = int(stc.get(rx2_res, 'MaxLatency')) if rx2_res else 0
        p2_min_lat = int(stc.get(rx2_res, 'MinLatency')) if rx2_res else 0
        p2_jitter = max(0, p2_max_lat - p2_min_lat)
        
        cumul_prbs2 = int(stc.get(rx2_res, 'PrbsBitErrorCount')) if rx2_res else 0
        p2_prbs_iter = cumul_prbs2 - prev_prbs2
        prev_prbs2 = cumul_prbs2
        
        # --- VERBOSE STATE EVALUATIONS ---
        fail_reason = None

        if not p1_online or not p2_online:
            fail_reason = "DISCONNECTED"
        elif p1_fcs_iter > 0 or p2_fcs_iter > 0:
            fail_reason = "FCS_ERRORS"
        elif p1_drops_iter > 0 or p2_drops_iter > 0:
            fail_reason = "OUT_OF_SEQUENCE"
        elif p1_max_lat > THRESH_MAX_LATENCY_NS or p2_max_lat > THRESH_MAX_LATENCY_NS:
            fail_reason = "HIGH_LATENCY"
        elif p1_jitter > THRESH_JITTER_NS or p2_jitter > THRESH_JITTER_NS:
            fail_reason = "HIGH_JITTER"
        elif p1_prbs_iter > THRESH_PRBS_ERRORS or p2_prbs_iter > THRESH_PRBS_ERRORS:
            fail_reason = "PRBS_BIT_ERRORS"
        elif p1_tx < THRESH_SPEED_BPS or p2_tx < THRESH_SPEED_BPS or p1_rx < THRESH_SPEED_BPS or p2_rx < THRESH_SPEED_BPS:
            fail_reason = "SPEED_DROP"

        if fail_reason:
            status = f"FAIL_{fail_reason}" if VERBOSE else "FAIL"
        else:
            status = "PASS"

        # --- TELEGRAF INFLUXDB LINE PROTOCOL OUTPUT ---
        # Format: measurement,tags fields (printing to standard out)
        
        # Port 1 Metrics
        print(f'spirent_metrics,port=1 status="{status}" tx_bps={p1_tx},rx_bps={p1_rx},drops={p1_drops_iter},fcs={p1_fcs_iter},max_lat_ns={p1_max_lat},jitter_ns={p1_jitter},prbs={p1_prbs_iter},iteration={iteration}', flush=True)
        
        # Port 2 Metrics
        print(f'spirent_metrics,port=2 status="{status}" tx_bps={p2_tx},rx_bps={p2_rx},drops={p2_drops_iter},fcs={p2_fcs_iter},max_lat_ns={p2_max_lat},jitter_ns={p2_jitter},prbs={p2_prbs_iter},iteration={iteration}', flush=True)
        
        # Print a small visual heartbeat to STDERR for the local terminal
        log(f"[Iter {iteration}] === {status.replace('_', ' ')} ===")
        
except KeyboardInterrupt:
    log("\nStopping Test...")
finally:
    stc.perform("GeneratorStopCommand", generatorList=generators)
    stc.perform("AnalyzerStopCommand", analyzerList=analyzers)
    log("Releasing Ports and Disconnecting...")
    stc.release([PORT1_LOC, PORT2_LOC])
    stc.disconnect(CHASSIS_IP)
    log("Test Complete.")