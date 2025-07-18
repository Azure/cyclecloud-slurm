#!/bin/bash
echo see .build.log for more information
log_file=".build.log"
check_dirty_changes() {
  if [ -n "$(git status --porcelain)" ]; then
    echo "Error: There are uncommitted changes in the current branch. Please commit or stash them before running this script."
    exit 1
  fi
}

# Call the function to check for dirty changes
check_dirty_changes

print_branch_and_last_commit() {
  branch=$(git rev-parse --abbrev-ref HEAD)
  last_commit=$(git log -1 --pretty=format:"%h - %s (%ci)")

  printf "%-20s: %s\n" "Current branch" "$branch"
  printf "%-20s: %s\n" "Last commit" "$last_commit"
}

delete_existing_blobs() {
  printf "%-20s: %s\n" "Deleting existing Blob Files" ""
  while IFS= read -r file; do
    if [ -f "blobs/$file" ]; then
      printf "%-20s: %s\n" "" "$file"
      rm -f "blobs/$file" || exit 1
    fi
  done < <(awk -F' *= *' '/^\[blobs\]/ {found=1} found && /^Files/ {gsub(/, */, "\n", $2); print $2; exit}' project.ini)
}

check_blobs_files_exist() {
  local version="$1"
  local missing_files=0

  printf "%-20s: %s\n" "Blob Files" ""
  while IFS= read -r file; do
    printf "%-20s: %s\n" "" "$file"
    if [ ! -f "blobs/$file" ]; then
      echo "Error: File blobs/$file does not exist."
      missing_files=1
    fi
  done < <(awk -F' *= *' '/^\[blobs\]/ {found=1} found && /^Files/ {gsub(/, */, "\n", $2); print $2; exit}' project.ini)

  if [ $missing_files -eq 1 ]; then
    echo "One or more required files are missing in the blobs directory."
    exit 1

  fi
}

get_version_from_project_ini() {
  version=$(awk -F' *= *' '/^\[project\]/ {found=1} found && /^version/ {print $2; exit}' project.ini)
  printf "%-20s: %s\n" "Project Version" "$version"
  check_blobs_files_exist "$version"
}

local_azslurm=/source/
if [ "$1" != "" ]; then
  scalelib=$(realpath $1)
  local_scalelib=/source/cyclecloud-scalelib
  extra_args="-v ${scalelib}:${local_scalelib}"
fi

if command -v docker; then
  runtime=docker
  runtime_args=
elif command -v podman; then
  runtime=podman
  runtime_args="--privileged"
else
  echo "`docker` or `podman` binary not found. Install docker or podman to build RPMs with this script"
  exit 1
fi

{
  delete_existing_blobs
  # allows caching
  $runtime build -t azslurm_build:latest -f util/Dockerfile .
  $runtime run -v $(pwd):${local_azslurm} $runtime_args $extra_args -ti azslurm_build:latest /bin/bash ${local_azslurm}/util/build.sh $local_scalelib
} &> $log_file

# Call the function to print the branch and the last commit
print_branch_and_last_commit
get_version_from_project_ini
