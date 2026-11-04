from typing import Any

from fastapi import Body, FastAPI

from app.diagnostics import analyze_snapshot

app = FastAPI(
    title="AI Kubernetes Troubleshooting Agent",
    description="Read-only Kubernetes workload diagnosis and remediation guidance.",
    version="1.0.0",
)


def get_demo_snapshot() -> dict[str, Any]:
    return {
        "source": "synthetic_demo",
        "pods": [
            {
                "name": "payments-api",
                "namespace": "production",
                "phase": "Running",
                "container_statuses": [
                    {
                        "name": "payments",
                        "restart_count": 8,
                        "state": {
                            "waiting": {
                                "reason": "CrashLoopBackOff",
                                "message": "Container repeatedly exited."
                            }
                        }
                    }
                ],
                "conditions": []
            },
            {
                "name": "frontend",
                "namespace": "production",
                "phase": "Pending",
                "container_statuses": [
                    {
                        "name": "frontend",
                        "restart_count": 0,
                        "state": {
                            "waiting": {
                                "reason": "ImagePullBackOff",
                                "message": "Registry returned an image-not-found error."
                            }
                        }
                    }
                ],
                "conditions": []
            },
            {
                "name": "worker",
                "namespace": "production",
                "phase": "Running",
                "container_statuses": [
                    {
                        "name": "worker",
                        "restart_count": 1,
                        "state": {
                            "running": {}
                        },
                        "last_state": {
                            "terminated": {
                                "reason": "OOMKilled",
                                "exit_code": 137
                            }
                        }
                    }
                ],
                "conditions": []
            },
            {
                "name": "catalog-api",
                "namespace": "staging",
                "phase": "Running",
                "container_statuses": [
                    {
                        "name": "catalog",
                        "restart_count": 0,
                        "ready": False,
                        "state": {"running": {}}
                    }
                ],
                "conditions": [
                    {"type": "Ready", "status": "False"}
                ]
            }
        ],
        "events": [],
        "deployments": [
            {
                "name": "checkout",
                "namespace": "production",
                "desired_replicas": 3,
                "updated_replicas": 1,
                "available_replicas": 1,
                "conditions": [
                    {
                        "type": "Progressing",
                        "status": "False",
                        "reason": "ProgressDeadlineExceeded",
                        "message": "Deployment exceeded its progress deadline."
                    }
                ]
            }
        ],
        "nodes": [
            {
                "name": "worker-node",
                "conditions": [
                    {
                        "type": "MemoryPressure",
                        "status": "True",
                        "message": "Node is reporting memory pressure."
                    }
                ]
            }
        ],
        "metrics": {
            "pods": [
                {
                    "namespace": "production",
                    "pod_name": "worker",
                    "cpu_percent": 35,
                    "memory_percent": 96
                }
            ]
        }
    }


@app.get("/")
def root() -> dict[str, str]:
    return {
        "application": "AI Kubernetes Troubleshooting Agent",
        "version": "1.0.0",
        "documentation": "/docs",
        "health": "/health"
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/api/v1/demo")
def demo() -> dict[str, Any]:
    return analyze_snapshot(get_demo_snapshot())


@app.post("/api/v1/analyze")
def analyze(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return analyze_snapshot(payload)

from fastapi import HTTPException
from kubernetes.client.exceptions import ApiException
from app.kubernetes_client import KubernetesCollector


@app.get("/api/v1/cluster/analyze")
def analyze_live_cluster(namespace: str | None = None) -> dict[str, Any]:
    """
    Collect real Kubernetes evidence and analyze it.
    Optional query parameter: namespace.
    """
    try:
        snapshot = KubernetesCollector().collect_snapshot(
            namespace=namespace
        )

        report = analyze_snapshot(snapshot)
        report["collected_at"] = snapshot["collected_at"]
        report["namespace_filter"] = namespace or "all namespaces"

        return report

    except ApiException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Kubernetes API access failed: {exc.reason}",
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
