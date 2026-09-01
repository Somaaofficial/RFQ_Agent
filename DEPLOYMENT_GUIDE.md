# RFQ Agent - Deployment Guide (Vercel + Render)

## 📋 Overview

Deploy your RFQ Agent to production:
- **Frontend:** Vercel (React)
- **Backend:** Render (Python Flask)
- **Result:** Live URL like `https://rfq-agent.vercel.app`

**Time needed:** 45 minutes  
**Cost:** Free (both platforms have free tier)

---

## 🚀 PHASE 1: PREPARE BACKEND (Render)

### Step 1: Push code to GitHub

**1.1** Create GitHub account (if you don't have one)
```
Go to: https://github.com/signup
Sign up and verify email
```

**1.2** Create new repository
```
Click: + icon (top right)
Select: New repository
Name: rfq-agent
Description: RFQ Intelligence Agent
Visibility: Public
Click: Create repository
```

**1.3** Push your code to GitHub

In PowerShell (in your RFQ_Agent folder):

```powershell
# Initialize git
git init

# Add files
git add .

# Commit
git commit -m "Initial RFQ Agent commit"

# Add remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/rfq-agent.git

# Push to GitHub
git branch -M main
git push -u origin main
```

### Step 2: Create Render account

**2.1** Go to Render
```
https://render.com
```

**2.2** Sign up
```
Click: Sign up
Select: GitHub
Authorize Render
```

**2.3** Create new Web Service
```
Click: New +
Select: Web Service
Connect GitHub repository
Select: rfq-agent
Click: Deploy
```

### Step 3: Configure Render service

**3.1** Set environment variables
```
In Render dashboard → rfq-agent-api:

Environment:
MISTRAL_API_KEY: [Your Mistral API Key]

Build Command:
pip install -r requirements.txt

Start Command:
gunicorn -w 1 -b 0.0.0.0:10000 rfq_agent.api:app
```

**3.2** Wait for deployment
```
Render deploys automatically
Monitor: Logs tab
Wait for: "Server is running"
```

**3.3** Get your backend URL
```
Example: https://rfq-agent-api.onrender.com
Copy this URL for Step 5
```

---

## 🎨 PHASE 2: PREPARE FRONTEND (Vercel)

### Step 4: Create React app

**4.1** In a new folder, create React app
```powershell
# Create new folder
mkdir rfq-agent-frontend
cd rfq-agent-frontend

# Create React app
npx create-react-app .
```

**4.2** Install dependencies
```powershell
npm install axios
```

**4.3** Create .env.local file
```powershell
# In rfq-agent-frontend folder, create: .env.local

REACT_APP_API_URL=https://rfq-agent-api.onrender.com
```

**4.4** Create RFQ components

Create file: `src/components/RFQForm.jsx`

```jsx
import React, { useState } from 'react';
import axios from 'axios';
import './RFQForm.css';

export default function RFQForm() {
  const [formData, setFormData] = useState({
    rfq_item: '',
    rfq_quantity: '',
    rfq_unit: 'kg',
    delivery_location: ''
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await axios.post(
        `${process.env.REACT_APP_API_URL}/api/rfq/process`,
        {
          rfq_item: formData.rfq_item,
          rfq_quantity: parseFloat(formData.rfq_quantity),
          rfq_unit: formData.rfq_unit,
          delivery_location: formData.delivery_location
        }
      );

      setResult(response.data);
    } catch (err) {
      setError(err.response?.data?.error || 'Error processing RFQ');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <div className="header">
        <h1>RFQ Intelligence Agent</h1>
        <p>Intelligent vendor comparison & selection</p>
      </div>

      <div className="card">
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Item Description *</label>
            <input
              type="text"
              name="rfq_item"
              value={formData.rfq_item}
              onChange={handleChange}
              placeholder="e.g., Steel Sheets 3mm"
              required
            />
          </div>

          <div className="form-group">
            <label>Quantity *</label>
            <input
              type="number"
              name="rfq_quantity"
              value={formData.rfq_quantity}
              onChange={handleChange}
              placeholder="e.g., 1000"
              required
            />
          </div>

          <div className="form-group">
            <label>Unit *</label>
            <select
              name="rfq_unit"
              value={formData.rfq_unit}
              onChange={handleChange}
            >
              <option value="kg">Kg</option>
              <option value="tons">Tons</option>
              <option value="pieces">Pieces</option>
              <option value="meters">Meters</option>
            </select>
          </div>

          <div className="form-group">
            <label>Delivery Location *</label>
            <input
              type="text"
              name="delivery_location"
              value={formData.delivery_location}
              onChange={handleChange}
              placeholder="e.g., Mumbai Warehouse"
              required
            />
          </div>

          <button type="submit" disabled={loading}>
            {loading ? 'Processing...' : 'Process RFQ'}
          </button>
        </form>

        {error && (
          <div className="error-message">
            <strong>Error:</strong> {error}
          </div>
        )}

        {result && (
          <div className="result-section">
            <h2>✅ Processing Complete</h2>
            <div className="result-box">
              <p><strong>Recommended Vendor:</strong> {result.result?.top_recommendation || 'N/A'}</p>
              <p><strong>Thread ID:</strong> {result.thread_id}</p>
              <p><strong>Status:</strong> {result.message}</p>
            </div>
            <p className="info-text">
              ✓ Check your Outlook Drafts for the recommendation email<br/>
              ✓ Excel report has been generated<br/>
              ✓ Risk assessment complete
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
```

Create file: `src/components/RFQForm.css`

```css
.container {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.header {
  color: white;
  text-align: center;
  margin-bottom: 2rem;
}

.header h1 {
  font-size: 32px;
  margin: 0;
}

.header p {
  margin: 0.5rem 0 0;
  opacity: 0.9;
}

.card {
  background: white;
  border-radius: 16px;
  padding: 2rem;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.1);
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 600;
  color: #2d3748;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #cbd5e0;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

button {
  width: 100%;
  padding: 0.75rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.3s;
}

button:hover:not(:disabled) {
  transform: translateY(-2px);
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-message {
  margin-top: 1.5rem;
  padding: 1rem;
  background: #fed7d7;
  border: 1px solid #fc8181;
  border-radius: 8px;
  color: #c53030;
}

.result-section {
  margin-top: 2rem;
  padding: 1.5rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
}

.result-section h2 {
  margin: 0 0 1rem;
  color: #166534;
}

.result-box {
  background: white;
  padding: 1rem;
  border-radius: 6px;
  margin-bottom: 1rem;
}

.result-box p {
  margin: 0.5rem 0;
  color: #2d3748;
}

.info-text {
  font-size: 12px;
  color: #22543d;
  margin: 1rem 0 0;
  line-height: 1.6;
}
```

Update file: `src/App.js`

```jsx
import React from 'react';
import RFQForm from './components/RFQForm';
import './App.css';

function App() {
  return <RFQForm />;
}

export default App;
```

### Step 5: Push frontend to GitHub

```powershell
cd rfq-agent-frontend

git init
git add .
git commit -m "Add RFQ frontend"
git remote add origin https://github.com/YOUR_USERNAME/rfq-agent-frontend.git
git branch -M main
git push -u origin main
```

---

## 🌐 PHASE 3: DEPLOY TO VERCEL

### Step 6: Create Vercel account

**6.1** Go to Vercel
```
https://vercel.com
```

**6.2** Sign up with GitHub

**6.3** Import project
```
Click: Import Project
Select: rfq-agent-frontend repository
Click: Import
```

**6.4** Set environment variables

```
In Vercel dashboard → Settings → Environment Variables:

Name: REACT_APP_API_URL
Value: https://rfq-agent-api.onrender.com
```

**6.5** Deploy

```
Click: Deploy
Wait for completion
Get your live URL: https://rfq-agent.vercel.app
```

---

## ✅ FINAL CHECKLIST

- [ ] GitHub account created
- [ ] Backend pushed to GitHub
- [ ] Render service deployed
- [ ] Backend URL obtained
- [ ] React frontend created
- [ ] .env.local configured
- [ ] Frontend pushed to GitHub
- [ ] Vercel account created
- [ ] Frontend deployed
- [ ] Live URL working

---

## 🎯 LIVE URLS

After deployment, you'll have:

```
Frontend: https://rfq-agent.vercel.app
Backend:  https://rfq-agent-api.onrender.com
API:      https://rfq-agent-api.onrender.com/api/rfq/process
```

---

## 📞 Troubleshooting

| Issue | Solution |
|-------|----------|
| Backend won't deploy | Check render.yaml exists in root |
| CORS error | Backend CORS is enabled |
| 502 Bad Gateway | Wait 5 mins for Render cold start |
| API not responding | Check MISTRAL_API_KEY in Render |

---

**You're live!** 🚀
