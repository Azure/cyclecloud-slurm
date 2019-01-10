#
# Cookbook Name:: slurm
# Recipe:: scheduler
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

include_recipe 'slurm::default'

slurmuser = node[:slurm][:user][:name]
myplatform = node[:platform]

execute 'Create munge key' do
  command "dd if=/dev/urandom bs=1 count=1024 >/sched/munge/munge.key"
  creates "/sched/munge/munge.key"
  action :run
end

file '/sched/munge/munge.key' do
  owner 'munge'
  group 'munge'
  mode 0700
end

remote_file '/etc/munge/munge.key' do
  source 'file:///sched/munge/munge.key'
  owner 'munge'
  group 'munge'
  mode '0700'
  action :create
end

service 'munge' do
  action [:enable, :restart]
end

template '/sched/slurm.conf' do
  owner "#{slurmuser}"
  source "slurm.conf_#{myplatform}.erb"
  action :create_if_missing
  variables lazy {{
    :nodename => node[:machinename]
  }}
end

bash 'Add nodes to slurm config' do
  code <<-EOH
    iplist=$(grep ip- /etc/hosts | awk '{print $2}' | cut -d'.' -f1 | paste -sd "," -)
    echo "\nNodename=${iplist} State=FUTURE" >> /sched/slurm.conf
    touch /etc/slurm.installed
    EOH
  not_if { ::File.exist?('/etc/slurm.installed') }
end

link '/etc/slurm/slurm.conf' do
  to '/sched/slurm.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

cookbook_file "/etc/security/limits.d/slurm-limits.conf" do
  source "slurm-limits.conf"
  owner "root"
  group "root"
  mode "0644"
  action :create
end

service 'slurmctld' do
  action [:enable, :start]
end

defer_block "Defer starting munge until end of converge" do
  service 'munge' do
    action [:enable, :restart]
  end
end

include_recipe "slurm::autostart"

