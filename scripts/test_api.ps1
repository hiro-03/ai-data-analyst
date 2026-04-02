param(
  [string]$StackName  = "ai-data-analyst-fishing",
  [string]$Region     = "ap-northeast-1",
  [double]$Lat        = 35.681236,
  [double]$Lon        = 139.767125,
  [string]$Username   = "",   # Cognito username (email)
  [string]$Password   = ""    # Cognito password (prompted if omitted)
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Helper: fetch a CloudFormation stack output value by key.
# ---------------------------------------------------------------------------
function Get-StackOutputValue([string]$Key) {
  $v = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query ("Stacks[0].Outputs[?OutputKey=='{0}'].OutputValue | [0]" -f $Key) `
    --output text
  if (-not $v -or $v -eq "None") { throw "Stack output '$Key' not found in stack '$StackName'" }
  return $v
}

# ---------------------------------------------------------------------------
# Resolve stack outputs.
# ---------------------------------------------------------------------------
$fishingUrl  = Get-StackOutputValue "FishingApiUrl"
$userPoolId  = Get-StackOutputValue "CognitoUserPoolId"
$clientId    = Get-StackOutputValue "CognitoUserPoolClientId"

Write-Host "FishingApiUrl       = $fishingUrl"  -ForegroundColor Green
Write-Host "CognitoUserPoolId   = $userPoolId"  -ForegroundColor Green
Write-Host "CognitoAppClientId  = $clientId"    -ForegroundColor Green

# ---------------------------------------------------------------------------
# Collect credentials interactively if not supplied as parameters.
# ---------------------------------------------------------------------------
if (-not $Username) {
  $Username = Read-Host "Cognito username (email)"
}
if (-not $Password) {
  $securePass = Read-Host "Cognito password" -AsSecureString
  $Password   = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
                  [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePass))
}

# ---------------------------------------------------------------------------
# Authenticate via ADMIN_USER_PASSWORD_AUTH and obtain the Cognito ID token.
# Requires: AWS credentials with cognito-idp:AdminInitiateAuth permission.
# ---------------------------------------------------------------------------
Write-Host "`nAuthenticating as $Username ..." -ForegroundColor Cyan
$authJson = aws cognito-idp admin-initiate-auth `
  --region $Region `
  --user-pool-id $userPoolId `
  --client-id $clientId `
  --auth-flow ADMIN_USER_PASSWORD_AUTH `
  --auth-parameters "USERNAME=$Username,PASSWORD=$Password" `
  --output json | ConvertFrom-Json

$idToken = $authJson.AuthenticationResult.IdToken
if (-not $idToken) { throw "Authentication failed: no IdToken in response" }
Write-Host "Auth OK (token length = $($idToken.Length) chars)" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Call POST /fishing with the JWT in the Authorization header.
# ---------------------------------------------------------------------------
$body = @{
  lat            = $Lat
  lon            = $Lon
  target_species = "aji"
  spot_type      = "harbor"
} | ConvertTo-Json

Write-Host "`nPOST $fishingUrl" -ForegroundColor Cyan
$fishingRaw = Invoke-WebRequest `
  -Method Post `
  -Uri $fishingUrl `
  -ContentType "application/json" `
  -Headers @{ Authorization = $idToken } `
  -Body $body `
  -TimeoutSec 60

Write-Host ("StatusCode  = {0}" -f $fishingRaw.StatusCode)                   -ForegroundColor Yellow
Write-Host ("ContentType = {0}" -f $fishingRaw.Headers["Content-Type"])       -ForegroundColor Yellow
Write-Host "Raw content:"                                                      -ForegroundColor Yellow
$fishingRaw.Content

Write-Host "`nParsed JSON (best-effort):" -ForegroundColor Yellow
try {
  ($fishingRaw.Content | ConvertFrom-Json) | ConvertTo-Json -Depth 30
} catch {
  Write-Host "Could not parse as JSON."
}
