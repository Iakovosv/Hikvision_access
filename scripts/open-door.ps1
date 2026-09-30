<#
    Open a door through the Hikvision Access Control integration in Home Assistant.

    This calls the integration's own service, so the request that reaches the terminal is
    built by the integration itself. Nothing here talks to the terminal directly.

    It first prints the exact request that would be sent, read from the diagnostics, then
    either sends it or, with -DryRun, stops there. A dry run builds and logs the request
    without sending it, so it is the safe way to confirm the command before a door moves.

    Usage:
        $env:HA_URL   = "http://homeassistant.local:8123"
        $env:HA_TOKEN = "<long lived access token>"

        ./open-door.ps1 -DryRun          # show the command, send nothing
        ./open-door.ps1                  # send the command for door 1
        ./open-door.ps1 -DoorNo 2        # send it for door 2

    Create the token under your Home Assistant profile: Security > Long-lived access
    tokens. It has to belong to an administrator, because the diagnostics are refused
    otherwise.
#>

[CmdletBinding()]
param(
    [string]$HaUrl = $env:HA_URL,
    [string]$Token = $env:HA_TOKEN,
    [int]$DoorNo = 1,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

if (-not $HaUrl) { throw "Set HA_URL to your Home Assistant address, for example http://homeassistant.local:8123" }
if (-not $Token) { throw "Set HA_TOKEN to a long-lived access token from your Home Assistant profile" }

$HaUrl = $HaUrl.TrimEnd('/')
$headers = @{ Authorization = "Bearer $Token" }

Write-Host "`n=== The integration and its door command ===" -ForegroundColor Cyan
$entries = Invoke-RestMethod -Uri "$HaUrl/api/config/config_entries/entry" -Headers $headers -Method Get
$entry = $entries | Where-Object { $_.domain -eq 'hikvision_access' } | Select-Object -First 1
if (-not $entry) { throw "No hikvision_access config entry found. Is the integration set up?" }

$diag = Invoke-RestMethod -Uri "$HaUrl/api/diagnostics/config_entry/$($entry.entry_id)" -Headers $headers -Method Get
$device = $diag.data.device
Write-Host ("Device: {0} {1}" -f $device.model, $device.firmware)
Write-Host ("Doors reported: {0}" -f ($diag.data.door_numbers -join ', '))

$preview = $diag.data.door_commands."door_$DoorNo"
if (-not $preview) {
    throw "The diagnostics name no door $DoorNo. Doors reported: $($diag.data.door_numbers -join ', ')"
}

Write-Host "`nThe exact request the integration would send:" -ForegroundColor Yellow
Write-Host ("  {0} /ISAPI/{1}" -f $preview.method, $preview.path)
Write-Host ("  body: {0}" -f $preview.body)

if ($DryRun) {
    Write-Host "`n=== Dry run: the request is built and logged, nothing is sent ===" -ForegroundColor Cyan
    $body = @{ door_no = $DoorNo; dry_run = $true } | ConvertTo-Json
    Invoke-RestMethod -Uri "$HaUrl/api/services/hikvision_access/open_door" -Headers $headers `
        -Method Post -Body $body -ContentType 'application/json' | Out-Null
    Write-Host "The service accepted the dry run. Home Assistant logs a line like:" -ForegroundColor Green
    Write-Host ("  Dry run: would send {0} {1} with body {2}" -f $preview.method, $preview.path, $preview.body)
    Write-Host "Nothing was sent to the terminal." -ForegroundColor Green
    return
}

Write-Host "`n=== Sending the command for door $DoorNo ===" -ForegroundColor Cyan
$body = @{ door_no = $DoorNo } | ConvertTo-Json
try {
    Invoke-RestMethod -Uri "$HaUrl/api/services/hikvision_access/open_door" -Headers $headers `
        -Method Post -Body $body -ContentType 'application/json' | Out-Null
    Write-Host "Home Assistant accepted the service call." -ForegroundColor Green
} catch {
    Write-Host "The service call failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "The command never reached the terminal." -ForegroundColor Red
    exit 1
}

# The diagnostics are read again so the answer comes from the terminal, not from the call.
Start-Sleep -Seconds 2
$diag2 = Invoke-RestMethod -Uri "$HaUrl/api/diagnostics/config_entry/$($entry.entry_id)" -Headers $headers -Method Get
$status = $diag2.data.door_status
if ($status.supported) {
    $door = $status.doors | Where-Object { $_.door_no -eq $DoorNo }
    Write-Host ("`nThe terminal now reports door {0}: lock={1} magnet={2}" -f `
        $DoorNo, $(if ($door.locked) { 'locked' } else { 'unlocked' }), $(if ($door.magnet_open) { 'OPEN' } else { 'closed' }))
    Write-Host "If lock turned unlocked, the terminal carried the command to the relay." -ForegroundColor Green
    Write-Host "A magnet that never reads OPEN points at the relay or the lock, not the command." -ForegroundColor Yellow
} else {
    Write-Host "`nThe terminal did not report a door status: $($status.error)" -ForegroundColor Yellow
}

if ($diag2.data.last_exception) {
    Write-Host ("`nThe integration recorded an error: {0}" -f $diag2.data.last_exception) -ForegroundColor Red
}
