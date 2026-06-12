import os
import random
import string
import base64
from io import BytesIO
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

class SquareReceiptPrinter:
    def __init__(self, **kwargs):
        pass

    def _generate_simple_logo(self, store_name):
        W, H = 150, 150
        img = Image.new('RGB', (W, H), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([10, 10, W-10, H-10], outline=(0,0,0), width=4)

        words = store_name.split()
        acr = ''.join([w[0].upper() for w in words if w.isalpha()][:3])
        if not acr: acr = "S"

        # Load a default font for fallback logo since we deleted the SQMarket fonts
        try:
            font = ImageFont.truetype("arial.ttf", 60)
        except:
            font = ImageFont.load_default(size=60) if hasattr(ImageFont, 'load_default') else ImageFont.load_default()

        bbox = d.textbbox((0, 0), acr, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((W - tw) // 2, (H - th) // 2 - 10), acr, fill=(0,0,0), font=font)
        return img

    def _img_to_b64(self, img):
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _generate_html(self, data):
        template_path = os.path.join(os.path.dirname(__file__), 'template.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()

        store_name = data.get('store_name', '')

        address_lines = data.get('address', '').split('\n')
        address_html = ""
        for line in address_lines:
            if line.strip():
                address_html += f'<div class="p receipt-address" x-apple-data-detectors="false">{line.strip()}</div>\n'

        phone = data.get('phone', '')

        txn_time = data.get('transaction_time', datetime.now())
        if isinstance(txn_time, str):
            try:
                txn_time = datetime.strptime(txn_time, "%m/%d/%Y %I:%M %p")
            except ValueError:
                try:
                    txn_time = datetime.strptime(txn_time, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    txn_time = datetime.now()

        date_str = f"{txn_time.month}/{txn_time.day}/{txn_time.year}"
        time_str = f"{txn_time.strftime('%I:%M %p').lstrip('0')}"

        # Logo Section
        logo_section = ""
        logo_path = data.get('logo_path')
        logo_img = None

        if logo_path and os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path).convert('RGB')
            except Exception:
                pass

        if not logo_img and data.get('auto_generate_logo', True):
            logo_img = self._generate_simple_logo(store_name)

        if logo_img:
            # 75x75 in CSS mapped to our width
            logo_img = logo_img.resize((150, 150), Image.Resampling.LANCZOS)
            b64 = self._img_to_b64(logo_img)
            logo_section = f'<div><img height="75" width="75" class="printable-image" alt="Merchant logo" src="data:image/png;base64,{b64}"></div>'

        # Items
        items_html = ""
        subtotal = 0.0
        for item in data.get('items', []):
            name = item.get('name', '')
            price = item.get('price', 0.0)
            subtotal += price
            qty_str = item.get('qty_str')

            items_html += f'<tr class="item-row"><td align="left" class="half-col-left payment-info-item" valign="top"><h2 class="p item-name">{name}</h2></td><td align="right" class="half-col-right" valign="top"><div class="p currency">${price:.2f}</div></td></tr>\n'
            if qty_str:
                items_html += f'<tr><td align="left" class="half-col-left payment-info-item"><div align="left" class="item-modifier-name"><div class="p item-description item-quantity">{qty_str}</div></div></td></tr>\n'

        # Taxes & Totals
        tax_rate = data.get('tax_rate', '0%')
        tax_amount = data.get('tax_amount', 0.0)
        total = subtotal + tax_amount

        receipt_id = ''.join(random.choices(string.ascii_letters, k=4))
        payment_method = random.choice(["Cash", "Credit Card"])
        footer_text = data.get("footer_text", "Return Policy: No cash refunds. Store credit only.")

        html = html.replace('{store_name}', store_name)
        html = html.replace('{address_html}', address_html)
        html = html.replace('{phone}', phone)
        html = html.replace('{date_str}', date_str)
        html = html.replace('{time_str}', time_str)
        html = html.replace('{items_html}', items_html)
        html = html.replace('{subtotal}', f"{subtotal:.2f}")
        html = html.replace('{tax_rate}', tax_rate)
        html = html.replace('{tax_amount}', f"{tax_amount:.2f}")
        html = html.replace('{total}', f"{total:.2f}")
        html = html.replace('{receipt_id}', receipt_id)
        html = html.replace('{payment_method}', payment_method)
        html = html.replace('{footer_text}', footer_text)
        html = html.replace('<!-- LOGO_SECTION -->', logo_section)

        return html

    def build_image(self, data):
        html_content = self._generate_html(data)

        from playwright.sync_api import sync_playwright
        import tempfile

        with sync_playwright() as p:
            browser = p.chromium.launch()
            # The CSS #outer-wrapper is 375px wide.
            # Device scale factor maps it exactly to 576 pixels wide output image (375 * 1.536 = 576)
            page = browser.new_page(
                viewport={'width': 375, 'height': 2000},
                device_scale_factor=1.536
            )
            page.set_content(html_content, wait_until="networkidle")

            # Extract the actual height of the #inner-wrapper to crop properly without borders
            wrapper = page.locator('#inner-wrapper')
            box = wrapper.bounding_box()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                temp_path = tf.name

            page.screenshot(path=temp_path, clip={'x': 0, 'y': 0, 'width': 375, 'height': box['y'] + box['height'] + 32})
            browser.close()

        # The user's goal is pixel-perfect alignment *but* mapped for an 80mm printer.
        # Returning a pristine 8-bit Grayscale preserves the visual "greys" that the HTML specified,
        # avoiding the aggressive, destructive 1-bit thresholding previously done.
        # This will dither nicely or print smoothly on modern thermal drivers.
        img = Image.open(temp_path).convert('L')
        os.unlink(temp_path)
        return img


if __name__ == "__main__":
    data = {
        "store_name": "Retreat 21",
        "address": "11433 Industrial Pkwy, Ste 110\nMARYSVILLE, OH 43040",
        "phone": "(804) 631-3874",
        "transaction_time": "6/12/2026 4:07 AM",
        "tax_rate": "7.24%",
        "tax_amount": 2.89,
        "items": [
            {"name": "Hershey S Chocolate Pudding Cups Snack ct Cups", "price": 3.49},
            {"name": "Suntory -196 Peach Vodka Seltzer 4-Pack 355ml × 2", "price": 19.98, "qty_str": "($9.99 ea.)"},
            {"name": "Suntory -196 Grapefruit Vodka Seltzer 4-Pack 355ml", "price": 9.99},
            {"name": "Nabisco Ritz Peanut Butter 1x1 oz", "price": 3.29},
            {"name": "Suntory -196 Grapefruit Vodka Seltzer 4-Pack 355ml", "price": 9.99}
        ],
        "footer_text": "Return Policy: No cash refunds. Store credit only.",
        "auto_generate_logo": True,
        "logo_path": "logo.png"
    }

    printer = SquareReceiptPrinter()
    img = printer.build_image(data)
    img.save("test_output_playwright.png")
    print("Saved test_output_playwright.png")
