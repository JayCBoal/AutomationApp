import json
from pathlib import Path
from engine.telemetry_client import TelemetryClient

# 1. Initialize client with temporary test spool directory
spool_dir = Path("./test_spool")
instance_id = 99999

print("Testing TelemetryClient spool creation...")
with TelemetryClient(spool_dir=str(spool_dir), instance_id=instance_id) as client:
    # Emulate an Operation log
    client.log_operation(
        op_type="FILE_COPY",
        step_id=101,
        status="SUCCESS",
        execution_time_ms=12,
        source_path="/tmp/source",
        source_filename="data.csv",
        dest_path="/tmp/dest",
        dest_filename="data.csv",
        bytes_transferred=2048,
        details={"checksum": "a1b2c3d4"}
    )
    
    # Emulate an Audit log
    client.log_audit(
        action="STEP_EXECUTION_FAILURE",
        actor="Runner_PID_1234",
        resource_type="JobStep",
        resource_id="102",
        status="FAILED",
        details={"error": "Permission denied"}
    )

    # Check that active .tmp files exist during context execution
    tmp_files = list(spool_dir.glob("*.tmp"))
    print(f"Active .tmp files created: {[f.name for f in tmp_files]}")

# 2. After exiting context manager, verify atomic rename to .jsonl
completed_files = list(spool_dir.glob("*.jsonl"))
print(f"Completed .jsonl files ready for ingestion: {[f.name for f in completed_files]}")

# 3. Read and print contents of completed spool files
for completed_file in completed_files:
    print(f"\n--- Contents of {completed_file.name} ---")
    with open(completed_file, "r") as f:
        for line in f:
            print(json.dumps(json.loads(line), indent=2))

# Cleanup test directory
import shutil
shutil.rmtree(spool_dir)
print("\nTelemetry test completed successfully!")