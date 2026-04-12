# infra 配下の IAM サンプルについて

このディレクトリの `deploy-policy.json` および `deploy-minimal-fixed.json` は、**過去の検討用・学習用のサンプル**であり、**本リポジトリの運用ポリシー（Virtual CTO / 最小権限）の正としては使いません**。

- いずれも **`Resource: "*"` を含む**ため、GitHub Actions OIDC 用ロールへの適用は **`scripts/deploy-extra-policy.json` を使用**してください。
- 新規セットアップ時は README の「セキュリティ設計方針」と「GitHub Actions OIDC セットアップ」を参照し、サンプル JSON をそのまま本番に貼り付けないでください。
