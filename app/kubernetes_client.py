
import re
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException

from app.prometheus_client import PrometheusClient, PrometheusError


def _iso(value: Any) -> str | None:
    """Convert a Kubernetes timestamp to ISO 8601."""
    return value.isoformat() if value else None


def _container_state(state: Any) -> dict[str, Any]:
    """Convert Kubernetes container state into a JSON-compatible dictionary."""

    if state is None:
        return {}

    result = {}

    if state.waiting:
        result["waiting"] = {
            "reason": state.waiting.reason,
            "message": state.waiting.message,
        }

    if state.running:
        result["running"] = {
            "started_at": _iso(state.running.started_at),
        }

    if state.terminated:
        result["terminated"] = {
            "reason": state.terminated.reason,
            "exit_code": state.terminated.exit_code,
            "message": state.terminated.message,
        }

    return result


def _sanitize_log(text: str) -> list[str]:
    """
    Remove common credential patterns before returning log evidence.

    This is a basic safeguard, not a complete secret-detection system.
    """

    result = []

    for line in text.splitlines()[-30:]:
        line = line.strip()

        if not line:
            continue

        # Redact Bearer authorization credentials.
        line = re.sub(
            r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+",
            r"\1[REDACTED]",
            line,
        )

        # Redact common password, token and secret assignments.
        line = re.sub(
            r"(?i)\b(password|passwd|token|api[_-]?key|secret)"
            r"(\s*[:=]\s*)([^\s,;]+)",
            r"\1\2[REDACTED]",
            line,
        )

        result.append(line[:500])

    return result


class KubernetesCollector:
    """
    Collect read-only Kubernetes evidence and Prometheus metrics.

    Supports:
      1. Local kubeconfig authentication.
      2. In-cluster ServiceAccount authentication.

    Does not modify Kubernetes resources.
    """

    def __init__(self):
        self.source = self._load_configuration()

        self.core_api = client.CoreV1Api()
        self.apps_api = client.AppsV1Api()

        # Connect to Prometheus.
        self.prometheus = PrometheusClient()

    @staticmethod
    def _load_configuration() -> str:
        """
        Load Kubernetes authentication configuration.

        Try in-cluster authentication first.
        Fall back to the developer's kubeconfig.
        """

        try:
            config.load_incluster_config()
            return "in_cluster"

        except ConfigException:
            pass

        try:
            config.load_kube_config()
            return "kubeconfig"

        except (ConfigException, FileNotFoundError, OSError) as exc:
            raise RuntimeError(
                "Unable to load Kubernetes configuration."
            ) from exc

    def _collect_pod_logs(
        self,
        pod_name: str,
        namespace: str,
        container: Any,
    ) -> dict[str, Any] | None:
        """
        Collect recent container logs.

        For restarted containers, try to retrieve the previous
        container instance logs.
        """

        state = container.state

        waiting_reason = (
            state.waiting.reason
            if state and state.waiting
            else None
        )

        # An image that cannot be pulled has no container logs.
        if waiting_reason in (
            "ImagePullBackOff",
            "ErrImagePull",
            "InvalidImageName",
        ):
            return None

        previous = bool(
            container.last_state
            and container.last_state.terminated
        )

        should_collect = (
            (container.restart_count or 0) > 0
            or not container.ready
            or bool(state and state.waiting)
        )

        if not should_collect:
            return None

        try:
            raw_logs = self.core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container.name,
                previous=previous,
                tail_lines=30,
                timestamps=True,
            )

            return {
                "container": container.name,
                "previous": previous,
                "lines": _sanitize_log(raw_logs or ""),
            }

        except ApiException:
            # Logs may not exist or log permissions may be unavailable.
            return None

    def _serialize_pod(self, pod: Any) -> dict[str, Any]:
        """Normalize a Kubernetes Pod object."""

        statuses = (
            pod.status.container_statuses or []
        ) + (
            pod.status.init_container_statuses or []
        )

        container_statuses = []
        logs = []

        for status in statuses:
            container_statuses.append(
                {
                    "name": status.name,
                    "restart_count": status.restart_count,
                    "ready": status.ready,
                    "state": _container_state(status.state),
                    "last_state": _container_state(status.last_state),
                }
            )

            log_result = self._collect_pod_logs(
                pod_name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                container=status,
            )

            if log_result:
                logs.append(log_result)

        conditions = [
            {
                "type": condition.type,
                "status": condition.status,
                "reason": condition.reason,
                "message": condition.message,
            }
            for condition in (pod.status.conditions or [])
        ]

        return {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "phase": pod.status.phase,
            "node_name": pod.spec.node_name,
            "container_statuses": container_statuses,
            "conditions": conditions,
            "logs": logs,
        }

    def _collect_pods(
        self,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Collect pods from one namespace or all namespaces."""

        if namespace:
            response = self.core_api.list_namespaced_pod(
                namespace=namespace
            )
        else:
            response = self.core_api.list_pod_for_all_namespaces()

        return [
            self._serialize_pod(pod)
            for pod in response.items
        ]

    def _collect_events(
        self,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Kubernetes events."""

        if namespace:
            response = self.core_api.list_namespaced_event(
                namespace=namespace
            )
        else:
            response = self.core_api.list_event_for_all_namespaces()

        events = []

        for event in response.items:
            involved_object = event.involved_object

            events.append(
                {
                    "namespace": event.metadata.namespace,
                    "involved_object_name": (
                        involved_object.name
                        if involved_object
                        else None
                    ),
                    "reason": event.reason,
                    "type": event.type,
                    "message": event.message,
                    "count": event.count,
                    "last_timestamp": _iso(
                        event.last_timestamp or event.event_time
                    ),
                }
            )

        return events

    def _collect_deployments(
        self,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Collect deployment replica counts and rollout conditions."""

        if namespace:
            response = self.apps_api.list_namespaced_deployment(
                namespace=namespace
            )
        else:
            response = self.apps_api.list_deployment_for_all_namespaces()

        deployments = []

        for deployment in response.items:
            status = deployment.status

            conditions = [
                {
                    "type": condition.type,
                    "status": condition.status,
                    "reason": condition.reason,
                    "message": condition.message,
                }
                for condition in (status.conditions or [])
            ]

            deployments.append(
                {
                    "name": deployment.metadata.name,
                    "namespace": deployment.metadata.namespace,
                    "desired_replicas": (
                        deployment.spec.replicas
                        if deployment.spec.replicas is not None
                        else 1
                    ),
                    "updated_replicas": status.updated_replicas or 0,
                    "available_replicas": status.available_replicas or 0,
                    "conditions": conditions,
                }
            )

        return deployments

    def _collect_nodes(self) -> list[dict[str, Any]]:
        """Collect node health conditions."""

        response = self.core_api.list_node()

        nodes = []

        for node in response.items:
            conditions = [
                {
                    "type": condition.type,
                    "status": condition.status,
                    "reason": condition.reason,
                    "message": condition.message,
                }
                for condition in (node.status.conditions or [])
            ]

            nodes.append(
                {
                    "name": node.metadata.name,
                    "conditions": conditions,
                }
            )

        return nodes

    def _collect_prometheus_metrics(
        self,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve actual CPU and memory metrics from Prometheus.

        If Prometheus is unavailable, preserve Kubernetes
        diagnostics instead of failing the entire collection.
        """

        try:
            return self.prometheus.get_pod_metrics(
                namespace=namespace
            )

        except PrometheusError as exc:
            return {
                "source": "prometheus",
                "status": "unavailable",
                "namespace_filter": namespace or "all namespaces",
                "pods": [],
                "error": str(exc),
            }

    def collect_snapshot(
        self,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """
        Collect the complete Kubernetes and Prometheus evidence snapshot.

        This snapshot is passed to the diagnostic engine.
        """

        metrics = self._collect_prometheus_metrics(namespace)

        return {
            "source": self.source,
            "collected_at": datetime.now(timezone.utc).isoformat(),

            "pods": self._collect_pods(namespace),

            "events": self._collect_events(namespace),

            "deployments": self._collect_deployments(namespace),

            "nodes": self._collect_nodes(),

            "metrics": metrics,
        }
