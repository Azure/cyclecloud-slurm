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

cookbook_file "#{node[:cyclecloud][:bootstrap]}/writeactivenodes.sh" do
    source "writeactivenodes.sh"
    mode "0700"
    owner "root"
    group "root"
end

cron "writeactivenodes" do
    command "#{node[:cyclecloud][:bootstrap]}/cron_wrapper.sh #{node[:cyclecloud][:bootstrap]}/writeactivenodes.sh"
    only_if { node['cyclecloud']['cluster']['autoscale']['start_enabled'] }
end

cookbook_file "#{node[:cyclecloud][:bootstrap]}/writenodeaddrs.sh" do
    source "writenodeaddrs.sh"
    mode "0700"
    owner "root"
    group "root"
end

cron "writenodeaddrs" do
    command "#{node[:cyclecloud][:bootstrap]}/cron_wrapper.sh #{node[:cyclecloud][:bootstrap]}/writenodeaddrs.sh"
end 

directory "#{node[:cyclecloud][:bootstrap]}/slurm" do
  user "root"
  group "root"
  recursive true
end


scripts = ["cyclecloud_slurm.py", "slurmcc.py", "cyclecloud_slurm.sh", "resume_program.sh", "resume_fail_program.sh", "suspend_program.sh"]
scripts.each do |filename| 
    cookbook_file "#{node[:cyclecloud][:bootstrap]}/slurm/#{filename}" do
        source "#{filename}"
        mode "0755"
        owner "root"
        group "root"
    end
end

# we will be appending to this file, so that the next step is monotonic
template '/sched/slurm.conf.base' do
  owner "#{slurmuser}"
  source "slurm.conf_#{myplatform}.erb"
  action :create_if_missing
  variables lazy {{
    :nodename => node[:machinename],
    :bootstrap => "#{node[:cyclecloud][:bootstrap]}/slurm",
    :resume_timeout => node[:slurm][:resume_timeout],
    :suspend_timeout => node[:slurm][:suspend_timeout],
    :suspend_time => node[:cyclecloud][:cluster][:autoscale][:idle_time_after_jobs]
  }}
end

bash 'Add nodes to slurm config' do
  code <<-EOH
    cp /sched/slurm.conf.base /sched/slurm.conf || exit 1;
    #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh slurm_conf >> /sched/slurm.conf || exit 1;
    #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh topology > /sched/topology.conf || exit 1;
    #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh create_nodes || exit 1;
    touch /etc/slurm.installed
    EOH
  not_if { ::File.exist?('/etc/slurm.installed') }
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
