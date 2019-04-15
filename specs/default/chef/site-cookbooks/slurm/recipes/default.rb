#
# Cookbook:: slurm
# Recipe:: default
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

slurmver = node[:slurm][:version]
slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]
mungeuser = node[:munge][:user][:name]

# Set up users for Slurm and Munge
group slurmuser do
  gid node[:slurm][:user][:gid]
  not_if "getent group #{slurmuser}"  
end

user slurmuser do
  comment 'User to run slurmd'
  shell '/bin/false'
  uid node[:slurm][:user][:uid]
  gid node[:slurm][:user][:gid]
  action :create
end


group mungeuser do
  gid node[:munge][:user][:gid]
  not_if "getent group #{mungeuser}"  
end

user mungeuser do
  comment 'User to run munged'
  shell '/bin/false'
  uid node[:munge][:user][:uid]
  gid node[:munge][:user][:gid]
  action :create
end


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
    owner slurmuser
    group slurmuser
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
  owner mungeuser
  group mungeuser
  mode 0700
end
directory "/var/lib/munge" do
  owner mungeuser
  group mungeuser
  mode 0711
end
directory "/var/log/munge" do
  owner mungeuser
  group mungeuser
  mode 0700
end
directory "/run/munge" do
  owner mungeuser
  group mungeuser
  mode 0755
end

directory "/sched/munge" do
  owner mungeuser
  group mungeuser
  mode 0700
end

directory '/var/spool/slurmd' do
  owner slurmuser
  action :create
end
  
directory '/var/log/slurmd' do
  owner slurmuser
  action :create
end

directory '/var/log/slurmctld' do
  owner slurmuser
  action :create
end

template '/etc/slurm/topology.conf' do
  owner "#{slurmuser}"
  source "topology.conf.erb"
  action :create_if_missing
  variables lazy {{
    :hostname => node[:hostname],
    :nodearray_machinetype => node[:cyclecloud][:node][:template] + (node[:autoscale].nil? ? "" : node[:autoscale][:machinetype]).gsub("_", ""),
    :placementgroup => node[:cyclecloud][:node][:placement_group]
  }}
end