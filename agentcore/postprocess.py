# agentcore/postprocess.py
import time
import json

def emit_emf(trace_id, station_id, model_version, api_stage, latency_ms, confidence, payload_size, status):
    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "WeatherInference",
                    "Dimensions": [["trace_id", "station_id", "model_version", "api_stage"]],
                    "Metrics": [
                        {"Name": "inference_latency_ms", "Unit": "Milliseconds"},
                        {"Name": "confidence", "Unit": "None"},
                        {"Name": "payload_size_bytes", "Unit": "Bytes"}
                    ]
                }
            ]
        },
        "trace_id": trace_id,
        "station_id": station_id,
        "model_version": model_version,
        "api_stage": api_stage,
        "inference_latency_ms": latency_ms,
        "confidence": confidence,
        "payload_size_bytes": payload_size,
        "status": status
    }

    print(json.dumps(emf))
    return emf