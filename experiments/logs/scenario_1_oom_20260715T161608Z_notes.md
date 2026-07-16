# Failure analysis — scenario_1_oom run 2026-07-15T16:16:08Z

The injection reported success ("connection dropped") but no OOMKill happened
(target pod ended with restartCount=0, no lastState), so ContainerOOMKilled
never fired and the run timed out.

Root cause (tooling race): right after `kubectl rollout status` returns, the
app-b Service can still route to the terminating old pod, which runs with the
*original* memory limit. The single /debug/memory call landed on that old pod;
its connection dropped because the pod was terminating, which the script
misread as the OOM kill starting. The new 96Mi pod never received the load.

Fix (chaos/scenario_1_oom.py): retry the allocation up to 5 times and only
report success after observing lastState.terminated.reason == "OOMKilled" on
the target pod. The rerun at 16:29:35Z confirmed the kill on attempt 1 and the
alert fired 103 s after injection.

Unrelated but discovered while debugging the same run: after a Docker daemon
restart, kindnet on one worker had written the *other* worker's podCIDR into
/etc/cni/net.d, giving new pods out-of-CIDR IPs and breaking Service routing
(connection refused from app-a). Remedied by restarting the kind node
containers in their original start order (so container IPs match the Node
objects' recorded InternalIPs) and recreating pods whose IP fell outside their
node's podCIDR. Baseline runs should start from the PROTOCOL.md pre-checks,
which catch this state.
