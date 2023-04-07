#!/usr/bin/env bash
accounting_enabled=0
if [ "False" -eq $(jetpack config slurm.accounting.enabled False) ]; then
    accounting_enabled=1
fi
suse_platform=$(jetpack config platform)
slurmver=$(jetpack config slurm.version)
slurmver_major=$(echo $slurmver | cut -d- -f1 | cut -d. -f1)
slurmver_minor=$(echo $slurmver | cut -d- -f1 | cut -d. -f2)
grep -q "sle-hpc" /etc/os-release
if [ $1 -eq 0 ]; then
    suse_platform="sle-hpc"
fi

case $suse_platform in
    sle-hpc|sle_hpc)
        packages="slurm slurm-devel slurm-config slurm-munge slurm-torque perl-slurm"
    ;;

    opensuseleap|opensuse-tumbleweed)
        packages="slurm slurm-devel slurm-config slurm-munge slurm-torque slurm-perlapi slurm-example-configs"
    ;;
    *)
        echo "Unsupported platform: $suse_platform"
        exit 1
        ;;
esac


# Install packages
for package in $packages; do
    if [ "$suse_platform" == "sle-hpc" ]; then
        package=$(echo $package | sed "s/slurm/slurm_${slurmver_major}_${slurmver_minor}/g")
    fi
    zypper --non-interactive install $package
done

if [ $accounting_enabled -eq 1 ]; then
    if [ "$suse_platform" == "sle-hpc" ]; then
        package=$(echo $package | sed "slurm_${slurmver_major}_${slurmver_minor}-slurmdbd")
    fi
    zypper --non-interactive install $package
if
