#!/usr/bin/env
set -e
. ~/./demo_vars.sh
cd
wget https://github.com/fullstorydev/grpcurl/releases/download/v1.8.7/grpcurl_1.8.7_linux_x86_64.tar.gz
tar xzf grpcurl_1.8.7_linux_x86_64.tar.gz
~/grpcurl -insecure -d '{"id": "'${DEMO_SUBSCRIPTION_ID}'", "properties": {"tenant_id": "5678", "registration_state": "Registered", "registration_date": "2021-02-01T14:01:01Z"}}' localhost:5679 microsoft.batchclusters.Service/CreateOrUpdateSubscription