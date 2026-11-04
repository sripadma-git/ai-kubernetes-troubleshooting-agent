from typing import Any


def _finding(
    code: str,
    severity: str,
    resource: str,
    summary: str,
    root_cause: str,
    evidence: list[str],
    remediation: list[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "resource": resource,
        "summary": summary,
        "root_cause": root_cause,
        "evidence": evidence,
        "remediation": remediation,
    }


def analyze_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Analyze normalized Kubernetes evidence.

    Expected snapshot keys:
      pods, events, deployments, nodes, metrics.

    This function is deliberately read-only. It never changes a cluster.
    """
    findings: list[dict[str, Any]] = []

    pods = snapshot.get("pods", [])
    events = snapshot.get("events", [])
    deployments = snapshot.get("deployments", [])
    nodes = snapshot.get("nodes", [])
    metrics = snapshot.get("metrics", {})

    # Analyze individual pods and their container states.
    for pod in pods:
        name = pod.get("name", "unknown")
        namespace = pod.get("namespace", "default")
        resource = f"Pod/{namespace}/{name}"

        statuses = pod.get("container_statuses", [])
        ready_condition = next(
            (
                condition
                for condition in pod.get("conditions", [])
                if condition.get("type") == "Ready"
            ),
            None,
        )

        related_events = [
            event
            for event in events
            if event.get("involved_object_name") == name
            and event.get("namespace", namespace) == namespace
        ]

        detected_waiting_issue = False

        for container in statuses:
            container_name = container.get("name", "unknown")
            state = container.get("state", {})
            waiting = state.get("waiting") or {}
            waiting_reason = waiting.get("reason", "")

            if waiting_reason == "CrashLoopBackOff":
                detected_waiting_issue = True
                findings.append(
                    _finding(
                        code="CrashLoopBackOff",
                        severity="critical",
                        resource=resource,
                        summary=f"Container {container_name} is repeatedly restarting.",
                        root_cause=(
                            waiting.get("message")
                            or "The container repeatedly exits after starting."
                        ),
                        evidence=[
                            f"Container: {container_name}",
                            f"Restart count: {container.get('restart_count', 0)}",
                            f"Waiting reason: {waiting_reason}",
                        ],
                        remediation=[
                            f"kubectl logs -n {namespace} {name} -c {container_name} --previous",
                            f"kubectl describe pod -n {namespace} {name}",
                            "Inspect application startup errors, dependencies, configuration, and health probes.",
                        ],
                    )
                )

            elif waiting_reason in ("ImagePullBackOff", "ErrImagePull"):
                detected_waiting_issue = True
                findings.append(
                    _finding(
                        code="ImagePullBackOff",
                        severity="critical",
                        resource=resource,
                        summary=f"Container {container_name} image could not be pulled.",
                        root_cause=(
                            waiting.get("message")
                            or "The container image could not be downloaded from its registry."
                        ),
                        evidence=[
                            f"Container: {container_name}",
                            f"Waiting reason: {waiting_reason}",
                        ],
                        remediation=[
                            f"kubectl describe pod -n {namespace} {name}",
                            "Verify the image repository, tag, and registry availability.",
                            "Check imagePullSecrets and registry authentication without exposing credentials.",
                        ],
                    )
                )

            states_to_check = [
                state.get("terminated") or {},
                (container.get("last_state") or {}).get("terminated") or {},
            ]

            for terminated in states_to_check:
                if terminated.get("reason") == "OOMKilled":
                    findings.append(
                        _finding(
                            code="ResourcePressure",
                            severity="critical",
                            resource=resource,
                            summary=f"Container {container_name} was terminated due to memory exhaustion.",
                            root_cause=(
                                "The container exceeded its available memory limit."
                            ),
                            evidence=[
                                f"Container: {container_name}",
                                "Termination reason: OOMKilled",
                                f"Exit code: {terminated.get('exit_code', 'unknown')}",
                            ],
                            remediation=[
                                f"kubectl describe pod -n {namespace} {name}",
                                f"kubectl top pod -n {namespace} {name}",
                                "Inspect memory usage and application memory leaks before adjusting resource limits.",
                            ],
                        )
                    )
                    break

        # Detect readiness failures and failed health probes.
        readiness_failed = (
            ready_condition is not None
            and ready_condition.get("status") == "False"
        )

        unhealthy_events = [
            event
            for event in related_events
            if event.get("reason") in ("Unhealthy", "FailedScheduling")
        ]

        if (
            (readiness_failed or unhealthy_events or pod.get("phase") == "Failed")
            and not detected_waiting_issue
        ):
            evidence = [f"Pod phase: {pod.get('phase', 'unknown')}"]

            if readiness_failed:
                evidence.append(
                    f"Ready condition: {ready_condition.get('status')}"
                )

            for event in unhealthy_events[:5]:
                evidence.append(
                    f"Event {event.get('reason')}: {event.get('message', '')}"
                )

            findings.append(
                _finding(
                    code="UnhealthyWorkload",
                    severity="warning",
                    resource=resource,
                    summary="Pod is not healthy or ready.",
                    root_cause=(
                        "The readiness condition, workload phase, or Kubernetes events "
                        "indicate a workload health problem."
                    ),
                    evidence=evidence,
                    remediation=[
                        f"kubectl describe pod -n {namespace} {name}",
                        f"kubectl logs -n {namespace} {name} --all-containers",
                        "Inspect readiness and liveness probe configuration.",
                    ],
                )
            )

    # Analyze deployment rollout status.
    for deployment in deployments:
        name = deployment.get("name", "unknown")
        namespace = deployment.get("namespace", "default")

        desired = deployment.get("desired_replicas", 0)
        updated = deployment.get("updated_replicas", 0)
        available = deployment.get("available_replicas", 0)

        conditions = deployment.get("conditions", [])

        failed_condition = next(
            (
                condition
                for condition in conditions
                if condition.get("reason") in ("ProgressDeadlineExceeded", "ReplicaFailure") and condition.get("status") in ("False", "True")
            ),
            None,
        )

        if failed_condition or (desired > 0 and available < desired):
            reason = (
                failed_condition.get("reason")
                if failed_condition
                else "ReplicaMismatch"
            )

            findings.append(
                _finding(
                    code="FailedRollout",
                    severity="critical",
                    resource=f"Deployment/{namespace}/{name}",
                    summary="Deployment has not reached its desired available replica count.",
                    root_cause=(
                        failed_condition.get("message", reason)
                        if failed_condition
                        else "Available replicas are fewer than desired replicas."
                    ),
                    evidence=[
                        f"Desired replicas: {desired}",
                        f"Updated replicas: {updated}",
                        f"Available replicas: {available}",
                        f"Rollout condition: {reason}",
                    ],
                    remediation=[
                        f"kubectl rollout status deployment/{name} -n {namespace}",
                        f"kubectl describe deployment {name} -n {namespace}",
                        f"kubectl get rs -n {namespace}",
                        "Inspect the new ReplicaSet and its pods for scheduling, image, configuration, and readiness failures.",
                    ],
                )
            )

    # Analyze node-level pressure conditions.
    for node in nodes:
        node_name = node.get("name", "unknown")

        for condition in node.get("conditions", []):
            condition_type = condition.get("type", "")
            condition_status = condition.get("status", "")

            if (
                condition_type in ("MemoryPressure", "DiskPressure", "PIDPressure")
                and condition_status == "True"
            ):
                findings.append(
                    _finding(
                        code="ResourcePressure",
                        severity="warning",
                        resource=f"Node/{node_name}",
                        summary=f"Node reports {condition_type}.",
                        root_cause=condition.get("message") or condition_type,
                        evidence=[
                            f"Node: {node_name}",
                            f"Condition: {condition_type}=True",
                        ],
                        remediation=[
                            f"kubectl describe node {node_name}",
                            "Inspect node capacity, allocated resources, and workloads consuming resources.",
                        ],
                    )
                )

    # Analyze Prometheus metrics when available.
    for metric in metrics.get("pods", []):
        namespace = metric.get("namespace", "default")
        pod_name = metric.get("pod_name", "unknown")

        for metric_name in ("cpu_percent", "memory_percent"):
            value = metric.get(metric_name)

            if isinstance(value, (int, float)) and value >= 90:
                findings.append(
                    _finding(
                        code="ResourcePressure",
                        severity="warning",
                        resource=f"Pod/{namespace}/{pod_name}",
                        summary=f"Pod {metric_name.replace('_', ' ')} is at least 90%.",
                        root_cause=(
                            f"Observed {metric_name} is {value}%, indicating high resource utilization."
                        ),
                        evidence=[f"{metric_name}: {value}%"],
                        remediation=[
                            f"kubectl top pod -n {namespace} {pod_name}",
                            "Review resource requests, limits, and application utilization patterns.",
                        ],
                    )
                )

    status = "issues_detected" if findings else "healthy"

    return {
        "status": status,
        "summary": (
            f"Detected {len(findings)} potential issue(s)."
            if findings
            else "No issues detected in the supplied evidence."
        ),
        "source": snapshot.get("source", "unknown"),
        "resource_counts": {
            "pods": len(pods),
            "deployments": len(deployments),
            "nodes": len(nodes),
            "events": len(events),
        },
        "findings": findings,
    }

