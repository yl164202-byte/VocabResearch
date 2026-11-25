[CmdletBinding()]
param(
    [switch] $Cloud,
    [ValidateSet('Local','Browser','Cloud','Offline','All')]
    [string] $Mode='Offline',
    [string] $Cli='supabase',
    [string] $Chrome=(Join-Path $env:ProgramFiles 'Google/Chrome/Application/chrome.exe')
)
$ErrorActionPreference='Stop'
if($Cloud){
    if($PSBoundParameters.ContainsKey('Mode')){throw 'Use either -Cloud or -Mode, not both'}
    $Mode='All'
}
$runLocal=$Mode -in 'Local','Offline','All'
$runBrowser=$Mode -in 'Browser','Offline','All'
$runCloud=$Mode -in 'Cloud','All'
if(($runBrowser -or $runCloud) -and !(Test-Path -LiteralPath $Chrome -PathType Leaf)){
    throw 'Chrome executable not found for browser tests. Specify -Chrome or use -Mode Local.'
}
$repo=Split-Path -Parent $PSScriptRoot
$ref='pznehaenpfadyjdqgpyh'
$previousPreview=$env:VOCAB_PREVIEW_HTML
$preview=Join-Path ([IO.Path]::GetTempPath()) ("vocab-preview-"+[guid]::NewGuid()+".html")

function Check-Exit($stage) {
    if($LASTEXITCODE -ne 0){throw "$stage failed with exit code $LASTEXITCODE"}
}

Push-Location -LiteralPath $repo
try {
    $env:PYTHONIOENCODING='utf-8'
    if($runBrowser){
        $env:VOCAB_PREVIEW_HTML=$preview
    } else {
        Remove-Item Env:VOCAB_PREVIEW_HTML -ErrorAction SilentlyContinue
    }
    if($runBrowser -or $runCloud){
        $env:VOCAB_E2E_CHROME=$Chrome
    }
    if($runLocal){
        python -B tests/teacher_acceptance.py
        Check-Exit 'Teacher GUI acceptance'
        node --test tests/supabase.test.mjs
        Check-Exit 'Local database tests'
    } elseif($runBrowser){
        python -B tests/teacher_acceptance.py TeacherAcceptance.test_07_reopen_saved_version_and_restore_preview
        Check-Exit 'Generate teacher preview fixture'
    }
    if($runBrowser){
        node --test tests/preview-browser.test.mjs
        Check-Exit 'Chrome preview'
    }
    if(!$runCloud){return}

    $origin=git remote get-url origin
    Check-Exit 'Read GitHub origin'
    if($origin -notmatch '^https://github\.com/yl164202-byte/VocabResearch(?:\.git)?$'){
        throw 'Cloud acceptance requires the VocabResearch GitHub origin'
    }
    $env:GIT_TERMINAL_PROMPT='0'
    $env:GCM_INTERACTIVE='Never'
    $env:SUPABASE_CLI=$Cli
    $raw=(& $Cli projects api-keys --remote=$ref --output-format json 2>$null) -join "`n"
    Check-Exit 'Supabase public configuration'
    $env:VOCAB_E2E_KEY=[regex]::Match($raw,'sb_publishable_[A-Za-z0-9_-]+').Value
    Remove-Variable raw
    if(!$env:VOCAB_E2E_KEY){throw 'No publishable key returned'}
    $env:VOCAB_E2E_URL="https://$ref.supabase.co"
    if(!$env:GITHUB_TOKEN){
        $credential=@("protocol=https`nhost=github.com`npath=yl164202-byte/VocabResearch.git`n`n" |
            git -c credential.interactive=never credential fill 2>$null)
        Check-Exit 'GitHub Credential Manager'
        $password=$credential | Where-Object {$_.StartsWith('password=')} | Select-Object -First 1
        if(!$password){throw 'GitHub credentials unavailable'}
        $env:GITHUB_TOKEN=$password.Substring(9)
        $injectedToken=$true
        Remove-Variable password,credential
    }
    $id=[guid]::NewGuid().ToString('N')
    $env:VOCAB_E2E_BRANCH='codex/vocab-accept-it-'+$id.Substring(0,8)
    $env:VOCAB_E2E_COURSE='IT_'+$id
    $env:VOCAB_E2E_CODE='IT_'+$id.Substring(0,20)
    $env:VOCAB_E2E_CODE2=$env:VOCAB_E2E_CODE+'B'
    $env:VOCAB_E2E_PIN=[guid]::NewGuid().ToString('N')
    $env:VOCAB_E2E_PIN2=[guid]::NewGuid().ToString('N')
    $generatedTestIdentity=$true
    $env:VOCAB_E2E_MULTIPLE='1'
    git -c credential.interactive=never push origin "HEAD:refs/heads/$env:VOCAB_E2E_BRANCH"
    Check-Exit 'Create isolated GitHub branch'
    python -B tests/teacher_gui.py --cloud
    Check-Exit 'Live teacher GUI publication'
    $published=git ls-remote origin "refs/heads/$env:VOCAB_E2E_BRANCH"
    Check-Exit 'Read isolated branch'
    if(!$published){throw 'Isolated branch not found'}
    $sha=($published -split '\s+')[0]
    $env:VOCAB_E2E_ASSET_BASE="https://raw.githubusercontent.com/yl164202-byte/VocabResearch/$sha/student"
    node --test tests/cloud-browser.test.mjs
    Check-Exit 'Live student browser acceptance'
    python -B tests/teacher_gui.py --status
    Check-Exit 'Teacher records and stored event parity'
    "Verified synthetic publication: $env:VOCAB_E2E_BRANCH"
} finally {
    Pop-Location
    if(Test-Path -LiteralPath $preview){Remove-Item -LiteralPath $preview}
    if($null -eq $previousPreview){
        Remove-Item Env:VOCAB_PREVIEW_HTML -ErrorAction SilentlyContinue
    } else {
        $env:VOCAB_PREVIEW_HTML=$previousPreview
    }
    if($generatedTestIdentity){
        foreach($var in @('VOCAB_E2E_PIN','VOCAB_E2E_PIN2')){
            Remove-Item "Env:$var" -ErrorAction SilentlyContinue
        }
    }
    if($injectedToken){Remove-Item Env:GITHUB_TOKEN -ErrorAction SilentlyContinue}
}
