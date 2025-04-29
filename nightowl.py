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
import requests
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
GITHUB_API_URL = "https://api.github.com"

# Template .env if missing
default_env = """# Configuration
GITHUB_TOKEN=placeholder
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

GITHUB_TOKEN = env_vars['GITHUB_TOKEN']
PRIVATE_REPO_OWNER = env_vars['PRIVATE_REPO_OWNER']
PRIVATE_REPO_NAME = env_vars['PRIVATE_REPO_NAME']
PRIVATE_BRANCH = env_vars['PRIVATE_BRANCH']
PARENT_BRANCH = env_vars['PARENT_BRANCH']

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
    try:
        subprocess.check_output([sys.executable, "-m", "pip", "show", package])
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

def check_and_install_requirements():
    # Check if the installation check file exists
    if not os.path.exists('.installed'):
        log_status("Installing required packages...")
        install_requirements()
        # After installation, create the .installed file
        with open('.installed', 'w') as f:
            f.write("Requirements installed.")
        log_status("Requirements installed and .installed file created.")
    else:
        log_status("Requirements already installed, skipping...")

# ---------- FUNCTION: CLEAR PYCACHE ----------

def clear_pycache():
    for root, dirs, files in os.walk("."):
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(root, "__pycache__"))

# ---------- FUNCTION: CLONE PARENT REPO ----------

def clone_repos():
    tmp_dir = os.path.join('tmp')
    os.makedirs(tmp_dir, exist_ok=True)

    log_status(f"Cloning parent repository into {tmp_dir}...")
    subprocess.run(['git', 'clone', '-b', PARENT_BRANCH, '.', tmp_dir], check=True)

    return tmp_dir

# ---------- FUNCTION: GET COMMITS FROM PRIVATE REPO ----------

def get_latest_commits(PRIVATE_REPO_OWNER, PRIVATE_REPO_NAME, PRIVATE_BRANCH, GITHUB_TOKEN):
    url = f"https://api.github.com/repos/{PRIVATE_REPO_OWNER}/{PRIVATE_REPO_NAME}/commits?sha={PRIVATE_BRANCH}"
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        try:
            # Parse the JSON response
            data = response.json()
            
            # Print the response to debug its structure
            print(f"Response Data: {data}")
            
            if not data:
                print("No commits found in the response.")
                return None
            
            # Safely access the latest commit data
            latest_commit = data[0]  # The first commit is the latest one
            sha = latest_commit.get('sha', 'No SHA available')
            message = latest_commit.get('commit', {}).get('message', 'No message available')

            # Shorten commit hash to 7 characters
            commit_data = {
                'commit_hash': sha[:7],
                'commit_message': message
            }

            print(f"Latest Commit Data: {commit_data}")
            return commit_data

        except Exception as e:
            print(f"Error processing commit data: {e}")
            return None
    else:
        print(f"Error {response.status_code}: {response.text}")
        return None

# ---------- FUNCTION: FILTER AND PROCESS NEW COMMITS ----------

def filter_and_process_commits(commits):
    # Load the last processed commit hash from the file if it exists
    try:
        with open(last_processed_commit_file, 'r') as f:
            last_commit_hash = json.load(f).get("commit_hash")
    except FileNotFoundError:
        last_commit_hash = None  # If the file doesn't exist, we haven't processed any commits yet
    
    new_commits = []

    for commit_hash, commit_message in commits:
        # Ensure the commit hash is limited to 7 characters
        commit_hash = commit_hash[:7]

        # If the commit is new (not the last processed one), process it
        if commit_hash != last_commit_hash:
            new_commits.append((commit_hash, commit_message))
            # Update last processed commit hash
            last_commit_hash = commit_hash

    # Save the last processed commit hash to a JSON file
    with open(last_processed_commit_file, 'w') as f:
        json.dump({"commit_hash": last_commit_hash}, f)

    return new_commits

# ---------- FUNCTION: SAVE COMMIT DATA ----------

def generate_random_hash(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def get_commit_info(commit_hash):
    # Get commit message
    msg_cmd = ['git', 'show', '--no-patch', '--format=%s', commit_hash]
    msg_proc = subprocess.run(msg_cmd, capture_output=True, text=True)
    commit_msg = msg_proc.stdout.strip()

    # Get commit date in MM.DD.YY format
    date_cmd = ['git', 'show', '--no-patch', '--format=%cd', '--date=format:%m.%d.%y', commit_hash]
    date_proc = subprocess.run(date_cmd, capture_output=True, text=True)
    commit_date = date_proc.stdout.strip()

    return commit_msg, commit_date

def save_commits(new_commits, parent_branch):
    nightly_dir = os.path.join("tmp", "nightly")
    os.makedirs(nightly_dir, exist_ok=True)

    # Ensure we are on the correct branch
    subprocess.run(['git', '-C', 'tmp', 'checkout', parent_branch], check=True)

    for commit_hash in new_commits:
        short_hash = commit_hash[:7]
        rand_hash = generate_random_hash()
        commit_msg, commit_date = get_commit_info(commit_hash)

        filename = f"{commit_date}-{rand_hash}.log"
        filepath = os.path.join(nightly_dir, filename)

        # Write log contents
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"{short_hash} > {commit_msg}\n")

        # Add the new log file
        subprocess.run(["git", "-C", "tmp", "add", filepath], check=True)

        # Commit and push with the correct commit message
        subprocess.run(["git", "-C", "tmp", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "-C", "tmp", "push", "origin", parent_branch], check=True)

# ---------- FUNCTION: FORCE REMOVES ----------

def force_remove(path):
    # Check if the path exists
    if os.path.exists(path):
        # If it's a directory, recurse and delete its contents
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path, topdown=False):
                for name in files:
                    try:
                        os.chmod(os.path.join(root, name), 0o777)  # Make the file writable
                        os.remove(os.path.join(root, name))
                    except Exception as e:
                        print(f"Error removing file {name}: {e}")
                for name in dirs:
                    try:
                        os.chmod(os.path.join(root, name), 0o777)  # Make the directory writable
                        os.rmdir(os.path.join(root, name))
                    except Exception as e:
                        print(f"Error removing directory {name}: {e}")
            # Now delete the main folder
            try:
                os.rmdir(path)
            except Exception as e:
                print(f"Error removing directory {path}: {e}")
        else:
            try:
                os.remove(path)
            except Exception as e:
                print(f"Error removing file {path}: {e}")

# ---------- INITIALIZES ----------

log_status("Clearing pycache...")
clear_pycache()

log_status("Checking for package updates and requirements...")
check_and_install_requirements()

# ---------- MAIN SCRIPT ----------

if __name__ == '__main__':
    while True:

        load_dotenv()

        # Step 1: Remove the tmp folder if it already exists
        tmp_dir = "tmp"
        log_status("Checking for pre-existing temporary folders...")
        if os.path.exists(tmp_dir):
            log_status(f"Temporary directory ({tmp_dir}) exists. Deleting it...")
            try:
                force_remove(tmp_dir)
                log_status(f"Temporary directory ({tmp_dir}) deleted.")
            except Exception as e:
                log_status(f"Failed to delete temporary directory ({tmp_dir}): {e}", level=logging.ERROR)

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
            commit_data = get_latest_commits(PRIVATE_REPO_OWNER, PRIVATE_REPO_NAME, PRIVATE_BRANCH, GITHUB_TOKEN)
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
            # Step 5: Save commit data to files and push them
            log_status(f"Saving {len(new_commits)} new commits to files...")
            save_commits(new_commits, PARENT_BRANCH)
        else:
            log_status("No new commits to process.")

        # Step 6: Clean up
        log_status(f"Cleaning up temporary directory {tmp_dir}...")
        shutil.rmtree(tmp_dir)
        log_status("Process completed successfully!")

        # Wait for 60 seconds before the next iteration
        log_status("Waiting 60 seconds before next iteration...")
        time.sleep(60)
