import json,urllib.request,urllib.error

def vision(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:8091'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=8) as r:return json.load(r)
    except urllib.error.HTTPError as exc:
        raise ValueError(json.loads(exc.read()).get('error','视觉服务拒绝请求')) from exc
