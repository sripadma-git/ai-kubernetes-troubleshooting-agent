from app.diagnostics import analyze_snapshot


def make_snapshot(**overrides):
    snapshot = {
        "source": "test",
        "pods": [],
        "events": [],
        "deployments": [],
        "nodes": [],
        "metrics": {"pods": []},
    }
    snapshot.update(overrides)
    return snapshot


def test_detect_crash_loop_backoff():
    snapshot = make_snapshot(
        pods=[{
            "name": "backend",
            "namespace": "default",
            "phase": "Running",
            "container_statuses": [{
                "name": "api",
                "restart_count": 5,
                "state": {
                    "waiting": {
                        "reason": "CrashLoopBackOff",
                        "message": "Application exited repeatedly",
                    }
                },
            }],
            "conditions": [],
        }]
    )

    report = analyze_snapshot(snapshot)

    assert any(
        f["code"] == "CrashLoopBackOff"
        for f in report["findings"]
    )


def test_detect_image_pull_backoff():
    snapshot = make_snapshot(
        pods=[{
            "name": "frontend",
            "namespace": "default",
            "phase": "Pending",
            "container_statuses": [{
                "name": "web",
                "restart_count": 0,
                "state": {
                    "waiting": {
                        "reason": "ImagePullBackOff",
                        "message": "Image not found",
                    }
                },
            }],
            "conditions": [],
        }]
    )

    report = analyze_snapshot(snapshot)

    assert any(
        f["code"] == "ImagePullBackOff"
        for f in report["findings"]
    )


def test_detect_failed_rollout():
    snapshot = make_snapshot(
        deployments=[{
            "name": "backend",
            "namespace": "default",
            "desired_replicas": 3,
            "updated_replicas": 1,
            "available_replicas": 1,
            "conditions": [{
                "type": "Progressing",
                "status": "False",
                "reason": "ProgressDeadlineExceeded",
                "message": "Deployment rollout timed out",
            }],
        }]
    )

    report = analyze_snapshot(snapshot)

    assert any(
        f["code"] == "FailedRollout"
        for f in report["findings"]
    )


def test_detect_unhealthy_workload():
    snapshot = make_snapshot(
        pods=[{
            "name": "payments",
            "namespace": "default",
            "phase": "Running",
            "container_statuses": [],
            "conditions": [{
                "type": "Ready",
                "status": "False",
            }],
        }]
    )

    report = analyze_snapshot(snapshot)

    assert any(
        f["code"] == "UnhealthyWorkload"
        for f in report["findings"]
    )


def test_detect_node_resource_pressure():
    snapshot = make_snapshot(
        nodes=[{
            "name": "worker",
            "conditions": [{
                "type": "MemoryPressure",
                "status": "True",
                "message": "Memory pressure detected",
            }],
        }]
    )

    report = analyze_snapshot(snapshot)

    assert any(
        f["code"] == "ResourcePressure"
        for f in report["findings"]
    )


def test_detect_high_prometheus_memory_usage():
    snapshot = make_snapshot(
        metrics={
            "pods": [{
                "namespace": "default",
                "pod_name": "backend",
                "cpu_percent": 40,
                "memory_percent": 95,
            }]
        }
    )

    report = analyze_snapshot(snapshot)

    assert any(
        f["code"] == "ResourcePressure"
        and "memory" in f["summary"].lower()
        for f in report["findings"]
    )


def test_healthy_snapshot_returns_no_findings():
    report = analyze_snapshot(make_snapshot())

    assert report["status"] == "healthy"
    assert report["findings"] == []


def test_remediation_is_included():
    snapshot = make_snapshot(
        pods=[{
            "name": "backend",
            "namespace": "default",
            "phase": "Running",
            "container_statuses": [{
                "name": "api",
                "restart_count": 3,
                "state": {
                    "waiting": {
                        "reason": "CrashLoopBackOff",
                    }
                },
            }],
            "conditions": [],
        }]
    )

    report = analyze_snapshot(snapshot)
    finding = report["findings"][0]

    assert finding["root_cause"]
    assert finding["evidence"]
    assert finding["remediation"]
