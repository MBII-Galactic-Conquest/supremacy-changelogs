import os
import shutil
import sqlite3
import git
from git import Repo
from datetime import datetime
import json
import subprocess
import time
import sys

############################
#   NIGHTOWL IS            #
# A PYTHON SCRIPT          #
#   THAT CHECKS            #
# FOR PRIVATE REPOSITORY   #
#  COMMIT HISTORY          #
# STORING LOGS OF THEM     #
############################

# ---------- CONFIG SETUP ----------

ENV_FILE = 'nightowl.env'

# Template .env if missing
default_env = """# Configuration
SSH_USER=git
SSH_KEY_PATH=sshkey/
PRIVATE_REPO_OWNER=placeholder
PRIVATE_REPO_NAME=placeholder
PRIVATE_BRANCH=placeholder
PARENT_BRANCH=placeholder
"""

# Create .env if missing
if not os.path.exists(ENV_FILE):
    with open(ENV_FILE, 'w') as f:
        f.write(default_env)
    print(f"Created default {ENV_FILE}. Please fill it out and rerun the script.")
    exit()

# Load .env
env_vars = {}
with open(ENV_FILE, 'r') as f:
    for line in f:
        if line.strip() and not line.startswith('#'):
            key, value = line.strip().split('=', 1)
            env_vars[key] = value

SSH_USER = env_vars['SSH_USER']
SSH_KEY_PATH = os.path.expanduser(env_vars['SSH_KEY_PATH'])  # Now points to folder
PRIVATE_REPO_OWNER = env_vars['PRIVATE_REPO_OWNER']
PRIVATE_REPO_NAME = env_vars['PRIVATE_REPO_NAME']
PRIVATE_BRANCH = env_vars['PRIVATE_BRANCH']
PARENT_BRANCH = env_vars['PARENT_BRANCH']

# ---------- CHECK FOR PLACEHOLDERS IN .env ----------

for key, value in env_vars.items():
    if "Placeholder" in value:
        print(f"Error: Placeholder detected in {ENV_FILE}. Please replace the placeholders with valid values.")
        exit(1)

# ---------- CHECK FOR SSH KEY IN FOLDER ----------

def find_ssh_key(directory):
    """Find the first valid private key file in the given directory."""
    for filename in os.listdir(directory):
        if filename.endswith('.rsa') or filename.endswith('.pem') or filename.endswith('.key'):
            return os.path.join(directory, filename)
    return None

# Try to find a valid SSH key in the folder
SSH_KEY_PATH = find_ssh_key(SSH_KEY_PATH)

if not SSH_KEY_PATH:
    print("Error: No SSH key found in the specified directory. Please add an SSH key and rerun the script.")
    exit(1)  # Exit the script with an error code

# ---------- DATABASE SETUP ----------

DB_FILE = 'commits.db'
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

cursor.execute(''' 
    CREATE TABLE IF NOT EXISTS processed_commits (
        commit_hash TEXT PRIMARY KEY
    )
''')
conn.commit()

# ---------- LAST PROCESSED COMMIT JSON ----------

last_processed_commit_file = 'last_processed_commit.json'
last_commit_hash = None

if os.path.exists(last_processed_commit_file):
    with open(last_processed_commit_file, 'r') as f:
        data = json.load(f)
        last_commit_hash = data.get('commit_hash')

# ---------- LOGGING SETUP ----------

logs_folder = 'logs'
os.makedirs(logs_folder, exist_ok=True)
log_file_path = os.path.join(logs_folder, 'activity.log')

def log_status(message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file_path, 'a') as log_file:
        log_file.write(f"[{now}] {message}\n")
    print(f"[{now}] {message}")

# ---------- FUNCTION: CHECK IF PACKAGE IS INSTALLED ----------

def is_package_installed(package):
    """Check if a package is installed."""
    try:
        subprocess.check_output([sys.executable, "-m", "pip", "show", package], stderr=subprocess.STDOUT)
        return True  # Package is installed
    except subprocess.CalledProcessError:
        return False  # Package is not installed

# ---------- FUNCTION: CHECK FOR OUTDATED PACKAGES ----------

def check_for_updates():
    try:
        outdated_packages = subprocess.check_output([sys.executable, "-m", "pip", "list", "--outdated"]).decode('utf-8')
        if outdated_packages:
            print("The following packages are outdated:\n")
            print(outdated_packages)
            return True  # Indicate that there are outdated packages
        else:
            print("All packages are up to date.")
            return False  # Indicate that there are no outdated packages
    except subprocess.CalledProcessError:
        print("Error checking for outdated packages.")
        return False  # Return False in case of error, to allow the script to proceed

# ---------- FUNCTION: INSTALL REQUIRED PACKAGES ----------

def install_requirements():
    try:
        # Check for outdated packages
        outdated = check_for_updates()

        with open('requirements.txt', 'r') as f:
            required_packages = f.read().splitlines()

        # Install missing packages if they are not already installed
        for package in required_packages:
            if not is_package_installed(package):
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                    print(f"Installed {package}.")
                except subprocess.CalledProcessError:
                    print(f"Error installing {package}.")
            else:
                print(f"{package} is already installed.")

        # If there are no outdated packages, proceed with the script
        if not outdated:
            print("No outdated packages, continuing with the script...")

    except FileNotFoundError:
        print("Error: requirements.txt not found. Please ensure the file exists.")
        exit(1)

# ---------- FUNCTION: GET COMMITS FROM PRIVATE REPO ----------

def get_private_commits():
    cmd = [
        'git', 'ls-remote', '--refs',
        PRIVATE_REPO_URL, f'refs/heads/{PRIVATE_BRANCH}'
    ]
    env = os.environ.copy()
    env['GIT_SSH_COMMAND'] = f'ssh -i {SSH_KEY_PATH} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no'
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        log_status(f"Error fetching commits: {result.stderr}")
        exit(1)
    commits = result.stdout.strip().splitlines()
    return [(line.split()[0], line.split()[1]) for line in commits]

# ---------- FUNCTION: GET COMMIT DATE ----------

def get_commit_date(commit_hash):
    cmd = [
        'git', 'show', '-s', '--format=%ci', commit_hash
    ]
    env = os.environ.copy()
    env['GIT_SSH_COMMAND'] = f'ssh -i {SSH_KEY_PATH} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no'
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        log_status(f"Error fetching commit date: {result.stderr}")
        return datetime.now()  # fallback to now
    date_str = result.stdout.strip()
    return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")

# ---------- FUNCTION: CHECK FOR REMOTE CHANGES ----------

def check_for_remote_changes():
    try:
        # Fetch the latest remote changes for the PARENT_BRANCH without merging them
        cmd = ['git', 'fetch', 'origin', PARENT_BRANCH]
        env = os.environ.copy()
        env['GIT_SSH_COMMAND'] = f'ssh -i {SSH_KEY_PATH} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no'
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            log_status(f"Error checking for remote changes: {result.stderr}")
            return False
        return True
    except Exception as e:
        log_status(f"Error during remote check: {str(e)}")
        return False

# ---------- MAIN LOOP ----------

nightly_folder = 'nightly'
os.makedirs(nightly_folder, exist_ok=True)

parent_repo_path = '.'
parent_repo = Repo(parent_repo_path)

while True:
    try:
        commits = get_private_commits()

        new_commits = []
        start_processing = False

        for commit_hash, _ in commits:
            if not last_commit_hash or commit_hash == last_commit_hash:
                start_processing = True
                continue

            if start_processing:
                cursor.execute('SELECT 1 FROM processed_commits WHERE commit_hash = ?', (commit_hash,))
                if cursor.fetchone() is None:
                    new_commits.append(commit_hash)

        if new_commits:
            log_status(f"Found {len(new_commits)} new commit(s) to process.")

            # Check for remote changes before pulling
            if check_for_remote_changes():
                # Always PULL before making any changes
                origin = parent_repo.remote(name='origin')
                log_status("Pulling latest changes from parent repo...")
                origin.pull(refspec=f"{PARENT_BRANCH}:{PARENT_BRANCH}")

            for commit_hash in new_commits:
                commit_date = get_commit_date(commit_hash)
                short_hash = commit_hash[:7]
                filename = f"{commit_date.month}.{commit_date.day}.{str(commit_date.year)[2:]}-{short_hash}.log"
                filepath = os.path.join(nightly_folder, filename)

                if not os.path.exists(filepath):
                    # Get the actual commit message for the log file from the private repo
                    cmd = ['git', 'show', '-s', '--format=%s', commit_hash]
                    env = os.environ.copy()
                    env['GIT_SSH_COMMAND'] = f'ssh -i {SSH_KEY_PATH} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no'
                    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
                    commit_message = result.stdout.strip() if result.returncode == 0 else 'No commit message available'
                    
                    with open(filepath, 'w') as f:
                        f.write(f"{commit_hash} > {commit_message}")
                    log_status(f"Created .log for {commit_hash}")

                # Record into database
                cursor.execute('INSERT OR IGNORE INTO processed_commits (commit_hash) VALUES (?)', (commit_hash,))
                conn.commit()

            # Stage, Commit, Push
            commit_message = f"{commit_message}"
            parent_repo.git.add(os.path.join(nightly_folder, '*'))
            parent_repo.index.commit(commit_message)
            origin.push(refspec=f"{PARENT_BRANCH}:{PARENT_BRANCH}")
            log_status(f"Pushed new commit to parent repo with message: {commit_message}")

            # Update last processed commit JSON
            with open(last_processed_commit_file, 'w') as f:
                json.dump({'commit_hash': new_commits[-1]}, f)
            last_commit_hash = new_commits[-1]

        else:
            log_status("No new commits found.")

    except Exception as e:
        log_status(f"Error: {str(e)}")

    # Sleep for 60 seconds
    time.sleep(60)
