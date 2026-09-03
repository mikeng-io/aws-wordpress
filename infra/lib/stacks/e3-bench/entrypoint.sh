#!/usr/bin/env bash
# Runs the benchmark against both mounts in sequence within one task, so the only
# variable between the two result sets is which mount served the request - same
# CPU, same kernel, same moment in time.
set -euo pipefail

mkdir -p /local-bench/tree /efs-bench/tree

echo "E3: benchmarking local ephemeral storage"
bench /local-bench/tree > /local-bench/results.csv
echo "E3: local done, $(wc -l < /local-bench/results.csv) ops"

echo "E3: benchmarking EFS"
bench /efs-bench/tree > /efs-bench/results.csv
echo "E3: efs done, $(wc -l < /efs-bench/results.csv) ops"

# Printed to stdout (captured by awslogs) since the task's ephemeral storage does
# not survive task exit - this is the only way the results leave the task.
echo "===LOCAL_CSV_START==="
cat /local-bench/results.csv
echo "===LOCAL_CSV_END==="
echo "===EFS_CSV_START==="
cat /efs-bench/results.csv
echo "===EFS_CSV_END==="
