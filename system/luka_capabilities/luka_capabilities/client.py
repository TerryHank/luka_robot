import json,urllib.request,urllib.error

def http(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:8503'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
 except urllib.error.HTTPError as e:
  try:raise ValueError(json.loads(e.read()).get('error','小车接口拒绝请求'))
  except json.JSONDecodeError:raise ValueError('小车接口拒绝请求')

def execute_remote(tool,arguments,source,generation=None):
 body={'tool':tool,'arguments':arguments,'source':source}
 if generation is not None:body['generation']=generation
 return http('/api/assistant/execute',body)
