param(
    [string]$TaskName = "SplitwiseArbitrage",
    [string]$At = "06:00",
    [string]$ProjectPath = (Resolve-Path "$PSScriptRoot\..").Path
)

$python = Join-Path $ProjectPath ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python virtualenv not found at $python"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m splitwise_arbitrage run" `
    -WorkingDirectory $ProjectPath

$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily Splitwise Office/Office Servicios arbitrage" `
    -Force

Write-Host "Installed scheduled task '$TaskName' at $At."
