import json
import os
from typing import Any

import requests


class PrometheusError(RuntimeError):
    """Raised when Prometheus cannot provide valid query results."""


class PrometheusClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 5.0,
    ):
        self.base_url = (
            base_url
            or os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")
        ).rstrip("/")

        self.timeout = timeout
        self.session = requests.Session()

    @staticmethod
    def _selector(namespace: str | None) -> str:
        filters = [
            'container!=""',
            'image!=""',
        ]

        if namespace:
            filters.append(f"namespace={json.dumps(namespace)}")

        return ",".join(filters)

    @staticmethod
    def _limit_selector(
        resource: str,
        namespace: str | None,
    ) -> str:
        filters = [
            f'resource="{resource}"',
            'unit="core"' if resource == "cpu" else 'unit="byte"',
        ]

        if namespace:
            filters.append(f"namespace={json.dumps(namespace)}")

        return ",".join(filters)

    def query_vector(self, promql: str) -> dict[tuple[str, str], float]:
        """Execute an instant PromQL query and group values by namespace and pod."""
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()

        except (requests.RequestException, ValueError) as exc:
            raise PrometheusError(
                f"Prometheus query failed: {exc}"
            ) from exc

        if payload.get("status") != "success":
            raise PrometheusError(
                payload.get("error", "Prometheus returned an unsuccessful query.")
            )

        data = payload.get("data", {})

        if data.get("resultType") != "vector":
            raise PrometheusError(
                "Expected a Prometheus instant-vector result."
            )

        results: dict[tuple[str, str], float] = {}

        for sample in data.get("result", []):
            labels = sample.get("metric", {})
            value = sample.get("value", [])

            namespace = labels.get("namespace")
            pod = labels.get("pod")

            if not namespace or not pod or len(value) < 2:
                continue

            try:
                numeric_value = float(value[1])
            except (TypeError, ValueError):
                continue

            key = (namespace, pod)
            results[key] = results.get(key, 0.0) + numeric_value

        return results

    def get_pod_metrics(
        self,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Collect CPU and memory usage and compare against container limits."""
        selector = self._selector(namespace)

        cpu_usage_query = (
            "sum by (namespace, pod) "
            f"(rate(container_cpu_usage_seconds_total{{{selector}}}[5m]))"
        )

        memory_usage_query = (
            "sum by (namespace, pod) "
            f"(container_memory_working_set_bytes{{{selector}}})"
        )

        cpu_limit_selector = self._limit_selector("cpu", namespace)
        memory_limit_selector = self._limit_selector("memory", namespace)

        cpu_limit_query = (
            "sum by (namespace, pod) "
            f"(kube_pod_container_resource_limits{{{cpu_limit_selector}}})"
        )

        memory_limit_query = (
            "sum by (namespace, pod) "
            f"(kube_pod_container_resource_limits{{{memory_limit_selector}}})"
        )

        cpu_usage = self.query_vector(cpu_usage_query)
        memory_usage = self.query_vector(memory_usage_query)
        cpu_limits = self.query_vector(cpu_limit_query)
        memory_limits = self.query_vector(memory_limit_query)

        all_pods = (
            set(cpu_usage)
            | set(memory_usage)
            | set(cpu_limits)
            | set(memory_limits)
        )

        results = []

        for pod_namespace, pod_name in sorted(all_pods):
            key = (pod_namespace, pod_name)

            cpu = cpu_usage.get(key)
            memory = memory_usage.get(key)
            cpu_limit = cpu_limits.get(key)
            memory_limit = memory_limits.get(key)

            cpu_percent = (
                round(cpu / cpu_limit * 100, 2)
                if cpu is not None and cpu_limit and cpu_limit > 0
                else None
            )

            memory_percent = (
                round(memory / memory_limit * 100, 2)
                if memory is not None and memory_limit and memory_limit > 0
                else None
            )

            results.append({
                "namespace": pod_namespace,
                "pod_name": pod_name,
                "cpu_cores": round(cpu, 6) if cpu is not None else None,
                "memory_bytes": memory,
                "cpu_limit_cores": cpu_limit,
                "memory_limit_bytes": memory_limit,
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
            })

        return {
            "source": "prometheus",
            "status": "available",
            "namespace_filter": namespace or "all namespaces",
            "pods": results,
        }