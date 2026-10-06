"""One-time Etsy login (OAuth 2 with PKCE). Prints the refresh token and shop id to store as secrets."""
import base64
import hashlib
import secrets
import urllib.parse

import requests

from .agents.etsy import SCOPES, TOKEN_URL

AUTH_URL = "https://www.etsy.com/oauth/connect"


def main(keystring, shared_secret, redirect_uri):
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": keystring, "redirect_uri": redirect_uri, "scope": SCOPES,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    print("\n1. Open this link, sign in to Etsy and click 'Grant access':\n\n" + url)
    print("\n2. Your browser then goes to your redirect URL (the page may fail to load; that's fine).")
    back = input("   Paste the full address from the browser bar here: ").strip()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    if query.get("state", [""])[0] != state:
        raise SystemExit("State mismatch: start again and paste the newest address.")
    tok = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code", "client_id": keystring, "redirect_uri": redirect_uri,
        "code": query["code"][0], "code_verifier": verifier}, timeout=60)
    tok.raise_for_status()
    tok = tok.json()
    user_id = tok["access_token"].split(".")[0]
    shop = requests.get(f"https://api.etsy.com/v3/application/users/{user_id}/shops",
                        headers={"x-api-key": f"{keystring}:{shared_secret}",
                                 "Authorization": f"Bearer {tok['access_token']}"}, timeout=60)
    shop.raise_for_status()
    shop_id = shop.json().get("shop_id")
    print("\nDone. Save these as secrets (GitHub: Settings > Secrets and variables > Actions; locally: .env):\n")
    print(f"ETSY_REFRESH_TOKEN={tok['refresh_token']}")
    print(f"ETSY_SHOP_ID={shop_id}")
