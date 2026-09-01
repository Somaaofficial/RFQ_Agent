import React, { useState, useEffect } from 'react';
import './App.css';
import RFQUpload from './components/RFQUpload';
import ReviewPanel from './components/ReviewPanel';
import Dashboard from './components/Dashboard';

function App() {
  const [currentPage, setCurrentPage] = useState('upload');
  const [uploadId, setUploadId] = useState(null);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const token = localStorage.getItem('authToken');
        if (token) {
          const response = await fetch('/api/auth/me', {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          if (response.ok) {
            const data = await response.json();
            setUser(data.user);
          } else {
            localStorage.removeItem('authToken');
          }
        }
      } catch (error) {
        console.error('Auth check failed:', error);
      } finally {
        setLoading(false);
      }
    };

    checkAuth();
  }, []);

  const handleUploadSuccess = (newUploadId) => {
    setUploadId(newUploadId);
    setCurrentPage('review');
  };

  const handleBackToUpload = () => {
    setCurrentPage('upload');
    setUploadId(null);
  };

  const handleViewDashboard = () => {
    setCurrentPage('dashboard');
  };

  const handleLogout = () => {
    localStorage.removeItem('authToken');
    setUser(null);
    setCurrentPage('upload');
  };

  if (loading) {
    return (
      <div className="app-loading">
        <div className="spinner"></div>
        <p>Loading...</p>
      </div>
    );
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="app-header-content">
          <div className="app-logo">
            <h1>RFQ Agent</h1>
            <p>Intelligent Purchase Order Processing</p>
          </div>

          <nav className="app-nav">
            <button
              className={`nav-btn ${currentPage === 'upload' ? 'active' : ''}`}
              onClick={() => setCurrentPage('upload')}
            >
              📤 Upload
            </button>
            <button
              className={`nav-btn ${currentPage === 'review' ? 'active' : ''}`}
              onClick={handleViewDashboard}
            >
              📋 Dashboard
            </button>
            <button className="nav-btn help-btn" title="Help">
              ❓ Help
            </button>
          </nav>

          <div className="app-user-section">
            {user ? (
              <>
                <span className="user-name">{user.name || user.email}</span>
                <button className="logout-btn" onClick={handleLogout}>
                  Logout
                </button>
              </>
            ) : (
              <button className="login-btn" onClick={() => setCurrentPage('login')}>
                Login
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="app-main">
        {currentPage === 'upload' && (
          <div className="page-upload">
            <RFQUpload onUploadSuccess={handleUploadSuccess} />
          </div>
        )}

        {currentPage === 'review' && uploadId && (
          <div className="page-review">
            <ReviewPanel uploadId={uploadId} onBack={handleBackToUpload} />
          </div>
        )}

        {currentPage === 'dashboard' && (
          <div className="page-dashboard">
            <Dashboard />
          </div>
        )}
      </main>

      <footer className="app-footer">
        <div className="footer-content">
          <p>&copy; 2026 RFQ Agent. All rights reserved.</p>
          <div className="footer-links">
            <a href="#about">About</a>
            <a href="#privacy">Privacy</a>
            <a href="#terms">Terms</a>
            <a href="#contact">Contact</a>
          </div>
        </div>
      </footer>

      <ErrorBoundary />
    </div>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('Error caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <h2>Something went wrong</h2>
          <p>{this.state.error?.message}</p>
          <button onClick={() => window.location.reload()}>
            Reload Page
          </button>
        </div>
      );
    }

    return null;
  }
}

export default App;
