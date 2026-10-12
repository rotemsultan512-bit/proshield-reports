"""Build an immutable delivery-note PDF with a recipient-signature appendix."""

from io import BytesIO
from datetime import timezone
import hashlib
import os
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter


def _font(size):
    for path in (
        os.path.join(os.path.dirname(__file__), 'static', 'fonts', 'NotoSansHebrew.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
        'C:/Windows/Fonts/arial.ttf',
        'DejaVuSans.ttf',
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise RuntimeError('A font supporting Hebrew is required for signed delivery notes')


def _original_pdf(path):
    with open(path, 'rb') as source:
        data = source.read()
    if path.lower().endswith('.pdf'):
        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 50:
                raise ValueError('תעודת המשלוח אינה ניתנת לחתימה')
            return data, reader
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('קובץ PDF לא תקין') from exc

    try:
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 25_000_000:
                raise ValueError('תמונת התעודה גדולה מדי')
            converted = image.convert('RGB')
            converted.thumbnail((2480, 3508), Image.Resampling.LANCZOS)
            output = BytesIO()
            converted.save(output, format='PDF', resolution=200)
            return data, PdfReader(BytesIO(output.getvalue()))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('תמונת התעודה אינה תקינה') from exc


def validate_delivery_source(path):
    _original_pdf(path)


def create_signed_pdf(original_path, signature_image, customer_name, address,
                      recipient_name, signed_at, note_id):
    """Keep original pages unchanged and append an explicit signed receipt page."""
    original_bytes, original_reader = _original_pdf(original_path)
    page = Image.new('RGB', (1240, 1754), '#ffffff')
    draw = ImageDraw.Draw(page)
    title_font = _font(58)
    body_font = _font(33)
    small_font = _font(25)
    right = 1140

    draw.rounded_rectangle((78, 78, 1162, 1674), radius=24, outline='#d4e0ea', width=3)
    draw.rectangle((78, 78, 1162, 205), fill='#154d78')
    draw.text((right, 112), 'אישור קבלת סחורה', font=title_font, fill='white', anchor='ra', direction='rtl')
    draw.text((right, 280), 'דף חתימה המצורף לתעודת המשלוח המקורית',
              font=body_font, fill='#203449', anchor='ra', direction='rtl')

    details = (
        ('מספר תעודה במערכת', str(note_id)),
        ('לקוח', customer_name),
        ('כתובת אספקה', address),
        ('שם מקבל הסחורה', recipient_name),
        ('תאריך ושעת חתימה (ישראל)', signed_at.replace(tzinfo=timezone.utc)
         .astimezone(ZoneInfo('Asia/Jerusalem')).strftime('%d/%m/%Y %H:%M')),
    )
    y = 385
    for label, value in details:
        draw.text((right, y), f'{label}: {value}', font=body_font,
                  fill='#203449', anchor='ra', direction='rtl')
        y += 91

    draw.text((right, 895), 'חתימת מקבל הסחורה', font=body_font,
              fill='#203449', anchor='ra', direction='rtl')
    draw.rounded_rectangle((140, 970, 1100, 1290), radius=18, outline='#bfd0dc', width=3)
    signature = signature_image.convert('RGBA')
    signature.thumbnail((860, 250), Image.Resampling.LANCZOS)
    page.paste(signature, (int((1240 - signature.width) / 2), 1005), signature)

    digest = hashlib.sha256(original_bytes).hexdigest()
    draw.text((right, 1420), 'החתימה נאספה באפליקציית Proshield ומצורפת למסמך המקור.',
              font=small_font, fill='#4d6475', anchor='ra', direction='rtl')
    draw.text((right, 1470), f'SHA-256: {digest[:32]}', font=small_font,
              fill='#4d6475', anchor='ra')
    draw.text((right, 1510), digest[32:], font=small_font,
              fill='#4d6475', anchor='ra')

    appendix = BytesIO()
    page.save(appendix, format='PDF', resolution=150)
    appendix.seek(0)
    writer = PdfWriter()
    writer.append(original_reader)
    writer.append(PdfReader(appendix))
    output = BytesIO()
    writer.write(output)
    if output.tell() > 25 * 1024 * 1024:
        raise ValueError('התעודה החתומה גדולה מדי')
    return output.getvalue()
