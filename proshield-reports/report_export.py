"""Print-friendly Excel reports with one work report per row."""

from collections import defaultdict
from datetime import datetime
from io import BytesIO
import math

from flask import send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins


NAVY = '123A5A'
AMBER = 'F3AE45'
PALE = 'F2F6F9'
LINE = 'D8E2EA'


def _print_setup(sheet, widths, title_rows):
    sheet.sheet_view.rightToLeft = True
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = title_rows
    sheet.page_margins = PageMargins(left=.25, right=.25, top=.4, bottom=.4, header=.15, footer=.2)
    sheet.oddFooter.center.text = 'עמוד &P מתוך &N'
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width


def _header(sheet, row, titles):
    for column, title in enumerate(titles, 1):
        cell = sheet.cell(row, column, title)
        cell.fill = PatternFill('solid', fgColor=NAVY)
        cell.font = Font(name='Arial', size=10, bold=True, color='FFFFFF')
        cell.alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)
    sheet.row_dimensions[row].height = 28


def _body_cell(cell, shaded=False):
    cell.font = Font(name='Arial', size=9, color=NAVY)
    cell.alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)
    cell.border = Border(bottom=Side(style='hair', color=LINE))
    if shaded:
        cell.fill = PatternFill('solid', fgColor=PALE)


def _lines_for_width(value, width):
    return sum(max(1, math.ceil(len(part) / width)) for part in str(value).split('\n'))


def export_reports_to_excel(reports, filename_prefix, report_owner, unit_labels):
    wb = Workbook()
    sheet = wb.active
    sheet.title = 'דוחות להדפסה'
    _print_setup(sheet, {'A':18, 'B':16, 'C':40, 'D':43, 'E':35}, '1:4')
    sheet.freeze_panes = 'A5'

    sheet.merge_cells('A1:E1')
    sheet['A1'] = 'PROSHIELD | דוח עבודה'
    sheet['A1'].font = Font(name='Arial', size=17, bold=True, color=NAVY)
    sheet.row_dimensions[1].height = 30

    sheet.merge_cells('A2:E2')
    worker = report_owner.full_name if report_owner else 'כל העובדים'
    dates = [report.timestamp for report in reports if report.timestamp]
    period = f"{min(dates):%d.%m.%Y} – {max(dates):%d.%m.%Y}" if dates else 'ללא דוחות'
    sheet['A2'] = f'{worker}  |  {period}  |  {len(reports)} דוחות'
    sheet['A2'].font = Font(name='Arial', size=10, color=NAVY)
    sheet.row_dimensions[2].height = 24
    sheet.merge_cells('A3:E3')
    sheet['A3'] = 'כל שורה היא דוח אחד. כמויות נפרדות לפי יחידת מידה.'
    sheet['A3'].font = Font(name='Arial', size=9, color='64788A')
    _header(sheet, 4, ['תאריך ושעה', 'סוג ומצב', 'אתר ולקוח', 'מוצרים וכמויות', 'צוות והערות'])

    totals = defaultdict(float)
    daily = defaultdict(lambda: {'delivery':0, 'installation':0, 'details':[]})
    for row_number, report in enumerate(sorted(reports, key=lambda r: r.timestamp or datetime.min), 5):
        site = '\n'.join(part for part in [report.company_project, report.customer_name, report.address] if part)
        product_lines = []
        for product in report.products:
            unit = product.quantity_unit or 'unit'
            product_lines.append(f'{product.product_name} · {product.quantity:g} {unit_labels.get(unit, unit)}')
            totals[(product.product_name, unit)] += product.quantity
        details = '\n'.join(part for part in [
            f'דווח על ידי: {report.author.full_name}' if report.author else '',
            f'צוות: {report.additional_worker_name}' if report.additional_worker_name else '',
            f'מקבל הסחורה: {report.recipient_name}' if report.recipient_name else '',
            f'הערות: {report.notes}' if report.notes else '',
        ] if part)
        values = [
            report.timestamp.strftime('%d.%m.%Y\n%H:%M') if report.timestamp else '',
            f"דוח #{report.id}\n" + ('אספקה' if report.report_type == 'delivery' else 'התקנה') + '\n' +
            ('הושלם' if report.status == 'completed' else 'נדרש חזרה'),
            site, '\n'.join(product_lines), details,
        ]
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_number, column, value)
            _body_cell(cell, row_number % 2 == 0)
        sheet.row_dimensions[row_number].height = min(330, max(42,
            15 * max(_lines_for_width(value, width) for value, width in zip(values, [16,14,37,40,32])) + 8))
        if report.timestamp:
            day = report.timestamp.date()
            daily[day][report.report_type] += 1
            daily[day]['details'].append(report.address or '')

    last_row = max(4, len(reports) + 4)
    sheet.print_area = f'A1:E{last_row}'
    sheet.auto_filter.ref = f'A4:E{last_row}'

    products_sheet = wb.create_sheet('סיכום מוצרים')
    _print_setup(products_sheet, {'A':48, 'B':18, 'C':17}, '1:1')
    _header(products_sheet, 1, ['מוצר', 'יחידה', 'כמות כוללת'])
    for row_number, ((name, unit), quantity) in enumerate(sorted(totals.items()), 2):
        for column, value in enumerate([name, unit_labels.get(unit, unit), quantity], 1):
            _body_cell(products_sheet.cell(row_number, column, value), row_number % 2 == 0)
    products_sheet.print_area = f'A1:C{max(1, len(totals)+1)}'

    daily_sheet = wb.create_sheet('סיכום יומי')
    _print_setup(daily_sheet, {'A':17, 'B':16, 'C':16, 'D':17, 'E':60}, '1:1')
    _header(daily_sheet, 1, ['תאריך', 'מספר דוחות', 'אספקות', 'התקנות', 'כתובות'])
    for row_number, (day, values) in enumerate(sorted(daily.items()), 2):
        cells = [day.strftime('%d.%m.%Y'), values['delivery'] + values['installation'],
                 values['delivery'], values['installation'], ' | '.join(values['details'])]
        for column, value in enumerate(cells, 1):
            _body_cell(daily_sheet.cell(row_number, column, value), row_number % 2 == 0)
        daily_sheet.row_dimensions[row_number].height = 28
    daily_sheet.print_area = f'A1:E{max(1, len(daily)+1)}'

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name=f'{filename_prefix}_{datetime.now():%Y%m%d_%H%M%S}.xlsx')
