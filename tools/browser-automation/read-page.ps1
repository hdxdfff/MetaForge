param(
  [Parameter(Mandatory=$true)][string]$Url,
  [string]$Out = "D:\codex\output\browser\page.json",
  [string]$Screenshot = "",
  [string]$Profile = "",
  [string]$Proxy = "",
  [switch]$Headed,
  [string]$WaitFor = "",
  [string]$Selector = "body"
)
$node = 'D:\codex\tools\node-v22.22.1-win-x64\node.exe'
$script = 'D:\codex\tools\browser-automation\read-page.js'
$args = @($script, '--url', $Url, '--out', $Out, '--selector', $Selector)
if ($Screenshot) { $args += @('--screenshot', $Screenshot) }
if ($Profile) { $args += @('--profile', $Profile) }
if ($Proxy) { $args += @('--proxy', $Proxy) }
if ($Headed) { $args += '--headed' }
if ($WaitFor) { $args += @('--waitFor', $WaitFor) }
& $node @args
