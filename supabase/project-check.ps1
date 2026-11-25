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
        $migrationDir = Join-Path $PSScriptRoot 'migrations'
        Write-Output 'Local migration files:'
        Get-ChildItem -LiteralPath $migrationDir -Filter '*.sql' -File | Sort-Object Name | ForEach-Object Name
        Write-Output 'Remote migration history:'
        $historyQuery = @"
select to_regclass('supabase_migrations.schema_migrations') as history_table,
       case when to_regclass('supabase_migrations.schema_migrations') is null then array[]::text[]
            else xpath('//version/text()', query_to_xml(
                'select version from supabase_migrations.schema_migrations order by version',
                true, false, ''
            ))::text[] end as versions;
"@
        Invoke-ProjectCli db query $target --read-only $historyQuery
    } else {
        Invoke-ProjectCli db query $target --file $integration --yes
    }
} finally {
    Pop-Location
}
