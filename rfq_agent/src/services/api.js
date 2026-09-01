const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:5000';

export const uploadRFQFiles = async (files) => {
  const formData = new FormData();
  files.forEach(file => {
    formData.append('files', file);
  });

  const token = localStorage.getItem('authToken');
  const headers = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/api/rfq/upload`, {
    method: 'POST',
    body: formData,
    headers,
  });

  if (!response.ok) {
    throw new Error('Upload failed');
  }

  return response.json();
};

export const getReviewData = async (uploadId) => {
  const token = localStorage.getItem('authToken');
  const headers = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/api/rfq/review/${uploadId}`, {
    headers,
  });

  if (!response.ok) {
    throw new Error('Failed to load review data');
  }

  return response.json();
};

export const approvePOs = async (uploadId, poIds) => {
  const token = localStorage.getItem('authToken');
  const headers = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/api/rfq/approve`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      uploadId,
      poIds,
      action: 'approve',
    }),
  });

  if (!response.ok) throw new Error('Approval failed');
  return response.json();
};

export const getDashboardStats = async (timeRange = '30d') => {
  const token = localStorage.getItem('authToken');
  const headers = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/api/rfq/stats?range=${timeRange}`, {
    headers,
  });

  if (!response.ok) throw new Error('Failed to load stats');
  return response.json();
};

export const isAuthenticated = () => {
  return !!localStorage.getItem('authToken');
};

export const getAuthToken = () => {
  return localStorage.getItem('authToken');
};

export const setAuthToken = (token) => {
  localStorage.setItem('authToken', token);
};

export default {
  uploadRFQFiles,
  getReviewData,
  approvePOs,
  getDashboardStats,
  isAuthenticated,
  getAuthToken,
  setAuthToken,
};
