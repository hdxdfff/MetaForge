param(
  [Parameter(Mandatory=$true)][string]$Url,
  [string]$Profile = "default"
)
$node = 'D:\codex\tools\node-v22.22.1-win-x64\node.exe'
$script = 'D:\codex\tools\browser-automation\login-session.js'
$arguments = @($script, '--url', $Url, '--profile', $Profile)
Start-Process -FilePath $node -ArgumentList $arguments | Out-Null
$result = @{
  ok = $true
  message = 'Login session launched in a separate browser process. Sign in, then close the browser window to persist the session.'
  url = $Url
  profile = $Profile
  profileDir = "D:\codex\tools\browser-automation\profiles\$Profile"
  timestamp = (Get-Date).ToString('o')
}
$result | ConvertTo-Json -Depth 3
