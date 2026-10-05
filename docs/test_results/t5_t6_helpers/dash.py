"""Dashboard GET helper. Reads AGX_DASH_USER / AGX_DASH_PASSWORD from .env; never prints them."""
import base64, json, urllib.request
def _creds():
    u = p = None
    for line in open("/home/tonyho/driveragent-agx/.env"):
        line = line.strip()
        if line.startswith("AGX_DASH_USER="): u = line.split("=", 1)[1].strip().strip('"\'')
        if line.startswith("AGX_DASH_PASSWORD="): p = line.split("=", 1)[1].strip().strip('"\'')
    return u, p
_U, _P = _creds()
_H = {"Authorization": "Basic " + base64.b64encode(f"{_U}:{_P}".encode()).decode()}
def get(path, raw=False, timeout=3):
    r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8700" + path, headers=_H), timeout=timeout)
    b = r.read()
    return (r.status, b) if raw else json.loads(b)
if __name__ == "__main__":
    import sys
    print(json.dumps(get(sys.argv[1]), indent=1)[: int(sys.argv[2]) if len(sys.argv) > 2 else 4000])
