#
# Cookbook Name:: slurm
# Recipe:: sethostname

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.


if node[:slurm][:ensure_waagent_monitor_hostname] then
  execute 'ensure hostname monitoring' do
    command 'sed -i s/Provisioning.MonitorHostName=n/Provisioning.MonitorHostName=y/g  /etc/waagent.conf && systemctl restart walinuxagent'
    only_if "grep -Eq '^Provisioning.MonitorHostName=n$' /etc/waagent.conf" 
  end
end

nodename = node[:cyclecloud][:node][:name]
dns_suffix = node[:slurm][:node_domain_suffix]
if !dns_suffix.nil? && !dns_suffix.empty? && dns_suffix[0] != "." then
  dns_suffix = "." + dns_suffix
end


if node[:slurm][:use_nodename_as_hostname] then
  
  execute 'unset hostname' do
    command "hostnamectl set-hostname #{nodename}-unset#{dns_suffix}"
    only_if "hostname | grep -qv #{nodename}-unset"
    only_if "nslookup #{node[:ipaddress]} | grep -v #{nodename}"
    # reboot detected
    only_if { ::File.exist?("/etc/slurm.reenabled")}
  end
  
  execute 'wait for hostname unset detection' do
    command "nslookup #{node[:ipaddress]} | grep #{nodename}-unset"
    # wait for waagent to notice the change
    only_if "hostname | grep -q #{nodename}-unset"
    retries 12
    retry_delay 10
  end
  
  execute 'set hostname' do
    command "hostnamectl set-hostname #{nodename}#{dns_suffix}"
    action :run
  end

  execute 'wait for hostname detection' do
    command "nslookup #{node[:ipaddress]} | grep #{nodename} | grep -v #{nodename}-unset"
    only_if "hostname | grep -q #{nodename}"
    action :run
    retries 12
    retry_delay 10
  end
end
