param(
    [string]$KnowledgeBase = (Join-Path $PSScriptRoot '..\datasets\knowledge-base')
)

$ErrorActionPreference = 'Stop'
$kbRoot = [System.IO.Path]::GetFullPath($KnowledgeBase)
$expectedCategories = @('Project KB', 'Standards KB', 'Defect Cases KB', 'Quality Rules KB')
$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure {
    param([string]$Message)
    $failures.Add($Message)
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Label)
    if ($Actual -ne $Expected) {
        Add-Failure "$Label expected '$Expected' but got '$Actual'"
    }
}

function Get-KbFile {
    param([string]$RelativePath)
    $fullPath = [System.IO.Path]::GetFullPath((Join-Path $kbRoot $RelativePath))
    $allowedPrefix = $kbRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($allowedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest path escapes knowledge-base root: $RelativePath"
    }
    return $fullPath
}

if (-not (Test-Path -LiteralPath $kbRoot -PathType Container)) {
    throw "Knowledge-base directory not found: $kbRoot"
}

$actualCategories = @(Get-ChildItem -LiteralPath $kbRoot -Directory | Select-Object -ExpandProperty Name | Sort-Object)
$expectedSorted = @($expectedCategories | Sort-Object)
Assert-Equal ($actualCategories -join '|') ($expectedSorted -join '|') 'Top-level categories'

$manifestPath = Join-Path $kbRoot 'manifest.json'
try {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
catch {
    Add-Failure "manifest.json is invalid: $($_.Exception.Message)"
}

if ($null -ne $manifest) {
    Assert-Equal $manifest.datasets.Count 17 'Manifest dataset count'
    foreach ($dataset in $manifest.datasets) {
        $datasetPath = Get-KbFile $dataset.local_path
        if (-not (Test-Path -LiteralPath $datasetPath -PathType Container)) {
            Add-Failure "Missing dataset directory: $($dataset.local_path)"
        }
        foreach ($asset in @($dataset.assets)) {
            if ($null -eq $asset) {
                continue
            }
            $assetPath = Get-KbFile $asset.path
            if (-not (Test-Path -LiteralPath $assetPath -PathType Leaf)) {
                Add-Failure "Missing asset: $($asset.path)"
                continue
            }
            Assert-Equal (Get-Item -LiteralPath $assetPath).Length $asset.bytes "Byte length: $($asset.path)"
            $actualHash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
            Assert-Equal $actualHash $asset.sha256 "SHA-256: $($asset.path)"
        }
    }
}

try {
    Get-Content -LiteralPath (Join-Path $kbRoot 'Standards KB\standards-catalog.json') -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
}
catch {
    Add-Failure "standards-catalog.json is invalid: $($_.Exception.Message)"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipRoot = [System.IO.Path]::GetFullPath((Join-Path ([System.IO.Path]::GetTempPath()) 'kb-zip-validation'))
$zipPrefix = $zipRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
foreach ($archive in Get-ChildItem -LiteralPath $kbRoot -Recurse -File -Filter '*.zip') {
    try {
        $zip = [System.IO.Compression.ZipFile]::OpenRead($archive.FullName)
        try {
            foreach ($entry in $zip.Entries) {
                $entryTarget = [System.IO.Path]::GetFullPath((Join-Path $zipRoot $entry.FullName))
                if (-not $entryTarget.StartsWith($zipPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                    Add-Failure "Unsafe ZIP entry: $($archive.FullName) -> $($entry.FullName)"
                    break
                }
            }
        }
        finally {
            $zip.Dispose()
        }
    }
    catch {
        Add-Failure "Unreadable ZIP: $($archive.FullName): $($_.Exception.Message)"
    }
}

foreach ($pdf in Get-ChildItem -LiteralPath (Join-Path $kbRoot 'Standards KB') -Recurse -File -Filter '*.pdf') {
    $stream = [System.IO.File]::OpenRead($pdf.FullName)
    try {
        $buffer = [byte[]]::new(5)
        [void]$stream.Read($buffer, 0, $buffer.Length)
        Assert-Equal ([System.Text.Encoding]::ASCII.GetString($buffer)) '%PDF-' "PDF signature: $($pdf.Name)"
    }
    finally {
        $stream.Dispose()
    }
}

foreach ($office in Get-ChildItem -LiteralPath $kbRoot -Recurse -File | Where-Object { $_.Extension -in '.docx', '.xlsx' }) {
    $stream = [System.IO.File]::OpenRead($office.FullName)
    try {
        $buffer = [byte[]]::new(2)
        [void]$stream.Read($buffer, 0, $buffer.Length)
        Assert-Equal ([System.Text.Encoding]::ASCII.GetString($buffer)) 'PK' "Office ZIP signature: $($office.Name)"
    }
    finally {
        $stream.Dispose()
    }
}

$cm1Root = Join-Path $kbRoot 'Project KB\cm1-nasa-trace\raw'
$cm1Source = [xml](Get-Content -LiteralPath (Join-Path $cm1Root 'CM1-sourceArtifacts.xml') -Raw)
$cm1Target = [xml](Get-Content -LiteralPath (Join-Path $cm1Root 'CM1-targetArtifacts.xml') -Raw)
$cm1Answers = [xml](Get-Content -LiteralPath (Join-Path $cm1Root 'CM1-answerSet.xml') -Raw)
Assert-Equal $cm1Source.artifacts_collection.artifacts.artifact.Count 22 'CM1 high-level artifacts'
Assert-Equal $cm1Target.artifacts_collection.artifacts.artifact.Count 53 'CM1 low-level artifacts'
Assert-Equal $cm1Answers.answer_set.links.link.Count 45 'CM1 gold links'

$ambiguityCsv = @(Get-ChildItem -LiteralPath (Join-Path $kbRoot 'Defect Cases KB\requirements-ambiguity\raw') -Recurse -File -Filter '*_labeled.csv')
$ambiguityRows = 0
foreach ($csv in $ambiguityCsv) {
    $ambiguityRows += @(Import-Csv -LiteralPath $csv.FullName).Count
}
Assert-Equal $ambiguityRows 8405 'Requirements ambiguity rows'

$codocFiles = @(Get-ChildItem -LiteralPath (Join-Path $kbRoot 'Project KB\codocbench\raw') -Recurse -File -Filter '*.jsonl')
foreach ($expected in @{'codocbench.jsonl' = 4573; 'train.jsonl' = 2300; 'test.jsonl' = 2273}.GetEnumerator()) {
    $file = $codocFiles | Where-Object Name -eq $expected.Key | Select-Object -First 1
    if ($null -eq $file) {
        Add-Failure "Missing CoDocBench file: $($expected.Key)"
    }
    else {
        Assert-Equal @(Get-Content -LiteralPath $file.FullName).Count $expected.Value "CoDocBench rows: $($expected.Key)"
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    throw "Knowledge-base validation failed with $($failures.Count) error(s)."
}

$summary = foreach ($category in $expectedCategories) {
    $categoryPath = Join-Path $kbRoot $category
    $files = @(Get-ChildItem -LiteralPath $categoryPath -Recurse -File)
    [pscustomobject]@{
        Category = $category
        Datasets = @(Get-ChildItem -LiteralPath $categoryPath -Directory).Count
        Files = $files.Count
        Bytes = ($files | Measure-Object Length -Sum).Sum
    }
}

$summary | Format-Table -AutoSize
Write-Host "Validation passed: 17 datasets in exactly four categories."
