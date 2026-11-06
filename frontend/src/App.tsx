import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";
const ANALYZE_ENDPOINT = `${API_BASE_URL}/api/v1/cluster/analyze`;

type Severity = "critical" | "warning" | "info" | string;

interface Finding {
  code: string;
  severity: Severity;
  resource: string;
  summary: string;
  root_cause: string;
  evidence: string[];
  remediation: string[];
  explanation?: string;
  impact?: string;
  confidence?: "high" | "medium" | "low" | string;
  priority?: number;
}

interface ResourceCounts {
  pods: number;
  deployments: number;
  nodes: number;
  events: number;
}

interface AnalysisResponse {
  status: string;
  summary: string;
  source: string;
  resource_counts: ResourceCounts;
  findings: Finding[];
  collected_at?: string;
  namespace_filter?: string;
}

type SeverityFilter = "all" | "critical" | "warning" | "info";

const DEFAULT_COUNTS: ResourceCounts = {
  pods: 0,
  deployments: 0,
  nodes: 0,
  events: 0,
};

function formatDate(value?: string): string {
  if (!value) return "Not analyzed yet";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Not analyzed yet";
  }

  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function getSeverityClass(severity: Severity): string {
  const normalized = severity.toLowerCase();

  if (normalized === "critical" || normalized === "high") {
    return "critical";
  }

  if (normalized === "warning" || normalized === "medium") {
    return "warning";
  }

  return "info";
}

function getFindingIcon(code: string): string {
  if (code.toLowerCase().includes("image")) return "▧";
  if (code.toLowerCase().includes("rollout")) return "↻";
  if (code.toLowerCase().includes("crash")) return "⚡";
  if (code.toLowerCase().includes("memory")) return "◧";
  if (code.toLowerCase().includes("cpu")) return "◉";
  return "⚠";
}

function App() {
  const [namespace, setNamespace] = useState("default");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const analyzeCluster = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const params = new URLSearchParams({
        namespace,
      });

      const response = await fetch(`${ANALYZE_ENDPOINT}?${params.toString()}`);

      if (!response.ok) {
        throw new Error(
          `Analysis request failed with HTTP ${response.status}.`
        );
      }

      const data = (await response.json()) as AnalysisResponse;

      if (!Array.isArray(data.findings)) {
        throw new Error("The API response does not contain a findings array.");
      }

      setAnalysis(data);

      setSelectedFinding((current) => {
        if (!data.findings.length) return null;

        if (current) {
          const matchingFinding = data.findings.find(
            (finding) =>
              finding.resource === current.resource &&
              finding.code === current.code
          );

          if (matchingFinding) return matchingFinding;
        }

        return data.findings[0];
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "An unknown error occurred.";

      setError(
        message.includes("Failed to fetch")
          ? "Unable to reach the FastAPI service. Confirm it is running at 127.0.0.1:8000 and check CORS."
          : message
      );
    } finally {
      setLoading(false);
    }
  }, [namespace]);

  useEffect(() => {
  const timer = window.setTimeout(() => {
    void analyzeCluster();
  }, 0);

  return () => window.clearTimeout(timer);
}, [analyzeCluster]);

  const findings = useMemo(
    () => analysis?.findings ?? [],
    [analysis?.findings]
  );

  const counts = analysis?.resource_counts ?? DEFAULT_COUNTS;

  const severityCounts = useMemo(() => {
    return findings.reduce(
      (totals, finding) => {
        const severity = getSeverityClass(finding.severity);

        if (severity === "critical") {
          totals.critical += 1;
        } else if (severity === "warning") {
          totals.warning += 1;
        } else {
          totals.info += 1;
        }

        return totals;
      },
      { critical: 0, warning: 0, info: 0 }
    );
  }, [findings]);

  const filteredFindings = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();

    return findings.filter((finding) => {
      const matchesSeverity =
        severityFilter === "all" ||
        getSeverityClass(finding.severity) === severityFilter;

      const matchesSearch =
        !query ||
        finding.code.toLowerCase().includes(query) ||
        finding.resource.toLowerCase().includes(query) ||
        finding.summary.toLowerCase().includes(query) ||
        finding.root_cause.toLowerCase().includes(query);

      return matchesSeverity && matchesSearch;
    });
  }, [findings, searchQuery, severityFilter]);

  const lastAnalyzed = formatDate(analysis?.collected_at);

  const handleNamespaceChange = (value: string) => {
    setNamespace(value);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <span className="brand-mark-inner">K</span>
          </div>
          <div>
            <div className="brand-name">KubeSage</div>
            <div className="brand-subtitle">Cluster intelligence</div>
          </div>
        </div>

        <div className="sidebar-section-label">WORKSPACE</div>

        <nav className="sidebar-nav">
          <a className="nav-link active" href="#overview">
            <span className="nav-icon" aria-hidden="true">▦</span>
            <span>Overview</span>
          </a>
          <a className="nav-link" href="#metrics">
            <span className="nav-icon" aria-hidden="true">◉</span>
            <span>Cluster health</span>
          </a>
          <a className="nav-link" href="#incidents">
             <span className="nav-icon">⋯</span>
            <span>Incidents</span>
            {findings.length > 0 && (
              <span className="nav-count">{findings.length}</span>
            )}
          </a>
          <a className="nav-link" href="#insights">
            <span className="nav-icon">✧</span>
            <span>AI insights</span>
          </a>
        </nav>

        <div className="sidebar-bottom">
          <div className="connection-card">
            <div className="connection-top">
              <span className="connection-dot" />
              <span>Local cluster</span>
            </div>
            <div className="connection-detail">Connected through kubeconfig</div>
            <div className="connection-footer">
              <span className="connection-status">API reachable</span>
              <span className="connection-symbol">↗</span>
            </div>
          </div>

          <div className="sidebar-user">
            <div className="user-avatar">S</div>
            <div className="user-info">
              <div className="user-name">KubeSage</div>
              <div className="user-role">Cluster operator</div>
            </div>
            <span className="user-menu">•••</span>
          </div>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span>
            <span className="breadcrumb-separator">/</span>
            <strong>Overview</strong>
          </div>

          <div className="topbar-right">
            <div className="live-indicator">
              <span className="live-dot" />
              Live data
            </div>
            <div className="topbar-avatar">S</div>
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <div className="eyebrow">
                <span className="eyebrow-sparkle">✦</span>
                CLUSTER INTELLIGENCE
              </div>
              <h1>Kubernetes overview</h1>
              <p className="page-description">
                Monitor your workloads, detect issues, and understand what
                needs attention across your cluster.
              </p>
            </div>

            <div className="analysis-meta">
              <span className="analysis-meta-label">LAST ANALYZED</span>
              <span className="analysis-meta-value">{lastAnalyzed}</span>
            </div>
          </section>

          <section className="control-bar">
            <div className="namespace-control">
              <label htmlFor="namespace-select">Namespace</label>
              <select
                id="namespace-select"
                value={namespace}
                onChange={(event) => handleNamespaceChange(event.target.value)}
              >
                <option value="default">default</option>
                <option value="kube-system">kube-system</option>
                <option value="all">All namespaces</option>
              </select>
            </div>

            <button
              className="primary-button"
              onClick={() => void analyzeCluster()}
              disabled={loading}
            >
              <span className={loading ? "button-spinner" : "button-sparkle"}>
                {loading ? "" : "✦"}
              </span>
              {loading ? "Analyzing cluster..." : "Analyze cluster"}
            </button>
          </section>

          {error && (
            <div className="error-banner" role="alert">
              <div className="error-icon">!</div>
              <div className="error-content">
                <strong>Unable to complete analysis</strong>
                <span>{error}</span>
              </div>
              <button
                className="error-retry"
                onClick={() => void analyzeCluster()}
              >
                Retry
              </button>
            </div>
          )}

          <section className="status-card">
            <div className="status-card-left">
              <div className="status-icon">
                {loading ? "↻" : findings.length > 0 ? "!" : "✓"}
              </div>
              <div>
                <div className="status-label">CURRENT CLUSTER STATUS</div>
                <h2>
                  {loading
                    ? "Analyzing cluster"
                    : findings.length > 0
                      ? "Issues detected"
                      : "Cluster looks healthy"}
                </h2>
                <p>
                  {loading
                    ? "Collecting and analyzing cluster resources..."
                    : analysis?.summary ??
                      "Run an analysis to inspect your cluster."}
                </p>
              </div>
            </div>

            <div className="status-card-right">
              <span className="status-live-dot" />
              <span>{error ? "Connection issue" : "Live data received"}</span>
            </div>
          </section>

          <section className="metrics-grid" id="metrics">
            <MetricCard
              icon="⌘"
              label="Nodes"
              value={counts.nodes}
              description="Cluster compute"
              footer="NODE INVENTORY"
              accent="purple"
            />
            <MetricCard
              icon="⚡"
              label="Pods"
              value={counts.pods}
              description={`Namespace: ${analysis?.namespace_filter ?? namespace}`}
              footer="WORKLOADS"
              accent="blue"
            />
            <MetricCard
              icon="◧"
              label="Deployments"
              value={counts.deployments}
              description="Deployment resources"
              footer="APPLICATIONS"
              accent="cyan"
            />
            <MetricCard
              icon="⚠"
              label="Active findings"
              value={findings.length}
              description={`${severityCounts.critical} critical · ${severityCounts.warning} warning`}
              footer="DIAGNOSTICS"
              accent="orange"
            />
          </section>

          <section className="workspace-section" id="incidents">
            <div className="section-heading">
              <div>
                <div className="section-eyebrow">OBSERVABILITY</div>
                <h2>Incident workspace</h2>
                <p>
                  Review detected issues and inspect their diagnostic context.
                </p>
              </div>

              <div className="source-badge">
                <span className="source-dot" />
                {analysis?.source ?? "Waiting for data"}
              </div>
            </div>

            <div className="incident-layout">
              <section className="findings-panel">
                <div className="panel-heading">
                  <div className="panel-title">
                    <h3>Findings</h3>
                    <span className="panel-count">{findings.length}</span>
                  </div>
                  <button
                    className="icon-button"
                    aria-label="Refresh analysis"
                    title="Refresh analysis"
                    onClick={() => void analyzeCluster()}
                    disabled={loading}
                  >
                    ↻
                  </button>
                </div>

                <div className="findings-search">
                  <span className="search-icon">⌕</span>
                  <input
                    type="search"
                    placeholder="Search incidents..."
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    aria-label="Search incidents"
                  />
                  <span className="search-shortcut">⌘ K</span>
                </div>

                <div className="severity-filters">
                  {(["all", "critical", "warning", "info"] as const).map(
                    (filter) => (
                      <button
                        key={filter}
                        className={`severity-filter ${
                          severityFilter === filter ? "selected" : ""
                        }`}
                        onClick={() => setSeverityFilter(filter)}
                      >
                        {filter === "all"
                          ? "All severities"
                          : filter.charAt(0).toUpperCase() + filter.slice(1)}
                      </button>
                    )
                  )}
                </div>

                <div className="findings-list">
                  {loading && findings.length === 0 ? (
                    <div className="list-state">
                      <div className="large-spinner" />
                      <span>Analyzing cluster resources...</span>
                    </div>
                  ) : filteredFindings.length === 0 ? (
                    <div className="list-state">
                      <div className="empty-state-icon">✓</div>
                      <strong>No findings match</strong>
                      <span>Try changing your search or severity filter.</span>
                    </div>
                  ) : (
                    filteredFindings.map((finding, index) => {
                      const isSelected =
                        selectedFinding?.resource === finding.resource &&
                        selectedFinding?.code === finding.code;

                      return (
                        <button
                          key={`${finding.resource}-${finding.code}-${index}`}
                          className={`finding-item ${
                            isSelected ? "selected" : ""
                          }`}
                          onClick={() => setSelectedFinding(finding)}
                        >
                          <div
                            className={`finding-icon ${getSeverityClass(
                              finding.severity
                            )}`}
                          >
                            {getFindingIcon(finding.code)}
                          </div>

                          <div className="finding-content">
                            <div className="finding-title-row">
                              <span className="finding-code">
                                {finding.code}
                              </span>
                              <span
                                className={`severity-badge ${getSeverityClass(
                                  finding.severity
                                )}`}
                              >
                                {finding.severity}
                              </span>
                            </div>
                            <div className="finding-resource">
                              {finding.resource}
                            </div>
                            <div className="finding-summary">
                              {finding.summary}
                            </div>
                          </div>

                          <span className="finding-chevron">›</span>
                        </button>
                      );
                    })
                  )}
                </div>

                <div className="findings-footer">
                  Showing {filteredFindings.length} of {findings.length} findings
                </div>
              </section>

              <section className="insight-panel" id="insights">
                <div className="insight-panel-heading">
                  <div className="insight-heading-icon">✦</div>
                  <div>
                    <h3>Diagnostic insight</h3>
                    <p>Evidence and recommended actions</p>
                  </div>
                  <span className="analysis-label">ANALYSIS</span>
                </div>

                {selectedFinding ? (
                  <FindingDetails finding={selectedFinding} />
                ) : (
                  <div className="insight-empty">
                    <div className="empty-state-icon">✧</div>
                    <strong>Select a finding</strong>
                    <span>
                      Choose an incident to view its root cause, evidence, and
                      recommended remediation.
                    </span>
                  </div>
                )}

                <div className="insight-footer">
                  <span className="insight-footer-icon">K</span>
                  <span>
                    Evidence source: {analysis?.source ?? "Not available"}
                  </span>
                  <span className="read-only-badge">READ-ONLY ANALYSIS</span>
                </div>
              </section>
            </div>
          </section>

          <footer className="page-footer">
            <div className="footer-brand">
              <span className="footer-logo">K</span>
              <span>KubeSage</span>
              <span className="footer-divider">·</span>
              <span>AI Kubernetes Troubleshooting Agent</span>
            </div>
            <span className="footer-version">LOCAL ENVIRONMENT</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

interface MetricCardProps {
  icon: string;
  label: string;
  value: number;
  description: string;
  footer: string;
  accent: string;
}

function MetricCard({
  icon,
  label,
  value,
  description,
  footer,
  accent,
}: MetricCardProps) {
  return (
    <article className={`metric-card ${accent}`}>
      <div className="metric-top">
        <div className={`metric-icon ${accent}`}>{icon}</div>
        <span className="metric-label">{label}</span>
        <span className="metric-menu">•••</span>
      </div>

      <div className="metric-value">{value}</div>
      <div className="metric-description">{description}</div>

      <div className="metric-bottom">
        <span>{footer}</span>
        <span className="metric-bottom-symbol">↗</span>
      </div>
    </article>
  );
}

function FindingDetails({ finding }: { finding: Finding }) {
  return (
    <div className="finding-details">
      <div className="detail-topline">
        <span className={`severity-badge ${getSeverityClass(finding.severity)}`}>
          {finding.severity}
        </span>
        <span className="detail-resource">{finding.resource}</span>
      </div>

      <div className="finding-meta">
        <span className={`priority-badge priority-${finding.priority ?? 3}`}>
          Priority {finding.priority ?? "—"}
        </span>
        <span className={`confidence-badge confidence-${finding.confidence ?? "low"}`}>
          Confidence: {finding.confidence ?? "Not provided"}
        </span>
      </div>

      <h2 className="detail-title">{finding.code}</h2>
      <p className="detail-summary">{finding.summary}</p>

      {finding.explanation && (
        <div className="detail-section">
          <div className="detail-section-heading">
            <span className="detail-section-icon">i</span>
            <h4>Explanation</h4>
          </div>
          <div className="root-cause-text">{finding.explanation}</div>
        </div>
      )}

      {finding.impact && (
        <div className="detail-section">
          <div className="detail-section-heading">
            <span className="detail-section-icon">!</span>
            <h4>Potential impact</h4>
          </div>
          <div className="root-cause-text">{finding.impact}</div>
        </div>
      )}

      <div className="detail-section">
        <div className="detail-section-heading">
          <span className="detail-section-icon">⌕</span>
          <h4>Root cause</h4>
        </div>
        <div className="root-cause-text">{finding.root_cause}</div>
      </div>

      <div className="detail-section">
        <div className="detail-section-heading">
          <span className="detail-section-icon">◧</span>
          <h4>Evidence</h4>
        </div>
        {finding.evidence.length > 0 ? (
          <ul className="evidence-list">
            {finding.evidence.map((item, index) => (
              <li key={`${item}-${index}`}>
                <span className="evidence-bullet" />
                {item}
              </li>
            ))}
          </ul>
        ) : (
          <div className="no-evidence">No evidence was supplied.</div>
        )}
      </div>

      <div className="detail-section remediation-section">
        <div className="detail-section-heading">
          <span className="detail-section-icon">↗</span>
          <h4>Recommended remediation</h4>
        </div>

        {finding.remediation.length > 0 ? (
          <ol className="remediation-list">
            {finding.remediation.map((item, index) => {
              const isCommand =
                item.trim().startsWith("kubectl") ||
                item.trim().startsWith("helm");

              return (
                <li key={`${item}-${index}`}>
                  <span className="remediation-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  {isCommand ? (
                    <code>{item}</code>
                  ) : (
                    <span className="remediation-text">{item}</span>
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <div className="no-evidence">No remediation was supplied.</div>
        )}
      </div>
    </div>
  );
}

export default App;