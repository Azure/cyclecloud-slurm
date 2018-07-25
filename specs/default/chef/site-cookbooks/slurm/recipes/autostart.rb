#
# Cookbook Name:: slurm
# Recipe:: autostart
#


cookbook_file "#{node[:cyclecloud][:bootstrap]}/autostart.py" do
    source "autostart.py"
    mode "0700"
    owner "root"
    group "root"
end

cron "autostart" do
    command "#{node[:cyclecloud][:bootstrap]}/cron_wrapper.sh #{node[:cyclecloud][:bootstrap]}/autostart.py"
    only_if { node['cyclecloud']['cluster']['autoscale']['start_enabled'] }
end