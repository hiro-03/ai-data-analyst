import requests

class Preprocessor:
    def run(self, lat, lon, station_id):
        # 気象庁 API URL（例：アメダス）
        url = f"https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
        # 本番では station_id に応じた URL を組み立てる

        # 気象庁データ取得
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        jma_data = response.json()

        # 特徴量生成（例）
        features = {
            "lat": lat,
            "lon": lon,
            "station_id": station_id,
            "temperature": jma_data["temp"],
            "humidity": jma_data["humidity"],
            "wind": jma_data["wind"]
        }

        return features