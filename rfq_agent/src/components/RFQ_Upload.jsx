import React, { useState, useRef } from 'react';
import './RFQUpload.css';

export default function RFQUpload() {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [success, setSuccess] = useState(false);
  const fileInputRef = useRef(null);
  const dropZoneRef = useRef(null);

  const handleDragOver = (e) => {
    e.preventDefault();
    dropZoneRef.current.style.borderColor = '#4299e1';
    dropZoneRef.current.style.background = '#ebf8ff';
  };

  const handleDragLeave = () => {
    dropZoneRef.current.style.borderColor = '#cbd5e0';
    dropZoneRef.current.style.background = '#f7fafc';
  };

  const handleDrop = (e) => {
    e.preventDefault();
    dropZoneRef.current.style.borderColor = '#cbd5e0';
    dropZoneRef.current.style.background = '#f7fafc';
    
    const files = Array.from(e.dataTransfer.files).filter(
      f => f.name.endsWith('.zip') || f.name.endsWith('.rar')
    );
    
    if (files.length === 0) {
      alert('Please drop ZIP or RAR files only');
      return;
    }
    
    setSelectedFiles(files);
  };

  const handleFileInput = (e) => {
    setSelectedFiles(Array.from(e.target.files));
  };

  const removeFile = (index) => {
    setSelectedFiles(selectedFiles.filter((_, i) => i !== index));
  };

  const clearFiles = () => {
    setSelectedFiles([]);
    fileInputRef.current.value = '';
  };

  const submitFiles = async () => {
    if (selectedFiles.length === 0) return;

    setUploading(true);
    setProgress(0);

    const formData = new FormData();
    selectedFiles.forEach((file) => {
      formData.append('files', file);
    });

    try {
      // Send to your backend
      const response = await fetch('/api/rfq/upload', {
        method: 'POST',
        body: formData,
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}` // If using auth
        }
      });

      if (!response.ok) {
        throw new Error('Upload failed');
      }

      const data = await response.json();
      setProgress(100);
      setSuccess(true);
      setSelectedFiles([]);
      
      // Redirect to review page
      setTimeout(() => {
        window.location.href = `/dashboard/review/${data.uploadId}`;
      }, 2000);

    } catch (error) {
      console.error('Upload error:', error);
      alert('Upload failed. Please try again.');
      setUploading(false);
      setProgress(0);
    }
  };

  return (
    <div className="rfq-upload-container">
      <div className="rfq-upload-wrapper">
        {/* Header */}
        <div className="rfq-upload-header">
          <h1>RFQ Agent</h1>
          <p>Upload your PO documents for intelligent processing</p>
        </div>

        {/* Main Card */}
        <div className="rfq-upload-card">
          {/* Upload Zone */}
          <div
            ref={dropZoneRef}
            className="rfq-drop-zone"
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current.click()}
          >
            <div className="rfq-drop-icon">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
            </div>

            <h2>Drag & drop your files here</h2>
            <p>or click to select ZIP files or folders</p>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".zip,.rar"
              onChange={handleFileInput}
              style={{ display: 'none' }}
            />

            <button className="rfq-browse-btn">Browse Files</button>
            <p className="rfq-file-hint">ZIP or RAR format • Max 500MB</p>
          </div>

          {/* Files List */}
          {selectedFiles.length > 0 && (
            <div className="rfq-files-list">
              <h3>Files to upload</h3>
              <div className="rfq-files-container">
                {selectedFiles.map((file, index) => (
                  <div key={index} className="rfq-file-item">
                    <div>
                      <p className="rfq-file-name">{file.name}</p>
                      <p className="rfq-file-size">
                        {(file.size / (1024 * 1024)).toFixed(2)} MB
                      </p>
                    </div>
                    <button
                      onClick={() => removeFile(index)}
                      className="rfq-remove-btn"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Progress */}
          {uploading && (
            <div className="rfq-progress-section">
              <h3>Upload progress</h3>
              <div className="rfq-progress-bar">
                <div
                  className="rfq-progress-fill"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
              <div className="rfq-progress-text">
                <span>{Math.round(progress)}% complete</span>
                <span>{selectedFiles.length} file(s)</span>
              </div>
            </div>
          )}

          {/* Success Message */}
          {success && (
            <div className="rfq-success-message">
              <strong>✓ Files processed successfully!</strong>
              <p>Your RFQ data is being analyzed. Redirecting to dashboard...</p>
            </div>
          )}

          {/* Action Buttons */}
          {selectedFiles.length > 0 && (
            <div className="rfq-action-buttons">
              <button
                onClick={clearFiles}
                className="rfq-clear-btn"
                disabled={uploading}
              >
                Clear
              </button>
              <button
                onClick={submitFiles}
                className="rfq-submit-btn"
                disabled={uploading}
              >
                Process Files
              </button>
            </div>
          )}
        </div>

        {/* Info Section */}
        <div className="rfq-info-section">
          <h3>How it works</h3>
          <div className="rfq-info-grid">
            <div className="rfq-info-item">
              <p className="rfq-info-step">1. Upload</p>
              <p>Drag your ZIP file containing PO documents</p>
            </div>
            <div className="rfq-info-item">
              <p className="rfq-info-step">2. Parse</p>
              <p>AI extracts material, vendor, and quantity data</p>
            </div>
            <div className="rfq-info-item">
              <p className="rfq-info-step">3. Review</p>
              <p>Validate and approve before creation</p>
            </div>
            <div className="rfq-info-item">
              <p className="rfq-info-step">4. Create</p>
              <p>Auto-approve or escalate based on rules</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}