#
# Cookbook Name:: slurm
# Recipe:: autostart
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#


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

directory "#{node[:cyclecloud][:bootstrap]}/slurm" do
  user "root"
  group "root"
  recursive true
end

cookbook_file "#{node[:cyclecloud][:bootstrap]}/slurm/autostart.py" do
    source "autostart.py"
    mode "0700"
    owner "root"
    group "root"
end

cookbook_file "#{node[:cyclecloud][:bootstrap]}/slurm/logging_init.py" do
    source "logging_init.py"
    mode "0700"
    owner "root"
    group "root"
end

cookbook_file "#{node[:cyclecloud][:bootstrap]}/slurm/slurmcc.py" do
    source "slurmcc.py"
    mode "0700"
    owner "root"
    group "root"
end

cookbook_file "#{node[:cyclecloud][:bootstrap]}/slurm/topology.py" do
    source "topology.py"
    mode "0700"
    owner "root"
    group "root"
end

cron "autostart" do
    command "#{node[:cyclecloud][:bootstrap]}/cron_wrapper.sh #{node[:cyclecloud][:bootstrap]}/slurm/autostart.py"
    only_if { node['cyclecloud']['cluster']['autoscale']['start_enabled'] }
end
