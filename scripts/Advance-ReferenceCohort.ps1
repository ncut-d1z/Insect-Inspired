[CmdletBinding()]
param(
    [Parameter(Mandatory)][int]$StartIndex,
    [Parameter(Mandatory)][int]$EndIndex,
    [Parameter(Mandatory)][string]$VerificationRepository,
    [int]$ParentsPerBatch=256,
    [int]$IdentityGroupsPerBatch=12,
    [string]$ReadbackUrl='https://github.com/ncut-d1z/Insect-Inspired.git'
)

$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
$root=(git rev-parse --show-toplevel)
Set-Location -LiteralPath $root
$private=(git rev-parse --absolute-git-dir)
$haltFile=Join-Path $private 'RUN-0012-sync-halt'
$mutex=[Threading.Mutex]::new($false,'Local\InsectInspiredGitMainRun0012')
$verifyRef='refs/verification/run12'
$state=Get-Content -Raw -Encoding utf8 temp/runs/RUN-0012.json | ConvertFrom-Json
if ($state.status -ne 'running' -or $StartIndex -lt 0 -or $EndIndex -le $StartIndex -or $EndIndex -gt $state.queue_count -or $ParentsPerBatch -lt 1 -or $IdentityGroupsPerBatch -lt 1) { throw 'Invalid run state or ordered cohort' }
if ((git branch --show-current) -cne 'main' -or (git -C $VerificationRepository rev-parse --is-bare-repository) -cne 'true' -or (Test-Path -LiteralPath (Join-Path $VerificationRepository 'objects/info/alternates'))) { throw 'A main worktree and independent verification object store are required' }

function Publish-Paths([string[]]$Paths,[string]$Message) {
    if (!$Paths.Count) { return }
    $locked=$false
    try {
        while (!$locked) {
            if (Test-Path -LiteralPath $haltFile) { throw 'A previous Git synchronization requires recovery' }
            $locked=$mutex.WaitOne(10000)
        }
        if ((Test-Path -LiteralPath $haltFile) -or @(git diff --cached --name-only).Count) { throw 'Inspect previous synchronization or staged changes' }
        $watch=[Diagnostics.Stopwatch]::StartNew()
        $log=[ordered]@{started_at_utc=[DateTime]::UtcNow.ToString('o')}
        git add -A -- @Paths
        $log.stage_seconds=$watch.Elapsed.TotalSeconds
        if (!@(git diff --cached --name-only).Count) {return}
        $watch.Restart()
        git diff --cached --check
        $log.check_seconds=$watch.Elapsed.TotalSeconds
        $watch.Restart()
        git commit --quiet -m $Message
        $log.commit_seconds=$watch.Elapsed.TotalSeconds
        $watch.Restart()
        git push --quiet origin refs/heads/main:refs/heads/main
        $log.push_seconds=$watch.Elapsed.TotalSeconds
        $watch.Restart()
        try {
            git -C $VerificationRepository -c http.lowSpeedTime=30 -c http.lowSpeedLimit=1024 -c credential.interactive=false fetch --quiet --no-tags $ReadbackUrl ('refs/heads/main:'+$verifyRef)
        } catch {
            $originUrl=(git remote get-url origin)
            git -C $VerificationRepository fetch --quiet --no-tags $originUrl ('refs/heads/main:'+$verifyRef)
        }
        $log.commit=(git rev-parse HEAD)
        $log.tree=(git rev-parse 'HEAD^{tree}')
        if ($log.commit -cne (git -C $VerificationRepository rev-parse $verifyRef) -or $log.tree -cne (git -C $VerificationRepository rev-parse ($verifyRef+'^{tree}'))) {throw 'Independent GitHub commit or tree differs'}
        $log.fetch_and_compare_seconds=$watch.Elapsed.TotalSeconds
        [IO.File]::AppendAllText((Join-Path $private 'RUN-0012-publish-timings.jsonl'),($log|ConvertTo-Json -Compress)+[char]10,[Text.UTF8Encoding]::new($false))
        git log -1 --format='%h %s'
    } catch {
        if ($locked -and !(Test-Path -LiteralPath $haltFile)) {[IO.File]::WriteAllText($haltFile,$_.Exception.Message)}
        throw
    } finally {
        if ($locked) {$mutex.ReleaseMutex()}
    }
}

function Cohort-Label([int]$Start,[int]$End) {
    return ($Start+1).ToString('D5')+'-'+$End.ToString('D5')
}
function Verify-State {
    if (Test-Path -LiteralPath $haltFile) {throw 'Reconcile Git synchronization before further research'}
}
try {
    Verify-State
    for ($at=$StartIndex; $at -lt $EndIndex; $at+=$ParentsPerBatch) {
        $next=[Math]::Min($at+$ParentsPerBatch,$EndIndex)
        $label=Cohort-Label $at $next
        $report='temp/reports/RUN-0012-batches/'+$label+'.json'
        python -B -X utf8 scripts/run12_reference_search.py $at ($next-$at)
        $prefix='temp/query-results/Q-RUN12-B'+($at+1).ToString('D5')+'-*.json'
        $fresh=@(git ls-files --others --exclude-standard -- $prefix)
        if (@(git diff --name-only -- $prefix).Count) {throw 'A published raw source receipt changed'}
        Publish-Paths @($fresh+$report) ('Record ordered parent bibliographies '+$label)
    }
    $cohort=Cohort-Label $StartIndex $EndIndex
    $plan='temp/reports/RUN-0012-identities/'+$cohort+'.json'
    python -B -X utf8 scripts/run12_canonical.py plan $StartIndex $EndIndex
    Publish-Paths @($plan) ('Bind identity lookup groups to parent cohort '+$cohort)
    $groups=(Get-Content -Raw -Encoding utf8 -LiteralPath $plan|ConvertFrom-Json).groups.Count
    for ($g=0; $g -lt $groups; $g+=$IdentityGroupsPerBatch) {
        Verify-State
        $used=@(Get-ChildItem -LiteralPath temp/query-results -Filter 'Q-RUN12-*.json').Count
        $remaining=$state.budget.external_requests-$used
        if ($remaining -le 0) {break}
        $take=[Math]::Min($remaining,[Math]::Min($IdentityGroupsPerBatch,$groups-$g))
        python -B -X utf8 scripts/run12_canonical.py hydrate $StartIndex $EndIndex --offset $g --groups $take
        $paths=@(git ls-files --others --exclude-standard -- 'temp/query-results/Q-RUN12-ID-*.json')
        Publish-Paths $paths ('Verify identifier groups '+($g+1)+' to '+($g+$take)+' for '+$cohort)
        if ($take -lt $IdentityGroupsPerBatch) {break}
    }
    for ($at=$StartIndex; $at -lt $EndIndex; $at+=$ParentsPerBatch) {
        $next=[Math]::Min($at+$ParentsPerBatch,$EndIndex)
        $label=Cohort-Label $at $next
        $report='temp/reports/RUN-0012-canonical/'+$label+'.json'
        if (Test-Path -LiteralPath $report) {
            if (!(git -C $VerificationRepository ls-tree --name-only $verifyRef -- $report)) {throw 'Canonical transaction is not independently verified'}
            continue
        }
        if (@(git status --porcelain).Count) {throw 'Canonical transactions require committed source inputs'}
        $before=(git rev-parse HEAD)
        $watch=[Diagnostics.Stopwatch]::StartNew()
        python -B -X utf8 scripts/run12_canonical.py apply $at $next
        $duration=$watch.Elapsed.TotalSeconds
        $receipt=Get-Content -Raw -Encoding utf8 -LiteralPath $report|ConvertFrom-Json -AsHashtable -Depth 100
        if ($receipt.before_commit -cne $before -or $receipt.next_index -ne $next) {throw 'Canonical receipt does not bind the input commit and end position'}
        $paths=@('temp/partitions',$report)+@($receipt.datasets.Keys|ForEach-Object {'temp/'+$_+'.jsonl'})
        Publish-Paths $paths ('Register canonical Works, reference positions, edges and gaps for '+$label)
        $timing=[ordered]@{cohort=$label;canonical_seconds=$duration;commit=(git rev-parse HEAD)}
        [IO.File]::AppendAllText((Join-Path $private 'RUN-0012-canonical-timings.jsonl'),($timing|ConvertTo-Json -Compress)+[char]10,[Text.UTF8Encoding]::new($false))
    }
    python -B -X utf8 scripts/run12_progress.py
    $progress='temp/reports/RUN-0012-progress-'+$EndIndex.ToString('D5')+'.json'
    Publish-Paths @($progress) ('Reconcile source, canonical, research and maintenance totals at position '+$EndIndex)
} finally {
    $mutex.Dispose()
}
