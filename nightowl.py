import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from dotenv import load_dotenv
import json
import time
import sys
import platform
import logging

############################
#   NIGHTOWL IS            #
# A PYTHON SCRIPT          #
#   THAT CHECKS            #
# FOR PRIVATE REPOSITORY   #
#  COMMIT HISTORY          #
# STORING LOGS OF THEM     #
############################

# ---------- CONFIG SETUP ----------

ENV_FILE = "nightowl.env"

# Template .env if missing
default_env = """# Configuration
SSH_USER=git
SSH_KEY=placeholder
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

load_dotenv(dotenv_path=ENV_FILE)

SSH_USER = env_vars['SSH_USER']
SSH_KEY_PATH = env_vars['SSH_KEY']
PRIVATE_REPO_OWNER = env_vars['PRIVATE_REPO_OWNER']
PRIVATE_REPO_NAME = env_vars['PRIVATE_REPO_NAME']
PRIVATE_BRANCH = env_vars['PRIVATE_BRANCH']
PARENT_BRANCH = env_vars['PARENT_BRANCH']

PRIVATE_REPO_URL = f"git@github.com:{PRIVATE_REPO_OWNER}/{PRIVATE_REPO_NAME}.git"

# ---------- CHECK FOR PLACEHOLDERS IN .ENV ----------

for key, value in env_vars.items():
    if "Placeholder" in value:
        print(f"Error: Placeholder detected in {ENV_FILE}. Please replace the placeholders with valid values.")
        exit(1)

# ---------- LOGGING SETUP ----------

# Create the logs directory if it doesn't exist
logs_folder = 'logs'
os.makedirs(logs_folder, exist_ok=True)

# Set up logging configuration
log_file_path = os.path.join(logs_folder, 'activity.log')

# Remove the existing log file if it exists
if os.path.exists(log_file_path):
    os.remove(log_file_path)

# Configure logging to write to both a file and the console
logging.basicConfig(
    level=logging.DEBUG,  # Log all levels (DEBUG and higher)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log format with time, level, and message
    handlers=[
        logging.FileHandler(log_file_path),  # Log to file
        logging.StreamHandler()  # Log to console
    ]
)

# ---------- FUNCTION: MESSAGE LOGGING ----------

def log_status(message, level=logging.INFO):
    """Logs a message to both file and console with the specified log level."""
    if level == logging.DEBUG:
        logging.debug(message)
    elif level == logging.INFO:
        logging.info(message)
    elif level == logging.WARNING:
        logging.warning(message)
    elif level == logging.ERROR:
        logging.error(message)
    elif level == logging.CRITICAL:
        logging.critical(message)

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

# Check if the file exists
if os.path.exists(last_processed_commit_file):
    with open(last_processed_commit_file, 'r') as f:
        data = json.load(f)
        last_commit_hash = data.get('commit_hash')
else:
    # If the file does not exist, create it with a default commit_hash (None or empty string)
    with open(last_processed_commit_file, 'w') as f:
        json.dump({"commit_hash": None}, f)
    log_status(f"Created {last_processed_commit_file} with default commit hash (None).")

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

        # If there are no outdated packages, proceed with the script
        if not outdated:
            print("No outdated packages, continuing with the script...")
            exit(1)

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

    except FileNotFoundError:
        print("Error: requirements.txt not found. Please ensure the file exists.")
        exit(1)

# ---------- FUNCTION: INITIALIZE SSH AGENT ----------

def initialize_sshagent():
    """Starts the SSH agent and adds the key based on the platform (Windows or Unix)."""
    load_dotenv()
    SSH_KEY = os.getenv("SSH_KEY")  # This will retrieve the value from the .env file

    if not SSH_KEY:
        print("[ERROR] SSH_KEY not found in the .env file.")
        exit(1)

    if platform.system() == "Windows":
        try:
            # Path to your PowerShell script
            PS_SCRIPT_PATH = os.path.abspath("lib/win/ssh_agent.ps1")

            # Escape spaces in the file path by wrapping it in double quotes
            PS_SCRIPT_PATH = f'"{PS_SCRIPT_PATH}"'
            SSH_KEY = f'"{SSH_KEY}"'  # Make sure the SSH key path is also escaped

            # Properly escape the spaces in the file path and pass to PowerShell
            command = f'\"{PS_SCRIPT_PATH}\" -SSH_KEY_PATH \"{SSH_KEY}\"'

            # Run the PowerShell script with elevated privileges
            subprocess.run([
                'powershell', 
                '-ExecutionPolicy', 
                'Bypass', 
                '-Command', 
                f'Start-Process powershell -ArgumentList "{command}" -Verb RunAs'
            ], check=True)

            print("[INFO] PowerShell script executed successfully.")

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to run PowerShell script: {e}")
            exit(1)
    else:
        # For Unix-like systems (Linux/macOS)
        try:
            print("[INFO] Detected Unix-based system. Adding SSH key to agent...")

            # Start the SSH agent
            subprocess.run(['ssh-agent', '-s'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Add the SSH key to the agent
            subprocess.run(['ssh-add', SSH_KEY], check=True)
            print("[INFO] SSH key added to the agent successfully.")

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Error while adding SSH key to the agent: {e}")
            exit(1)

# ---------- FUNCTION: CLONE PARENT REPO ----------

def clone_repos():
    tmp_dir = os.path.join('tmp')
    os.makedirs(tmp_dir, exist_ok=True)

    log_status(f"Cloning parent repository into {tmp_dir}...")
    subprocess.run(['git', 'clone', '-b', PARENT_BRANCH, '.', tmp_dir], check=True)

    return tmp_dir

# ---------- FUNCTION: GET COMMITS FROM PRIVATE REPO ----------

def get_private_commits():
    log_status(f"Fetching commits from private repository {PRIVATE_REPO_NAME} (branch: {PRIVATE_BRANCH})...")

    private_repo_url = f"git@github.com:{PRIVATE_REPO_OWNER}/{PRIVATE_REPO_NAME}.git"
    cmd = ['git', 'ls-remote', '--refs', private_repo_url, f'refs/heads/{PRIVATE_BRANCH}']
    env = os.environ.copy()
    env['GIT_SSH_COMMAND'] = f'ssh -i {SSH_KEY_PATH} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Timeout: SSH connection to private repo took too long.")
    except Exception as e:
        raise RuntimeError(f"Failed to run git ls-remote: {str(e)}")

    if result.returncode != 0:
        raise RuntimeError(f"Git ls-remote failed: {result.stderr.strip()}")

    lines = result.stdout.strip().splitlines()
    commits = [(line.split()[0], line.split()[1]) for line in lines]
    log_status(f"Found {len(commits)} commits.")
    return commits

# ---------- FUNCTION: FILTER AND PROCESS NEW COMMITS ----------

def filter_and_process_commits(commits):
    last_commit_hash = None
    new_commits = []
    for commit_hash, commit_message in commits:
        if commit_hash != last_commit_hash:
            new_commits.append((commit_hash, commit_message))
            # Update last processed commit hash
            last_commit_hash = commit_hash

    # Save the last processed commit hash to a JSON file
    with open(last_processed_commit_file, 'w') as f:
        json.dump({"commit_hash": last_commit_hash}, f)

    return new_commits

# ---------- FUNCTION: SAVE COMMIT DATA ----------

def save_commits(new_commits):
    for commit_hash, commit_message in new_commits:
        log_status(f"Processing commit: {commit_hash} - {commit_message}")

        # Write logs to the nightly folder
        commit_message = commit_message.replace("\n", " ").strip()
        log_filename = f"{commit_hash}.log"

        with open(f"nightly/{log_filename}", 'w') as f:
            f.write(commit_message)

        # Commit and push changes
        subprocess.run(['git', 'add', '.'], check=True)
        subprocess.run(['git', 'commit', '-m', f"Add commit log for {commit_hash}"], check=True)
        subprocess.run(['git', 'push'], check=True)

# ---------- INITIALIZES ----------

log_status("Checking for package updates and requirements...")
install_requirements()

log_status("Initializing SSH agent...")
initialize_sshagent()

# ---------- MAIN SCRIPT ----------

if __name__ == '__main__':
    while True:

        # Step 1: Remove the tmp folder if it already exists
        tmp_dir = "tmp"
        log_status("Checking for pre-existing temporary folders...")
        if os.path.exists(tmp_dir):
            log_status(f"Temporary directory ({tmp_dir}) exists. Deleting it...")
            shutil.rmtree(tmp_dir)
            log_status(f"Temporary directory ({tmp_dir}) deleted.")

        # Step 2: Clone the parent repository
        log_status("Cloning parent repository into tmp...")
        tmp_dir = clone_repos()

        if not tmp_dir:
            log_status("Error: Temporary directory not created after cloning.")
            continue

        log_status(f"Cloned repository into {tmp_dir}.")

        # Step 3: Get commits from the private repo
        try:
            log_status("Getting private repo commits...")
            commits = get_private_commits()
            log_status(f"Retrieved {len(commits)} commits.")
        except Exception as e:
            log_status(f"Error while retrieving commits: {e}", level=logging.ERROR)
            time.sleep(60)
            continue

        if commits is None:
            log_status("Error fetching commits. Skipping iteration.")
            continue

        log_status(f"Processing {len(commits)} commits...")
        new_commits = filter_and_process_commits(commits)

        if new_commits:
            # Step 5: Save commit data to files
            log_status(f"Saving {len(new_commits)} new commits to files...")
            save_commits(new_commits)
        else:
            log_status("No new commits to process.")

        # Step 6: Clean up
        log_status(f"Cleaning up temporary directory {tmp_dir}...")
        shutil.rmtree(tmp_dir)
        log_status("Process completed successfully!")

        # Wait for 60 seconds before the next iteration
        log_status("Waiting 60 seconds before next iteration...")
        time.sleep(60)
