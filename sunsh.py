import json
import requests
from requests.auth import HTTPBasicAuth
import os
import dotenv

dotenv.load_dotenv()  # Load environment variables from .env file

SUNSHINE_URL = os.environ.get("SUNSHINE_URL", "https://localhost:47989")
USERNAME = os.environ.get("SUNSHINE_USERNAME", "admin")
PASSWORD = os.environ.get("SUNSHINE_PASSWORD", "admin")
print(f"Using Sunshine URL: {SUNSHINE_URL}")

# Check available endpoints / app list
def get_logs():
    r = requests.get(
        auth=HTTPBasicAuth(USERNAME, PASSWORD),
        url=f'{SUNSHINE_URL}/api/logs',
        verify=False,
    ).text
    return r

import re
from datetime import datetime

LOG_PATTERN = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]: \w+: (.+)')
EXECUTING_PATTERN = re.compile(r'Executing \[(.+?)\]')
SESSION_PATTERN = re.compile(r'New streaming session started \[active sessions: (\d+)\]')

def parse_sunshine_session(log_text: str) -> dict:
    lines = log_text.strip().splitlines()

    streaming = False
    current_app = None
    session_start = None
    pending_app = None  # app name seen just before session confirmed

    for line in lines:
        m = LOG_PATTERN.match(line)
        if not m:
            continue
        timestamp_str, message = m.groups()
        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")

        # Capture app name from "Executing [AppName]"
        exec_match = EXECUTING_PATTERN.search(message)
        if exec_match:
            pending_app = exec_match.group(1)

        # Session count line is the ground truth
        session_match = SESSION_PATTERN.search(message)
        if session_match:
            active = int(session_match.group(1))
            if active > 0:
                streaming = True
                session_start = timestamp
                current_app = pending_app  # lock in the app name
            else:
                streaming = False
                current_app = None
                session_start = None
                pending_app = None

    return {
        "streaming": streaming,
        "app": current_app,
        "since": session_start.isoformat() if session_start else None,
    }


def get_sunshine_session() -> dict:
    logs = get_logs()
    return parse_sunshine_session(logs)

""" # Get current active sessions
def get_sessions():
    r = session.get(f"{SUNSHINE_URL}/api/sessions")
    r.raise_for_status()
    return r.json() """




if __name__ == "__main__":
    print("=== SUNSHINE SESSION ===")
    print(get_sunshine_session())
    """ print(get_logs()) """
    """ print("=== APPS ===")
    print(json.dumps(get_apps(), indent=2))

    print("\n=== SESSIONS ===")
    print(json.dumps(get_sessions(), indent=2))

    print("\n=== CONFIG ===")
    print(json.dumps(get_config(), indent=2)) """