.PHONY: help sam-validate sam-build sam-deploy seed-stations test-api

STACK_NAME ?= ai-data-analyst-fishing
REGION ?= ap-northeast-1

help:
	@echo "Usage:"
	@echo "  make sam-validate"
	@echo "  make sam-build"
	@echo "  make sam-deploy STACK_NAME=ai-data-analyst-fishing REGION=ap-northeast-1"
	@echo "  make seed-stations STACK_NAME=ai-data-analyst-fishing REGION=ap-northeast-1"
	@echo "  make test-api"

sam-validate:
	sam validate --template-file template.yaml

sam-build:
	sam build

sam-deploy:
	sam deploy --stack-name "$(STACK_NAME)" --s3-prefix "$(STACK_NAME)" --resolve-s3 --region "$(REGION)" --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM

seed-stations:
	powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_stations.ps1 -StackName "$(STACK_NAME)" -Region "$(REGION)"

test-api:
	powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_api.ps1