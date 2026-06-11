import os
import platform
import random
import string
import math
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, features

class SquareReceiptPrinter:
    def __init__(self, reg='fonts/sqmarket-regular.ttf', med='fonts/sqmarket-medium.ttf', bold='fonts/sqmarket-bold.ttf'):
        # 80mm thermal paper standard width: 576 pixels
        self.canvas_width = 576
        # The CSS uses a wrapper of 375px with 16px margins.
        # Scaling that up: 16 / 375 * 576 = ~24.5px. We use 24px.
        self.margin = 24
        self.content_width = self.canvas_width - self.margin * 2

        self.reg_font_path = reg
        self.med_font_path = med
        self.bold_font_path = bold
        self.has_raqm = features.check('raqm')

        # Exact mapped CSS spacing
        self.block_spacing = 36  # maps to .section margin-bottom: 24px
        self.item_spacing = 12   # maps to .item-row margin-top: 8px

        self.current_y = 30

        try:
            # Maps from CSS (14px base, 16px large, line-height 24px)
            # Base text: 22px (~14px * 1.536)
            self.font_reg = ImageFont.truetype(reg, 22)
            self.font_med = ImageFont.truetype(med, 22)
            # Large text (Titles, Totals): 24px (~16px * 1.536)
            self.font_large_med = ImageFont.truetype(med, 24)
            # Huge total text (Not in css but keeps visual impact)
            self.font_total_huge = ImageFont.truetype(bold, 36)
        except Exception:
            raise RuntimeError("SQ Market fonts missing.")

    def _get_line_height(self, font) -> int:
        # Exact match of CSS line-height.
        return int(font.size * 1.68)

    def _draw_text_exact(self, draw, x, y, text, font, align="left", color=0):
        kwargs = {'features': ['+tnum']} if self.has_raqm else {}
        anchor = "la" if align == "left" else ("ra" if align == "right" else "ma")
        draw.text((x, y), text, fill=color, font=font, anchor=anchor, **kwargs)

    def _draw_left(self, draw, text, font, indent=0):
        self._draw_text_exact(draw, self.margin + indent, self.current_y, text, font, align="left")
        self.current_y += self._get_line_height(font)

    def _draw_left_right(self, draw, left, right, font_left, font_right=None, indent=0, y_offset=0):
        if font_right is None: font_right = font_left
        y = self.current_y + y_offset
        self._draw_text_exact(draw, self.margin + indent, y, left, font_left, align="left")
        self._draw_text_exact(draw, self.canvas_width - self.margin, y, right, font_right, align="right")
        self.current_y += max(self._get_line_height(font_left), self._get_line_height(font_right)) + y_offset

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

    def _draw_line(self, draw):
        self.current_y += 16
        # The CSS uses a spacer image for a dashed effect.
        try:
            spacer = Image.open('spacer.png').convert('1')
            sw, sh = spacer.size
            if sw == 0 or sh == 0: raise ValueError
            # If the spacer is large, we tile it. If small, tile tightly.
            for x in range(self.margin, self.canvas_width - self.margin, sw):
                if x + sw > self.canvas_width - self.margin:
                    crop_w = (self.canvas_width - self.margin) - x
                    draw.bitmap((x, self.current_y), spacer.crop((0, 0, crop_w, sh)), fill=0)
                else:
                    draw.bitmap((x, self.current_y), spacer, fill=0)
            self.current_y += sh
        except Exception:
            # Fallback exact dashed line mapping (1px solid #e0e1e2 originally,
            # we use thin black for B&W thermal)
            draw.line([(self.margin, self.current_y), (self.canvas_width - self.margin, self.current_y)], fill=0, width=1)
            self.current_y += 1
        self.current_y += 16

    def _generate_simple_logo(self, store_name):
        W, H = 200, 200
        img = Image.new('1', (W, H), color=1)
        d = ImageDraw.Draw(img)
        d.rectangle([10, 10, W-10, H-10], outline=0, width=4)
        words = store_name.split()
        acr = ''.join([w[0].upper() for w in words if w.isalpha()][:3])
        if not acr: acr = "S"

        font = ImageFont.truetype(self.bold_font_path, 80)
        bbox = d.textbbox((0, 0), acr, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((W - tw) // 2, (H - th) // 2 - 10), acr, fill=0, font=font)
        return img

    def build_image(self, data):
        img = Image.new('L', (self.canvas_width, 4000), color=255)
        draw = ImageDraw.Draw(img)
        self.current_y = 48  # Initial padding

        # --- 1. Logo ---
        logo_path = data.get('logo_path')
        logo_img = None
        if logo_path and os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path).convert('L')
            except: pass

        if not logo_img and data.get('auto_generate_logo', True):
            logo_img = self._generate_simple_logo(data.get('store_name', 'Store'))

        if logo_img:
            max_w, max_h = 160, 160
            lw, lh = logo_img.size
            ratio = min(max_w / lw, max_h / lh, 1.0)
            new_w, new_h = int(lw * ratio), int(lh * ratio)
            logo_resized = logo_img.resize((new_w, new_h), Image.Resampling.LANCZOS).convert('1', dither=Image.Dither.FLOYDSTEINBERG)
            paste_x = (self.canvas_width - new_w) // 2
            img.paste(logo_resized, (paste_x, self.current_y))
            self.current_y += new_h + 48

        # --- 2. Header (Two column structure) ---
        self._draw_left(draw, data['store_name'], self.font_large_med)

        address_lines = data.get('address', '').split('\n')
        phone = data.get('phone', '')
        left_header_lines = address_lines + ([phone] if phone else [])


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
        right_header_lines = [date_str, time_str]

        max_lines = max(len(left_header_lines), len(right_header_lines))
        for i in range(max_lines):
            left_text = left_header_lines[i] if i < len(left_header_lines) else ""
            right_text = right_header_lines[i] if i < len(right_header_lines) else ""
            self._draw_left_right(draw, left_text, right_text, self.font_reg, self.font_reg)

        self.current_y += self.block_spacing

        # Solid border separator
        draw.line([(self.margin, self.current_y - self.block_spacing//2),
                   (self.canvas_width - self.margin, self.current_y - self.block_spacing//2)], fill=0, width=1)

        # --- 3. Items ---
        price_col_width = 150
        item_text_width = self.content_width - price_col_width

        for idx, item in enumerate(data['items']):
            if idx > 0:
                self.current_y += self.item_spacing

            qty = item.get('qty', 1)
            unit_price = item['price']
            line_total = round(qty * unit_price, 2)

            display_name = item['name']
            if item.get('taxable', False):
                display_name = f"{item['name']} T"

            name_lines = self._wrap_text(draw, display_name, self.font_med, item_text_width)

            self._draw_left_right(draw, name_lines[0], f"${line_total:.2f}", self.font_med, self.font_med)

            for line in name_lines[1:]:
                self._draw_left(draw, line, self.font_med, indent=0)

            if qty > 1:
                qty_str = f"{qty}" if qty == int(qty) else f"{qty:.2f}"
                self._draw_left(draw, f"{qty_str} x ${unit_price:.2f}", self.font_reg, indent=0)

        # --- Dotted Spacer ---
        self._draw_line(draw)

        # --- 4. Subtotals & Totals ---
        tax_rate_str = data.get('tax_rate', '0%')
        tax_rate = float(tax_rate_str.strip('%')) / 100.0 if '%' in tax_rate_str else float(tax_rate_str)

        full_subtotal = sum(i['price'] * i.get('qty', 1) for i in data['items'])
        taxable_items = [i for i in data['items'] if i.get('taxable', False)]
        tax_amount = round(sum(i['price'] * i.get('qty', 1) for i in taxable_items) * tax_rate, 2)
        total = full_subtotal + tax_amount

        self._draw_left_right(draw, "Purchase Subtotal", f"${full_subtotal:.2f}", self.font_reg, self.font_reg)

        if tax_amount >= 0:
            self._draw_left_right(draw, f"Sales Tax ({tax_rate_str})", f"${tax_amount:.2f}", self.font_reg, self.font_reg)

        self.current_y += 12
        self._draw_left_right(draw, "Total", f"${total:.2f}", self.font_large_med, self.font_large_med)

        self.current_y += self.block_spacing

        # Solid border separator
        draw.line([(self.margin, self.current_y - self.block_spacing//2),
                   (self.canvas_width - self.margin, self.current_y - self.block_spacing//2)], fill=0, width=1)

        # --- 5. Receipt ID and Payment Type ---
        chars = string.ascii_letters
        receipt_id = ''.join(random.choices(chars, k=4))
        payment_method = random.choice(["Cash", "Credit Card"])

        self._draw_left_right(draw, f"Receipt {receipt_id}", payment_method, self.font_reg, self.font_reg)

        self.current_y += self.block_spacing

        # Solid border separator
        draw.line([(self.margin, self.current_y - self.block_spacing//2),
                   (self.canvas_width - self.margin, self.current_y - self.block_spacing//2)], fill=0, width=1)

        # --- 6. Policy ---
        policy = data.get("footer_text", "Return Policy: No cash refunds. Store credit only.")
        policy_lines = self._wrap_text(draw, policy, self.font_reg, self.content_width)
        for line in policy_lines:
            self._draw_left(draw, line, self.font_reg)

        self.current_y += 80
        cropped_img = img.crop((0, 0, self.canvas_width, self.current_y))

        # Crisp 1-bit B&W for Epson compatibility
        return cropped_img.point(lambda x: 255 if x > 128 else 0, mode='1')

    def print_image(self, img):
        if platform.system() == "Windows":
            try:
                import win32print, win32ui
                from PIL import ImageWin
                hDC = win32ui.CreateDC()
                hDC.CreatePrinterDC(win32print.GetDefaultPrinter())
                hDC.StartDoc('Square Receipt')
                hDC.StartPage()
                ImageWin.Dib(img).draw(hDC.GetHandleOutput(), (0, 0, img.size[0], img.size[1]))
                hDC.EndPage()
                hDC.EndDoc()
                hDC.DeleteDC()
            except Exception as e:
                print(f"[WARN] Print failed: {e}")


if __name__ == "__main__":
    data = {
        "store_name": "Retreat 21",
        "address": "11433 Industrial Pkwy, Ste 110\nMARYSVILLE, OH 43040",
        "phone": "(804) 631-3874",
        "transaction_time": "6/12/2026 4:23 AM",
        "tax_rate": "7.24%",
        "items": [
            {"name": "Custom Amount", "price": 55.55, "qty": 1, "taxable": True},
            {"name": "Hershey S Chocolate Pudding Cups Snack ct Cups", "price": 3.49, "qty": 1, "taxable": True},
            {"name": "Fetzer Gewurztraminer 750ml", "price": 8.99, "qty": 1, "taxable": True},
            {"name": "Eppa SupraFruta Organic Red Sangria 750ml", "price": 12.99, "qty": 2, "taxable": True},
            {"name": "Kono Marlborough Sauvignon Blanc 750ml", "price": 15.99, "qty": 1, "taxable": True},
            {"name": "Nabisco Ritz Peanut Butter 1x1 oz", "price": 3.29, "qty": 1, "taxable": True}
        ],
        "footer_text": "Return Policy: No cash refunds. Store credit only.",
        "auto_generate_logo": True,
        "logo_path": "logo.png"
    }

    printer = SquareReceiptPrinter(reg='receipt_generator/fonts/sqmarket-regular.ttf', med='receipt_generator/fonts/sqmarket-medium.ttf', bold='receipt_generator/fonts/sqmarket-bold.ttf')
    img = printer.build_image(data)
    img.save("test_output.png")
    print("Saved test_output.png")
