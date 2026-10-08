"""Bounded volatile chat history, kept separate from robot command routing."""
import time
import json
import re
import urllib.request

class ChatMemory:
    def __init__(self):
        self.turns=[]
        self.updated=0.0
        self.generation=0

    def clear(self):
        self.turns.clear()
        self.generation+=1
        self.updated=0.0

    def messages(self,system,text):
        if self.turns and time.monotonic()-self.updated>600:self.clear()
        result=[{'role':'system','content':system}]
        for user,answer in self.turns:
            result.extend([{'role':'user','content':user},{'role':'assistant','content':answer}])
        result.append({'role':'user','content':text})
        return result

    def add(self,user,answer):
        # Keep enough of a turn for natural follow-up questions.  This is a
        # bounded conversation buffer, not a speech-length limit.
        self.turns.append((user[:800],answer[:2400]))
        while len(self.turns)>8 or sum(len(u)+len(a) for u,a in self.turns)>7200:
            self.turns.pop(0)
        self.updated=time.monotonic()

def chat_with_messages(client,messages):
    if client.api=='openai':
        path='/chat/completions' if client.base_url.endswith('/v1') else '/v1/chat/completions'
        body=client._post(path,{'model':client.model,'messages':messages,'stream':False,
            'temperature':client.temperature,'max_tokens':client.max_tokens,
            'enable_thinking':False,'chat_template_kwargs':{'enable_thinking':False}})
        answer=body['choices'][0]['message']['content']
    else:
        body=client._post('/api/chat',{'model':client.model,'messages':messages,'stream':False,
            'think':False,'options':{'temperature':client.temperature,'num_ctx':client.num_ctx}})
        answer=body['message']['content']
    if not isinstance(answer,str) or not answer.strip():raise ValueError('empty chat response')
    return answer

def stream_chat_with_messages(client, messages, on_sentence):
    """Emit an early first clause, then stream complete sentences without truncation."""
    if client.api != 'openai':
        return chat_with_messages(client, messages)
    path = '/chat/completions' if client.base_url.endswith('/v1') else '/v1/chat/completions'
    headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
    if client.api_key:
        headers['Authorization'] = 'Bearer ' + client.api_key
    payload = {'model': client.model, 'messages': messages, 'stream': True,
               'temperature': client.temperature, 'max_tokens': client.max_tokens,
               'enable_thinking': False,
               'chat_template_kwargs': {'enable_thinking': False}}
    request = urllib.request.Request(client.base_url + path,
        data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    pending, spoken = '', []
    def emit(text):
        text = re.sub(r'\s+', ' ', text).strip()
        if text:
            spoken.append(text)
            on_sentence(text)
    with urllib.request.urlopen(request, timeout=client.timeout_sec) as response:
        for raw in response:
            line = raw.decode('utf-8').strip()
            if not line.startswith('data:'): continue
            data = line[5:].strip()
            if data == '[DONE]': break
            event = json.loads(data)
            if 'error' in event: raise RuntimeError(str(event['error']))
            choices = event.get('choices') or []
            if not choices: continue
            pending += choices[0].get('delta', {}).get('content') or ''
            while True:
                match = re.search(r'[。！？!?]', pending)
                # Start speaking at a natural clause boundary instead of waiting
                # for a long first sentence. Later sentences stay grouped so the
                # voice queue does not fill with tiny audio fragments.
                if not spoken:
                    clause = next((m for m in re.finditer(r'[，；：;:]', pending)
                                   if len(pending[:m.start()].strip()) >= 8), None)
                    if clause and (match is None or clause.end() < match.end()):
                        match = clause
                if not match: break
                emit(pending[:match.end()])
                pending = pending[match.end():]
            # Continue to EOS; splitting for playback never limits answer length.
    emit(pending)
    if not spoken: raise ValueError('empty chat response')
    return ''.join(spoken)
