param(
    [string]$LinkPath,
    [string]$Target,
    [string]$ScriptArgs = "",
    [string]$WorkDir = "",
    [string]$Icon = ""
)

$shell = New-Object -ComObject WScript.Shell

$name = "LyriCast.lnk"

if ($LinkPath -eq "DESKTOP") {
    $LinkPath = Join-Path $shell.SpecialFolders.Item("Desktop") $name
} elseif ($LinkPath -eq "STARTUP") {
    $LinkPath = Join-Path $shell.SpecialFolders.Item("Startup") $name
}

$s = $shell.CreateShortcut($LinkPath)
$s.TargetPath = $Target
if ($ScriptArgs) {
    if ($ScriptArgs.Contains(" ")) {
        $s.Arguments = '"' + $ScriptArgs + '"'
    } else {
        $s.Arguments = $ScriptArgs
    }
}
if ($WorkDir) { $s.WorkingDirectory = $WorkDir }
if ($Icon)    { $s.IconLocation = $Icon }
$s.Description = "LyriCast - desktop lyrics for LAN speakers"
$s.Save()

Write-Output ("OK: " + $LinkPath)
Write-Output ("    Args    = " + $s.Arguments)
Write-Output ("    WorkDir = " + $s.WorkingDirectory)
