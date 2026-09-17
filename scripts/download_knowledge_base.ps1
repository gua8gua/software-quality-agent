param(
    [string]$Destination = (Join-Path $PSScriptRoot '..\datasets\knowledge-base')
)

$ErrorActionPreference = 'Stop'
$destinationRoot = [System.IO.Path]::GetFullPath($Destination)
$datasetRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\datasets'))

function New-KbDirectory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-KbPath {
    param([string]$RelativePath)
    $resolved = [System.IO.Path]::GetFullPath((Join-Path $destinationRoot $RelativePath))
    if (-not $resolved.StartsWith($destinationRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes knowledge-base root: $RelativePath"
    }
    return $resolved
}

function Save-RemoteFile {
    param(
        [string]$Url,
        [string]$Target
    )
    New-KbDirectory (Split-Path -Parent $Target)
    if ((Test-Path -LiteralPath $Target) -and (Get-Item -LiteralPath $Target).Length -gt 0) {
        Write-Host "Already downloaded: $Target"
        return
    }
    Write-Host "Downloading: $Url"
    & curl.exe -L --fail --show-error --retry 3 --output $Target $Url
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed: $Url"
    }
}

function Expand-SafeZip {
    param(
        [string]$Archive,
        [string]$TargetDirectory
    )
    if (Test-Path -LiteralPath $TargetDirectory) {
        Write-Host "Already expanded: $TargetDirectory"
        return
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $targetRoot = [System.IO.Path]::GetFullPath($TargetDirectory)
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $entryTarget = [System.IO.Path]::GetFullPath((Join-Path $targetRoot $entry.FullName))
            if (-not $entryTarget.StartsWith($targetRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe ZIP entry in $Archive`: $($entry.FullName)"
            }
        }
    }
    finally {
        $zip.Dispose()
    }
    New-KbDirectory $TargetDirectory
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Archive, $TargetDirectory)
}

function Copy-ExistingDataset {
    param(
        [string]$ExistingName,
        [string]$Category,
        [string]$NewName = $ExistingName
    )
    $source = Join-Path $datasetRoot $ExistingName
    $target = Get-KbPath (Join-Path $Category $NewName)
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Existing dataset not found: $source"
    }
    if (-not (Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath $source -Destination $target -Recurse
    }
}

$categories = @('Project KB', 'Standards KB', 'Defect Cases KB', 'Quality Rules KB')
New-KbDirectory $destinationRoot
foreach ($category in $categories) {
    New-KbDirectory (Get-KbPath $category)
}

# Existing, already validated datasets. Originals remain in datasets/ for compatibility.
Copy-ExistingDataset 'safa-dronology-v0-v1' 'Project KB'
Copy-ExistingDataset 'lissa-smos-req2code' 'Project KB'
Copy-ExistingDataset 'irrelevant-requirements' 'Defect Cases KB'
Copy-ExistingDataset 'arta-requirement-testability' 'Quality Rules KB'

$downloads = @(
    @{
        Category = 'Project KB'; Name = 'easyclinic'; File = 'EasyClinic.zip'
        Url = 'http://sarec.nd.edu/coest/datasets/EasyClinic.zip'; Expand = $true
    },
    @{
        Category = 'Project KB'; Name = 'cm1-nasa-trace'; File = 'CM1-NASA.zip'
        Url = 'http://sarec.nd.edu/coest/datasets/CM1-NASA.zip'; Expand = $true
    },
    @{
        Category = 'Project KB'; Name = 'ebt'; File = 'EBT.zip'
        Url = 'http://sarec.nd.edu/coest/datasets/EBT.zip'; Expand = $true
    },
    @{
        Category = 'Project KB'; Name = 'codocbench'; File = 'codocbench-ee0256d.zip'
        Url = 'https://codeload.github.com/kunpai/codocbench/zip/ee0256da15a07dcf265d5313fe51a269aa7268e0'; Expand = $true
    },
    @{
        Category = 'Project KB'; Name = 'ardoco-architecture-benchmark'; File = 'ardoco-benchmark-e60ddb2.zip'
        # The archive contains paths beyond the default Windows path limit; keep the verified ZIP intact.
        Url = 'https://codeload.github.com/ardoco/benchmark/zip/e60ddb2676358048131178c925e86a5b33ec38f2'; Expand = $false
    },
    @{
        Category = 'Standards KB'; Name = 'nist-ssdf-1.1'; File = 'NIST.SP.800-218.pdf'
        Url = 'https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218.pdf'; Expand = $false
    },
    @{
        Category = 'Standards KB'; Name = 'nasa-npr-7150.2d'; File = 'N_PR_7150_002D.pdf'
        Url = 'https://nodis3.gsfc.nasa.gov/npg_img/N_PR_7150_002D_/N_PR_7150_002D_.pdf'; Expand = $false
    },
    @{
        Category = 'Standards KB'; Name = 'nasa-std-8739.8b'; File = 'NASA-STD-8739.8B.pdf'
        Url = 'https://standards.nasa.gov/sites/default/files/standards/NASA/B/0/NASA-STD-87398RevB.pdf'; Expand = $false
    },
    @{
        Category = 'Defect Cases KB'; Name = 'defects4j'; File = 'defects4j-8c16da8.zip'
        # Keep the complete metadata/framework archive intact; individual buggy projects are fetched separately by Defects4J.
        Url = 'https://codeload.github.com/rjust/defects4j/zip/8c16da8230843cdc918eaf4ddb449637f02b83c6'; Expand = $false
    },
    @{
        Category = 'Defect Cases KB'; Name = 'requirements-ambiguity'; File = 'requirements-ambiguity-v1.0.1.zip'
        Url = 'https://codeload.github.com/profzivkovic/software-requirements-ambiguity-detection-replication/zip/refs/tags/v1.0.1'; Expand = $true
    },
    @{
        Category = 'Defect Cases KB'; Name = 'nasa-cm1-defect-metrics'; File = 'cm1.zip'
        Url = 'https://zenodo.org/records/268434/files/cm1.zip?download=1'; Expand = $true
    },
    @{
        Category = 'Quality Rules KB'; Name = 'nist-ssdf-1.1'; File = 'nist.sp.800-218.ssdf-table.xlsx'
        Url = 'https://csrc.nist.gov/files/pubs/sp/800/218/final/docs/nist.sp.800-218.ssdf-table.xlsx'; Expand = $false
    },
    @{
        Category = 'Quality Rules KB'; Name = 'nasa-requirements-checklists'; File = 'PAT-013-Software-Requirements-Checklist.docx'
        Url = 'https://swehb.nasa.gov/download/attachments/114328303/PAT-013%20-%20Software%20Requirements%20Checklist.docx?api=v2'; Expand = $false
    },
    @{
        Category = 'Quality Rules KB'; Name = 'nasa-requirements-checklists'; File = 'PAT-034-SA-Requirements-Analysis-Checklist.docx'
        Url = 'https://swehb.nasa.gov/download/attachments/154501148/PAT-034%20-%20SA%20Requirements%20Analysis%20Checklist.docx?api=v2'; Expand = $false
    },
    @{
        Category = 'Quality Rules KB'; Name = 'nasa-requirements-checklists'; File = 'PAT-079-Requirements-Quality-Checklist.docx'
        Url = 'https://swehb.nasa.gov/download/attachments/207290572/PAT-079%20-%20Requirements%20Quality%20Checklist.docx?api=v2'; Expand = $false
    },
    @{
        Category = 'Quality Rules KB'; Name = 'nasa-requirements-checklists'; File = 'PAT-080-Requirements-Content-Checklist.docx'
        Url = 'https://swehb.nasa.gov/download/attachments/207290574/PAT-080%20-%20Requirements%20Content%20Checklist.docx?api=v2'; Expand = $false
    },
    @{
        Category = 'Quality Rules KB'; Name = 'nasa-requirements-checklists'; File = 'PAT-081-Requirements-Editorial-Checklist.docx'
        Url = 'https://swehb.nasa.gov/download/attachments/207290577/PAT-081%20-%20Requirements%20Editorial%20Checklist.docx?api=v2'; Expand = $false
    }
)

foreach ($item in $downloads) {
    $datasetDirectory = Get-KbPath (Join-Path $item.Category $item.Name)
    New-KbDirectory $datasetDirectory
    $archive = Join-Path $datasetDirectory $item.File
    Save-RemoteFile -Url $item.Url -Target $archive
    if ($item.Expand) {
        Expand-SafeZip -Archive $archive -TargetDirectory (Join-Path $datasetDirectory 'raw')
    }
}

Write-Host "Knowledge-base data is available at: $destinationRoot"
