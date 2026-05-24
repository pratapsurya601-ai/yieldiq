# Mass-close the 18 stale auto-filed GitHub issues identified 2026-05-24.
# Run AFTER `gh auth refresh -s repo` so the keyring token is valid.
# Safe to re-run: skips already-closed issues.

$repo = 'pratapsurya601-ai/yieldiq'

# 15 cron-dead-man + 3 data-completeness + #307 (0/20 broken, false-fire) + #512 (INFY HTTP 0 flake)
$issues = @(
    612, 544, 540, 536, 514, 484, 447, 446, 441, 414, 379, 369, 368, 367,  # cron dead-man
    283, 235, 234,                                                          # data completeness weekly
    307,                                                                    # canary 0/20 broken (false-fire)
    512                                                                     # post-deploy smoke INFY HTTP 0 flake
)

foreach ($n in $issues) {
    Write-Host "Closing #$n..." -NoNewline
    $out = gh issue close $n --repo $repo --reason "not planned" --comment "Auto-filed by monitoring workflow. Mass-closed 2026-05-24 as part of dead-man dedupe cleanup. The dead-man checker workflow has been patched (PR pending) to use a stable rolling title + auto-close on cron recovery, so this pile-up won't recur." 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host " OK" -ForegroundColor Green } else { Write-Host " FAIL: $out" -ForegroundColor Red }
}

Write-Host "`nVerifying..."
$remaining = gh issue list --repo $repo --state open --limit 50 --json number | ConvertFrom-Json
Write-Host "Open issues remaining: $($remaining.Count)"
