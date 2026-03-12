class InferenceEngine:
    def __init__(self, model):
        self.model = model

    def run(self, features):
        return self.model.predict(features)