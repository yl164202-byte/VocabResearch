[CmdletBinding()]
param(
    [ValidateSet('Audit', 'SyntheticTest')]
    [string] $Action = 'Audit',
    [string] $Cli = 'supabase'
)

$ErrorActionPreference = 'Stop'
$projectRef = 'pznehaenpfadyjdqgpyh'
$target = "--remote=$projectRef"
$repository = Split-Path -Parent $PSScriptRoot
$preflight = Join-Path $PSScriptRoot 'preflight.sql'
$integration = Join-Path $PSScriptRoot 'cloud_integration.sql'

function Invoke-ProjectCli {
    & $Cli @args
    if ($LASTEXITCODE -ne 0) {
        throw "Supabase CLI failed with exit code $LASTEXITCODE."
    }
}

Push-Location -LiteralPath $repository
try {
    Invoke-ProjectCli db query $target --read-only --file $preflight
    if ($Action -eq 'Audit') {
        Invoke-ProjectCli migration list $target
    } else {
        Invoke-ProjectCli db query $target --file $integration --yes
    }
} finally {
    Pop-Location
}
