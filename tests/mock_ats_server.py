"""Lightweight Mock ATS Server for Local Testing.

Serves realistic Greenhouse / Lever / Ashby style application pages
allowing end-to-end testing of ApplyFlow locally.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from typing import Optional


HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Senior Distributed Systems Engineer - CloudScale AI | Careers</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 40px; }
    .container { max-width: 760px; margin: 0 auto; background: #ffffff; padding: 36px; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
    h1 { font-size: 26px; color: #0f172a; margin-bottom: 6px; }
    .org { font-size: 16px; color: #64748b; font-weight: 600; margin-bottom: 24px; }
    .job-description { line-height: 1.6; border-bottom: 2px solid #e2e8f0; padding-bottom: 24px; margin-bottom: 28px; }
    .field { margin-bottom: 20px; }
    label { display: block; font-weight: 600; margin-bottom: 6px; font-size: 14px; }
    .req { color: #ef4444; }
    input[type="text"], input[type="email"], input[type="tel"], select, textarea {
      width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; box-sizing: border-box;
    }
    textarea { height: 110px; resize: vertical; }
    .radio-group { display: flex; gap: 20px; margin-top: 6px; }
    .radio-group label { font-weight: normal; cursor: pointer; }
    .submit-btn {
      background: #2563eb; color: #ffffff; border: none; padding: 12px 24px; font-size: 16px; font-weight: 600;
      border-radius: 6px; cursor: pointer; width: 100%; margin-top: 16px;
    }
    .submit-btn:hover { background: #1d4ed8; }
    .success-message { display: none; padding: 20px; background: #dcfce7; color: #15803d; border-radius: 6px; font-weight: 600; }
  </style>
</head>
<body>
  <div class="container">
    <h1 data-qa="job-title">Senior Distributed Systems Engineer</h1>
    <div class="org" data-qa="company-name">CloudScale AI</div>

    <div class="job-description" data-qa="job-description">
      <h3>About the Role</h3>
      <p>CloudScale AI is searching for a Senior Distributed Systems Engineer to scale our real-time LLM inference pipelines. You will lead the architecture of high-throughput backend services handling millions of concurrent requests.</p>
      <h3>Strict Requirements</h3>
      <ul>
        <li>5+ years of production experience in Python, FastAPI, or Go.</li>
        <li>Deep hands-on expertise with Docker, Kubernetes, and distributed caching (Redis).</li>
        <li>Demonstrated experience designing high-availability REST and gRPC microservices.</li>
        <li>Must be legally authorized to work in the United States without current or future sponsorship.</li>
        <li>Bachelor's degree in Computer Science or equivalent practical experience.</li>
      </ul>
    </div>

    <h2>Apply for this Job</h2>
    <form id="application_form" method="POST" action="/submit" enctype="multipart/form-data">
      <div class="field">
        <label for="first_name">First Name <span class="req">*</span></label>
        <input type="text" id="first_name" name="first_name" required>
      </div>

      <div class="field">
        <label for="last_name">Last Name <span class="req">*</span></label>
        <input type="text" id="last_name" name="last_name" required>
      </div>

      <div class="field">
        <label for="email">Email <span class="req">*</span></label>
        <input type="email" id="email" name="email" required>
      </div>

      <div class="field">
        <label for="phone">Phone <span class="req">*</span></label>
        <input type="tel" id="phone" name="phone" required>
      </div>

      <div class="field">
        <label for="resume">Resume / CV (PDF) <span class="req">*</span></label>
        <input type="file" id="resume" name="resume" accept=".pdf,.doc,.docx" required>
      </div>

      <div class="field">
        <label for="linkedin">LinkedIn Profile URL</label>
        <input type="text" id="linkedin" name="urls[LinkedIn]" placeholder="https://linkedin.com/in/...">
      </div>

      <div class="field">
        <label>Are you legally authorized to work in the United States? <span class="req">*</span></label>
        <div class="radio-group">
          <label><input type="radio" name="work_auth" value="Yes" required> Yes</label>
          <label><input type="radio" name="work_auth" value="No"> No</label>
        </div>
      </div>

      <div class="field">
        <label>Will you now or in the future require visa sponsorship? <span class="req">*</span></label>
        <div class="radio-group">
          <label><input type="radio" name="sponsorship" value="Yes" required> Yes</label>
          <label><input type="radio" name="sponsorship" value="No"> No</label>
        </div>
      </div>

      <div class="field">
        <label for="clearance_status">Do you hold an active US security clearance?</label>
        <select id="clearance_status" name="clearance">
          <option value="">-- Select --</option>
          <option value="None">None</option>
          <option value="Confidential">Confidential</option>
          <option value="Secret">Secret</option>
          <option value="Top Secret">Top Secret</option>
        </select>
      </div>

      <div class="field">
        <label for="notice_period">What is your notice period?</label>
        <input type="text" id="notice_period" name="notice_period" placeholder="e.g. 2 weeks">
      </div>

      <div class="field">
        <label for="essay_why">Why do you want to join our engineering team at CloudScale AI?</label>
        <textarea id="essay_why" name="why_company" placeholder="Tell us why you are excited about this role..."></textarea>
      </div>

      <button type="submit" class="submit-btn" id="submit_app_btn">Submit Application</button>
    </form>

    <div id="success_box" class="success-message">
      Application submitted successfully! Our talent team will review your qualifications.
    </div>
  </div>

  <script>
    document.getElementById('application_form').addEventListener('submit', function(e) {
      e.preventDefault();
      document.getElementById('application_form').style.display = 'none';
      document.getElementById('success_box').style.display = 'block';
    });
  </script>
</body>
</html>
"""


class MockATSHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_CONTENT.encode("utf-8"))

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "received"}).encode("utf-8"))

    def log_message(self, format, *args):
        # Silence standard HTTP access logging to keep terminal clean
        return


def run_mock_server(port: int = 8088):
    server = HTTPServer(("127.0.0.1", port), MockATSHandler)
    print(f"Mock ATS Server running at http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    run_mock_server()
