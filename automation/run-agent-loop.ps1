[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Requirement,

    [ValidateRange(1, 2)]
    [int]$MaxIterations,

    [switch]$Execute,

    [string]$WorktreeRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[agent-loop] $Message"
}

function Get-RequirementStructureErrors {
    param([AllowEmptyString()][string]$Text)

    $requiredSections = @(
        [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('TeG7pWMgdGnDqnU=')),
        [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('UGjhuqFtIHZpIMSRxrDhu6NjIHBow6lw')),
        [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('xJBp4buBdSBj4bqlbQ==')),
        [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('VGnDqnUgY2jDrSBob8OgbiB0aMOgbmg='))
    )
    $errors = @()
    foreach ($section in $requiredSections) {
        $pattern = '(?im)^\s*#{0,6}\s*' + [Regex]::Escape($section) + '\s*:?[ \t]*$'
        if ($Text -notmatch $pattern) {
            $errors += "Requirement is missing required section: $section"
        }
    }
    return @($errors)
}

function Assert-RequirementStructure {
    param([AllowEmptyString()][string]$Text)

    $errors = @(Get-RequirementStructureErrors -Text $Text)
    if ($errors.Count -gt 0) {
        throw ($errors -join '; ')
    }
    return $true
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
        [int]$TimeoutSeconds = 600,
        [hashtable]$Environment = @{}
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Command
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $startInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $hasStandardInput = $PSBoundParameters.ContainsKey('StandardInput')
    $startInfo.RedirectStandardInput = $hasStandardInput
    $startInfo.CreateNoWindow = $true

    # ProcessStartInfo.ArgumentList is unavailable in Windows PowerShell 5.1.
    $startInfo.Arguments = (@($Arguments | ForEach-Object { ConvertTo-NativeArgument -Argument ([string]$_) }) -join ' ')

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $previousEnvironment = @{}
    try {
        foreach ($name in $Environment.Keys) {
            $environmentName = [string]$name
            $previousEnvironment[$environmentName] = [System.Environment]::GetEnvironmentVariable($environmentName, 'Process')
            [System.Environment]::SetEnvironmentVariable($environmentName, [string]$Environment[$name], 'Process')
        }
        if (-not $process.Start()) {
            throw "Could not start command: $Command"
        }
    }
    finally {
        foreach ($name in $previousEnvironment.Keys) {
            [System.Environment]::SetEnvironmentVariable([string]$name, $previousEnvironment[$name], 'Process')
        }
    }

    if ($hasStandardInput) {
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $bytes = $utf8.GetBytes($StandardInput)
        $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        $process.StandardInput.BaseStream.Flush()
        $process.StandardInput.BaseStream.Close()
    }

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

function Resolve-GitExecutable {
    $command = Get-Command git.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $resolved = [System.IO.Path]::GetFullPath($command.Source)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "Resolved git.exe does not exist: $resolved"
    }
    return $resolved
}

function Resolve-AgentExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$WorktreeRoot,
        [Parameter(Mandatory = $true)][string]$RunDirectory
    )

    if ([string]::IsNullOrWhiteSpace($Command)) {
        throw 'Agent executable command cannot be empty.'
    }

    if ([System.IO.Path]::IsPathRooted($Command)) {
        $candidate = [System.IO.Path]::GetFullPath($Command)
    }
    else {
        $application = Get-Command -Name $Command -CommandType Application -ErrorAction Stop | Select-Object -First 1
        if ($null -eq $application -or [string]::IsNullOrWhiteSpace([string]$application.Source)) {
            throw "Could not resolve agent executable from PATH: $Command"
        }
        $resolvedSource = [string]$application.Source
        if (-not [System.IO.Path]::IsPathRooted($resolvedSource)) {
            throw "Get-Command returned a non-absolute agent executable path: $resolvedSource"
        }
        $candidate = [System.IO.Path]::GetFullPath($resolvedSource)
    }

    $repositoryPath = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd([char[]]@('\', '/'))
    $worktreePath = [System.IO.Path]::GetFullPath($WorktreeRoot).TrimEnd([char[]]@('\', '/'))
    $runPath = [System.IO.Path]::GetFullPath($RunDirectory).TrimEnd([char[]]@('\', '/'))
    $candidatePrefixChecks = @(
        @{ Name = 'repository root'; Path = $repositoryPath }
        @{ Name = 'worktree root'; Path = $worktreePath }
        @{ Name = 'run directory'; Path = $runPath }
    )
    foreach ($check in $candidatePrefixChecks) {
        $prefix = $check.Path + [System.IO.Path]::DirectorySeparatorChar
        if ($candidate.Equals($check.Path, [System.StringComparison]::OrdinalIgnoreCase) -or $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Agent executable is inside the protected $($check.Name): $candidate"
        }
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        throw "Resolved agent executable is not an absolute path: $candidate"
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Resolved agent executable does not exist: $candidate"
    }
    return $candidate
}

function New-GitGuard {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$RealGitExecutable,
        [Parameter(Mandatory = $true)][object[]]$ForbiddenArguments
    )

    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    $escapedGit = $RealGitExecutable.Replace("'", "''")
    $forbiddenLiterals = @($ForbiddenArguments | ForEach-Object { "    '" + ([string]$_).ToLowerInvariant().Replace("'", "''") + "'" }) -join ",`r`n"
    $guardScript = @"
param([Parameter(ValueFromRemainingArguments = `$true)][string[]]`$GitArguments)
`$ErrorActionPreference = 'Stop'
`$realGit = '$escapedGit'
`$allowedCommands = @('status', 'diff', 'ls-files', 'log', 'show', 'rev-parse', 'grep')
`$forbiddenArguments = @(
$forbiddenLiterals
)
`$normalized = ((@(`$GitArguments) -join ' ').Trim().ToLowerInvariant() -replace '\s+', ' ')
foreach (`$forbidden in `$forbiddenArguments) {
    if (`$normalized -eq `$forbidden -or `$normalized.StartsWith(`$forbidden + ' ')) {
        [Console]::Error.WriteLine("git guard: forbidden command: `$normalized")
        exit 97
    }
}
if (`$GitArguments.Count -eq 0 -or `$allowedCommands -notcontains `$GitArguments[0].ToLowerInvariant()) {
    [Console]::Error.WriteLine("git guard: command is not in the read-only allowlist: `$normalized")
    exit 97
}
& `$realGit @GitArguments
exit `$LASTEXITCODE
"@
    Set-Content -LiteralPath (Join-Path $Directory 'git.ps1') -Value $guardScript -Encoding utf8
    $guardCommand = @'
@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0git.ps1" %*
exit /b %ERRORLEVEL%
'@
    Set-Content -LiteralPath (Join-Path $Directory 'git.cmd') -Value $guardCommand -Encoding ascii
}

function Get-GitSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $head = Invoke-NativeCapture -Command $GitExecutable -Arguments @('rev-parse', 'HEAD') -WorkingDirectory $WorkingDirectory
    $branch = Invoke-NativeCapture -Command $GitExecutable -Arguments @('rev-parse', '--abbrev-ref', 'HEAD') -WorkingDirectory $WorkingDirectory
    $status = Invoke-NativeCapture -Command $GitExecutable -Arguments @('status', '--porcelain=v1', '--untracked-files=all') -WorkingDirectory $WorkingDirectory
    foreach ($result in @($head, $branch, $status)) {
        if ($result.ExitCode -ne 0) { throw "Could not capture Git snapshot: $($result.StdErr)" }
    }
    return [pscustomobject]@{
        Head = $head.StdOut.Trim()
        Branch = $branch.StdOut.Trim()
        Status = $status.StdOut.TrimEnd([char[]]@("`r", "`n"))
    }
}

function Test-HasDeletedFiles {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $status = Invoke-NativeCapture -Command $GitExecutable -Arguments @('status', '--porcelain=v1', '--untracked-files=all') -WorkingDirectory $WorkingDirectory
    if ($status.ExitCode -ne 0) { throw "Could not inspect deleted files: $($status.StdErr)" }
    foreach ($line in ($status.StdOut -split "`r?`n")) {
        if ($line.Length -ge 2 -and $line.Substring(0, 2) -match '[DR]') { return $true }
    }
    return $false
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
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $result = Invoke-NativeCapture -Command $GitExecutable -Arguments @('status', '--porcelain=v1', '--untracked-files=all') -WorkingDirectory $WorkingDirectory
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
        [Parameter(Mandatory = $true)]$Safety,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $changedPaths = @(Get-ChangedPaths -WorkingDirectory $WorkingDirectory -GitExecutable $GitExecutable)
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
    if (Test-HasDeletedFiles -WorkingDirectory $WorkingDirectory -GitExecutable $GitExecutable) {
        throw 'Deleted or renamed files are forbidden by policy.'
    }
    $reviewDiff = Get-ReviewDiff -WorkingDirectory $WorkingDirectory -GitExecutable $GitExecutable
    $diffLineCount = if ([string]::IsNullOrEmpty($reviewDiff)) { 0 } else { @($reviewDiff -split "`r?`n").Count }
    if ($diffLineCount -gt [int]$Safety.maxDiffLines) {
        throw "Diff line count $diffLineCount exceeds policy limit $($Safety.maxDiffLines)."
    }
    return $changedPaths
}

function Get-ReviewDiff {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $tracked = Invoke-NativeCapture -Command $GitExecutable -Arguments @('diff', '--no-ext-diff', '--binary', 'HEAD') -WorkingDirectory $WorkingDirectory
    if ($tracked.ExitCode -ne 0) { throw "Could not capture tracked diff: $($tracked.StdErr)" }

    $untrackedResult = Invoke-NativeCapture -Command $GitExecutable -Arguments @('ls-files', '--others', '--exclude-standard') -WorkingDirectory $WorkingDirectory
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

function Assert-AgentPostconditions {
    param(
        [Parameter(Mandatory = $true)]$BaselineMain,
        [Parameter(Mandatory = $true)]$BaselineWorktree,
        [Parameter(Mandatory = $true)][string]$MainRepository,
        [Parameter(Mandatory = $true)][string]$Worktree,
        [Parameter(Mandatory = $true)]$Safety,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $currentMain = Get-GitSnapshot -WorkingDirectory $MainRepository -GitExecutable $GitExecutable
    $currentWorktree = Get-GitSnapshot -WorkingDirectory $Worktree -GitExecutable $GitExecutable
    if ($currentMain.Head -ne $BaselineMain.Head) { throw 'SAFETY VIOLATION: main repository HEAD changed.' }
    if ($currentMain.Branch -ne $BaselineMain.Branch) { throw 'SAFETY VIOLATION: main repository branch changed.' }
    if ($currentMain.Status -ne $BaselineMain.Status) { throw 'SAFETY VIOLATION: main working tree status changed.' }
    if ($currentWorktree.Head -ne $BaselineWorktree.Head) { throw 'SAFETY VIOLATION: isolated worktree HEAD changed.' }
    if ($currentWorktree.Branch -ne $BaselineWorktree.Branch) { throw 'SAFETY VIOLATION: isolated worktree branch changed.' }
    [void](Assert-ChangePolicy -WorkingDirectory $Worktree -Safety $Safety -GitExecutable $GitExecutable)
    return $true
}

function Invoke-GitDiffCheck {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$GitExecutable,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    $result = Invoke-NativeCapture -Command $GitExecutable -Arguments @('diff', '--check', 'HEAD') -WorkingDirectory $WorkingDirectory
    Set-Content -LiteralPath $LogPath -Value ($result.StdOut + $result.StdErr) -Encoding utf8
    return ($result.ExitCode -eq 0)
}

function Test-ClaudeEligibility {
    param(
        [Parameter(Mandatory = $true)][bool]$TestsPassed,
        [Parameter(Mandatory = $true)][bool]$DiffCheckPassed,
        [Parameter(Mandatory = $true)][bool]$PolicyPassed,
        [Parameter(Mandatory = $true)][bool]$NoDeletedFiles,
        [Parameter(Mandatory = $true)][bool]$StateStable,
        [Parameter(Mandatory = $true)][int]$ClaudeCalls,
        [Parameter(Mandatory = $true)][int]$MaxClaudeCalls
    )

    return ($TestsPassed -and $DiffCheckPassed -and $PolicyPassed -and $NoDeletedFiles -and $StateStable -and $ClaudeCalls -lt $MaxClaudeCalls)
}

function Invoke-ClaudeGate {
    param(
        [Parameter(Mandatory = $true)][bool]$TestsPassed,
        [Parameter(Mandatory = $true)][bool]$DiffCheckPassed,
        [Parameter(Mandatory = $true)][bool]$PolicyPassed,
        [Parameter(Mandatory = $true)][bool]$NoDeletedFiles,
        [Parameter(Mandatory = $true)][bool]$StateStable,
        [Parameter(Mandatory = $true)][int]$ClaudeCalls,
        [Parameter(Mandatory = $true)][int]$MaxClaudeCalls,
        [Parameter(Mandatory = $true)][scriptblock]$Invocation
    )

    $eligible = Test-ClaudeEligibility -TestsPassed $TestsPassed -DiffCheckPassed $DiffCheckPassed -PolicyPassed $PolicyPassed -NoDeletedFiles $NoDeletedFiles -StateStable $StateStable -ClaudeCalls $ClaudeCalls -MaxClaudeCalls $MaxClaudeCalls
    if (-not $eligible) { return [pscustomobject]@{ Called = $false; Result = $null } }
    return [pscustomobject]@{ Called = $true; Result = (& $Invocation) }
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

function Write-DeepSeekTaskFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Prompt
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "DeepSeek task directory does not exist: $parent"
    }
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Prompt, $utf8NoBom)
}

function Get-DeepSeekInvocation {
    param(
        [Parameter(Mandatory = $true)]$Configuration,
        [Parameter(Mandatory = $true)][string]$TaskFile
    )

    if ([string]::IsNullOrWhiteSpace($TaskFile)) { throw 'DeepSeek task file path cannot be empty.' }
    $instruction = 'Read the DeepSeek task file at "' + $TaskFile + '" and follow its instructions. Return only the requested analysis.'
    return [pscustomobject]@{
        Command = [string]$Configuration.command
        Arguments = @($Configuration.arguments) + @($instruction)
        TaskFile = $TaskFile
    }
}

function Invoke-DeepSeekStage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Configuration,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$TaskFile,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [hashtable]$Environment = @{}
    )

    Write-DeepSeekTaskFile -Path $TaskFile -Prompt $Prompt
    $invocation = Get-DeepSeekInvocation -Configuration $Configuration -TaskFile $TaskFile
    $stageConfiguration = [pscustomobject]@{
        command = $invocation.Command
        arguments = $invocation.Arguments
        timeoutSeconds = $Configuration.timeoutSeconds
    }
    return (Invoke-AgentStage -Name $Name -Configuration $stageConfiguration -Prompt '' -WorkingDirectory $WorkingDirectory -OutputPath $OutputPath -Environment $Environment -NoStandardInput)
}

function Get-DeepSeekVerdict {
    param([AllowEmptyString()][string]$Output)

    $matches = [Regex]::Matches($Output, '(?im)^\s*VERDICT\s*:\s*([^\s]+)\s*$')
    if ($matches.Count -ne 1) {
        throw 'DeepSeek output must contain exactly one VERDICT: READY or VERDICT: BLOCKED marker.'
    }
    $verdict = $matches[0].Groups[1].Value.ToUpperInvariant()
    if ($verdict -notin @('READY', 'BLOCKED')) {
        throw "DeepSeek returned an invalid verdict marker: $verdict"
    }
    return $verdict
}

function Assert-DeepSeekReady {
    param([AllowEmptyString()][string]$Output)

    $verdict = Get-DeepSeekVerdict -Output $Output
    if ($verdict -ne 'READY') {
        throw 'DeepSeek verdict is BLOCKED; Codex will not be called.'
    }
    return $true
}

function Invoke-AgentStage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Configuration,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [hashtable]$Environment = @{},
        [switch]$NoStandardInput
    )

    $resolvedCommand = [string]$Configuration.command
    Write-Step "Running $Name"
    try {
        if (-not [System.IO.Path]::IsPathRooted($resolvedCommand) -or -not (Test-Path -LiteralPath $resolvedCommand -PathType Leaf)) {
            throw "Agent stage command must be an existing absolute path: $resolvedCommand"
        }
        $standardInput = if ($NoStandardInput) { $null } else { $Prompt }
        $result = Invoke-NativeCapture -Command $resolvedCommand -Arguments @($Configuration.arguments) -WorkingDirectory $WorkingDirectory -StandardInput $standardInput -TimeoutSeconds ([int]$Configuration.timeoutSeconds) -Environment $Environment
    }
    catch {
        $result = [pscustomobject]@{ ExitCode = -1; StdOut = ''; StdErr = $_.Exception.Message }
    }
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
    return [pscustomobject]@{ ExitCode = $result.ExitCode; Output = $result.StdOut; Error = $result.StdErr }
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
        try {
            $result = Invoke-NativeCapture -Command ([string]$test.command) -Arguments @($test.arguments) -WorkingDirectory $WorkingDirectory -TimeoutSeconds ([int]$test.timeoutSeconds)
        }
        catch {
            $result = [pscustomobject]@{ ExitCode = -1; StdOut = ''; StdErr = $_.Exception.Message }
        }
        $safeName = ([string]$test.name) -replace '[^A-Za-z0-9_.-]', '-'
        $logPath = Join-Path $OutputDirectory "test-$safeName.log"
        $log = "Exit code: $($result.ExitCode)`r`n`r`n$($result.StdOut)`r`n$($result.StdErr)"
        Set-Content -LiteralPath $logPath -Value $log -Encoding utf8
        $combined += "## $($test.name) (exit $($result.ExitCode))`n$($result.StdOut)`n$($result.StdErr)"
        if ($result.ExitCode -ne 0) { $allPassed = $false }
    }
    return [pscustomobject]@{ Passed = $allPassed; Output = ($combined -join "`n`n"); Count = @($Tests).Count }
}

if ($env:AGENT_LOOP_LIBRARY_ONLY -eq '1') {
    return
}

Assert-RequirementStructure -Text $Requirement

$policyFullPath = Join-Path $PSScriptRoot 'policy.json'
if (-not (Test-Path -LiteralPath $policyFullPath -PathType Leaf)) {
    throw "Policy file not found: $policyFullPath"
}
$policy = Get-Content -LiteralPath $policyFullPath -Raw | ConvertFrom-Json
if ([int]$policy.version -ne 1) { throw "Unsupported policy version: $($policy.version)" }

$gitExecutable = Resolve-GitExecutable
$repositoryResult = Invoke-NativeCapture -Command $gitExecutable -Arguments @('rev-parse', '--show-toplevel') -WorkingDirectory $PSScriptRoot
if ($repositoryResult.ExitCode -ne 0) { throw 'The automation directory is not inside a Git repository.' }
$repositoryRoot = $repositoryResult.StdOut.Trim()

foreach ($relativePath in @($policy.execution.runDirectory) + @($policy.safety.allowedChangedPaths) + @($policy.safety.protectedPaths)) {
    Assert-RelativeRepositoryPath -Path ([string]$relativePath)
}

$policyIterationLimit = [int]$policy.execution.maxIterations
if ($policyIterationLimit -lt 1 -or $policyIterationLimit -gt 2) {
    throw "Policy maxIterations must be between 1 and 2; found $policyIterationLimit."
}
if (-not $PSBoundParameters.ContainsKey('MaxIterations')) {
    $MaxIterations = $policyIterationLimit
}
elseif ($MaxIterations -gt $policyIterationLimit) {
    throw "MaxIterations $MaxIterations exceeds the policy limit $policyIterationLimit."
}
if ([int]$policy.execution.maxClaudeCalls -ne 1) { throw 'Policy maxClaudeCalls must equal 1.' }
if ([int]$policy.safety.maxChangedFiles -lt 1 -or [int]$policy.safety.maxChangedFiles -gt 20) { throw 'Policy maxChangedFiles must be between 1 and 20.' }
if ([int]$policy.safety.maxDiffLines -lt 1 -or [int]$policy.safety.maxDiffLines -gt 1000) { throw 'Policy maxDiffLines must be between 1 and 1000.' }
if (@($policy.tests).Count -ne 2) { throw 'Policy must configure exactly two test suites.' }
if (@($policy.safety.forbiddenGitArguments).Count -eq 0) { throw 'Policy forbiddenGitArguments must not be empty.' }

$repositoryFullPath = [System.IO.Path]::GetFullPath($repositoryRoot).TrimEnd([char[]]@('\', '/'))
if ([string]::IsNullOrWhiteSpace($WorktreeRoot)) {
    $worktreeRootFullPath = [System.IO.Path]::GetFullPath((Join-Path $repositoryFullPath ([string]$policy.execution.runDirectory)))
}
elseif ([System.IO.Path]::IsPathRooted($WorktreeRoot)) {
    $worktreeRootFullPath = [System.IO.Path]::GetFullPath($WorktreeRoot)
}
else {
    $worktreeRootFullPath = [System.IO.Path]::GetFullPath((Join-Path $repositoryFullPath $WorktreeRoot))
}
$repositoryPrefix = $repositoryFullPath + [System.IO.Path]::DirectorySeparatorChar
if (-not $worktreeRootFullPath.StartsWith($repositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "WorktreeRoot must be inside the repository: $worktreeRootFullPath"
}

$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$runDirectory = Join-Path $worktreeRootFullPath $runId
$worktreeDirectory = Join-Path $runDirectory 'worktree'
$branchName = ([string]$policy.execution.branchPrefix) + $runId

$promptNames = @('deepseekAnalysis', 'codexImplementation', 'deepseekTestTriage', 'claudeReview')
foreach ($promptName in $promptNames) {
    $relativePrompt = [string]$policy.agents.$promptName.prompt
    Assert-RelativeRepositoryPath -Path $relativePrompt
    $templatePath = Join-Path $repositoryRoot $relativePrompt
    if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) { throw "Prompt not found: $relativePrompt" }
}

$agentNames = @('deepseekAnalysis', 'codexImplementation', 'deepseekTestTriage', 'claudeReview')
$resolvedAgentExecutables = @{}
$agentConfigurations = @{}
foreach ($agentName in $agentNames) {
    try {
        $resolvedPath = Resolve-AgentExecutable -Command ([string]$policy.agents.$agentName.command) -RepositoryRoot $repositoryFullPath -WorktreeRoot $worktreeRootFullPath -RunDirectory $runDirectory
        $resolvedAgentExecutables[$agentName] = $resolvedPath
        $agentConfigurations[$agentName] = [pscustomobject]@{
            command = $resolvedPath
            arguments = @($policy.agents.$agentName.arguments)
            timeoutSeconds = [int]$policy.agents.$agentName.timeoutSeconds
        }
    }
    catch {
        if ($Execute) { throw "Could not resolve $agentName before execution: $($_.Exception.Message)" }
    }
}

if (-not $Execute) {
    Write-Step 'DRY RUN: no files, branches, worktrees, agents, or tests will be created or executed.'
    Write-Step "Repository: $repositoryRoot"
    Write-Step "Would create branch: $branchName"
    Write-Step "Would create worktree: $worktreeDirectory"
    Write-Step "Iterations: $MaxIterations"
    Write-Step "Resolved git.exe: $gitExecutable"
    foreach ($agentName in $agentNames) {
        if ($resolvedAgentExecutables.ContainsKey($agentName)) {
            Write-Step "Resolved $agentName executable: $($resolvedAgentExecutables[$agentName])"
        }
        else {
            Write-Step "Unresolved $agentName executable (dry-run only)"
        }
    }
    Write-Step "Limits: Claude calls=1; changed files=$($policy.safety.maxChangedFiles); diff lines=$($policy.safety.maxDiffLines)"
    Write-Step "Stages: DeepSeek analysis -> Codex implementation -> tests -> DeepSeek triage (on failure) -> Claude review"
    Write-Step "Test commands: $(@($policy.tests | ForEach-Object { ([string]$_.command + ' ' + (@($_.arguments) -join ' ')).Trim() }) -join '; ')"
    exit 0
}

if ([bool]$policy.safety.neverCommit -ne $true -or [bool]$policy.safety.neverPush -ne $true -or [bool]$policy.safety.neverMerge -ne $true) {
    throw 'This runner requires neverCommit, neverPush, and neverMerge to remain enabled.'
}

if ([bool]$policy.execution.requireCleanWorktree) {
    $initialChanges = @(Get-ChangedPaths -WorkingDirectory $repositoryRoot -GitExecutable $gitExecutable)
    if ($initialChanges.Count -gt 0) {
        throw "The primary worktree must be clean before execution. Found: $($initialChanges -join ', ')"
    }
}

$baselineMain = Get-GitSnapshot -WorkingDirectory $repositoryRoot -GitExecutable $gitExecutable
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$gitWorktree = Invoke-NativeCapture -Command $gitExecutable -Arguments @('worktree', 'add', '-b', $branchName, $worktreeDirectory, 'HEAD') -WorkingDirectory $repositoryRoot
if ($gitWorktree.ExitCode -ne 0) { throw "Could not create isolated worktree: $($gitWorktree.StdErr)" }
$baselineWorktree = Get-GitSnapshot -WorkingDirectory $worktreeDirectory -GitExecutable $gitExecutable
$baselineRecord = [ordered]@{
    recordedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    mainRepository = @{ head = $baselineMain.Head; branch = $baselineMain.Branch; status = $baselineMain.Status }
    worktree = @{ head = $baselineWorktree.Head; branch = $baselineWorktree.Branch; status = $baselineWorktree.Status }
}
$baselineRecord | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runDirectory 'git-baseline.json') -Encoding utf8

$guardDirectory = Join-Path $runDirectory 'git-guard'
New-GitGuard -Directory $guardDirectory -RealGitExecutable $gitExecutable -ForbiddenArguments @($policy.safety.forbiddenGitArguments)
$codexEnvironment = @{
    PATH = $guardDirectory + [System.IO.Path]::PathSeparator + $env:PATH
    GIT_TERMINAL_PROMPT = '0'
    GCM_INTERACTIVE = 'Never'
}

$analysisTemplate = Join-Path $repositoryRoot ([string]$policy.agents.deepseekAnalysis.prompt)
$analysisPrompt = Expand-Prompt -TemplatePath $analysisTemplate -Values @{ TASK = $Requirement; WORKSPACE = $worktreeDirectory }
$analysisStage = Invoke-DeepSeekStage -Name 'DeepSeek analysis' -Configuration $agentConfigurations.deepseekAnalysis -Prompt $analysisPrompt -TaskFile (Join-Path $runDirectory 'deepseek-analysis.task.md') -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $runDirectory 'analysis.md')
[void](Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $repositoryRoot -Worktree $worktreeDirectory -Safety $policy.safety -GitExecutable $gitExecutable)
if ($analysisStage.ExitCode -ne 0) { throw "DeepSeek analysis failed with exit code $($analysisStage.ExitCode). Worktree retained: $worktreeDirectory" }
$analysisOutput = $analysisStage.Output
[void](Assert-DeepSeekReady -Output $analysisOutput)

$feedback = 'No prior implementation feedback.'
$finalVerdict = 'NOT_APPROVED'
$claudeCalls = 0
for ($iteration = 1; $iteration -le $MaxIterations; $iteration++) {
    $iterationDirectory = Join-Path $runDirectory ("iteration-{0:D2}" -f $iteration)
    New-Item -ItemType Directory -Path $iterationDirectory -Force | Out-Null
    Write-Step "Iteration $iteration of $MaxIterations"

    $implementationTemplate = Join-Path $repositoryRoot ([string]$policy.agents.codexImplementation.prompt)
    $implementationPrompt = Expand-Prompt -TemplatePath $implementationTemplate -Values @{
        TASK = $Requirement
        WORKSPACE = $worktreeDirectory
        ANALYSIS = $analysisOutput
        FEEDBACK = $feedback
    }
    $implementationStage = Invoke-AgentStage -Name 'Codex implementation' -Configuration $agentConfigurations.codexImplementation -Prompt $implementationPrompt -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $iterationDirectory 'implementation.md') -Environment $codexEnvironment
    $stateStable = Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $repositoryRoot -Worktree $worktreeDirectory -Safety $policy.safety -GitExecutable $gitExecutable
    if ($implementationStage.ExitCode -ne 0) { throw "Codex implementation failed with exit code $($implementationStage.ExitCode). Worktree retained: $worktreeDirectory" }
    $changedPaths = @(Assert-ChangePolicy -WorkingDirectory $worktreeDirectory -Safety $policy.safety -GitExecutable $gitExecutable)
    $policyPassed = $true
    $noDeletedFiles = -not (Test-HasDeletedFiles -WorkingDirectory $worktreeDirectory -GitExecutable $gitExecutable)

    $testResult = Invoke-TestSuite -Tests @($policy.tests) -WorkingDirectory $worktreeDirectory -OutputDirectory $iterationDirectory
    $stateStable = Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $repositoryRoot -Worktree $worktreeDirectory -Safety $policy.safety -GitExecutable $gitExecutable
    $triage = 'All configured tests passed; no failure triage was required.'
    if (-not $testResult.Passed) {
        $triageTemplate = Join-Path $repositoryRoot ([string]$policy.agents.deepseekTestTriage.prompt)
        $triagePrompt = Expand-Prompt -TemplatePath $triageTemplate -Values @{
            TASK = $Requirement
            WORKSPACE = $worktreeDirectory
            CHANGED_FILES = ($changedPaths -join "`n")
            TEST_OUTPUT = $testResult.Output
        }
        $triageStage = Invoke-DeepSeekStage -Name 'DeepSeek test triage' -Configuration $agentConfigurations.deepseekTestTriage -Prompt $triagePrompt -TaskFile (Join-Path $iterationDirectory 'deepseek-test-triage.task.md') -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $iterationDirectory 'test-triage.md')
        [void](Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $repositoryRoot -Worktree $worktreeDirectory -Safety $policy.safety -GitExecutable $gitExecutable)
        if ($triageStage.ExitCode -ne 0) { throw "DeepSeek triage failed with exit code $($triageStage.ExitCode). Worktree retained: $worktreeDirectory" }
        $triage = $triageStage.Output
        $feedback = $triage
        if ($iteration -eq $MaxIterations) { $finalVerdict = 'TEST_FAILED' }
        continue
    }

    $diffCheckPassed = Invoke-GitDiffCheck -WorkingDirectory $worktreeDirectory -GitExecutable $gitExecutable -LogPath (Join-Path $iterationDirectory 'git-diff-check.log')
    if (-not $diffCheckPassed) { throw "git diff --check failed. Worktree retained: $worktreeDirectory" }
    $stateStable = Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $repositoryRoot -Worktree $worktreeDirectory -Safety $policy.safety -GitExecutable $gitExecutable
    $noDeletedFiles = -not (Test-HasDeletedFiles -WorkingDirectory $worktreeDirectory -GitExecutable $gitExecutable)
    $reviewDiff = Get-ReviewDiff -WorkingDirectory $worktreeDirectory -GitExecutable $gitExecutable
    $reviewTemplate = Join-Path $repositoryRoot ([string]$policy.agents.claudeReview.prompt)
    $reviewPrompt = Expand-Prompt -TemplatePath $reviewTemplate -Values @{
        TASK = $Requirement
        WORKSPACE = $worktreeDirectory
        CHANGED_FILES = ($changedPaths -join "`n")
        DIFF = $reviewDiff
        TEST_OUTPUT = $testResult.Output
        TRIAGE = $triage
    }
    $claudeGate = Invoke-ClaudeGate -TestsPassed $testResult.Passed -DiffCheckPassed $diffCheckPassed -PolicyPassed $policyPassed -NoDeletedFiles $noDeletedFiles -StateStable $stateStable -ClaudeCalls $claudeCalls -MaxClaudeCalls ([int]$policy.execution.maxClaudeCalls) -Invocation {
        Invoke-AgentStage -Name 'Claude review' -Configuration $agentConfigurations.claudeReview -Prompt $reviewPrompt -WorkingDirectory $worktreeDirectory -OutputPath (Join-Path $iterationDirectory 'review.md')
    }
    if (-not $claudeGate.Called) { throw "Claude gate rejected the review stage. Worktree retained: $worktreeDirectory" }
    $claudeCalls++
    $reviewStage = $claudeGate.Result
    [void](Assert-AgentPostconditions -BaselineMain $baselineMain -BaselineWorktree $baselineWorktree -MainRepository $repositoryRoot -Worktree $worktreeDirectory -Safety $policy.safety -GitExecutable $gitExecutable)
    if ($reviewStage.ExitCode -ne 0) { throw "Claude review failed with exit code $($reviewStage.ExitCode). Worktree retained: $worktreeDirectory" }
    $review = $reviewStage.Output

    if ($review.Contains([string]$policy.execution.approvalMarker)) {
        $finalVerdict = 'APPROVED'
    }
    else { $finalVerdict = 'CHANGES_REQUESTED' }
    break
}

$summary = @(
    '# Agent loop summary',
    '',
    "Run: $runId",
    "Requirement: $Requirement",
    "Verdict: $finalVerdict",
    "Claude calls: $claudeCalls",
    "Branch: $branchName",
    "Worktree: $worktreeDirectory",
    '',
    'No commit, merge, push, or worktree removal was performed.'
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $runDirectory 'summary.md') -Value $summary -Encoding utf8
Write-Step "Finished with verdict: $finalVerdict"
Write-Step "Artifacts: $runDirectory"
Write-Step 'Changes remain uncommitted in the isolated worktree for human inspection.'
