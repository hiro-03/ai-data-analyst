"""
Staging smoke test script.

Queries CloudFormation stack outputs to obtain the API URL and Cognito
identifiers, authenticates as a pre-provisioned smoke-test user via
ADMIN_USER_PASSWORD_AUTH (plain-text password to Cognito, requires AWS
IAM credentials on the caller side – safe in CI where OIDC role is
assumed), and fires a POST /fishing request with a known-good payload.

Note: ADMIN_USER_PASSWORD_AUTH is enabled only for the staging Cognito
app client (IsNotProd condition in template.yaml). Production uses SRP
exclusively to avoid transmitting passwords in plain text.

Exit code 0  – smoke test passed (HTTP 200 with a parseable JSON body).
Exit code 1  – smoke test failed (non-200, timeout, or schema violation).

Usage:
    python scripts/smoke_test.py \
        --stack-name ai-data-analyst-fishing-stg \
        --region    ap-northeast-1 \
        --username  smoke@example.com \
        --password  <secret>

The script is intentionally dependency-free (stdlib + boto3 only) so it
runs without installing the full requirements-dev.txt in CI.
"""
import argparse
import json
import sys
import urllib.request
from typing import Any, Dict
from urllib.error import HTTPError, URLError

import boto3


# ---------------------------------------------------------------------------
# CloudFormation helpers
# ---------------------------------------------------------------------------

def _get_stack_outputs(stack_name: str, region: str) -> Dict[str, str]:
    cf = boto3.client("cloudformation", region_name=region)
    resp = cf.describe_stacks(StackName=stack_name)
    stacks = resp.get("Stacks", [])
    if not stacks:
        raise RuntimeError(f"Stack {stack_name!r} not found")
    outputs = stacks[0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


# ---------------------------------------------------------------------------
# Cognito authentication via ADMIN_USER_PASSWORD_AUTH
# Enabled only on the staging app client (ALLOW_ADMIN_USER_PASSWORD_AUTH
# is conditional on IsNotProd in template.yaml). Requires AWS IAM
# credentials on the caller, which are provided by the CI OIDC role.
# ---------------------------------------------------------------------------

def _get_id_token(
    user_pool_id: str,
    client_id: str,
    username: str,
    password: str,
    region: str,
) -> str:
    cognito = boto3.client("cognito-idp", region_name=region)
    resp = cognito.admin_initiate_auth(
        UserPoolId=user_pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    token: str = resp["AuthenticationResult"]["IdToken"]
    return token


# ---------------------------------------------------------------------------
# Smoke test request
# ---------------------------------------------------------------------------

def _post_fishing(api_url: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=api_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            return {"status": resp.status, "body": body}
    except HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return {"status": e.code, "body": body_text}
    except URLError as e:
        raise RuntimeError(f"Request failed: {e.reason}") from e


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Staging smoke test for the Fishing API")
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--username", default="", help="Cognito smoke-test user email")
    parser.add_argument("--password", default="", help="Cognito smoke-test user password")
    args = parser.parse_args()

    if not args.username or not args.password:
        print("[smoke] SKIP: --username / --password not provided (secrets not configured).")
        print("[smoke] Set STG_SMOKE_USER_EMAIL and STG_SMOKE_USER_PASSWORD in GitHub Secrets to enable.")
        sys.exit(0)

    print(f"[smoke] Fetching outputs for stack: {args.stack_name}")
    outputs = _get_stack_outputs(args.stack_name, args.region)

    api_url = outputs.get("FishingApiUrl")
    pool_id = outputs.get("CognitoUserPoolId")
    client_id = outputs.get("CognitoUserPoolClientId")

    if not api_url or not pool_id or not client_id:
        print(f"[smoke] FAIL: Missing stack outputs: {list(outputs.keys())}", file=sys.stderr)
        sys.exit(1)

    print(f"[smoke] API URL : {api_url}")
    print(f"[smoke] Authenticating as {args.username} ...")
    token = _get_id_token(pool_id, client_id, args.username, args.password, args.region)
    print("[smoke] Auth OK")

    payload = {"lat": 35.6762, "lon": 139.6503, "target_species": "aji", "spot_type": "harbor"}
    print(f"[smoke] POST {api_url} payload={payload}")
    result = _post_fishing(api_url, token, payload)

    status = result["status"]
    body = result["body"]
    print(f"[smoke] Response HTTP {status}: {json.dumps(body, ensure_ascii=False)[:500]}")

    if status != 200:
        print(f"[smoke] FAIL: expected HTTP 200, got {status}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(body, dict):
        print("[smoke] FAIL: response body is not a JSON object", file=sys.stderr)
        sys.exit(1)

    if "error" in body and "trace_id" not in body:
        print(f"[smoke] FAIL: response contains error with no trace_id: {body}", file=sys.stderr)
        sys.exit(1)

    print("[smoke] PASS: staging smoke test completed successfully")
    sys.exit(0)


if __name__ == "__main__":
    main()
