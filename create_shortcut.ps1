$ErrorActionPreference = 'Stop'
$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop 'CapCut Auto Editor.lnk'))
$link.TargetPath = (Join-Path $env:windir 'System32\wscript.exe')
$link.Arguments = '"' + (Join-Path $folder 'start_hidden.vbs') + '"'
$link.WorkingDirectory = $folder
$link.IconLocation = (Join-Path $folder 'assets\app_icon.ico') + ',0'
$link.Description = 'CapCut Auto Editor — монтаж музыки и субтитров'
$link.Save()
Write-Host "Shortcut created on Desktop: $($link.FullName)"
