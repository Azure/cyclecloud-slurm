#
# Cookbook Name:: slurm
# Recipe:: execute
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

include_recipe "slurm::default"
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

link '/etc/slurm/topology.conf' do
  to '/sched/topology.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

defer_block "Defer starting slurmd until end of converge" do
  nodename=shell_out("grep '#{node[:ipaddress]} ' /sched/nodeaddrs | cut -d' ' -f2-").stdout
  if nodename.nil? || nodename.strip().empty?() then
    raise "Waiting for nodeaddr to appear in /sched/nodeaddrs. If this persists, check that writenodeaddrs.sh is running on the master"
  end

  nodename=nodename.strip()

  slurmd_sysconfig="SLURMD_OPTIONS=-N #{nodename}"
  # TODO RDH
  file '/etc/sysconfig/slurmd' do
    content slurmd_sysconfig
    mode '0700'
    owner 'slurm'
    group 'slurm'
  end

  service 'slurmd' do
    action [:enable, :start]
  end

  service 'munge' do
    action [:enable, :restart]
  end

  myhost = lambda { node[:hostname] }
  # Re-enable a host the first time it converges in the event it was drained
  execute 'set node to active' do
    command "scontrol update nodename=#{nodename} state=UNDRAIN && touch /etc/slurm.reenabled"
    creates '/etc/slurm.reenabled'
  end
end

#include_recipe "slurm::autostop"
