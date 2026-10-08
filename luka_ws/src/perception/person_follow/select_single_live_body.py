"""Select the sole fresh strong body for a static target-continuity test."""
import json
from urllib.request import Request, urlopen

base = 'http://127.0.0.1:8097/api/people/'
with urlopen(base + 'status', timeout=3) as response:
    state = json.load(response)
tracks = state.get('tracks') or []
if (state.get('active') is not True or state.get('motion_enabled') is not False or
        (state.get('camera_age') or 9) >= .5 or len(tracks) != 1 or
        tracks[0].get('observation_strength') != 'strong' or
        tracks[0].get('association_ambiguous')):
    print('not_selected: state unsuitable for safe static selection')
else:
    track_id = tracks[0]['track_id']
    request = Request(base + 'select', data=json.dumps({'track_id': track_id}).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=3) as response:
        result = json.load(response)
    print('selected_track', track_id, 'result', result.get('ok'))
