# SIH26034 — LabelGuard AI

A local working web prototype for the Smart India Hackathon 2026 packaged-commodity compliance problem.

## Features
- Good-looking responsive web UI
- Upload a package image
- Live camera capture from laptop/mobile browser
- Image preprocessing before OCR
- Tesseract OCR
- Structured field extraction
- Rule-engine screening for key packaged-commodity declarations
- PASS / FAIL / REVIEW / NOT APPLICABLE
- Detected values + reasons
- PDF inspection report
- Product category and imported-product options

## 1. Open the project
Extract this folder somewhere, then open it in VS Code.

## 2. Create/activate venv
Windows PowerShell:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

## 3. Install Python packages
```powershell
pip install -r requirements.txt
```

Tesseract OCR must also be installed. The app expects the common Windows path:
`C:\Program Files\Tesseract-OCR\tesseract.exe`
If yours is elsewhere, edit `app.py`.

## 4. Start the website
```powershell
python app.py
```

Open:
`http://127.0.0.1:5000`

## 5. Camera
Click **Open Camera** and allow camera permission. On a phone, the same web app can use the rear camera when served from a secure/appropriate context. For the laptop demo, localhost camera access is supported by modern browsers.

## Rule-engine note
This is a screening prototype, not a final legal decision system. The Department of Consumer Affairs' official material identifies mandatory declarations including manufacturer/packer/importer information, country of origin for imports, common/generic name, net quantity, MRP inclusive of taxes, unit sale price, applicable date declarations and consumer-care details. The exact requirement can depend on product category, exemptions and amendments.

Before an SIH demonstration, validate the rule library against the latest official notifications and the exact product category.
