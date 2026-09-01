import React, { useState, useEffect } from 'react';
import { getReviewData } from '../services/api';
import './ReviewPanel.css';

export default function ReviewPanel({ uploadId, onBack }) {
  const [reviewData, setReviewData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedPOs, setSelectedPOs] = useState([]);
  const [filterRisk, setFilterRisk] = useState('all');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await getReviewData(uploadId);
        setReviewData(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [uploadId]);

  const handleSelectPO = (poId) => {
    setSelectedPOs(prev =>
      prev.includes(poId)
        ? prev.filter(id => id !== poId)
        : [...prev, poId]
    );
  };

  const filteredPOs = () => {
    if (!reviewData?.needs_review) return [];
    if (filterRisk === 'all') return reviewData.needs_review;
    return reviewData.needs_review.filter(po => po.risk_level === filterRisk);
  };

  const handleApprove = async () => {
    if (selectedPOs.length === 0) {
      alert('Please select POs to approve');
      return;
    }

    try {
      const response = await fetch(`/api/rfq/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`
        },
        body: JSON.stringify({
          uploadId,
          poIds: selectedPOs,
          action: 'approve'
        })
      });

      if (!response.ok) throw new Error('Approval failed');

      alert(`${selectedPOs.length} PO(s) approved successfully!`);
      setSelectedPOs([]);
      const data = await getReviewData(uploadId);
      setReviewData(data);
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  };

  if (loading) {
    return (
      <div className="review-loading">
        <div className="spinner"></div>
        <p>Loading review data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="review-error">
        <h2>Error Loading Data</h2>
        <p>{error}</p>
        <button onClick={onBack}>Go Back</button>
      </div>
    );
  }

  const filteredList = filteredPOs();
  const autoCount = reviewData?.auto_approved?.length || 0;

  return (
    <div className="review-container">
      <div className="review-header">
        <button className="back-btn" onClick={onBack}>← Back</button>
        <h1>Review & Approve Purchase Orders</h1>
        <p>Upload ID: {uploadId}</p>
      </div>

      <div className="review-summary">
        <div className="summary-card total">
          <div className="summary-number">{reviewData.total || 0}</div>
          <div className="summary-label">Total POs</div>
        </div>
        <div className="summary-card auto">
          <div className="summary-number">{autoCount}</div>
          <div className="summary-label">Auto-Approved</div>
        </div>
        <div className="summary-card review">
          <div className="summary-number">{filteredList.length}</div>
          <div className="summary-label">Need Review</div>
        </div>
        <div className="summary-card selected">
          <div className="summary-number">{selectedPOs.length}</div>
          <div className="summary-label">Selected</div>
        </div>
      </div>

      <div className="review-controls">
        <select value={filterRisk} onChange={(e) => setFilterRisk(e.target.value)}>
          <option value="all">All Risks</option>
          <option value="low">Low Risk</option>
          <option value="medium">Medium Risk</option>
          <option value="high">High Risk</option>
          <option value="critical">Critical Risk</option>
        </select>

        <div className="action-buttons">
          <button className="action-btn approve" onClick={handleApprove} disabled={selectedPOs.length === 0}>
            ✓ Approve ({selectedPOs.length})
          </button>
        </div>
      </div>

      <div className="review-table-container">
        <table className="review-table">
          <thead>
            <tr>
              <th><input type="checkbox" /></th>
              <th>PO #</th>
              <th>Vendor</th>
              <th>Material</th>
              <th>Qty</th>
              <th>Amount</th>
              <th>Risk Level</th>
            </tr>
          </thead>
          <tbody>
            {filteredList.length === 0 ? (
              <tr>
                <td colSpan="7" className="empty-state">No POs to review</td>
              </tr>
            ) : (
              filteredList.map((po, idx) => (
                <tr key={idx} className={`risk-${po.risk_level}`}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedPOs.includes(po.id)}
                      onChange={() => handleSelectPO(po.id)}
                    />
                  </td>
                  <td className="po-number">{po.po_number || `PO-${idx + 1}`}</td>
                  <td>{po.vendor}</td>
                  <td>{po.material}</td>
                  <td>{po.quantity}</td>
                  <td className="amount">₹{po.amount?.toLocaleString()}</td>
                  <td>
                    <span className={`risk-badge ${po.risk_level}`}>
                      {po.risk_level?.toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
