
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.diagnostics import analyze_snapshot
from app.kubernetes_client import KubernetesCollector


app = FastAPI(
    title="AI Kubernetes Troubleshooting Agent",
    description=(
        "A read-only API that collects Kubernetes evidence "
        "and identifies common cluster issues."
    ),
    version="1.0.0",
)

# Allow the local React/Vite frontend to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "AI Kubernetes Troubleshooting Agent API is running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/api/v1/demo")
def demo() -> dict[str, Any]:
    """
    Return sample diagnostic data for frontend testing.
    """
    snapshot = {
        "source": "demo",
        "pods": [
            {
                "name": "payment-api",
                "namespace": "default",
                "phase": "Running",
                "conditions": [
                    {"type": "Ready", "status": "False"}
                ],
                "container_statuses": [
                    {
                        "name": "app",
                        "restart_count": 5,
                        "state": {
                            "waiting": {
                                "reason": "CrashLoopBackOff",
                                "message": "The container repeatedly exits after starting.",
                            }
                        },
                    }
                ],
            },
            {
                "name": "orders-api",
                "namespace": "default",
                "phase": "Pending",
                "conditions": [],
                "container_statuses": [
                    {
                        "name": "app",
                        "restart_count": 0,
                        "state": {
                            "waiting": {
                                "reason": "ImagePullBackOff",
                                "message": "The container image could not be pulled.",
                            }
                        },
                    }
                ],
            },
        ],
        "events": [],
        "deployments": [],
        "nodes": [],
        "metrics": {},
    }

    return analyze_snapshot(snapshot)


@app.post("/api/v1/analyze")
def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Analyze a supplied Kubernetes evidence snapshot.
    """
    try:
        return analyze_snapshot(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(exc)}",
        ) from exc


@app.get("/api/v1/cluster/analyze")
def analyze_live_cluster(
    namespace: str | None = Query(
        default=None,
        description="Optional Kubernetes namespace to analyze.",
    ),
) -> dict[str, Any]:
    """
    Collect evidence from the configured cluster and analyze it.
    """
    try:
        collector = KubernetesCollector()
        snapshot = collector.collect_snapshot(namespace=namespace)
        return analyze_snapshot(snapshot)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Cluster analysis failed: {str(exc)}",
        ) from exc
