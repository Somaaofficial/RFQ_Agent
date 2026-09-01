import React, { useState, useEffect } from 'react';
import './Dashboard.css';

export default function Dashboard() {
  const [stats, setStats] = useState({
    total_pos: 1000,
    auto_approved: 600,
    manual_reviewed: 300,
    rejected: 50,
    pending: 50,
    avg_processing_time: '15 min',
    total_value: 50000000
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(false);
  }, []);

  const data = stats;
  const approvalRate = data.total_pos > 0
    ? Math.round(((data.auto_approved + data.manual_reviewed) / data.total_pos) * 100)
    : 0;

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1>RFQ Dashboard</h1>
        <p>Monitor your PO processing pipeline</p>
      </div>

      <div className="dashboard-kpi">
        <div className="kpi-card">
          <div className="kpi-icon">📊</div>
          <div className="kpi-content">
            <div className="kpi-value">{data.total_pos}</div>
            <div className="kpi-label">Total POs</div>
          </div>
        </div>

        <div className="kpi-card success">
          <div className="kpi-icon">✓</div>
          <div className="kpi-content">
            <div className="kpi-value">{data.auto_approved}</div>
            <div className="kpi-label">Auto-Approved</div>
          </div>
        </div>

        <div className="kpi-card warning">
          <div className="kpi-icon">👤</div>
          <div className="kpi-content">
            <div className="kpi-value">{data.manual_reviewed}</div>
            <div className="kpi-label">Reviewed</div>
          </div>
        </div>

        <div className="kpi-card danger">
          <div className="kpi-icon">✕</div>
          <div className="kpi-content">
            <div className="kpi-value">{data.rejected}</div>
            <div className="kpi-label">Rejected</div>
          </div>
        </div>

        <div className="kpi-card value">
          <div className="kpi-icon">₹</div>
          <div className="kpi-content">
            <div className="kpi-value">{(data.total_value / 100000).toFixed(1)}L</div>
            <div className="kpi-label">Total Value</div>
          </div>
        </div>
      </div>

      <div className="dashboard-metrics">
        <div className="metric-card">
          <h3>Approval Rate</h3>
          <div className="metric-value-large">
            {approvalRate}%
            <span className="metric-unit">approved</span>
          </div>
        </div>

        <div className="metric-card">
          <h3>Processing Time</h3>
          <div className="metric-value-large">
            {data.avg_processing_time}
            <span className="metric-unit">avg</span>
          </div>
        </div>

        <div className="metric-card">
          <h3>Automation Savings</h3>
          <div className="metric-value-large">
            {Math.round((data.auto_approved / data.total_pos) * 100)}%
            <span className="metric-unit">auto</span>
          </div>
        </div>
      </div>

      <div className="dashboard-risk">
        <h2>Risk Distribution</h2>
        <div className="risk-bars">
          <div className="risk-bar-item">
            <label>Low Risk</label>
            <div className="risk-bar">
              <div className="risk-fill low" style={{ width: '45%' }}></div>
            </div>
            <span className="risk-count">450 POs</span>
          </div>
          <div className="risk-bar-item">
            <label>Medium Risk</label>
            <div className="risk-bar">
              <div className="risk-fill medium" style={{ width: '30%' }}></div>
            </div>
            <span className="risk-count">300 POs</span>
          </div>
          <div className="risk-bar-item">
            <label>High Risk</label>
            <div className="risk-bar">
              <div className="risk-fill high" style={{ width: '20%' }}></div>
            </div>
            <span className="risk-count">200 POs</span>
          </div>
          <div className="risk-bar-item">
            <label>Critical Risk</label>
            <div className="risk-bar">
              <div className="risk-fill critical" style={{ width: '5%' }}></div>
            </div>
            <span className="risk-count">50 POs</span>
          </div>
        </div>
      </div>
    </div>
  );
}
