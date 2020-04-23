# Taken from https://github.com/pypa/pip/blob/ceaf75b9ede9a9c25bcee84fe512fa6774889685/.azure-pipelines/scripts/New-RAMDisk.ps1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true,
    HelpMessage="Drive letter to use for the RAMDisk")]
    [String]$drive,
    [Parameter(HelpMessage="Size to allocate to the RAMDisk")]
    [UInt64]$size=1GB
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Output "Installing FS-iSCSITarget-Server"
Install-WindowsFeature -Name FS-iSCSITarget-Server

Write-Output "Starting MSiSCSI"
Start-Service MSiSCSI
$retry = 10
do {
    $service = Get-Service MSiSCSI
    if ($service.Status -eq "Running") {
        break;
    }
    $retry--
    Start-Sleep -Milliseconds 500
} until ($retry -eq 0)

$service = Get-Service MSiSCSI
if ($service.Status -ne "Running") {
    throw "MSiSCSI is not running"
}

Write-Output "Configuring Firewall"
Get-NetFirewallServiceFilter -Service MSiSCSI | Enable-NetFirewallRule

Write-Output "Configuring RAMDisk"
# Must use external-facing IP address, otherwise New-IscsiTargetPortal is
# unable to connect.
$ip = (
    Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {$_.IPAddress -ne "127.0.0.1"}
)[0].IPAddress
if (
    -not (Get-IscsiServerTarget -ComputerName localhost | Where-Object {$_.TargetName -eq "ramdisks"})
) {
    New-IscsiServerTarget `
        -ComputerName localhost `
        -TargetName ramdisks `
        -InitiatorId IPAddress:$ip
}

$newVirtualDisk = New-IscsiVirtualDisk `
    -ComputerName localhost `
    -Path ramdisk:local$drive.vhdx `
    -Size $size
Add-IscsiVirtualDiskTargetMapping `
    -ComputerName localhost `
    -TargetName ramdisks `
    -Path ramdisk:local$drive.vhdx

Write-Output "Connecting to iSCSI"
New-IscsiTargetPortal -TargetPortalAddress $ip
Get-IscsiTarget | Where-Object {!$_.IsConnected} | Connect-IscsiTarget

Write-Output "Configuring disk"
$newDisk = Get-IscsiConnection |
    Get-Disk |
    Where-Object {$_.SerialNumber -eq $newVirtualDisk.SerialNumber}

Set-Disk -InputObject $newDisk -IsOffline $false
Initialize-Disk -InputObject $newDisk -PartitionStyle MBR
New-Partition -InputObject $newDisk -UseMaximumSize -DriveLetter $drive

Format-Volume -DriveLetter $drive -NewFileSystemLabel Temp -FileSystem NTFS
