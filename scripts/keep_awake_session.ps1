# Keeps the laptop awake for the duration of this PowerShell session.
# Uses the Win32 SetThreadExecutionState API - the clean, official way
# Windows exposes "this process needs the machine to stay on" semantics.
# Zero side effects: no fake keystrokes, no Scroll Lock toggling, no
# registry changes. When you close this PowerShell window, sleep
# prevention lifts automatically.
#
# Run this in a SEPARATE PowerShell window from the one doing the work.
# The flag is per-thread, so the other window's sleep/lid behaviour is
# untouched unless it also runs this.

$sig = @"
using System;
using System.Runtime.InteropServices;
public static class Power {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
Add-Type -TypeDefinition $sig

# ES_CONTINUOUS         = 0x80000000 - the flag is in effect until cleared
# ES_SYSTEM_REQUIRED    = 0x00000001 - prevents sleep
# ES_DISPLAY_REQUIRED   = 0x00000002 - prevents display turning off
[uint32]$ES_CONTINUOUS       = [uint32]2147483648
[uint32]$ES_SYSTEM_REQUIRED  = 1
[uint32]$ES_DISPLAY_REQUIRED = 2

$flags = $ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_DISPLAY_REQUIRED
$prev = [Power]::SetThreadExecutionState($flags)

Write-Host "Keep-awake ACTIVE. Sleep + display-off are suppressed for this"
Write-Host "PowerShell session. Close this window (or Ctrl+C) to release."
Write-Host ""
Write-Host ("(Previous execution state: 0x{0:X8})" -f $prev)
Write-Host ""
Write-Host "Heartbeat every 60s. Press Ctrl+C to stop:"

try {
    $i = 0
    while ($true) {
        $i++
        $stamp = Get-Date -Format "HH:mm:ss"
        Write-Host ("  [{0}] heartbeat #{1} - machine kept awake" -f $stamp, $i)
        Start-Sleep -Seconds 60
    }
} finally {
    # Release on exit (including Ctrl+C).
    [Power]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Write-Host ""
    Write-Host "Keep-awake RELEASED. Normal sleep behaviour restored."
}
