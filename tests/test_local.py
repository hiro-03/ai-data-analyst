import boto3
import os

os.environ["LOCAL_MODE"] = "true"

def get_dynamodb():
    return boto3.resource(
        "dynamodb",
        region_name="ap-northeast-1",
        endpoint_url="http://localhost:8000"
    )

def main():
    dynamodb = get_dynamodb()
    table = dynamodb.Table("Stations")

    print("Scanning Stations table...")
    resp = table.scan()
    print(resp)

if __name__ == "__main__":
    main()