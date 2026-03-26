param(
  [string]$StackName = "ai-data-analyst-fishing",
  [string]$Region = "ap-northeast-1",
  [string]$SeedFile = (Join-Path $PSScriptRoot "stations.seed.json")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SeedFile)) {
  throw "Seed file not found: $SeedFile"
}

Write-Host "Resolving physical DynamoDB table name from stack..." -ForegroundColor Cyan
$tableName = aws cloudformation describe-stack-resources `
  --stack-name $StackName `
  --region $Region `
  --query "StackResources[?LogicalResourceId=='StationsTable'].PhysicalResourceId | [0]" `
  --output text

if (-not $tableName -or $tableName -eq "None") {
  throw "Could not resolve StationsTable from stack '$StackName' in region '$Region'."
}

Write-Host "StationsTable = $tableName" -ForegroundColor Green

$stations = Get-Content -Raw -Path $SeedFile | ConvertFrom-Json
if (-not $stations) {
  throw "No stations found in seed file: $SeedFile"
}

Write-Host ("Seeding {0} station(s)..." -f $stations.Count) -ForegroundColor Cyan

foreach ($s in $stations) {
  if (-not $s.station_id) { throw "station_id missing in seed file." }
  if ($null -eq $s.latitude) { throw "latitude missing for station_id=$($s.station_id)" }
  if ($null -eq $s.longitude) { throw "longitude missing for station_id=$($s.station_id)" }

  $payload = @{
    TableName = $tableName
    Item      = @{
      station_id = @{ S = [string]$s.station_id }
      latitude   = @{ N = ([string]$s.latitude) }
      longitude  = @{ N = ([string]$s.longitude) }
    }
  } | ConvertTo-Json -Compress

  $tmp = Join-Path $env:TEMP ("ddb-put-item-{0}.json" -f ([Guid]::NewGuid().ToString("n")))
  try {
    # Windows PowerShell's UTF8 includes BOM; AWS CLI can fail to decode it.
    # Payload is ASCII-safe JSON, so write as ASCII to avoid BOM issues.
    Set-Content -Path $tmp -Value $payload -Encoding ASCII

    aws dynamodb put-item `
      --region $Region `
      --cli-input-json ("file://{0}" -f $tmp) | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw ("aws dynamodb put-item failed for station_id={0} (exit={1})" -f $s.station_id, $LASTEXITCODE)
    }

    Write-Host ("- upserted {0} ({1}, {2})" -f $s.station_id, $s.latitude, $s.longitude)
  }
  finally {
    if (Test-Path $tmp) { Remove-Item -Force $tmp }
  }
}

Write-Host "Done." -ForegroundColor Green

