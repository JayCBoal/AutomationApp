import sys
from pathlib import Path

print("DEBUG: 1. Script started and imports/path setup beginning...", flush=True)

# --- Robust Project Root Path Resolver (Mandatory Test Header) ---
def find_project_root(current_path: Path) -> Path:
    for parent in [current_path] + list(current_path.parents):
        if (parent / "engine").is_dir() and (parent / "app").is_dir():
            return parent
    return current_path.parents[2]

ROOT_DIR = find_project_root(Path(__file__).resolve())
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

print(f"DEBUG: 2. Root directory resolved to: {ROOT_DIR}", flush=True)

# --- Test Imports & Logic ---
import os
import shutil
import json
from engine.telemetry_client import LocalSpoolTelemetryClient
from engine.handlers.file_handler import FileOpHandler

print("DEBUG: 3. Imports successful. Defining test function...", flush=True)

def test_file_handler_execution():
    print("DEBUG: 4. Entering test_file_handler_execution()...", flush=True)
    
    # Setup isolated test workspace
    workspace = Path("./test_workspace")
    source_dir = workspace / "source"
    dest_dir = workspace / "dest"
    spool_dir = workspace / "spool"
    
    for d in [source_dir, dest_dir, spool_dir]:
        d.mkdir(parents=True, exist_ok=True)
        
    print("DEBUG: 5. Workspace directories created.", flush=True)
        
    # Create dummy source files for glob matching
    (source_dir / "data_alpha.csv").write_text("id,val\n1,alpha")
    (source_dir / "data_beta.csv").write_text("id,val\n2,beta")
    
    print("DEBUG: 6. Dummy source files created in:", source_dir, flush=True)
    
    # Define step configuration dictionary
    step_config = {
        "StepID": 201,
        "StepType": "COPY_FILES"
    }
    
    # Define resolved parameters supporting glob pattern matching
    resolved_params = {
        "Source": str(source_dir / "*.csv"),
        "Dest": str(dest_dir),
        "Move": "False",
        "CreateFolder": "True"
    }
    
    instance_id = 88888
    
    print("DEBUG: 7. Entering LocalSpoolTelemetryClient context...", flush=True)
    try:
        with LocalSpoolTelemetryClient(spool_dir=str(spool_dir), instance_id=instance_id) as telemetry:
            print("DEBUG: 8. Telemetry client active. Initializing FileOpHandler...", flush=True)
            handler = FileOpHandler(step_config=step_config, telemetry_client=telemetry)
            print("DEBUG: 9. Running handler...", flush=True)
            result = handler.run(resolved_params)
            print("DEBUG: 10. Handler execution finished successfully.", flush=True)
    except Exception as e:
        print(f"CRITICAL EXCEPTION INSIDE TELEMETRY CONTEXT: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise e
        
    print("\n--- Handler Execution Result ---")
    print(f"Status: {result['status']}")
    print(f"Execution Time: {result['execution_time_ms']} ms")
    print(json.dumps(result["result"], indent=2))
    
    # Verify file transfer results in destination directory
    copied_files = list(dest_dir.glob("*.csv"))
    print(f"\nFiles found in destination ({dest_dir}): {[f.name for f in copied_files]}")
    assert len(copied_files) == 2, "Expected exactly 2 copied files!"
    
    # Verify telemetry spool finalization
    completed_spools = list(spool_dir.glob("*.jsonl"))
    print(f"Completed telemetry spool files (.jsonl): {[f.name for f in completed_spools]}")
    
    if completed_spools:
        print("\n--- Spooled Telemetry Content ---")
        with open(completed_spools[0], "r") as f:
            for line in f:
                print(json.dumps(json.loads(line), indent=2))
                
    # Cleanup test workspace
    shutil.rmtree(workspace)
    print("\nFile Handler & Telemetry test completed successfully!")

if __name__ == "__main__":
    print("DEBUG: Main block reached. Calling test function...", flush=True)
    try:
        test_file_handler_execution()
    except Exception as e:
        print(f"FATAL ERROR AT TOP LEVEL: {e}", flush=True)
        import traceback
        traceback.print_exc()