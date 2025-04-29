param(
    [string]$SSH_KEY_PATH
)

# Check if ssh-agent is running, start it if not
$sshAgentService = Get-Service -Name "ssh-agent" -ErrorAction SilentlyContinue
if ($null -eq $sshAgentService) {
    Write-Host "[ERROR] ssh-agent service not found. Make sure OpenSSH is installed."
    exit 1
}

# Start the ssh-agent service if it's not running
if ($sshAgentService.Status -ne "Running") {
    Start-Service -Name "ssh-agent"
    Write-Host "[INFO] ssh-agent service started."
}

# Add the SSH key to the agent
if (-not (Test-Path $SSH_KEY_PATH)) {
    Write-Host "[ERROR] SSH key file not found at path: $SSH_KEY_PATH"
    exit 1
}

ssh-add $SSH_KEY_PATH
Write-Host "[INFO] SSH key added to ssh-agent."