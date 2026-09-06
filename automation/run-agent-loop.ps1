[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Task,

    [ValidateRange(1, 20)]
    [int]$MaxIterations = 0,

    [switch]$Execute,

    [string]$PolicyPath = (Join-Path $PSScriptRoot 'policy.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[agent-loop] $Message"
}

function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Argument)

    if ($Argument -notmatch '[\s"]' -and $Argument.Length -gt 0) {
        return $Argument
    }

    # Follow the CommandLineToArgvW quoting rules used by native Windows tools.
    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashCount = 0
    foreach ($character in $Argument.ToCharArray()) {
        if ($character -eq '\') {
            $backslashCount++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashCount * 2) + 1)))
            [void]$builder.Append('"')
        }
        else {
            [void]$builder.Append(('\' * $backslashCount))
            [void]$builder.Append($character)
        }
        $backslashCount = 0
    }
    [void]$builder.Append(('\' * ($backslashCount * 2)))
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string]$StandardInput,
        [int]$TimeoutSeconds = 600
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Command
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.CreateNoWindow = $true

    # ProcessStartInfo.ArgumentList is unavailable in Windows PowerShell 5.1.
    $startInfo.Arguments = (@($Arguments | ForEach-Object { ConvertTo-NativeArgument -Argument ([string]$_) }) -join ' ')

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Could not start command: $Command"
    }

    if ($null -ne $StandardInput) {
        $process.StandardInput.Write($StandardInput)
    }
    $process.StandardInput.Close()

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { Write-Warning $_.Exception.Message }
        throw "Command timed out after $TimeoutSeconds seconds: $Command"
    }

    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        StdOut = $stdoutTask.Result
        StdErr = $stderrTask.Result
    }
}

function Assert-RelativeRepositoryPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path) -or $Path -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "Policy path must be repository-relative: $Path"
    }
}

function Convert-GlobToRegex {
    param([Parameter(Mandatory = $true)][string]$Glob)

    $normalized = $Glob.Replace('\', '/')
    $escaped = [Regex]::Escape($normalized)
    $escaped = $escaped.Replace('\*\*', '.*').Replace('\*', '[^/]*').Replace('\?', '[^/]')
    return '^' + $escaped + '$'
}

function Test-PathMatchesAnyGlob {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object[]]$Globs
    )

    $normalized = $Path.Replace('\', '/')
    foreach ($glob in $Globs) {
        if ($normalized -match (Convert-GlobToRegex -Glob ([string]$glob))) {
            return $true
        }
    }
    return $false
}

function Get-ChangedPaths {
    param([Parameter(Mandatory = $true)][string]$WorkingDirectory)

    $result = Invoke-NativeCapture -Command 'git' -Arguments @('status', '--porcelain=v1', '--untracked-files=all') -WorkingDirectory $WorkingDirectory
    if ($result.ExitCode -ne 0) {
        throw "git status failed: $($result.StdErr)"
    }

    $paths = @()
    foreach ($line in ($result.StdOut -split "`r?`n")) {
        if ($line.Length -lt 4) { continue }
        $path = $line.Substring(3).Trim()
        if ($path.Contains(' -> ')) { $path = ($path -split ' -> ', 2)[1] }
        $paths += $path.Trim('"').Replace('\', '/')
    }
    return @($paths | Sort-Object -Unique)
}

function Assert-ChangePolicy {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]$Safety
    )

    $changedPaths = @(Get-ChangedPaths -WorkingDirectory $WorkingDirectory)
    if ($changedPaths.Count -gt [int]$Safety.maxChangedFiles) {
        throw "Changed file count $($changedPaths.Count) exceeds policy limit $($Safety.maxChangedFiles)."
    }

    foreach ($path in $changedPaths) {
        if (Test-PathMatchesAnyGlob -Path $path -Globs @($Safety.protectedPaths)) {
            throw "Protected path changed: $path"
        }
        if (-not (Test-PathMatchesAnyGlob -Path $path -Globs @($Safety.allowedChangedPaths))) {
            throw "Changed path is outside the allowlist: $path"
        }
    }
    return $changedPaths
}

function Get-ReviewDiff {
    param([Parameter(Mandatory = $true)][string]$WorkingDirectory)

    $tracked = Invoke-NativeCapture -Command 'git' -Arguments @('diff', '--no-ext-diff', '--binary', 'HEAD') -WorkingDirectory $WorkingDirectory
    if ($tracked.ExitCode -ne 0) { throw "Could not capture tracked diff: $($tracked.StdErr)" }

    $untrackedResult = Invoke-NativeCapture -Command 'git' -Arguments @('ls-files', '--others', '--exclude-standard') -WorkingDirectory $WorkingDirectory
    if ($untrackedResult.ExitCode -ne 0) { throw "Could not list untracked files: $($untrackedResult.StdErr)" }

    $sections = @($tracked.StdOut)
    foreach ($relativePath in ($untrackedResult.StdOut -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($relativePath)) { continue }
        $fullPath = Join-Path $WorkingDirectory $relativePath
        $bytes = [System.IO.File]::ReadAllBytes($fullPath)
        if ($bytes.Length -gt 262144) {
            $sections += "UNTRACKED FILE (content omitted; larger than 256 KiB): $relativePath"
            continue
        }
        if ($bytes -contains 0) {
            $sections += "UNTRACKED BINARY FILE (content omitted): $relativePath"
            continue
        }
        $content = [System.Text.Encoding]::UTF8.GetString($bytes)
        $sections += "diff --git a/$relativePath b/$relativePath`nnew file`n--- /dev/null`n+++ b/$relativePath`n@@ untracked file @@`n$content"
    }
    return ($sections -join "`n")
}

function Expand-Prompt {
    param(
        [Parameter(Mandatory = $true)][string]$TemplatePath,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )

    $content = Get-Content -LiteralPath $TemplatePath -Raw
    foreach ($key in $Values.Keys) {
        $content = $content.Replace('{{' + $key + '}}', [string]$Values[$key])
    }
    return $content
}

function Invoke-AgentStage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Configuration,
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )

    Write-Step "Running $Name"
    $result = Invoke-NativeCapture -Command ([string]$Configuration.command) -Arguments @($Configuration.arguments) -WorkingDirectory $WorkingDirectory -StandardInput $Prompt -TimeoutSeconds ([int]$Configuration.timeoutSeconds)
    $transcript = @(
        "# $Name",
        "",
        "Exit code: $($result.ExitCode)",
        "",
        "## Standard output",
        "",
        $result.StdOut,
        "",
        "## Standard error",
        "",
        $result.StdErr
    ) -join [Environment]::NewLine
    Set-Content -LiteralPath $OutputPath -Value $transcript -Encoding utf8
    if ($result.ExitCode -ne 0) {
        throw "$Name failed with exit code $($result.ExitCode). See $OutputPath"
    }
    return $result.StdOut
}

function Invoke-TestSuite {
    param(
        [Parameter(Mandatory = $true)][object[]]$Tests,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$OutputDirectory
    )

    $allPassed = $true
    $combined = @()
    foreach ($test in $Tests) {
        Write-Step "Running test: $($test.name)"
        $result = Invoke-NativeCapture -Command ([string]$test.command) -Arguments @($test.arguments) -WorkingDirectory $WorkingDirectory -TimeoutSeconds ([int]$test.timeoutSeconds)
        $safeName = ([string]$test.name) -replace '[^A-Za-z0-9_.-]', '-'
        $logPath = Join-Path $OutputDirectory "test-$safeName.log"
        $log = "Exit code: $($result.ExitCode)`r`n`r`n$($result.StdOut)`r`n$($result.StdErr)"
        Set-Content -LiteralPath $logPath -Value $log -Encoding utf8
        $combined += "## $($test.name) (exit $($result.ExitCode))`n$($result.StdOut)`n$($result.StdErr)"
        if ($result.ExitCode -ne 0) { $allPassed = $false }
    }
    return [pscustomobject]@{ Passed = $allPassed; Output = ($combined -join "`n`n") }
}

$policyFullPath = [System.IO.Path]::GetFullPath($PolicyPath)
if (-not (Test-Path -LiteralPath $policyFullPath -PathType Leaf)) {
    throw "Policy file not found: $policyFullPath"
}
$policy = Get-Content -LiteralPath $policyFullPath -Raw | ConvertFrom-Json
if ([int]$policy.version -ne 1) { throw "Unsupported policy version: $($policy.version)" }

$repositoryResult = Invoke-NativeCapture -Command 'git' -Arguments @('rev-parse', '--show-toplevel') -WorkingDirectory $PSScriptRoot
if ($repositoryResult.ExitCode -ne 0) { throw 'The automation directory is not inside a Git repository.' }
$repositoryRoot = $repositoryResult.StdOut.Trim()

foreach ($relativePath in @($policy.execution.runDirectory) + @($policy.safety.allowedChangedPaths) + @($policy.safety.protectedPaths)) {
    Assert-RelativeRepositoryPath -Path ([string]$relativePath)
}

if ($MaxIterations -eq 0) { $MaxIterations = [int]$policy.execution.maxIterations }
$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$runRoot = Join-Path $repositoryRoot ([string]$policy.execution.runDirectory)
$runDirectory = Join-Path $runRoot $runId
$worktreeDirectory = Join-Path $runDirectory 'worktree'
$branchName = ([string]$policy.execution.branchPrefix) + $runId

$promptNames = @('deepseekAnalysis', 'codexImplementation', 'deepseekTestTriage', 'claudeReview')
foreach ($promptName in $promptNames) {
    $relativePrompt = [string]$policy.agents.$promptName.prompt
    Assert-RelativeRepositoryPath -Path $relativePrompt
    $templatePath = Join-Path $repositoryRoot $relativePrompt
    if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) { throw "Prompt not found: $relativePrompt" }
}

if (-not $Execute) {
    Write-Step 'DRY RUN: no files, branches, worktrees, agents, or tests will be created or executed.'
    Write-Step "Repository: $repositoryRoot"
    Write-Step "Would create branch: $branchName"
    Write-Step "Would create worktree: $worktreeDirectory"
    Write-Step "Iterations: $MaxIterations"
    Write-Step "Stages: DeepSeek analysis -> Codex implementation -> tests -> DeepSeek triage (on failure) -> Claude review"
    Write-Step "Test commands: $(@($policy.tests | ForEach-Object { ([string]$_.command + ' ' + (@($_.arguments) -join ' ')).Trim() }) -join '; ')"
    exit 0
}

if ([bool]$policy.safety.neverCommit -ne $true -or [bool]$policy.safety.neverPush -ne $true -or [bool]$policy.safety.neverMerge -ne $true) {
    throw 'This runner requires neverCommit, neverPush, and neverMerge to remain enabled.'
}

if ([bool]$policy.execution.requireCleanWorktree) {
    $initialChanges = @(Get-ChangedPaths -WorkingDirectory $repositoryRoot)
    if ($initialChanges.Count -gt 0) {
        throw "The primary worktree must be clean before execution. Found: $($initialChanges -join ', ')"
    }
}

New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$gitWorktree = Invoke-NativeCapture -Command 'git' -Arguments @('worktree', 'add', '-b', $branchName, $worktreeDirectory, 'HEAD') -WorkingDirectory $repositoryRoot
if ($gitWorktree.ExitCode -ne 0) { throw "Could not create isolated worktree: $($gitWorktree.StdErr)" }

$analysisTemplate = Join-Path $repositoryRoot ([string]$policy.agents.deepseekAnalysis.prompt)
$analysisPrompt = Expand-Prompt -TemplatePath $analysisTemplate -Values @{ TASK = $Task; WORKSPACE = $worktreeDirectory }
$analysisOutput = Invoke-AgentStage -Name 'DeepSeek analysis' -Configuration $policy.agents.deepseekAnalysis -Prompt $analysisPrompt -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $runDirectory 'analysis.md')

$feedback = 'No prior implementation feedback.'
$finalVerdict = 'NOT APPROVED'
for ($iteration = 1; $iteration -le $MaxIterations; $iteration++) {
    $iterationDirectory = Join-Path $runDirectory ("iteration-{0:D2}" -f $iteration)
    New-Item -ItemType Directory -Path $iterationDirectory -Force | Out-Null
    Write-Step "Iteration $iteration of $MaxIterations"

    $implementationTemplate = Join-Path $repositoryRoot ([string]$policy.agents.codexImplementation.prompt)
    $implementationPrompt = Expand-Prompt -TemplatePath $implementationTemplate -Values @{
        TASK = $Task
        WORKSPACE = $worktreeDirectory
        ANALYSIS = $analysisOutput
        FEEDBACK = $feedback
    }
    [void](Invoke-AgentStage -Name 'Codex implementation' -Configuration $policy.agents.codexImplementation -Prompt $implementationPrompt -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $iterationDirectory 'implementation.md'))
    $changedPaths = @(Assert-ChangePolicy -WorkingDirectory $worktreeDirectory -Safety $policy.safety)

    $testResult = Invoke-TestSuite -Tests @($policy.tests) -WorkingDirectory $worktreeDirectory -OutputDirectory $iterationDirectory
    $triage = 'All configured tests passed; no failure triage was required.'
    if (-not $testResult.Passed) {
        $triageTemplate = Join-Path $repositoryRoot ([string]$policy.agents.deepseekTestTriage.prompt)
        $triagePrompt = Expand-Prompt -TemplatePath $triageTemplate -Values @{
            TASK = $Task
            WORKSPACE = $worktreeDirectory
            CHANGED_FILES = ($changedPaths -join "`n")
            TEST_OUTPUT = $testResult.Output
        }
        $triage = Invoke-AgentStage -Name 'DeepSeek test triage' -Configuration $policy.agents.deepseekTestTriage -Prompt $triagePrompt -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $iterationDirectory 'test-triage.md')
        if ([bool]$policy.execution.stopOnTestFailure) { break }
    }

    $reviewDiff = Get-ReviewDiff -WorkingDirectory $worktreeDirectory
    $reviewTemplate = Join-Path $repositoryRoot ([string]$policy.agents.claudeReview.prompt)
    $reviewPrompt = Expand-Prompt -TemplatePath $reviewTemplate -Values @{
        TASK = $Task
        WORKSPACE = $worktreeDirectory
        CHANGED_FILES = ($changedPaths -join "`n")
        DIFF = $reviewDiff
        TEST_OUTPUT = $testResult.Output
        TRIAGE = $triage
    }
    $review = Invoke-AgentStage -Name 'Claude review' -Configuration $policy.agents.claudeReview -Prompt $reviewPrompt -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $iterationDirectory 'review.md')
    $feedback = $review

    if ($testResult.Passed -and $review.Contains([string]$policy.execution.approvalMarker)) {
        $finalVerdict = 'APPROVED'
        break
    }
}

$summary = @(
    '# Agent loop summary',
    '',
    "Run: $runId",
    "Task: $Task",
    "Verdict: $finalVerdict",
    "Branch: $branchName",
    "Worktree: $worktreeDirectory",
    '',
    'No commit, merge, push, or worktree removal was performed.'
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $runDirectory 'summary.md') -Value $summary -Encoding utf8
Write-Step "Finished with verdict: $finalVerdict"
Write-Step "Artifacts: $runDirectory"
Write-Step 'Changes remain uncommitted in the isolated worktree for human inspection.'
