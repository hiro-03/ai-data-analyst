from datetime import datetime, timezone

class Postprocessor:
    def run(self, raw_output):
        return {
            "prediction": raw_output["prediction"],
            "confidence": raw_output.get("confidence", 0.9),
            "model_version": raw_output.get("model_version", "1.0.0"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }