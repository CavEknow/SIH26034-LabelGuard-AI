
from flask import Flask, render_template, request, jsonify, send_file
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
from pytesseract import Output
import re, os, uuid, json
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from werkzeug.utils import secure_filename

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
REPORT_DIR = os.path.join(BASE, "reports")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# Tesseract path. If Tesseract is already in PATH, this fallback is harmless.
TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT

ALLOWED = {"png", "jpg", "jpeg", "webp"}

def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED

def preprocess(img):
    # Keep color image for display; create an OCR-friendly grayscale image.
    img = img.convert("RGB")
    scale = 2 if max(img.size) < 2200 else 1
    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale))
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(1.7)
    gray = ImageEnhance.Sharpness(gray).enhance(1.5)
    gray = gray.filter(ImageFilter.SHARPEN)
    return img, gray

def ocr_image(path):
    original, prepared = preprocess(Image.open(path))
    text = pytesseract.image_to_string(prepared, config="--psm 6")
    data = pytesseract.image_to_data(prepared, config="--psm 6", output_type=Output.DICT)
    words = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if word:
            try:
                conf = float(data["conf"][i])
            except:
                conf = -1
            words.append({"text": word, "confidence": round(conf, 1)})
    return text, words

def normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()

def find_match(pattern, text, flags=re.I):
    return re.search(pattern, text, flags)

def extract_fields(text):
    t = normalize(text)
    fields = {}

    m = find_match(r"(?:mrp|m\.r\.p\.|rs\.?)\s*[:.\-]?\s*[@%₹rs\.\s]*([0-9]{1,7}(?:\.[0-9]{1,2})?)", t)
    fields["mrp"] = f"₹{m.group(1)}" if m else None

    m = find_match(r"(?:net\s*(?:wt|weight|quantity)|net\s*wt\.?)\s*[:.\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(kg|kgs|g|gm|grams?|ml|l|litre|liter|oz)\b", t)
    if not m:
        m = find_match(r"\b([0-9]+(?:\.[0-9]+)?)\s*(kg|kgs|g|gm|grams?|ml|l|litre|liter|oz)\b", t)
    fields["net_quantity"] = f"{m.group(1)} {m.group(2)}" if m else None

    m = find_match(r"(?:mfg|mfd|manufactur(?:ed|ing))\s*(?:on|date)?\s*[:.\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2})", t)
    fields["manufacturing_date"] = m.group(1) if m else None

    m = find_match(r"(?:best\s*before|use\s*by)\s*[:.\-]?\s*([a-z0-9 /-]{3,30})", t)
    fields["best_before"] = m.group(1).strip() if m else None

    m = find_match(r"(?:customer|consumer)\s*care\s*[:.\-]?\s*(.{0,80})", t)
    fields["consumer_care"] = m.group(1).strip(" .,-") if m else None

    m = find_match(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", t)
    fields["email"] = m.group(0) if m else None

    m = find_match(r"(?:manufactured|marketed|packed|imported)\s*(?:and\s*)?(?:marketed\s*)?(?:by|for)\s*[:.\-]?\s*(.{0,120})", t)
    fields["manufacturer"] = m.group(1).strip(" .,-") if m else None

    # Common/generic product name heuristics for demo; category-specific models can replace this later.
    generic = None
    for phrase in ["coffee powder", "instant coffee", "rice", "biscuits", "shampoo", "soap", "tea"]:
        if phrase in t:
            generic = phrase.title()
            break
    fields["generic_name"] = generic

    m = find_match(r"(?:unit\s*(?:sale|selling)\s*price|per\s*(?:kg|100g|100\s*g|litre|l|100ml))\s*[:.\-]?\s*([₹rs\.\s]*[0-9]+(?:\.[0-9]+)?)", t)
    fields["unit_sale_price"] = m.group(0).strip() if m else None

    fields["country_of_origin"] = bool(find_match(r"(?:country\s+of\s+origin|made\s+in|product\s+of)", t))
    fields["inclusive_taxes"] = bool(find_match(r"(?:inclusive\s+of\s+all\s+taxes|incl\.?\s*all\s+taxes)", t))
    return fields

def check_rules(text, fields, product_type="food", imported=False):
    t = normalize(text)
    results = []

    def add(key, label, status, reason, value=None, rule=""):
        results.append({"key": key, "label": label, "status": status, "reason": reason, "value": value, "rule": rule})

    add("manufacturer", "Name & address of manufacturer / packer / importer",
        "PASS" if fields["manufacturer"] else "FAIL",
        "Manufacturer/packer/importer information was detected." if fields["manufacturer"] else "No clear manufacturer/packer/importer declaration was detected.",
        fields["manufacturer"], "Mandatory declaration for pre-packaged retail commodities.")

    add("generic_name", "Common / generic name of commodity",
        "PASS" if fields["generic_name"] else "REVIEW",
        "A likely commodity name was detected." if fields["generic_name"] else "Commodity name could not be confidently identified from OCR; verify manually.",
        fields["generic_name"], "Mandatory declaration.")

    add("net_quantity", "Net quantity",
        "PASS" if fields["net_quantity"] else "FAIL",
        "Net quantity with a recognizable unit was detected." if fields["net_quantity"] else "No recognizable net quantity was detected.",
        fields["net_quantity"], "Mandatory declaration in standard units of weight/measure or number.")

    mrp_ok = bool(fields["mrp"])
    add("mrp", "MRP / retail sale price",
        "PASS" if mrp_ok else "FAIL",
        "MRP value was detected." if mrp_ok else "No recognizable MRP value was detected.",
        fields["mrp"], "Retail sale price is to be declared as MRP inclusive of all taxes.")

    add("taxes", "MRP inclusive of all taxes",
        "PASS" if fields["inclusive_taxes"] else ("REVIEW" if fields["mrp"] else "FAIL"),
        "The label contains an inclusive-of-all-taxes declaration." if fields["inclusive_taxes"] else "MRP was detected, but an explicit inclusive-of-all-taxes phrase was not confidently detected; verify the label.",
        None, "MRP declaration should be inclusive of all taxes.")

    add("unit_sale_price", "Unit sale price",
        "PASS" if fields["unit_sale_price"] else "REVIEW",
        "Unit sale price was detected." if fields["unit_sale_price"] else "No unit sale price was confidently detected; verify whether it is applicable and required for this package.",
        fields["unit_sale_price"], "Department FAQ states unit sale price is a required declaration w.e.f. 01.10.2022, subject to applicable provisions.")

    add("consumer_care", "Consumer care details",
        "PASS" if (fields["consumer_care"] or fields["email"]) else "FAIL",
        "Consumer-care/contact information was detected." if (fields["consumer_care"] or fields["email"]) else "No clear consumer-care/contact information was detected.",
        fields["consumer_care"] or fields["email"], "Consumer care details are required; official FAQ also states email address is mandatory.")

    if imported:
        add("origin", "Country of origin (imported product)",
            "PASS" if fields["country_of_origin"] else "FAIL",
            "Country-of-origin wording was detected." if fields["country_of_origin"] else "Imported product selected, but no country-of-origin declaration was detected.",
            None, "Country of origin is required for imported products.")
    else:
        add("origin", "Country of origin",
            "NOT_APPLICABLE",
            "Not checked because the user marked the product as not imported.",
            None, "Conditional: country of origin is required for imported products.")

    # Manufacturing date has an important food/cosmetics/seed exception in the Department FAQ.
    date_required = product_type not in {"food", "seeds", "cosmetics"}
    if date_required:
        add("manufacturing_date", "Month & year of manufacture",
            "PASS" if fields["manufacturing_date"] else "REVIEW",
            "Manufacturing date was detected." if fields["manufacturing_date"] else "No manufacturing date was detected; verify applicability and the package.",
            fields["manufacturing_date"], "Conditional according to the Department FAQ; food articles, seeds and cosmetics are listed as exceptions.")
    else:
        add("manufacturing_date", "Manufacturing date",
            "NOT_APPLICABLE",
            f"Not treated as a mandatory check for the selected category ({product_type}) in this prototype's current rule profile.",
            fields["manufacturing_date"], "Category-specific rule profile; verify the latest applicable notification.")

    # Best-before / use-by for commodities that can become unfit for human consumption.
    if product_type == "food":
        add("best_before", "Best before / use by",
            "PASS" if fields["best_before"] else "REVIEW",
            "A best-before/use-by declaration was detected." if fields["best_before"] else "No clear best-before/use-by declaration was detected; verify applicability.",
            fields["best_before"], "Required where the commodity may become unfit for human consumption with time.")
    else:
        add("best_before", "Best before / use by",
            "NOT_APPLICABLE",
            "Not automatically required by this basic profile; verify the product-specific provisions.",
            fields["best_before"], "Product-specific/conditional.")

    return results

def overall(results):
    fails = sum(r["status"] == "FAIL" for r in results)
    reviews = sum(r["status"] == "REVIEW" for r in results)
    passes = sum(r["status"] == "PASS" for r in results)
    applicable = sum(r["status"] != "NOT_APPLICABLE" for r in results)
    if fails:
        status = "NON-COMPLIANT / ATTENTION REQUIRED"
    elif reviews:
        status = "NEEDS REVIEW"
    else:
        status = "SCREENING PASS"
    return {"status": status, "passes": passes, "fails": fails, "reviews": reviews, "applicable": applicable}

def make_report(data, report_path):
    doc = SimpleDocTemplate(report_path, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("LabelGuard AI — Compliance Screening Report", styles["Title"]),
        Paragraph(f"Generated: {datetime.now().strftime('%d %b %Y, %H:%M')}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph(f"<b>Overall status:</b> {data['summary']['status']}", styles["Heading2"]),
        Paragraph(f"Pass: {data['summary']['passes']} | Fail: {data['summary']['fails']} | Review: {data['summary']['reviews']}", styles["Normal"]),
        Spacer(1, 12),
    ]
    rows = [["Check", "Status", "Detected value", "Reason"]]
    for r in data["results"]:
        rows.append([r["label"], r["status"], str(r["value"] or "—"), r["reason"]])
    table = Table(rows, colWidths=[125, 65, 95, 245])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f3b57")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#f5f7f8")]),
        ("LEFTPADDING",(0,0),(-1,-1),5),
        ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    story.append(table)
    story += [Spacer(1,12),
              Paragraph("<b>Important:</b> This is an AI-assisted screening prototype. It does not replace an authorized officer's legal determination. Applicable rules, exemptions, amendments, product category and package-specific requirements must be verified before enforcement action.", styles["Normal"])]
    doc.build(story)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/check", methods=["POST"])
def check():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded."}), 400
    f = request.files["image"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"error": "Please upload PNG, JPG, JPEG or WEBP."}), 400

    product_type = request.form.get("product_type", "food").lower()
    imported = request.form.get("imported", "false").lower() == "true"
    ext = f.filename.rsplit(".",1)[1].lower()
    job_id = uuid.uuid4().hex[:12]
    filename = secure_filename(f"product_{job_id}.{ext}")
    path = os.path.join(UPLOAD_DIR, filename)
    f.save(path)

    try:
        text, words = ocr_image(path)
        fields = extract_fields(text)
        results = check_rules(text, fields, product_type, imported)
        summary = overall(results)
        data = {
            "job_id": job_id,
            "image_url": f"/uploads/{filename}",
            "extracted_text": text,
            "ocr_words": words,
            "fields": fields,
            "results": results,
            "summary": summary,
            "product_type": product_type,
            "imported": imported
        }
        with open(os.path.join(REPORT_DIR, f"{job_id}.json"), "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
        pdf = os.path.join(REPORT_DIR, f"{job_id}.pdf")
        make_report(data, pdf)
        data["report_url"] = f"/report/{job_id}.pdf"
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/uploads/<name>")
def uploaded(name):
    return send_file(os.path.join(UPLOAD_DIR, name))

@app.route("/report/<name>")
def report(name):
    return send_file(os.path.join(REPORT_DIR, name), as_attachment=True)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
