FROM public.ecr.aws/lambda/python:3.12

# 依存ライブラリをインストール
COPY requirements.txt .
RUN pip install -r requirements.txt -t ${LAMBDA_TASK_ROOT}

# Lambda 関数コードだけをコピー
COPY lambda_function.py ${LAMBDA_TASK_ROOT}

ENTRYPOINT ["/lambda-entrypoint.sh"]
CMD ["lambda_function.lambda_handler"]