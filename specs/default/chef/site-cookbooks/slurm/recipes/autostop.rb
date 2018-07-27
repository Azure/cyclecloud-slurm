#
# Cookbook Name:: slurm
# Recipe:: autostop
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

cookbook_file "#{node[:cyclecloud][:bootstrap]}/autostop.rb" do
  source "autostop.rb"
  owner "root"
  group "root"
  mode "0700"
  action :create
end
    
# Convert our stop interval into a number of minutes rounded up and run the script on that interval
interval = (node[:cyclecloud][:cluster][:autoscale][:stop_interval].to_i / 60.0).ceil
cron "autostop" do
  minute "*/#{interval}"
  command "#{node[:cyclecloud][:bootstrap]}/cron_wrapper.sh #{node[:cyclecloud][:bootstrap]}/autostop.rb > /dev/null 2>&1"
  only_if { node[:cyclecloud][:cluster][:autoscale][:stop_enabled] }
end
