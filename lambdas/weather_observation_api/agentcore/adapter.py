import pickle
import os

class ModelAdapter:
    def load(self, model_name):
        model_path = f"/opt/models/{model_name}.pkl"
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        return model