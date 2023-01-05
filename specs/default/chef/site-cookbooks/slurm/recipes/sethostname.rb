#
# Cookbook Name:: slurm
# Recipe:: sethostname

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

case node[:platform_family] 
  when 'ubuntu', 'debian'
    waagent_service_name = "walinuxagent"
  else
    waagent_service_name = "waagent"
end

if node[:slurm][:ensure_waagent_monitor_hostname] then
  execute 'ensure hostname monitoring' do
    command "sed -i s/Provisioning.MonitorHostName=n/Provisioning.MonitorHostName=y/g  /etc/waagent.conf && systemctl restart #{waagent_service_name}"
    only_if "grep -Eq '^Provisioning.MonitorHostName=n$' /etc/waagent.conf" 
  end
end

nodename = node[:cyclecloud][:node][:name]
node_prefix = node[:slurm][:node_prefix]
if node_prefix && !nodename.downcase.start_with?(node_prefix.downcase) then
  nodename = node_prefix + nodename
end

dns_suffix = node[:slurm][:node_domain_suffix]
if !dns_suffix.nil? && !dns_suffix.empty? && dns_suffix[0] != "." then
  dns_suffix = "." + dns_suffix
end


if node[:slurm][:use_nodename_as_hostname] then

  # Change hostname and remove from /etc/hosts if present.
  # This to ensure effective DNS registration check. 
  bash 'Change hostname and remove from hosts' do
    code <<-EOH
      #!/bin/bash
      oldHostname=$(hostname)
      hostnamectl set-hostname #{nodename}#{dns_suffix}
      sed -i '/#{node[:cyclecloud][:instance][:ipv4]}/d' /etc/hosts
      EOH
  end
  
  # Remove published hostname file and remove waagent
  execute 'remove published_hostname' do
    command "rm -f /var/lib/waagent/published_hostname && systemctl restart #{waagent_service_name}"
    only_if "nslookup #{node[:ipaddress]} | grep -iv #{nodename}"
    only_if { ::File.exist?("/var/lib/waagent/published_hostname")}
  end

  execute 'wait for hostname detection' do
    command "nslookup #{node[:ipaddress]} | grep -i #{nodename}"
    only_if "hostname | grep -q #{nodename}"
    action :run
    retries 30
    retry_delay 10
  end
end
