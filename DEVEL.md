# Quick Start

```
CODE_DIR=~/code  # or where ever you wish to develop this
cd $CODE_DIR
git clone https://github.com/Azure/cyclecloud-scalelib.git
# cd cyclecloud-scalelib
# git checkout specific-branch

cd $CODE_DIR
git clone https://github.com/Azure/cyclecloud-slurm.git
cd cyclecloud-slurm

docker-package.sh ../cyclecloud-scalelib
```

## New Slurm Versions
1. Add a record to slurm/install/slurm_supported_version.py:SUPPORTED_VERSIONS
    Currently it looks like
    ```json
    SUPPORTED_VERSIONS = {
        "22.05.8-1": {
            "rhel": [{"platform_version": "el8", "arch": "x86_64"}],
            "debian": [{"arch": "amd64"}],
        },
        "23.02.3-1": {
            "rhel": [{"platform_version": "el8", "arch": "x86_64"}],
            "debian": [{"arch": "amd64"}],
        }
    }
    ```
2. Build the RPMs and DEBs
    ```bash
    # this should be all you need, but new versions may require
    # updates. See the below for more information, as they are what is run inside the
    # container.
    # ./specs/default/cluster-init/files/01-build-debs.sh
    # ./specs/default/cluster-init/files/00-build-slurm.sh
    ./docker-rpmbuild.sh
    ```

3. Create a new -bins release
    Currently we have a release called 2023-03-13-bins in GitHub.

    See `https://github.com/Azure/cyclecloud-slurm/releases/tag/2023-03-13-bins`

    Simply create a new release and upload all of the files in slurm/install/slurm-pkgs/.

3.  Update slurm/install/slurm_supported_version.py:CURRENT_DOWNLOAD_URL
    Point this variable at the latest slurm bins release.

4. Rerun docker-package.sh
    When you run docker-package.sh, even on a new repo, the files should now be downloaded.