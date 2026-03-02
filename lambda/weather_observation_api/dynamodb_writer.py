import boto3

dynamodb = boto3.resource('dynamodb')
OBS_TABLE = dynamodb.Table('WeatherObservations')

def save_observation(station_id, formatted_data):
    OBS_TABLE.put_item(
        Item={
            "station_id": station_id,
            "timestamp": formatted_data["timestamp"],
            "data": formatted_data
        }
    )