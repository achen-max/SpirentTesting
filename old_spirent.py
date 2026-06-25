import time
import csv
import os
from StcPython import StcPython

# --- CONFIGURATION ---
CHASSIS_IP = "192.168.0.100" # IP address of Spirent machine
PORT1_LOC = f"//{CHASSIS_IP}/1/1" # to/from ports that we are using
PORT2_LOC = f"//{CHASSIS_IP}/1/2" 

TCC_FILE = "tcc_configs/slipring_continuous.tcc" # which Spirent test to set up (.tcc)
CSV_METRICS = "slipring_metrics.csv" # record all metrics to
CSV_FAILURES = "slipring_failures.csv" # record all failures (and three surrounding scenarios) to
CSV_CONFIG = "slipring_config.csv" # traffic type

# --- THRESHOLDS ---
# for comparison to determine FAIL
THRESH_MAX_LATENCY_NS = 5000000   
THRESH_JITTER_NS = 1000000        
THRESH_PRBS_ERRORS = 0            
THRESH_SPEED_BPS = 980000000      
THRESH_DUPLICATE_FRAMES = 0       # Added threshold for Step 2 tracking

VERBOSE = True # toggle off if you don't want to see for what reason it failed                     
# ---------------------

stc = StcPython()

print("Loading Configuration...")
stc.perform("LoadFromDatabaseCommand", DatabaseConnectionString=TCC_FILE)

print(f"Connecting to Chassis {CHASSIS_IP}...")
stc.connect(CHASSIS_IP)

print("Reserving Ports and Mapping...")
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

print("\n==================================================")
print("VERIFYING LOADED TRAFFIC PATTERNS FROM TCC FILE")
print("==================================================")
config_rows = []
streamblocks = stc.get(port1_handle, "children-StreamBlock").split() + stc.get(port2_handle, "children-StreamBlock").split()

for sb in streamblocks:
    if sb:
        sb_name = stc.get(sb, "Name")
        len_mode = stc.get(sb, "FrameLengthMode")
        
        # Safely fetch frame size depending on the mode
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
            
        print(f"Stream Block: '{sb_name}' | Mode: {len_mode} | Size: {size_str}")
        config_rows.append([f"Stream '{sb_name}' Size", size_str])

for i, gen_handle in enumerate([gen1, gen2], start=1):
    if gen_handle:
        gen_config_list = stc.get(gen_handle, "children-GeneratorConfig").split()
        if gen_config_list:
            g_cfg = gen_config_list[0]
            try:
                # Fetch core parameters
                dur_mode = stc.get(g_cfg, "DurationMode")
                load = stc.get(g_cfg, "FixedLoad")
                load_unit = stc.get(g_cfg, "LoadUnit")
                
                # Duration doesn't apply the same way if mode is CONTINUOUS
                dur_val = stc.get(g_cfg, "Duration") if dur_mode != "CONTINUOUS" else "N/A"
                
                # Isolate BurstSize (Frame Count) so it doesn't crash if unsupported
                try:
                    frame_count = stc.get(g_cfg, "BurstSize")
                except Exception:
                    frame_count = "N/A"
                
                # Updated Print Statement
                print(f"Port {i} Generator: {dur_mode} | Load: {load} {load_unit} | Duration: {dur_val} | Frame Count: {frame_count}")
                
                config_rows.append([f"Port {i} Duration Mode", dur_mode])
                config_rows.append([f"Port {i} Load", f"{load} {load_unit}"])
                config_rows.append([f"Port {i} Duration", dur_val])
                config_rows.append([f"Port {i} Frame Count (Burst Size)", frame_count])

            except Exception as e:
                print(f"Port {i} Generator Config Error: {e}")
                config_rows.append([f"Port {i} Config Error", str(e)])

with open(CSV_CONFIG, mode='w', newline='') as f_cfg:
    writer_cfg = csv.writer(f_cfg)
    writer_cfg.writerow(["Parameter", "Value"])
    writer_cfg.writerows(config_rows)
print("==================================================\n")

generators = " ".join(filter(None, [gen1, gen2]))
analyzers = " ".join(filter(None, [analyzer1, analyzer2]))

print("Starting Analyzers...")
stc.perform("AnalyzerStartCommand", analyzerList=analyzers)
print("Starting Generators...")
stc.perform("GeneratorStartCommand", generatorList=generators)
print("Traffic Started. Entering Test Loop...")

if not os.path.exists(CSV_FAILURES):
    with open(CSV_FAILURES, mode='w', newline='') as f_fail:
        writer_fail = csv.writer(f_fail)
        writer_fail.writerow([
            "Iteration", "Timestamp", 
            "P1_Tx_Mbps", "P1_Rx_Mbps", "P1_Drops_Iter", "P1_FCS_Iter", "P1_Dup_Iter", "P1_MaxLat_us", "P1_Jitter_us", "P1_PRBS_Iter", 
            "P2_Tx_Mbps", "P2_Rx_Mbps", "P2_Drops_Iter", "P2_FCS_Iter", "P2_Dup_Iter", "P2_MaxLat_us", "P2_Jitter_us", "P2_PRBS_Iter", 
            "Reason"
        ])

iteration = 0
prev_fcs1, prev_fcs2 = 0, 0
prev_drops1, prev_drops2 = 0, 0
prev_prbs1, prev_prbs2 = 0, 0
prev_dup1, prev_dup2 = 0, 0 # Track previous duplicate states

with open(CSV_METRICS, mode='w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow([
        "Iteration", "Timestamp", 
        "P1_Tx_bps", "P1_Rx_bps", "P1_Drops_Iteration", "P1_FCS_Iteration", "P1_Dup_Iteration", "P1_MaxLat_ns", "P1_Jitter_ns", "P1_PRBS_Iteration",
        "P2_Tx_bps", "P2_Rx_bps", "P2_Drops_Iteration", "P2_FCS_Iteration", "P2_Dup_Iteration", "P2_MaxLat_ns", "P2_Jitter_ns", "P2_PRBS_Iteration",
        "Status"
    ])
    
    try:
        while True:
            iteration += 1
            time.sleep(1) 
            
            p1_online = stc.get(port1_handle, 'Online').lower() == 'true'
            p2_online = stc.get(port2_handle, 'Online').lower() == 'true'
            
            # --- READ PORT 1 ---
            p1_tx = int(stc.get(tx1_res, 'GeneratorBitRate')) if tx1_res else 0
            p1_rx = int(stc.get(rx1_res, 'L1BitRate')) if rx1_res else 0
            
            # OutSeqFrameCount acts as sequence errors / drops tracker
            cumul_drops1 = int(stc.get(rx1_res, 'OutSeqFrameCount')) if rx1_res else 0
            p1_drops_iter = cumul_drops1 - prev_drops1
            prev_drops1 = cumul_drops1
            
            cumul_fcs1 = int(stc.get(rx1_res, 'FcsErrorFrameCount')) if rx1_res else 0
            p1_fcs_iter = cumul_fcs1 - prev_fcs1
            prev_fcs1 = cumul_fcs1

            # Fetch Duplicate Frame Tracking (Step 2 Implementation)
            cumul_dup1 = int(stc.get(rx1_res, 'DuplicateFrameCount')) if rx1_res else 0
            p1_dup_iter = cumul_dup1 - prev_dup1
            prev_dup1 = cumul_dup1
            
            p1_max_lat = int(stc.get(rx1_res, 'MaxLatency')) if rx1_res else 0
            p1_min_lat = int(stc.get(rx1_res, 'MinLatency')) if rx1_res else 0
            p1_jitter = max(0, p1_max_lat - p1_min_lat)
            
            # Contact noise / PRBS
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

            # Fetch Duplicate Frame Tracking (Step 2 Implementation)
            cumul_dup2 = int(stc.get(rx2_res, 'DuplicateFrameCount')) if rx2_res else 0
            p2_dup_iter = cumul_dup2 - prev_dup2
            prev_dup2 = cumul_dup2
            
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
                fail_reason = "FCS ERRORS"
            elif p1_drops_iter > 0 or p2_drops_iter > 0:
                fail_reason = "OUT OF SEQUENCE (PACKET DROP)"
            elif p1_dup_iter > THRESH_DUPLICATE_FRAMES or p2_dup_iter > THRESH_DUPLICATE_FRAMES:
                fail_reason = "DUPLICATE FRAMES (TRAFFIC LOOP/REPLICATION)"
            elif p1_max_lat > THRESH_MAX_LATENCY_NS or p2_max_lat > THRESH_MAX_LATENCY_NS:
                fail_reason = "HIGH LATENCY (BRUSH BOUNCE)"
            elif p1_jitter > THRESH_JITTER_NS or p2_jitter > THRESH_JITTER_NS:
                fail_reason = "HIGH JITTER (VIBRATION CHATTER)"
            elif p1_prbs_iter > THRESH_PRBS_ERRORS or p2_prbs_iter > THRESH_PRBS_ERRORS:
                fail_reason = "PRBS BIT ERRORS (CONTACT NOISE)"
            elif p1_tx < THRESH_SPEED_BPS or p2_tx < THRESH_SPEED_BPS or p1_rx < THRESH_SPEED_BPS or p2_rx < THRESH_SPEED_BPS:
                fail_reason = "SPEED DROP (BELOW THRESHOLD)"

            timestamp = time.strftime('%H:%M:%S')

            if fail_reason:
                status = f"FAIL ({fail_reason})" if VERBOSE else "FAIL"
                
                # Write immediately to the failure CSV
                with open(CSV_FAILURES, mode='a', newline='') as f_fail:
                    writer_fail = csv.writer(f_fail)
                    writer_fail.writerow([
                        iteration, timestamp,
                        p1_tx//1000000, p1_rx//1000000, p1_drops_iter, p1_fcs_iter, p1_dup_iter,
                        p1_max_lat/1000 if p1_rx > 0 else "N/A", p1_jitter/1000 if p1_rx > 0 else "N/A", p1_prbs_iter,
                        p2_tx//1000000, p2_rx//1000000, p2_drops_iter, p2_fcs_iter, p2_dup_iter,
                        p2_max_lat/1000 if p2_rx > 0 else "N/A", p2_jitter/1000 if p2_rx > 0 else "N/A", p2_prbs_iter,
                        fail_reason
                    ])
            else:
                status = "PASS"
                
            p1_lat_str = f"{p1_max_lat/1000:.1f}us" if p1_rx > 0 else "N/A"
            p2_lat_str = f"{p2_max_lat/1000:.1f}us" if p2_rx > 0 else "N/A"
            
            # Print Multi-line Tree using standard print (Now includes Dup strings)
            print(f"[Iter {iteration}] === {status} ===")
            print(f"  ├─ P1: Tx {p1_tx//1000000:>3}M | Rx {p1_rx//1000000:>3}M | Drp: {p1_drops_iter:<2} | FCS: {p1_fcs_iter:<2} | Dup: {p1_dup_iter:<2} | Lat: {p1_lat_str:>7} | PRBS: {p1_prbs_iter}")
            print(f"  └─ P2: Tx {p2_tx//1000000:>3}M | Rx {p2_rx//1000000:>3}M | Drp: {p2_drops_iter:<2} | FCS: {p2_fcs_iter:<2} | Dup: {p2_dup_iter:<2} | Lat: {p2_lat_str:>7} | PRBS: {p2_prbs_iter}")
            print("") # Blank line for readability
            
            # Write standard metrics every iteration
            writer.writerow([
                iteration, timestamp, 
                p1_tx, p1_rx, p1_drops_iter, p1_fcs_iter, p1_dup_iter, p1_max_lat, p1_jitter, p1_prbs_iter,
                p2_tx, p2_rx, p2_drops_iter, p2_fcs_iter, p2_dup_iter, p2_max_lat, p2_jitter, p2_prbs_iter,
                status
            ])
            f.flush()
            
    except KeyboardInterrupt:
        print("\nStopping Test...")
    finally:
        stc.perform("GeneratorStopCommand", generatorList=generators)
        stc.perform("AnalyzerStopCommand", analyzerList=analyzers)
        print("Releasing Ports and Disconnecting...")
        stc.release([PORT1_LOC, PORT2_LOC])
        stc.disconnect(CHASSIS_IP)
        print("Test Complete.")