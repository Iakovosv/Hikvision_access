<#
    Check the Hikvision access door command without opening the door.

    Runs three read-only checks against Home Assistant:
      1. Reads the config entry for the integration.
      2. Downloads the diagnostics and prints the door_commands section, which is the
         exact method, path and body that would be sent for each door.
      3. Calls the open_door service with dry_run = true, which builds and logs the
         command without sending it.

    None of these send a door command to the terminal. Nothing unlocks.

    Usage:
        $env:HA_URL   = "http://homeassistant.local:8123"
        $env:HA_TOKEN = "<long lived access token>"
        ./check-door-command.ps1

    Create the token under your Home Assistant profile: Security > Long-lived access
    tokens. It has to belong to an administrator, otherwise the diagnostics are refused.
#>

[CmdletBinding()]
param(
    [string]$HaUrl = $env:HA_URL,
    [string]$Token = $env:HA_TOKEN
)

$ErrorActionPreference = 'Stop'

if (-not $HaUrl) { throw "Set HA_URL to your Home Assistant address, for example http://homeassistant.local:8123" }
if (-not $Token) { throw "Set HA_TOKEN to a long-lived access token from your Home Assistant profile" }

$HaUrl = $HaUrl.TrimEnd('/')
$headers = @{ Authorization = "Bearer $Token" }

Write-Host "`n=== 1. Looking for the integration ===" -ForegroundColor Cyan
$entries = Invoke-RestMethod -Uri "$HaUrl/api/config/config_entries/entry" -Headers $headers -Method Get
$entry = $entries | Where-Object { $_.domain -eq 'hikvision_access' } | Select-Object -First 1

if (-not $entry) {
    throw "No hikvision_access config entry found. Is the integration set up?"
}
Write-Host ("Entry {0}  state={1}" -f $entry.entry_id, $entry.state)

Write-Host "`n=== 2. Diagnostics: what would be sent ===" -ForegroundColor Cyan
$diag = Invoke-RestMethod -Uri "$HaUrl/api/diagnostics/config_entry/$($entry.entry_id)" -Headers $headers -Method Get

Write-Host ("Device: {0} {1}" -f $diag.data.device.model, $diag.data.device.firmware)
Write-Host ("Doors reported: {0}" -f ($diag.data.door_numbers -join ', '))
Write-Host ("Last update ok: {0}" -f $diag.data.last_update_success)

Write-Host "`nDoor commands that WOULD be sent (nothing is sent by reading this):" -ForegroundColor Yellow
$diag.data.door_commands.PSObject.Properties | ForEach-Object {
    $c = $_.Value
    Write-Host ("  {0}: {1} /ISAPI/{2}" -f $_.Name, $c.method, $c.path)
    Write-Host ("      body: {0}" -f $c.body)
}

Write-Host "`n=== 3. dry_run: build the command, send nothing ===" -ForegroundColor Cyan
$body = @{ door_no = 1; dry_run = $true } | ConvertTo-Json
try {
    Invoke-RestMethod -Uri "$HaUrl/api/services/hikvision_access/open_door" `
        -Headers $headers -Method Post -Body $body -ContentType 'application/json' | Out-Null
    Write-Host "Service accepted the dry run. Check Home Assistant logs for the line:" -ForegroundColor Green
    Write-Host "  Dry run: would send PUT AccessControl/RemoteControl/door/1 with body <RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>"
    Write-Host "(nothing was sent to the device)"
} catch {
    Write-Host "The service call failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "A failure here is itself useful: it says the command never reaches the device."
}

Write-Host "`nDone. No door command was sent." -ForegroundColor Green
Write-Host "If both sections name door/1 with PUT and <cmd>open</cmd>, the command is correct." -ForegroundColor Green
