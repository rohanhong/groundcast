#!/bin/sh
# Installs groundcast on Linux or macOS: creates the conda environment from
# environment.yml (or updates it when it exists), then runs `groundcast setup`
# in it, passing on this script's arguments (for example --yes, or
# --torch cpu --no-asr). Set GROUNDCAST_CONDA to a conda or mamba executable
# to choose which is used.
set -eu

root=$(cd "$(dirname "$0")" && pwd)
env_file="$root/environment.yml"
name=$(sed -n 's/^name:[[:space:]]*\([^[:space:]]*\).*/\1/p' "$env_file" | head -n 1)
[ -n "$name" ] || { echo "No 'name:' line in $env_file" >&2; exit 1; }

find_conda() {
  if [ -n "${GROUNDCAST_CONDA:-}" ]; then echo "$GROUNDCAST_CONDA"; return; fi
  if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then echo "$CONDA_EXE"; return; fi
  for tool in conda mamba; do
    if command -v "$tool" >/dev/null 2>&1; then command -v "$tool"; return; fi
  done
  # Default install folders of Miniforge, Miniconda, and Anaconda.
  for dist in miniforge3 miniconda3 anaconda3; do
    if [ -x "$HOME/$dist/bin/conda" ]; then echo "$HOME/$dist/bin/conda"; return; fi
  done
}

conda=$(find_conda)
if [ -z "$conda" ]; then
  echo "conda was not found. Install Miniforge from https://conda-forge.org/download/,"
  echo "open a new terminal, and run this installer again."
  exit 1
fi
echo "Using $conda"

cd "$root"
if "$conda" env list | awk '{print $1}' | grep -qx "$name"; then
  echo "Updating the conda environment $name"
  "$conda" env update -n "$name" -f "$env_file"
else
  echo "Creating the conda environment $name (Python, ffmpeg, poppler, Tesseract, groundcast)"
  "$conda" env create -f "$env_file"
fi
"$conda" run --no-capture-output -n "$name" groundcast setup "$@"
echo
echo "Done. Start groundcast from its shortcut in the applications menu, or run:"
echo "  conda activate $name"
echo "  groundcast launch"
