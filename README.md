# Fishing Advice API (Serverless + Full-set)

位置情報（lat/lon）から **最寄り観測所の判定**を行い、**潮汐（Stormglass）**・**海況（Open-Meteo Marine）**・**季節/月**などを収集して、**Amazon Bedrock AgentCore** による釣り推論結果を返すAPIです。

## 🏗 Architecture
- API Gateway (REST API): `POST /fishing`
- Lambda (API Proxy): 入力検証・trace_id付与・Step Functions（Express）を同期実行
- Step Functions (Express): データ取得を並列実行（潮汐/海況）→ 推論
- DynamoDB:
  - `StationsTable`: 観測所マスタ
  - `ExternalApiCacheTable`: 外部API結果のTTLキャッシュ
- Bedrock AgentCore: `InvokeAgent` による推論
- CloudWatch: Lambda標準メトリクス/アラーム

## 🚀 Deploy

```powershell
sam validate --template-file template.yaml
sam build
sam deploy --stack-name "ai-data-analyst-fishing" --s3-prefix "ai-data-analyst-fishing" --resolve-s3 --region ap-northeast-1 --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
```

## 🔑 External API Keys (SSM Parameter Store)

### Stormglass
- **SSM parameter**: `/ai-data-analyst/external/stormglass/api-key`
- `template.yaml` の `GetTideLambda` が `STORMGLASS_API_KEY` を dynamic reference で参照します。

例:

```bash
aws ssm put-parameter \
  --name "/ai-data-analyst/external/stormglass/api-key" \
  --type "SecureString" \
  --value "<YOUR_API_KEY>" \
  --overwrite
```

## 🌱 Seed Stations

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_stations.ps1 -StackName ai-data-analyst-fishing -Region ap-northeast-1
```

## 📡 Call API

```powershell
curl.exe -s -D - -X POST "https://<restApiId>.execute-api.ap-northeast-1.amazonaws.com/prod/fishing" -H "Content-Type: application/json" -d '{"lat":35.681236,"lon":139.767125,"target_species":"ajing","spot_type":"harbor"}'
```

## 🧠 Data collection details

### Tide (Stormglass)
- Endpoint: `GET /v2/tide/extremes`
- Cache key（概念）: `tide:stormglass:<lat_round>:<lon_round>:<YYYY-MM-DD>`
- TTL: おおむね **+2日**（日次で再利用しやすい形）

### Marine (Open-Meteo Marine)
- Endpoint: `https://marine-api.open-meteo.com/v1/marine`
- Variables: `sea_surface_temperature`, `wave_height`, `wave_direction`, `wave_period`
- Cache key（概念）: `marine:openmeteo:<lat_round>:<lon_round>:<YYYY-MM-DDTHH>`
- TTL: おおむね **+3日**

### Partial failure behavior (重要)
- Step Functions の並列取得は `Catch` を入れているため、
  - 潮汐/海況のどちらかが失敗しても **推論は継続**します
  - 欠損やエラーは `extras` に残り、AgentCore側では不確実性として扱える前提です

## 🧪 Notes
- `INFERENCE_PROVIDER=mock` の場合、Bedrockなしでレスポンス形だけ確認できます。

