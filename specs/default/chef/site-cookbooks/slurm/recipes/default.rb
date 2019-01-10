#
# Cookbook:: slurm
# Recipe:: default
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

slurmver = node[:slurm][:version]
slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]

myplatform=node[:platform]
case myplatform
when 'ubuntu'
  package 'Install slurm' do
    package_name 'slurm-wlm'
  end
  package 'Install slurm-torque compatibility package' do
    package_name 'slurm-wlm-torque'
  end
  # Add symlink because config path is different on ubuntu
  link '/etc/slurm' do
    to '/etc/slurm-llnl'
    owner "#{slurmuser}"
    group "#{slurmuser}"
  end

  link '/bin/sinfo' do
    to '/usr/bin/sinfo'
  end
  link '/bin/squeue' do
    to '/usr/bin/squeue'
  end
when 'centos'
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

#Fix munge permissions and create key
directory "/etc/munge" do
  owner 'munge'
  group 'munge'
  mode 0700
end
directory "/var/lib/munge" do
  owner 'munge'
  group 'munge'
  mode 0711
end
directory "/var/log/munge" do
  owner 'munge'
  group 'munge'
  mode 0700
end
directory "/run/munge" do
  owner 'munge'
  group 'munge'
  mode 0755
end

directory "/sched/munge" do
  owner 'munge'
  group 'munge'
  mode 0700
end

# Set up slurm 
user slurmuser do
  comment 'User to run slurmd'
  shell '/bin/false'
  action :create
end

directory '/var/spool/slurmd' do
  owner "#{slurmuser}"
  action :create
end
  
directory '/var/log/slurmd' do
  owner "#{slurmuser}"
  action :create
end

directory '/var/log/slurmctld' do
  owner "#{slurmuser}"
  action :create
end
