#!/usr/bin/env bash

function get_platform() {
    id=$(jetpack props get os.id rhel)
    valid_platforms="rhel ubuntu suse debian"
    if [[ ! " $valid_platforms " =~ " $id " ]]; then
        id_like=$(jetpack props get os.id_like rhel)
        for platform in ${id_like}; do
            if [[ " $valid_platforms " =~ " $platform " ]]; then
                id="$platform"
                break
            fi
        done
    fi
    echo "$id"
}