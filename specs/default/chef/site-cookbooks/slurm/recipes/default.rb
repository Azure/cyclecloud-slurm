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
  group slurmuser
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

include_recipe 'slurm::_install' if node[:slurm][:install]

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

# Set up slurm 
user slurmuser do
  comment 'User to run slurmd'
  shell '/bin/false'
  action :create
end

# add slurm to cyclecloud so it has access to jetpack / userdata
group 'cyclecloud' do
    members [slurmuser]
    append true
    action :modify
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
