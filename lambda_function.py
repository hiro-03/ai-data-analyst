import json

def lambda_handler(event, context):
    # event から "text" を受け取る
    body = json.loads(event.get("body", "{}"))
    user_text = body.get("text", "")

    # AgentCore を呼び出す部分（レベル①では仮の処理）
    # 本番ではここに AgentCore API を呼び出すコードを入れる
    result = f"あなたが送ったテキスト: {user_text}"

    # API Gateway に返す形式
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"result": result})
    }