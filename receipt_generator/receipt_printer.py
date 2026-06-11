import os
import platform
import random
import string
import math
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, features

class SquareReceiptPrinter:
    def __init__(self, reg='fonts/sqmarket-regular.ttf', med='fonts/sqmarket-medium.ttf', bold='fonts/sqmarket-bold.ttf'):
        # Target width is 576. Original web wrapper is 375. Scale = 576 / 375 = 1.536
        self.scale = 576 / 375.0
        self.canvas_width = 576

        # #inner-wrapper { margin: 32px 16px 32px 16px }
        self.margin_x = int(16 * self.scale)
        self.content_width = self.canvas_width - self.margin_x * 2

        self.reg_font_path = reg
        self.med_font_path = med
        self.bold_font_path = bold
        self.has_raqm = features.check('raqm')

        # Colors mapped from CSS
        self.color_primary = (0, 0, 0)       # #000000
        self.color_tertiary = (102, 113, 122) # #66717A

        try:
            # Fonts mapping from CSS
            # .text-tertiary: 14px 400. 14 * 1.536 = 21.504
            self.font_14_reg = ImageFont.truetype(reg, int(14 * self.scale))
            # .item-name: 14px 500
            self.font_14_med = ImageFont.truetype(med, int(14 * self.scale))
            # .text-primary: 16px 500
            self.font_16_med = ImageFont.truetype(med, int(16 * self.scale))
        except Exception:
            raise RuntimeError("SQ Market fonts missing.")

    def _draw_text_exact(self, draw, x, y, text, font, align="left", fill=(0,0,0)):
        kwargs = {'features': ['+tnum']} if self.has_raqm else {}
        if align == "right":
            length = draw.textlength(text, font=font, **kwargs)
            x -= length
        elif align == "center":
            length = draw.textlength(text, font=font, **kwargs)
            x -= length / 2
        draw.text((x, y), text, fill=fill, font=font, **kwargs)

    def _wrap_text(self, draw, text, font, max_width):
        kwargs = {'features': ['+tnum']} if self.has_raqm else {}
        words = text.split()
        lines = []
        for word in words:
            if draw.textlength(word, font=font, **kwargs) > max_width:
                current = ""
                for ch in word:
                    if draw.textlength(current + ch, font=font, **kwargs) <= max_width:
                        current += ch
                    else:
                        if current: lines.append(current)
                        current = ch
                if current: lines.append(current)
            else:
                if not lines:
                    lines.append(word)
                else:
                    test = lines[-1] + " " + word
                    if draw.textlength(test, font=font, **kwargs) <= max_width:
                        lines[-1] = test
                    else:
                        lines.append(word)
        return lines

    def _draw_dashed_line(self, draw, img):
        # Image height is 1px, we place it exactly as in HTML.
        # HTML: padding-bottom: 24px, margin-bottom: 24px for sections.
        # Wait, the dotted line is <td colspan="3" style="border-top: 1px dashed #e0e1e2;" height="1">
        # with spacer.png
        spacer_path = os.path.join(os.path.dirname(__file__), 'spacer.png')
        try:
            spacer = Image.open(spacer_path).convert('RGBA')
            sw, sh = spacer.size
            if sw == 0 or sh == 0: raise ValueError
            # Tile the spacer across the row
            x = self.margin_x
            while x < self.canvas_width - self.margin_x:
                crop_w = min(sw, self.canvas_width - self.margin_x - x)
                img.paste(spacer.crop((0, 0, crop_w, sh)), (x, int(self.current_y)), spacer.crop((0, 0, crop_w, sh)))
                x += crop_w
        except Exception:
            # Fallback
            draw.line([(self.margin_x, self.current_y), (self.canvas_width - self.margin_x, self.current_y)], fill=(224,225,226), width=1)
        self.current_y += 1

    def build_image(self, data):
        # RGB to preserve gray anti-aliased text perfectly as seen on web.
        img = Image.new('RGB', (self.canvas_width, 4000), color=(255,255,255))
        draw = ImageDraw.Draw(img)

        # Start offset: #inner-wrapper margin-top: 32px
        self.current_y = int(32 * self.scale)

        # 1. Logo
        logo_path = data.get('logo_path')
        if logo_path and os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path).convert('RGBA')
                # 75x75 in CSS
                logo_size = int(75 * self.scale)
                logo_resized = logo_img.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

                # Image paste with alpha blending if needed, here we use a white background
                bg = Image.new('RGBA', logo_resized.size, (255,255,255,255))
                bg.paste(logo_resized, (0, 0), logo_resized)

                paste_x = (self.canvas_width - logo_size) // 2
                img.paste(bg.convert('RGB'), (paste_x, int(self.current_y)))
                # CSS: margin: 0 auto 32px auto
                self.current_y += logo_size + int(32 * self.scale)
            except: pass

        # Line height in CSS is 24px for all these blocks.
        lh_14 = int(24 * self.scale)
        lh_16 = int(24 * self.scale)

        # 2. Header (Store Info & Date)
        # Store name: .text-primary (16px, 500, #000)
        self._draw_text_exact(draw, self.margin_x, self.current_y, data['store_name'], self.font_16_med, fill=self.color_primary)
        self.current_y += lh_16

        # Left and Right Columns
        start_cols_y = self.current_y

        # Left: Address & Phone (.text-tertiary 14px, #66717A)
        address_lines = data.get('address', '').split('\n')
        for line in address_lines:
            self._draw_text_exact(draw, self.margin_x, self.current_y, line, self.font_14_reg, fill=self.color_tertiary)
            self.current_y += lh_14

        phone = data.get('phone', '')
        if phone:
            self._draw_text_exact(draw, self.margin_x, self.current_y, phone, self.font_14_reg, fill=self.color_tertiary)
            self.current_y += lh_14

        left_end_y = self.current_y

        # Right: Date and Time (.text-tertiary 14px, #66717A)
        self.current_y = start_cols_y
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

        self._draw_text_exact(draw, self.canvas_width - self.margin_x, self.current_y, date_str, self.font_14_reg, align="right", fill=self.color_tertiary)
        self.current_y += lh_14
        self._draw_text_exact(draw, self.canvas_width - self.margin_x, self.current_y, time_str, self.font_14_reg, align="right", fill=self.color_tertiary)
        self.current_y += lh_14

        right_end_y = self.current_y

        # Max y defines end of section
        self.current_y = max(left_end_y, right_end_y)

        # Section separator: padding-bottom 24px, border-bottom 1px solid #000, margin-bottom 24px
        self.current_y += int(24 * self.scale) - lh_14 # compensate for last line height
        draw.line([(self.margin_x, self.current_y), (self.canvas_width - self.margin_x, self.current_y)], fill=self.color_primary, width=1)
        self.current_y += int(24 * self.scale)

        # 3. Items
        # Right column flex flex: 0 0 100px.
        right_col_w = int(100 * self.scale)
        item_text_width = self.content_width - right_col_w

        for idx, item in enumerate(data['items']):
            if idx > 0:
                self.current_y += int(8 * self.scale) # .item-row + .item-row margin-top 8px

            display_name = item['name']
            price_str = f"${item['price']:.2f}"

            # Both name and price use .item-name / .currency: 14px, 500, #000
            name_lines = self._wrap_text(draw, display_name, self.font_14_med, item_text_width)

            # Draw first line with price
            self._draw_text_exact(draw, self.margin_x, self.current_y, name_lines[0], self.font_14_med, fill=self.color_primary)
            self._draw_text_exact(draw, self.canvas_width - self.margin_x, self.current_y, price_str, self.font_14_med, align="right", fill=self.color_primary)
            self.current_y += lh_14

            # Draw remaining lines
            for line in name_lines[1:]:
                self._draw_text_exact(draw, self.margin_x, self.current_y, line, self.font_14_med, fill=self.color_primary)
                self.current_y += lh_14

        # Dotted Spacer: height 11px padding above/below.
        self.current_y += int(11 * self.scale)
        self._draw_dashed_line(draw, img)
        self.current_y += int(11 * self.scale)

        # 4. Totals
        # .p -> #66717A 14px 400
        full_subtotal = sum(i['price'] for i in data['items']) # Assuming data matches web exactly, quantity is already baked into item rows or price in user's prompt testing format.
        # But wait, to match the exact URL, the subtotal is sum of prices.

        tax_rate_str = data.get('tax_rate', '0%')
        tax_rate = float(tax_rate_str.strip('%')) / 100.0 if '%' in tax_rate_str else float(tax_rate_str)
        tax_amount = data.get('tax_amount', round(full_subtotal * tax_rate, 2))
        total = full_subtotal + tax_amount

        # Purchase Subtotal (Grey)
        self._draw_text_exact(draw, self.margin_x, self.current_y, "Purchase Subtotal", self.font_14_reg, fill=self.color_tertiary)
        self._draw_text_exact(draw, self.canvas_width - self.margin_x, self.current_y, f"${full_subtotal:.2f}", self.font_14_reg, align="right", fill=self.color_tertiary)
        self.current_y += lh_14

        # Sales Tax (Grey)
        self._draw_text_exact(draw, self.margin_x, self.current_y, f"Sales Tax ({tax_rate_str})", self.font_14_reg, fill=self.color_tertiary)
        self._draw_text_exact(draw, self.canvas_width - self.margin_x, self.current_y, f"${tax_amount:.2f}", self.font_14_reg, align="right", fill=self.color_tertiary)
        self.current_y += lh_14

        # Total (Black, 16px 500)
        self.current_y += int(12 * self.scale) # margin-top: 12px
        self._draw_text_exact(draw, self.margin_x, self.current_y, "Total", self.font_16_med, fill=self.color_primary)
        self._draw_text_exact(draw, self.canvas_width - self.margin_x, self.current_y, f"${total:.2f}", self.font_16_med, align="right", fill=self.color_primary)
        self.current_y += lh_16

        # Section separator
        self.current_y += int(24 * self.scale) - lh_16
        draw.line([(self.margin_x, self.current_y), (self.canvas_width - self.margin_x, self.current_y)], fill=self.color_primary, width=1)
        self.current_y += int(24 * self.scale)

        # 5. Receipt ID and Payment Type
        # Random 4 char
        receipt_id = ''.join(random.choices(string.ascii_letters, k=4))
        payment_method = random.choice(["Cash", "Credit Card"])

        # .text-tertiary 14px 400
        self._draw_text_exact(draw, self.margin_x, self.current_y, f"Receipt {receipt_id}", self.font_14_reg, fill=self.color_tertiary)
        self._draw_text_exact(draw, self.canvas_width - self.margin_x, self.current_y, payment_method, self.font_14_reg, align="right", fill=self.color_tertiary)
        self.current_y += lh_14

        # Section separator
        self.current_y += int(24 * self.scale) - lh_14
        draw.line([(self.margin_x, self.current_y), (self.canvas_width - self.margin_x, self.current_y)], fill=self.color_primary, width=1)
        self.current_y += int(24 * self.scale)

        # 6. Policy
        policy = data.get("footer_text", "Return Policy: No cash refunds. Store credit only.")
        policy_lines = self._wrap_text(draw, policy, self.font_14_reg, self.content_width)
        for line in policy_lines:
            self._draw_text_exact(draw, self.margin_x, self.current_y, line, self.font_14_reg, fill=self.color_tertiary)
            self.current_y += lh_14

        # Final bottom wrapper margin
        self.current_y += int(32 * self.scale)

        cropped_img = img.crop((0, 0, self.canvas_width, int(self.current_y)))
        return cropped_img


if __name__ == "__main__":
    # Test data identical to Square web layout
    data = {
        "store_name": "Retreat 21",
        "address": "11433 Industrial Pkwy, Ste 110\nMARYSVILLE, OH 43040",
        "phone": "(804) 631-3874",
        "transaction_time": "6/12/2026 4:23 AM",
        "tax_rate": "7.24%",
        "tax_amount": 6.77,
        "items": [
            {"name": "Custom Amount", "price": 55.55},
            {"name": "Hershey S Chocolate Pudding Cups Snack ct Cups", "price": 3.49},
            {"name": "Fetzer Gewurztraminer 750ml", "price": 8.99},
            {"name": "Eppa SupraFruta Organic Red Sangria 750ml", "price": 12.99},
            {"name": "Kono Marlborough Sauvignon Blanc 750ml", "price": 15.99},
            {"name": "Nabisco Ritz Peanut Butter 1x1 oz", "price": 3.29}
        ],
        "footer_text": "Return Policy: No cash refunds. Store credit only.",
        "auto_generate_logo": True,
        "logo_path": "logo.png"
    }

    # Running from receipt_generator/ directly
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    printer = SquareReceiptPrinter(
        reg='fonts/sqmarket-regular.ttf',
        med='fonts/sqmarket-medium.ttf',
        bold='fonts/sqmarket-bold.ttf'
    )
    img = printer.build_image(data)
    img.save("../test_output2.png")
    print("Saved test_output2.png")
