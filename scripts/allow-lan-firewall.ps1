#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [int[]]$Ports = @(8090, 8443)
)

$ErrorActionPreference = "Stop"

foreach ($port in $Ports) {
    $name = "NyankoFace LAN TCP $port"
    $existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue

    if ($existing) {
        Set-NetFirewallRule -DisplayName $name -Enabled True -Direction Inbound -Action Allow -Profile Any
        Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $existing -RemoteAddress LocalSubnet
        Set-NetFirewallPortFilter -AssociatedNetFirewallRule $existing -Protocol TCP -LocalPort $port
    }
    else {
        New-NetFirewallRule `
            -DisplayName $name `
            -Description "Allow NyankoFace from devices on the local subnet only." `
            -Enabled True `
            -Direction Inbound `
            -Action Allow `
            -Profile Any `
            -Protocol TCP `
            -LocalPort $port `
            -RemoteAddress LocalSubnet | Out-Null
    }
}

Write-Host "NyankoFace LAN firewall access enabled for TCP: $($Ports -join ', ')"
