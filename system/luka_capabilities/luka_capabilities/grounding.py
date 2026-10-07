def validate_grounding(arguments, source):
 for key in ('query','name'):
  if key in arguments:
   value=arguments[key]
   if not isinstance(value,str) or not 1<=len(value.strip())<=80 or value not in source:
    raise ValueError('目标必须来自你的原话，请说出名称')
