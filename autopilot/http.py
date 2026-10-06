"""Thin HTTP layer used by every agent, so tests can swap it out and dry runs never write anything."""
import requests

TIMEOUT = 60


class HttpError(RuntimeError):
    def __init__(self, method, url, status, body):
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def request(ctx, method, url, *, headers=None, params=None, data=None, json=None, files=None, auth=None):
    """Send a request and return parsed JSON (or {} for empty bodies).

    In dry-run mode only GET requests are sent; writes are logged and return {"dry_run": True}.
    """
    if ctx.dry_run and method.upper() != "GET":
        ctx.log(f"  [dry-run] would {method} {url}")
        return {"dry_run": True}
    resp = requests.request(method, url, headers=headers, params=params, data=data, json=json,
                            files=files, auth=auth, timeout=TIMEOUT)
    if resp.status_code >= 400:
        raise HttpError(method, url, resp.status_code, resp.text)
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {"text": resp.text}
