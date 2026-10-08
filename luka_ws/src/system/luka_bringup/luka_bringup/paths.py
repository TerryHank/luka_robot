import os
from pathlib import Path

def workspace_root():
 return Path(os.environ.get('LUKA_WORKSPACE_ROOT','/home/sunrise/luka_ws'))
