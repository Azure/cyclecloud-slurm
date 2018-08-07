#
# Cookbook Name:: slurm
# Recipe:: execute
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

include_recipe "slurm::default"

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
  mode '0700'
end

defer_block "Defer starting slurmd until end of converge" do
  service 'slurmd' do
    action [:enable, :start]
  end

  service 'munge' do
    action [:enable, :restart]
  end

  myhost = lambda { node[:hostname] }
  # Re-enable a host the first time it converges in the event it was drained
  execute 'set node to active' do
    command "scontrol update nodename=#{myhost.call} state=IDLE && touch /etc/slurm.reenabled"
    creates '/etc/slurm.reenabled'
  end
end

include_recipe "slurm::autostop"
