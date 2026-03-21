FROM public.ecr.aws/lambda/python:3.12

# 依存ライブラリをインストール
COPY requirements.txt .
RUN pip install -r requirements.txt -t ${LAMBDA_TASK_ROOT}

# Lambda 関数コード
COPY lambda_function.py ${LAMBDA_TASK_ROOT}

# weather_observation_api 内の Python モジュールをコピー
COPY agentcore ${LAMBDA_TASK_ROOT}/agentcore
COPY models ${LAMBDA_TASK_ROOT}/models
COPY parse_observation.py ${LAMBDA_TASK_ROOT}
COPY logger.py ${LAMBDA_TASK_ROOT}
COPY dynamodb_writer.py ${LAMBDA_TASK_ROOT}
COPY station_master.py ${LAMBDA_TASK_ROOT}
COPY geo_utils.py ${LAMBDA_TASK_ROOT}
COPY app.py ${LAMBDA_TASK_ROOT}
COPY config.json ${LAMBDA_TASK_ROOT}
COPY manifest.json ${LAMBDA_TASK_ROOT}

ENTRYPOINT ["/lambda-entrypoint.sh"]
CMD ["lambda_function.lambda_handler"]