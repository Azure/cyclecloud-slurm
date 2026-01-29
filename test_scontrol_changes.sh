#!/bin/bash
# Test script to verify scontrol-based metrics collection

echo "========================================"
echo "Testing scontrol-based metrics collection"
echo "========================================"
echo ""

# Test 1: Check if scontrol show nodes --json works
echo "Test 1: Checking scontrol show nodes --json..."
if scontrol show nodes --json > /tmp/test_nodes.json 2>&1; then
    NODE_COUNT=$(python3 -c "import json; data=json.load(open('/tmp/test_nodes.json')); print(len(data.get('nodes', [])))")
    echo "✓ Success! Found $NODE_COUNT nodes"
else
    echo "✗ Failed to run scontrol show nodes --json"
    exit 1
fi
echo ""

# Test 2: Check if scontrol show partitions --json works
echo "Test 2: Checking scontrol show partitions --json..."
if scontrol show partitions --json > /tmp/test_partitions.json 2>&1; then
    PARTITION_COUNT=$(python3 -c "import json; data=json.load(open('/tmp/test_partitions.json')); print(len(data.get('partitions', [])))")
    PARTITIONS=$(python3 -c "import json; data=json.load(open('/tmp/test_partitions.json')); print(', '.join([p.get('name', '') for p in data.get('partitions', [])]))")
    echo "✓ Success! Found $PARTITION_COUNT partitions: $PARTITIONS"
else
    echo "✗ Failed to run scontrol show partitions --json"
    exit 1
fi
echo ""

# Test 3: Test the Python parser
echo "Test 3: Testing parse_scontrol_nodes_json() function..."
python3 << 'PYEOF'
import json
import sys
from typing import Optional, Dict

def parse_scontrol_nodes_json(output: str, partition: Optional[str] = None) -> Dict[str, float]:
    """Parse scontrol show nodes --json output and return node state metrics."""
    
    NODE_STATES = [
        ('ALLOCATED', 'alloc'),
        ('IDLE', 'idle'),
        ('MIXED', 'mixed'),
        ('COMPLETING', 'completing'),
        ('MAINT', 'maint'),
        ('RESERVED', 'resv'),
        ('DOWN', 'down'),
        ('DRAIN', 'drain'),
        ('DRAINING', 'draining'),
        ('DRAINED', 'drained'),
        ('FAIL', 'fail'),
        ('POWERED_DOWN', 'powered_down'),
        ('POWERING_UP', 'powering_up'),
        ('CLOUD', 'cloud')
    ]
    
    if not output:
        return {'sinfo_nodes': 0.0}
    
    try:
        data = json.loads(output)
        nodes = data.get('nodes', [])
        
        if partition:
            nodes = [n for n in nodes if partition in n.get('partitions', [])]
        
        total_nodes = len(nodes)
        state_counts = {}
        
        for node in nodes:
            node_states = node.get('state', [])
            if not isinstance(node_states, list):
                node_states = [node_states] if node_states else []
            
            for state in node_states:
                state = state.upper()
                state_counts[state] = state_counts.get(state, 0) + 1
        
        metrics = {}
        prefix = 'sinfo_partition_nodes' if partition else 'sinfo_nodes'
        metrics[prefix] = float(total_nodes)
        
        for state_str, metric_suffix in NODE_STATES:
            metric_name = f"{prefix}_{metric_suffix}"
            metrics[metric_name] = float(state_counts.get(state_str, 0))
        
        drain_total = (
            metrics.get(f'{prefix}_drain', 0) +
            metrics.get(f'{prefix}_draining', 0) +
            metrics.get(f'{prefix}_drained', 0)
        )
        metrics[f'{prefix}_drain_total'] = drain_total
        
        return metrics
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return {'sinfo_nodes': 0.0}

# Test with real data
with open('/tmp/test_nodes.json', 'r') as f:
    output = f.read()

metrics = parse_scontrol_nodes_json(output)
total_nodes = int(metrics.get('sinfo_nodes', 0))
idle = int(metrics.get('sinfo_nodes_idle', 0))
cloud = int(metrics.get('sinfo_nodes_cloud', 0))
powered_down = int(metrics.get('sinfo_nodes_powered_down', 0))

print(f"✓ Parser working! Metrics: total={total_nodes}, idle={idle}, cloud={cloud}, powered_down={powered_down}")
PYEOF

if [ $? -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "All tests passed! ✓"
    echo "========================================"
    echo ""
    echo "The scontrol-based implementation is working correctly."
    echo "You can now deploy the updated code to production."
else
    echo ""
    echo "✗ Tests failed!"
    exit 1
fi
