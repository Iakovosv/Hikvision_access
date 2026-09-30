<#
    Test a Hikvision access terminal directly, without Home Assistant.

    Two read-only checks always run. The door only moves with -Open, so run it as often as
    you like without one.

    Usage:
        .\test-lock.ps1 -Ip 192.168.1.163 -Password 'THE_PASSWORD'
        .\test-lock.ps1 -Ip 192.168.1.163 -Password 'THE_PASSWORD' -Open

    The username defaults to admin, the door to 1.
#>

param(
    [string]$Ip = "192.168.1.163",
    [string]$User = "admin",
    [Parameter(Mandatory = $true)][string]$Password,
    [int]$DoorNo = 1,
    [switch]$Open
)

$ErrorActionPreference = 'Stop'
$base = "http://$Ip"
$creds = "${User}:${Password}"

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    throw "curl.exe is missing. It comes with Windows 10 1803 and later. PowerShell's own Invoke-RestMethod cannot do digest authentication, which the terminal requires."
}

function Invoke-Isapi {
    param([string]$Method, [string]$Path, [string]$Body)

    $curlArgs = @('--silent', '--show-error', '--digest', '-u', $creds, '-X', $Method,
        '-w', '__HTTP__%{http_code}')
    if ($Body) { $curlArgs += @('-H', 'Content-Type: application/xml', '-d', $Body) }
    $curlArgs += "$base/$Path"

    $raw = & curl.exe @curlArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot reach $Ip. Is the terminal powered on and on this network, and is ISAPI enabled?`n$raw"
    }

    $split = ($raw -join "`n") -split '__HTTP__'
    return @{ Body = $split[0].Trim(); Code = [int]$split[1] }
}

function Get-Isapi {
    param([string]$Path)

    $r = Invoke-Isapi -Method GET -Path $Path
    if ($r.Code -eq 401) { throw "Wrong username or password for $Ip (user '$User')." }
    if ($r.Code -ne 200) { throw "$Ip answered HTTP $($r.Code) for $Path.`n$($r.Body)" }
    return $r.Body
}

Write-Host "`n=== Terminal $Ip ===" -ForegroundColor Cyan

Write-Host "`n1. Which doors, and which commands does it accept? (read-only)" -ForegroundColor Yellow
$caps = Get-Isapi -Path "ISAPI/AccessControl/RemoteControl/door/capabilities"
Write-Host $caps
if ($caps -match '<cmd opt="([^"]*)"') {
    $commands = $Matches[1]
    if (($commands -split ',') -contains 'open') {
        Write-Host "   -> 'open' is accepted, so the door command is supported." -ForegroundColor Green
    } else {
        Write-Host "   -> 'open' is NOT in the list: $commands" -ForegroundColor Red
    }
    Write-Host "   -> The terminal accepts: $commands"
}
if ($caps -match '<doorNo[^>]*max="(\d+)"') {
    Write-Host "   -> The terminal controls $($Matches[1]) door(s)." -ForegroundColor Green
}

Write-Host "`n2. Lock and door state, before (read-only)" -ForegroundColor Yellow
$status = Get-Isapi -Path "ISAPI/AccessControl/AcsWorkStatus?format=json"
Write-Host $status
$parsed = $status | ConvertFrom-Json
$lockBefore = $parsed.AcsWorkStatus.doorLockStatus[0]
Write-Host ("   -> doorLockStatus = {0} ({1})" -f $lockBefore, $(if ($lockBefore -eq 0) { 'locked' } else { 'unlocked' })) -ForegroundColor Green
if ($parsed.AcsWorkStatus.doorStatus) {
    # A terminal with no door contact reports 4 here, which means "cannot tell".
    Write-Host ("   -> doorStatus = {0}. A 4 means the terminal has no door contact, so it cannot tell." -f $parsed.AcsWorkStatus.doorStatus[0])
}

if (-not $Open) {
    Write-Host "`nNothing was opened. Add -Open to send the command." -ForegroundColor Cyan
    return
}

Write-Host "`n3. Sending the open command for door $DoorNo" -ForegroundColor Yellow
$body = '<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>'
Write-Host "   PUT /ISAPI/AccessControl/RemoteControl/door/$DoorNo"
Write-Host "   body: $body"

$r = Invoke-Isapi -Method PUT -Path "ISAPI/AccessControl/RemoteControl/door/$DoorNo" -Body $body
if ($r.Code -eq 401) { throw "Wrong username or password for $Ip (user '$User')." }
Write-Host $r.Body

if ($r.Body -match '<statusString>OK</statusString>') {
    Write-Host "   -> The terminal accepted the command." -ForegroundColor Green
} else {
    Write-Host "   -> The terminal did not answer OK. Read the message above." -ForegroundColor Red
}

Start-Sleep -Seconds 2
Write-Host "`n4. Lock state, after (read-only)" -ForegroundColor Yellow
$after = Get-Isapi -Path "ISAPI/AccessControl/AcsWorkStatus?format=json"
$lockAfter = ($after | ConvertFrom-Json).AcsWorkStatus.doorLockStatus[0]
Write-Host ("   -> doorLockStatus = {0} ({1})" -f $lockAfter, $(if ($lockAfter -eq 0) { 'locked' } else { 'unlocked' })) -ForegroundColor Green

if ($lockBefore -eq 0 -and $lockAfter -eq 1) {
    Write-Host "`nThe lock went from locked to unlocked, so the relay fired." -ForegroundColor Green
} elseif ($lockAfter -eq 1) {
    Write-Host "`nThe lock reads unlocked." -ForegroundColor Green
} else {
    Write-Host "`nThe lock still reads locked. The terminal answered OK, so the command reached it" -ForegroundColor Yellow
    Write-Host "and it accepted it: the relay, its wiring, or the lock itself is the suspect." -ForegroundColor Yellow
}
