// routes/rfq.js
const express = require('express');
const multer = require('multer');
const path = require('path');
const router = express.Router();

const upload = multer({
  dest: 'uploads/',
  limits: { fileSize: 500 * 1024 * 1024 }, // 500MB
  fileFilter: (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase();
    if (['.zip', '.rar'].includes(ext)) {
      cb(null, true);
    } else {
      cb(new Error('Only ZIP and RAR files allowed'));
    }
  }
});

// Upload endpoint
router.post('/upload', upload.array('files'), async (req, res) => {
  try {
    if (!req.files || req.files.length === 0) {
      return res.status(400).json({ error: 'No files uploaded' });
    }

    const uploadId = `upload_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    // Store file metadata
    const fileMetadata = req.files.map(file => ({
      originalName: file.originalname,
      path: file.path,
      size: file.size
    }));

    // Trigger your RFQ agent to process files
    // Pass uploadId and fileMetadata to your agent
    await triggerRFQAgent(uploadId, fileMetadata);

    res.json({
      uploadId,
      message: 'Files uploaded successfully',
      files: fileMetadata.length
    });

  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get review data for uploaded files
router.get('/review/:uploadId', async (req, res) => {
  try {
    // Fetch processed data from your RFQ agent
    const reviewData = await getRFQReviewData(req.params.uploadId);
    res.json(reviewData);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;