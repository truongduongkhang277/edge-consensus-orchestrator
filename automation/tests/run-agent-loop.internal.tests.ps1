[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$automationRoot = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Split-Path -Parent $automationRoot
$runnerPath = Join-Path $automationRoot 'run-agent-loop.ps1'
$policy = Get-Content -LiteralPath (Join-Path $automationRoot 'policy.json') -Raw | ConvertFrom-Json
$temporaryRoot = Join-Path $repositoryRoot ('.tmp\agent-loop-tests-' + [Guid]::NewGuid().ToString('N'))
$mainStatusBefore = (git status --short | Out-String)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-GuardCase {
    param([string[]]$Arguments, [int]$ExpectedExitCode, [string]$Name)
    $result = Invoke-NativeCapture -Command (Join-Path $script:guardRoot 'git.cmd') -Arguments $Arguments -WorkingDirectory $repositoryRoot
    Assert-True -Condition ($result.ExitCode -eq $ExpectedExitCode) -Message "$Name returned $($result.ExitCode), expected $ExpectedExitCode."
    Write-Host "PASS: $Name"
}

$oldLibraryMode = $env:AGENT_LOOP_LIBRARY_ONLY
try {
    $env:AGENT_LOOP_LIBRARY_ONLY = '1'
    . $runnerPath -Requirement 'load internal test functions'
}
finally {
    $env:AGENT_LOOP_LIBRARY_ONLY = $oldLibraryMode
}

try {
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    foreach ($stageName in @('deepseekAnalysis', 'deepseekTestTriage')) {
        $stage = $policy.agents.$stageName
        Assert-True -Condition ($stage.command -eq 'npx.cmd') -Message "$stageName must use npx.cmd."
        Assert-True -Condition ((@($stage.arguments) -join ' ') -eq '@deepseek-ai/dsh --profile headless') -Message "$stageName has incorrect DSH arguments."
    }
    Write-Host 'PASS: DeepSeek stages resolve to npx.cmd headless profile'
    $script:guardRoot = Join-Path $temporaryRoot 'guard'
    $realGit = Resolve-GitExecutable
    New-GitGuard -Directory $script:guardRoot -RealGitExecutable $realGit -ForbiddenArguments @($policy.safety.forbiddenGitArguments)

    Invoke-GuardCase -Arguments @('commit', '-m', 'blocked') -ExpectedExitCode 97 -Name 'git commit is denied'
    Invoke-GuardCase -Arguments @('push') -ExpectedExitCode 97 -Name 'git push is denied'
    Invoke-GuardCase -Arguments @('reset', '--hard') -ExpectedExitCode 97 -Name 'git reset --hard is denied'
    Invoke-GuardCase -Arguments @('status', '--short') -ExpectedExitCode 0 -Name 'git status is allowed'

    $mockRoot = Join-Path $temporaryRoot 'mock'
    $mockMain = Join-Path $mockRoot 'main'
    $mockWorktree = Join-Path $mockRoot 'worktree'
    New-Item -ItemType Directory -Path $mockMain, $mockWorktree -Force | Out-Null
    $mockGitScript = @'
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArguments)
$location = (Get-Location).Path
$isMain = (Split-Path -Leaf $location) -eq 'main'
$command = @($GitArguments) -join ' '
if ($command -eq 'rev-parse HEAD') {
    if (Test-Path -LiteralPath (Join-Path $location 'head.changed')) { 'changed-head' } else { 'baseline-head' }
    exit 0
}
if ($command -eq 'rev-parse --abbrev-ref HEAD') {
    if ($isMain) { 'main-branch' } else { 'worktree-branch' }
    exit 0
}
if ($GitArguments[0] -eq 'status') {
    if (Test-Path -LiteralPath (Join-Path $location 'status.changed')) { ' M unexpected.txt' }
    exit 0
}
if ($GitArguments[0] -eq 'diff' -or $GitArguments[0] -eq 'ls-files') { exit 0 }
exit 2
'@
    Set-Content -LiteralPath (Join-Path $mockRoot 'mock-git.ps1') -Value $mockGitScript -Encoding utf8
    $mockGitCommand = @'
@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0mock-git.ps1" %*
exit /b %ERRORLEVEL%
'@
    Set-Content -LiteralPath (Join-Path $mockRoot 'mock-git.cmd') -Value $mockGitCommand -Encoding ascii
    $mockGit = Join-Path $mockRoot 'mock-git.cmd'
    $mockSafety = [pscustomobject]@{
        maxChangedFiles = 20
        maxDiffLines = 1000
        allowedChangedPaths = @('**')
        protectedPaths = @('.env')
    }
    $baselineMain = Get-GitSnapshot -WorkingDirectory $mockMain -GitExecutable $mockGit
    $baselineWorktree = Get-GitSnapshot -WorkingDirectory $mockWorktree -GitExecutable $mockGit

    [void](New-Item -ItemType File -Path (Join-Path $mockWorktree 'head.changed'))
    $headFailureDetected = $false
    try {
        [void](Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $mockMain -Worktree $mockWorktree -Safety $mockSafety -GitExecutable $mockGit)
    }
    catch { $headFailureDetected = $_.Exception.Message -match 'worktree HEAD changed' }
    Assert-True $headFailureDetected 'Changed worktree HEAD was not rejected.'
    Remove-Item -LiteralPath (Join-Path $mockWorktree 'head.changed')
    Write-Host 'PASS: changed HEAD fails the runner guard'

    [void](New-Item -ItemType File -Path (Join-Path $mockMain 'status.changed'))
    $mainStatusFailureDetected = $false
    try {
        [void](Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $mockMain -Worktree $mockWorktree -Safety $mockSafety -GitExecutable $mockGit)
    }
    catch { $mainStatusFailureDetected = $_.Exception.Message -match 'main working tree status changed' }
    Assert-True $mainStatusFailureDetected 'Changed main working tree was not rejected.'
    Remove-Item -LiteralPath (Join-Path $mockMain 'status.changed')
    Write-Host 'PASS: changed main working tree fails the runner guard'

    $mockClaudeScript = @'
[System.IO.File]::WriteAllText($env:MOCK_STDIN_FILE, [Console]::In.ReadToEnd())
[System.IO.File]::AppendAllText($env:MOCK_CALL_FILE, "called`r`n")
'VERDICT: APPROVED'
'@
    Set-Content -LiteralPath (Join-Path $mockRoot 'mock-claude.ps1') -Value $mockClaudeScript -Encoding utf8
    $mockClaudeCommand = @'
@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0mock-claude.ps1"
exit /b %ERRORLEVEL%
'@
    Set-Content -LiteralPath (Join-Path $mockRoot 'mock-claude.cmd') -Value $mockClaudeCommand -Encoding ascii
    $callFile = Join-Path $mockRoot 'claude-calls.log'
    $stdinFile = Join-Path $mockRoot 'claude-stdin.txt'
    $script:mockClaudeConfigurationForTest = [pscustomobject]@{ command = (Join-Path $mockRoot 'mock-claude.cmd'); arguments = @(); timeoutSeconds = 10 }
    $script:mockClaudeWorktreeForTest = $mockWorktree
    $script:mockClaudeRootForTest = $mockRoot
    $script:mockClaudeCallFileForTest = $callFile
    $script:mockClaudeStdinForTest = $stdinFile
    $mockClaudeInvocation = {
        Invoke-AgentStage -Name 'mock Claude' -Configuration $script:mockClaudeConfigurationForTest -Prompt 'review via stdin' -WorkingDirectory $script:mockClaudeWorktreeForTest -OutputPath (Join-Path $script:mockClaudeRootForTest 'mock-claude-output.md') -Environment @{ MOCK_CALL_FILE = $script:mockClaudeCallFileForTest; MOCK_STDIN_FILE = $script:mockClaudeStdinForTest }
    }

    $claudeCalls = 0
    $failedGate = Invoke-ClaudeGate -TestsPassed $false -DiffCheckPassed $true -PolicyPassed $true -NoDeletedFiles $true -StateStable $true -ClaudeCalls $claudeCalls -MaxClaudeCalls 1 -Invocation $mockClaudeInvocation
    Assert-True (-not $failedGate.Called -and -not (Test-Path -LiteralPath $callFile)) 'Claude was called after failed tests.'
    Write-Host 'PASS: failed tests do not call Claude'

    $passingGate = Invoke-ClaudeGate -TestsPassed $true -DiffCheckPassed $true -PolicyPassed $true -NoDeletedFiles $true -StateStable $true -ClaudeCalls $claudeCalls -MaxClaudeCalls 1 -Invocation $mockClaudeInvocation
    if ($passingGate.Called) { $claudeCalls++ }
    $secondGate = Invoke-ClaudeGate -TestsPassed $true -DiffCheckPassed $true -PolicyPassed $true -NoDeletedFiles $true -StateStable $true -ClaudeCalls $claudeCalls -MaxClaudeCalls 1 -Invocation $mockClaudeInvocation
    $callLines = @(if (Test-Path -LiteralPath $callFile) { Get-Content -LiteralPath $callFile })
    $passingExitCode = if ($null -ne $passingGate.Result) { $passingGate.Result.ExitCode } else { 'null' }
    $passingError = if ($null -ne $passingGate.Result) { $passingGate.Result.Error } else { 'null' }
    Assert-True ($passingGate.Called -and $passingExitCode -eq 0 -and -not $secondGate.Called -and $callLines.Count -eq 1) "Claude was not called exactly once after a passing gate (called=$($passingGate.Called), exit=$passingExitCode, second=$($secondGate.Called), lines=$($callLines.Count), error=$passingError)."
    Write-Host 'PASS: passing tests call Claude exactly once'

    $claudeStdin = Get-Content -LiteralPath $stdinFile -Raw
    Assert-True ($claudeStdin -eq 'review via stdin') 'Claude did not receive its prompt through stdin.'
    $codexStdinFile = Join-Path $mockRoot 'codex-stdin.txt'
    $codexStage = Invoke-AgentStage -Name 'mock Codex' -Configuration $script:mockClaudeConfigurationForTest -Prompt 'codex prompt via stdin' -WorkingDirectory $mockWorktree -OutputPath (Join-Path $mockRoot 'mock-codex-output.md') -Environment @{ MOCK_CALL_FILE = $callFile; MOCK_STDIN_FILE = $codexStdinFile }
    Assert-True ($codexStage.ExitCode -eq 0 -and (Get-Content -LiteralPath $codexStdinFile -Raw) -eq 'codex prompt via stdin') 'Codex did not receive its prompt through stdin.'
    Write-Host 'PASS: Codex and Claude prompts use stdin'

    $specialRequirement = "Yêu cầu `"đặc biệt`" & | ;`r`nkhông được chèn lệnh"
    $specialPrompt = "Requirement: $specialRequirement"
    $taskDirectory = Join-Path $temporaryRoot 'run-directory'
    New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null
    $taskFile = Join-Path $taskDirectory 'deepseek-task.md'
    Write-DeepSeekTaskFile -Path $taskFile -Prompt $specialPrompt
    $taskInvocation = Get-DeepSeekInvocation -Configuration $policy.agents.deepseekAnalysis -TaskFile $taskFile
    $taskBytes = [System.IO.File]::ReadAllBytes($taskFile)
    $taskText = [System.Text.Encoding]::UTF8.GetString($taskBytes)
    $nativeArguments = @($taskInvocation.Arguments | ForEach-Object { ConvertTo-NativeArgument -Argument ([string]$_) }) -join ' '
    Assert-True ($taskText -eq $specialPrompt) 'DeepSeek task file is not valid UTF-8 content.'
    Assert-True ([System.IO.Path]::GetFullPath($taskFile).StartsWith([System.IO.Path]::GetFullPath($taskDirectory), [System.StringComparison]::OrdinalIgnoreCase)) 'DeepSeek task file escaped its run directory.'
    Assert-True ($taskInvocation.Command -eq 'npx.cmd' -and $nativeArguments -notlike "*$specialRequirement*" -and $nativeArguments -like '*deepseek-task.md*') 'Requirement leaked into DeepSeek command arguments.'
    Write-Host 'PASS: DeepSeek prompt uses UTF-8 task file and safe positional path'

    $missingConfiguration = [pscustomobject]@{ command = (Join-Path $temporaryRoot 'missing-agent.cmd'); arguments = @(); timeoutSeconds = 1 }
    $launchFailureStage = Invoke-DeepSeekStage -Name 'mock DeepSeek launch failure' -Configuration $missingConfiguration -Prompt $specialPrompt -TaskFile (Join-Path $taskDirectory 'launch-failure.task.md') -WorkingDirectory $mockWorktree -OutputPath (Join-Path $mockRoot 'launch-failure.md')
    Assert-True ($launchFailureStage.ExitCode -eq -1) 'DeepSeek launch failure did not return failure for triage handling.'
    Write-Host 'PASS: DeepSeek launch failure follows failure path'

    $hangScript = Join-Path $mockRoot 'hang.ps1'
    Set-Content -LiteralPath $hangScript -Value 'Start-Sleep -Seconds 5' -Encoding utf8
    $timeoutConfiguration = [pscustomobject]@{ command = 'powershell.exe'; arguments = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $hangScript); timeoutSeconds = 1 }
    $timeoutStage = Invoke-DeepSeekStage -Name 'mock DeepSeek timeout' -Configuration $timeoutConfiguration -Prompt $specialPrompt -TaskFile (Join-Path $taskDirectory 'timeout.task.md') -WorkingDirectory $mockWorktree -OutputPath (Join-Path $mockRoot 'timeout.md')
    Assert-True ($timeoutStage.ExitCode -eq -1) 'DeepSeek timeout did not return failure for triage handling.'
    Write-Host 'PASS: DeepSeek timeout follows failure path'

    $beforeDryRunTasks = @(Get-ChildItem -LiteralPath $taskDirectory -Force -File | ForEach-Object FullName)
    $dryRunResult = Invoke-NativeCapture -Command 'powershell.exe' -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runnerPath, '-Requirement', $specialRequirement, '-MaxIterations', '1') -WorkingDirectory $repositoryRoot
    Assert-True ($dryRunResult.ExitCode -eq 0) 'Runner dry-run failed during task-file transport test.'
    $afterDryRunTasks = @(Get-ChildItem -LiteralPath $taskDirectory -Force -File | ForEach-Object FullName)
    $beforeDryRunTasksText = @($beforeDryRunTasks) -join "`n"
    $afterDryRunTasksText = @($afterDryRunTasks) -join "`n"
    Assert-True ($beforeDryRunTasksText -eq $afterDryRunTasksText) 'Dry-run created a DeepSeek task file.'
    Write-Host 'PASS: dry-run creates no DeepSeek task file'
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}

$mainStatusAfter = (git status --short | Out-String)
Assert-True ($mainStatusBefore -eq $mainStatusAfter) 'Internal tests changed the main Git status.'
Write-Host 'PASS: main Git status unchanged'

Write-Host 'All internal automation tests passed.'
exit 0
