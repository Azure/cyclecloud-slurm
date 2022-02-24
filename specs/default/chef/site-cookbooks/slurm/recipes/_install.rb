#
# Cookbook:: slurm
# Recipe:: _install
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

slurmver = node[:slurm][:version]
slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]
mungeuser = node[:munge][:user][:name]

myplatform = node[:platform]
case myplatform
when 'ubuntu'

  package 'Install munge' do
    package_name 'munge'
  end
  slurmrpms = %w[slurm slurm-devel slurm-example-configs slurm-slurmctld slurm-slurmd]
  slurmrpms.each do |slurmpkg|
    jetpack_download "#{slurmpkg}_#{slurmver}_amd64.deb" do
      project "slurm"
      not_if { ::File.exist?("#{node[:jetpack][:downloads]}/#{slurmpkg}_#{slurmver}_#{slurmarch}.deb") }
    end
  end

  slurmrpms.each do |slurmpkg|
    execute "Install #{slurmpkg}_#{slurmver}_amd64.deb" do
      command "apt install -y #{node[:jetpack][:downloads]}/#{slurmpkg}_#{slurmver}_#{slurmarch}.deb"
      action :run
      not_if { ::File.exist?("/var/spool/slurmd") }
    end
  end

  # Need to manually create links for libraries the RPMs are linked to
  link '/usr/lib/x86_64-linux-gnu/libreadline.so.6' do
    to '/lib/x86_64-linux-gnu/libreadline.so.7'
  end

  link '/usr/lib/x86_64-linux-gnu/libhistory.so.6' do
    to '/lib/x86_64-linux-gnu/libhistory.so.7'
  end

  link '/usr/lib/x86_64-linux-gnu/libncurses.so.5' do
    to '/lib/x86_64-linux-gnu/libncurses.so.5'
  end

  link '/usr/lib/x86_64-linux-gnu/libtinfo.so.5' do
    to '/lib/x86_64-linux-gnu/libtinfo.so.5'
  end

  # file '/etc/ld.so.conf.d/slurmlibs.conf' do
  #   content "/usr/lib/x86_64-linux-gnu/"
  #   action :create_if_missing
  # end



when 'centos', 'rhel', 'redhat', 'almalinux'
  # Required for munge
  package 'epel-release'

  # slurm package depends on munge
  package 'munge'

  execute 'Install perl-Switch' do
    command "dnf --enablerepo=powertools install -y perl-Switch"
    action :run
    only_if { node[:platform_version] >= '8' }
  end

  slurmrpms = %w[slurm slurm-devel slurm-example-configs slurm-slurmctld slurm-slurmd slurm-perlapi slurm-torque slurm-openlava]
  slurmrpms.each do |slurmpkg|
    jetpack_download "#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm" do
      project "slurm"
      not_if { ::File.exist?("#{node[:jetpack][:downloads]}/#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm") }
    end
  end

  slurmrpms.each do |slurmpkg|
    package "#{node[:jetpack][:downloads]}/#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm" do
      action :install
    end
  end
end