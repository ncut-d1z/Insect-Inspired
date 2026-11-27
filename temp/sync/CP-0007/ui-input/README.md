# CP7 UI 验证专用输入包

这个包只有当前 ref.html 和完全相同的 scripts/html-smoke.mjs 测试脚本，用于在 GitHub Actions 官方 Ubuntu 环境执行 10 项浏览器检查；它不是完整研究数据、不是 CP7 最终检查点。不要把它当成 main 合并依据。完整研究数据恢复、main 快进合并和临时分支清理须使用最终父目录 temp/sync/CP-0007/README.md。

固定 HTML：47780202 字节，SHA256 9a07565ca74d1d039426cb11cde5603259995f89c71565b4136d57469c0c6982。固定测试脚本：7227 字节，SHA256 9a927248fff3f66f521e75bbcde9a9b18c6cf73ef07294a358d0f7b7de11830a。Playwright 精确版本 1.62.1。HTML 以 gzip level 9、mtime 0 压缩为 5060987 字节，再分为 10 片；分片原始字节按 manifest 顺序连接，不使用文本管道。下面只恢复和校验输入，不运行浏览器，也不修改研究分支或 main。

## PowerShell：提取、顺序拼接、解压和哈希核验

需要 Git 和 Windows PowerShell 5.1 或更新版本。把 $Cp7UiRepo 改为现有仓库的绝对路径；所有输出放在相邻的新目录。

~~~powershell
$ErrorActionPreference = 'Stop'
$Cp7UiRepo = 'C:\path\to\Insect-Inspired'
function Invoke-Cp7UiGit {
    $cp7Result = @(& git -C $Cp7UiRepo -c core.hooksPath=/dev/null @args)
    if ($LASTEXITCODE -ne 0) { throw ('Git failed: ' + ($args -join ' ')) }
    $cp7Result
}
function Assert-Cp7UiEqual($Actual, $Expected, [string]$Label) {
    if ([string]$Actual -cne [string]$Expected) { throw ('Mismatch: ' + $Label) }
}
function Assert-Cp7UiHash([string]$Path, [string]$Hash) {
    Assert-Cp7UiEqual (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() $Hash $Path
}
Assert-Cp7UiEqual (Invoke-Cp7UiGit remote get-url origin) 'https://github.com/ncut-d1z/Insect-Inspired.git' 'origin'
Invoke-Cp7UiGit fetch --no-tags origin refs/heads/sync/cp7-checkpoint-import
$Cp7UiInputCommit = [string](Invoke-Cp7UiGit rev-parse FETCH_HEAD)
$Cp7UiRoot = Join-Path (Split-Path -Parent $Cp7UiRepo) ('cp7-ui-input-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Cp7UiRoot
$Cp7UiZip = Join-Path $Cp7UiRoot 'ui-input.zip'
$Cp7UiExtract = Join-Path $Cp7UiRoot 'extracted'
Invoke-Cp7UiGit archive --format=zip ('--output=' + $Cp7UiZip) $Cp7UiInputCommit -- temp/sync/CP-0007/ui-input scripts/html-smoke.mjs .github/workflows/verify-cp7-ui.yml
Expand-Archive -LiteralPath $Cp7UiZip -DestinationPath $Cp7UiExtract
$Cp7UiPackage = Join-Path $Cp7UiExtract 'temp/sync/CP-0007/ui-input'
$Cp7UiManifestPath = Join-Path $Cp7UiPackage 'manifest.json'
$Cp7UiManifest = Get-Content -LiteralPath $Cp7UiManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp7UiEqual $Cp7UiManifest.format_version 1 'format'
Assert-Cp7UiEqual $Cp7UiManifest.repository 'ncut-d1z/Insect-Inspired' 'repository'
Assert-Cp7UiEqual $Cp7UiManifest.checkpoint_id 'CP-0007' 'checkpoint'
Assert-Cp7UiEqual $Cp7UiManifest.purpose 'ui_validation_input_only' 'package purpose'
Assert-Cp7UiEqual $Cp7UiManifest.html.sha256 '9a07565ca74d1d039426cb11cde5603259995f89c71565b4136d57469c0c6982' 'fixed HTML SHA256'
Assert-Cp7UiEqual $Cp7UiManifest.html.bytes 47780202 'fixed HTML length'
Assert-Cp7UiEqual $Cp7UiManifest.compression.sha256 '21b987c73166fd560d5190056882375d573c6e5bb1f0d76f6662c74f53d70831' 'fixed gzip SHA256'
Assert-Cp7UiEqual $Cp7UiManifest.compression.bytes 5060987 'fixed gzip length'
Assert-Cp7UiEqual $Cp7UiManifest.compression.format 'gzip' 'compression'
Assert-Cp7UiEqual $Cp7UiManifest.compression.mtime 0 'gzip mtime'
Assert-Cp7UiEqual $Cp7UiManifest.test_script.path 'scripts/html-smoke.mjs' 'script path'
Assert-Cp7UiEqual $Cp7UiManifest.test_script.sha256 '9a927248fff3f66f521e75bbcde9a9b18c6cf73ef07294a358d0f7b7de11830a' 'fixed script SHA256'
Assert-Cp7UiEqual $Cp7UiManifest.playwright_version '1.62.1' 'Playwright version'
Assert-Cp7UiHash (Join-Path $Cp7UiPackage 'README.md') $Cp7UiManifest.readme_sha256
Assert-Cp7UiHash (Join-Path $Cp7UiExtract 'scripts/html-smoke.mjs') '9a927248fff3f66f521e75bbcde9a9b18c6cf73ef07294a358d0f7b7de11830a'
$Cp7UiParts = @($Cp7UiManifest.parts)
Assert-Cp7UiEqual $Cp7UiParts.Count 10 'part count'
$Cp7UiGzip = Join-Path $Cp7UiRoot 'ref.html.gz'
$Cp7UiOutput = [IO.File]::Open($Cp7UiGzip, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    for ($cp7PartIndex = 0; $cp7PartIndex -lt $Cp7UiParts.Count; $cp7PartIndex++) {
        $cp7Part = $Cp7UiParts[$cp7PartIndex]
        $cp7ExpectedName = 'parts/ref.html.gz.part-{0:D4}' -f ($cp7PartIndex + 1)
        Assert-Cp7UiEqual $cp7Part.index ($cp7PartIndex + 1) 'part index'
        Assert-Cp7UiEqual $cp7Part.path $cp7ExpectedName 'safe ordered part name'
        $cp7PartPath = Join-Path $Cp7UiPackage $cp7ExpectedName
        Assert-Cp7UiEqual (Get-Item -LiteralPath $cp7PartPath).Length $cp7Part.bytes 'part bytes'
        Assert-Cp7UiHash $cp7PartPath $cp7Part.sha256
        $cp7Input = [IO.File]::OpenRead($cp7PartPath)
        try { $cp7Input.CopyTo($Cp7UiOutput) } finally { $cp7Input.Dispose() }
    }
} finally { $Cp7UiOutput.Dispose() }
Assert-Cp7UiEqual (Get-Item -LiteralPath $Cp7UiGzip).Length 5060987 'gzip bytes'
Assert-Cp7UiHash $Cp7UiGzip '21b987c73166fd560d5190056882375d573c6e5bb1f0d76f6662c74f53d70831'
$Cp7UiHtml = Join-Path $Cp7UiRoot 'ref.html'
$Cp7UiSource = [IO.File]::OpenRead($Cp7UiGzip)
$Cp7UiDecoder = [IO.Compression.GZipStream]::new($Cp7UiSource, [IO.Compression.CompressionMode]::Decompress)
$Cp7UiDestination = [IO.File]::Open($Cp7UiHtml, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try { $Cp7UiDecoder.CopyTo($Cp7UiDestination) }
finally { $Cp7UiDestination.Dispose(); $Cp7UiDecoder.Dispose(); $Cp7UiSource.Dispose() }
Assert-Cp7UiEqual (Get-Item -LiteralPath $Cp7UiHtml).Length 47780202 'HTML bytes'
Assert-Cp7UiHash $Cp7UiHtml '9a07565ca74d1d039426cb11cde5603259995f89c71565b4136d57469c0c6982'
Write-Host ('Verified UI input: ' + $Cp7UiHtml)
Write-Host ('Fixed source script: ' + (Join-Path $Cp7UiExtract 'scripts/html-smoke.mjs'))
Write-Host ('Input transport commit: ' + $Cp7UiInputCommit)
~~~

CI 成功后会把两份原始 JSON、四张原始 PNG、此输入 manifest 和额外 Actions 来源回执保存到同一 sync 分支的 temp/sync/CP-0007/ui-evidence/。来源回执明确标注 github_actions、输入 Git commit、Actions run URL、HTML/脚本/依赖版本及输出 SHA256；不会声称本地容器已执行成功。GitHub 上下文的 GITHUB_SHA 是发布结果提交的唯一父项；若 sync 分支已被其他提交推进，工作流停止普通推送，不覆盖新提交。
