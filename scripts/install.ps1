# Installs groundcast: creates the conda environment from environment.yml (or
# updates it when it exists), then runs `groundcast setup` in it, passing on
# this script's arguments (for example -- --yes, or --torch cpu --no-asr).
# Set GROUNDCAST_CONDA to a conda or mamba executable to choose which is used.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "environment.yml"
$match = Select-String -Path $envFile -Pattern '^name:\s*(\S+)' | Select-Object -First 1
if (-not $match) { throw "No 'name:' line in $envFile" }
$name = $match.Matches[0].Groups[1].Value

function Find-Conda {
    if ($env:GROUNDCAST_CONDA) { return $env:GROUNDCAST_CONDA }
    if ($env:CONDA_EXE -and (Test-Path $env:CONDA_EXE)) { return $env:CONDA_EXE }
    foreach ($tool in "conda", "mamba") {
        $cmd = Get-Command $tool -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { return $cmd.Source }
    }
    # Default install folders of Miniforge, Miniconda, and Anaconda.
    foreach ($base in $env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData) {
        foreach ($dist in "miniforge3", "miniconda3", "anaconda3") {
            $exe = Join-Path $base "$dist\Scripts\conda.exe"
            if (Test-Path $exe) { return $exe }
        }
    }
    return $null
}

$conda = Find-Conda
if (-not $conda) {
    Write-Host "conda was not found. Install Miniforge from https://conda-forge.org/download/,"
    Write-Host "open a new terminal, and run this installer again."
    exit 1
}
Write-Host "Using $conda"

Push-Location $root
try {
    $envs = (& $conda env list --json | Out-String | ConvertFrom-Json).envs
    $exists = $envs | Where-Object { (Split-Path -Leaf $_) -eq $name }
    if ($exists) {
        Write-Host "Updating the conda environment $name"
        & $conda env update -n $name -f $envFile
    } else {
        Write-Host "Creating the conda environment $name (Python, ffmpeg, poppler, Tesseract, groundcast)"
        & $conda env create -f $envFile
    }
    if ($LASTEXITCODE) { throw "conda failed (exit status $LASTEXITCODE)" }
    & $conda run --no-capture-output -n $name groundcast setup @args
    $status = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($status -eq 0) {
    Write-Host ""
    Write-Host "Done. Start groundcast with the groundcast shortcut on the desktop or in the Start menu."
    Write-Host "From a terminal: conda activate $name, then groundcast launch"
}
exit $status
