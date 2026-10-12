"""Renders the printable health card (CR-80 ratio) with the QR code."""
from __future__ import annotations

import io

import qrcode
from PIL import Image, ImageDraw, ImageFont


def _font(size, bold=False):
    for name in (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_card(name: str, patient_id: str, blood_group: str, dob: str, qr_url: str) -> bytes:
    W, H = 1012, 638
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 110], fill=(14, 116, 144))
    d.text((40, 30), "Doctor Sahyog", font=_font(44, True), fill="white")
    d.text((W - 300, 45), "Digital Health Card", font=_font(26), fill="white")
    y = 160
    for label, val in [("Name", name), ("Patient ID", patient_id), ("Blood group", blood_group or "-"),
                       ("Date of birth", dob or "-")]:
        d.text((40, y), label.upper(), font=_font(20), fill=(100, 116, 139))
        d.text((40, y + 26), val, font=_font(34, True), fill=(15, 23, 42))
        y += 100
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(qr_url)
    qr.make(fit=True)
    q = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((360, 360))
    img.paste(q, (W - 400, 170))
    d.text((W - 400, 540), "Scan for emergency info", font=_font(20), fill=(100, 116, 139))
    d.rectangle([0, H - 20, W, H], fill=(14, 116, 144))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
