"""Composition host for Behavior/Mission and the compatible dashboard HTTP API."""
import os
import sys
from .paths import workspace_root

def main():
 root=workspace_root()
 os.environ['DDSM_WS']=str(root)
 sys.path.insert(0,str(root/'visualization/console'))
 import nx_dashboard
 nx_dashboard.app.main()
