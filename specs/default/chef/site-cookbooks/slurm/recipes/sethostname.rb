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
if node_prefix && !nodename.start_with?(node_prefix) then
  nodename = node_prefix + nodename
end

dns_suffix = node[:slurm][:node_domain_suffix]
if !dns_suffix.nil? && !dns_suffix.empty? && dns_suffix[0] != "." then
  dns_suffix = "." + dns_suffix
end


if node[:slurm][:use_nodename_as_hostname] then

  execute 'remove published_hostname' do
    command "rm -f /var/lib/waagent/published_hostname && systemctl restart #{waagent_service_name}"
    only_if "nslookup #{node[:ipaddress]} | grep -v #{nodename}"
    only_if "hostname | grep -qv #{nodename}"
    only_if { ::File.exist?("/var/lib/waagent/published_hostname")}
  end
  
  execute 'set hostname' do
    command "hostnamectl set-hostname #{nodename}#{dns_suffix}"
    action :run
  end

  bash "update hostname via jetpack" do
    code <<-EOF
    #{node[:cyclecloud][:home]}/system/embedded/bin/python -c "import jetpack.converge as jc; jc._send_installation_status('warning')"
  EOF
  end

  execute 'wait for hostname detection' do
    command "nslookup #{node[:ipaddress]} | grep #{nodename}"
    only_if "hostname | grep -q #{nodename}"
    action :run
    retries 12
    retry_delay 10
  end
end
