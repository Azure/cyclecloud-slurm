#!/bin/bash
# set-stack-limit.sh
# Sets stack size limit to 8192 KB persistently

STACK_KB=8192
STACK_LIMIT_FILE="/etc/security/limits.d/stack.conf"
echo "Setting interactive shell limits in $STACK_LIMIT_FILE..."
sudo bash -c "cat > $STACK_LIMIT_FILE" <<EOF
# Stack size limits for all users
*   soft    stack   ${STACK_KB}
*   hard    stack   ${STACK_KB}
EOF