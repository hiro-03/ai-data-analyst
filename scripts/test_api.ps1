param(
  [string]$StackName = "ai-data-analyst-fishing",
  [string]$Region = "ap-northeast-1",
  [double]$Lat = 35.681236,
  [double]$Lon = 139.767125
)

$ErrorActionPreference = "Stop"

function Get-StackOutputValue([string]$Key) {
  $v = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query ("Stacks[0].Outputs[?OutputKey=='{0}'].OutputValue | [0]" -f $Key) `
    --output text
  if (-not $v -or $v -eq "None") { throw "Stack output not found: $Key" }
  return $v
}

$fishingUrl = Get-StackOutputValue "FishingApiUrl"

Write-Host "FishingApiUrl = $fishingUrl" -ForegroundColor Green

$body = @{
  lat = $Lat
  lon = $Lon
} | ConvertTo-Json

Write-Host "`nPOST /fishing" -ForegroundColor Cyan
$fishingRaw = Invoke-WebRequest -Method Post -Uri $fishingUrl -ContentType "application/json" -Body $body -TimeoutSec 30
Write-Host ("StatusCode = {0}" -f $fishingRaw.StatusCode) -ForegroundColor Yellow
Write-Host ("ContentType = {0}" -f $fishingRaw.Headers["Content-Type"]) -ForegroundColor Yellow
Write-Host "Raw content:" -ForegroundColor Yellow
$fishingRaw.Content

Write-Host "`nParsed JSON (best-effort):" -ForegroundColor Yellow
try {
  ($fishingRaw.Content | ConvertFrom-Json) | ConvertTo-Json -Depth 30
} catch {
  Write-Host "Could not parse as JSON."
}

