#
# Cookbook Name:: slurm
# Recipe:: login

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

include_recipe "slurm::default"
include_recipe "slurm::sethostname"
require 'chef/mixin/shell_out'


slurmuser = node[:slurm][:user][:name]

remote_file '/etc/munge/munge.key' do
  source 'file:///sched/munge/munge.key'
  owner 'munge'
  group 'munge'
  mode '0700'
  action :create
end

link '/etc/slurm/slurm.conf' do
  to '/sched/slurm.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/cyclecloud.conf' do
  to '/sched/cyclecloud.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/cgroup.conf' do
  to '/sched/cgroup.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/topology.conf' do
  to '/sched/topology.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/gres.conf' do
  to '/sched/gres.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
  only_if { ::File.exist?('/sched/gres.conf') }
end

service 'munge' do
  action [:enable, :restart]
end