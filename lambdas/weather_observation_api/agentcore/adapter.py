from joblib import load
import os

class DummyModel:
    def predict(self, X):
        return {"prediction": 0.5}

class ModelAdapter:
    def load(self, model_name):
        mode = os.environ.get("INFERENCE_MODE", "MOCK")

        if mode == "MOCK":
            return DummyModel()

        # REAL モード（本番モデル）
        model_path = f"/opt/models/{model_name}.joblib"
        return load(model_path)