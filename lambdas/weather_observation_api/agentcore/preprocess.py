import requests
from datetime import datetime

class Preprocessor:
    def run(self, lat, lon, station_id):
        # 1. 最新時刻（ISO8601）を取得
        latest_time_url = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
        latest_time_resp = requests.get(latest_time_url, timeout=3)
        latest_time_resp.raise_for_status()
        iso_time = latest_time_resp.text.strip()

        # 2. 時刻フォーマットを変換（秒まで含めた14桁が必要）
        # 例: 2026-03-18T00:30:00+09:00 -> 20260318003000
        dt = datetime.fromisoformat(iso_time)
        amedas_time = dt.strftime("%Y%m%d%H%M%S")

        # 3. 全観測所データが含まれる「map」URLへリクエスト
        # このJSONに全ステーションのデータが格納されています
        map_url = f"https://www.jma.go.jp/bosai/amedas/data/map/{amedas_time}.json"

        map_resp = requests.get(map_url, timeout=3)
        map_resp.raise_for_status()
        all_obs = map_resp.json()

        # 4. 指定した station_id のデータを抽出
        # station_id が存在しない場合に備えて .get() を使用
        obs = all_obs.get(station_id)

        if not obs:
            raise ValueError(f"Station ID {station_id} not found in the latest data.")

        # 特徴量の整理
        # 気象庁のデータ構造に合わせて、インデックス [0] で値を取得
        features = {
            "lat": lat,
            "lon": lon,
            "station_id": station_id,
            "time": iso_time,
            "temperature": obs.get("temp", [None])[0],
            "humidity": obs.get("humidity", [None])[0],
            "wind": obs.get("wind", [None])[0]
        }

        return features