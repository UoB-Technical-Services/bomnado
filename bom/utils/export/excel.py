""" Tools for exporting to Excel format.
"""
import datetime
import itertools
import string
from collections import Counter
from pathlib import Path

import xlsxwriter
from PIL import Image

import bom
from bom.models import Part, SubAssemblyLineItem, Deal

bom_root = Path(bom.__file__).parent

PLACEHOLDER_DIR = bom_root / "static" / "assets" / "placeholders"

# Define placeholder paths
PART_PLACEHOLDER = PLACEHOLDER_DIR / "part_placeholder.png"
ASSEMBLY_PLACEHOLDER = PLACEHOLDER_DIR / "assembly_placeholder.png"
ROOT_ASSEMBLY_PLACEHOLDER = PLACEHOLDER_DIR / "root_assembly_placeholder.png"


def get_placeholder_path(item=None):
    """
    Get the appropriate placeholder image path based on item type.

    Args:
        item: The model instance (Part or SubAssembly) or None

    Returns:
        Path object to the placeholder image file or None if files don't exist
    """
    # Default to part placeholder if no item or it's a Part
    if item is None or isinstance(item, Part):
        placeholder = PART_PLACEHOLDER
    else:
        # It's an assembly - check if it's a root/toplevel assembly
        is_toplevel = getattr(item, "is_toplevel", False)
        placeholder = ROOT_ASSEMBLY_PLACEHOLDER if is_toplevel else ASSEMBLY_PLACEHOLDER

    # Verify the placeholder file exists
    return placeholder if placeholder.exists() else None


class ExcelColumn:
    """ Helper for writing data in columns to excel.
    """
    TITLE_ROW = 0
    HEADING_ROW = 1
    COL_LETTERS = list(string.ascii_uppercase) + [f'{r}{c}' for r, c, in
                                                  itertools.product(string.ascii_uppercase, repeat=2)]

    def __init__(self, sheet, col, width, name, style, heading_style, column_hidden=False):
        self.sheet = sheet
        self.style = style
        self.col = col
        self.width = width
        self.sheet.write(self.HEADING_ROW, self.col, name, heading_style)
        self.sheet.set_column(self.col, self.col, self.width, None, {'hidden': column_hidden})

    def text(self, row, value, style=None):
        style = style if style else self.style
        self.sheet.write(row + self.HEADING_ROW + 1, self.col, value, style)

    def comment(self, row, value):
        self.sheet.write_comment(row + self.HEADING_ROW + 1, self.col, value)

    def number(self, row, value, style=None):
        style = style if style else self.style
        self.sheet.write_number(row + self.HEADING_ROW + 1, self.col, value, style)

    def formula(self, row, value, style=None):
        style = style if style else self.style
        self.sheet.write_formula(row + self.HEADING_ROW + 1, self.col, value, style)

    def url(self, row, link, text, style=None):
        style = style if style else self.style
        self.sheet.write_url(row + self.HEADING_ROW + 1, self.col, link, style, string=text)

    def image(self, row, path=None, item=None):
        """
        Helper function to write an image into an excel doc.

        Args:
            row: The row to insert the image into
            path: Path to image file or None to use a placeholder
            item: The model instance to determine appropriate placeholder if path is None
        """
        def pt_to_width(pt):
            return pt * (61 / 8)

        def pt_to_height(pt):
            return pt_to_width(pt) / (61 / 45.75)

        sx = pt_to_width(self.width) - 1
        sy = pt_to_width(self.width) - 1
        row_height = pt_to_height(self.width)
        self.sheet.set_row(row=row + self.HEADING_ROW + 1, height=row_height)

        # If no path provided, try to get the appropriate placeholder
        if not path and item is not None:
            placeholder_path = get_placeholder_path(item)
            if placeholder_path:
                path = str(placeholder_path)

        if not path:
            return

        cell_aspect = sx / sy
        try:
            with Image.open(path) as img:
                ix, iy = img.size
                img_aspect = ix / iy
                scale = sy / iy if cell_aspect > img_aspect else sx / ix
                self.sheet.insert_image(row + self.HEADING_ROW + 1, self.col, path, {
                    'x_offset': 1, 'y_offset': 1,
                    'x_scale': scale,
                    'y_scale': scale,
                    'positioning': 2
                })
        except (FileNotFoundError, ValueError, OSError):
            # If the image can't be loaded, just skip it
            return

    def col_letter(self):
        """Get the column letter for this column, used in formua"""
        return self.COL_LETTERS[self.col]

    def location(self, row):
        """Get full location for a provided row in this column aka `A64` or `AJ9`"""
        return f'{self.col_letter()}{row + self.HEADING_ROW + 2}'


def export_database_to_excel(project, output, user=None):
    """ Export the BOM to an excel file.
    :param project: Root Assembly
    :param output: The BytesIO object to write into.
    :param user: Only this user's parts are listed; None keeps the old everything-in-the-database export.
    Note - you must call `workbook.close()` on the returned workbook.
    """

    # Create a workbook.
    workbook = xlsxwriter.Workbook(output, {'in_memory': True, 'remove_timezone': True})

    # Create the worksheets.
    sheet_pbs = workbook.add_worksheet('PBS')
    sheet_parts = workbook.add_worksheet('Parts')
    sheet_stats = workbook.add_worksheet('Statistics')

    # Setup Headings.
    fmt_heading = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'valign': 'vcenter'})
    fmt_bold = workbook.add_format({'bold': True, 'valign': 'vcenter'})
    fmt_cell = workbook.add_format({'valign': 'vcenter', 'shrink': True})
    fmt_cell_sm = workbook.add_format({'valign': 'vcenter', 'align': 'hcenter', 'shrink': True, 'font_size': '9'})
    fmt_pbsref = workbook.add_format({'valign': 'vcenter', 'shrink': True, 'font': 'Consolas', 'font_size': '9'})
    fmt_cell_date = workbook.add_format({'valign': 'vcenter', 'shrink': True, 'num_format': 'dd/mm/yyyy hh:mm'})
    fmt_link = workbook.add_format({'valign': 'vcenter', 'bold': True, 'underline': True, 'font_color': '#0000ff'})
    fmt_orange = workbook.add_format({'align': 'center', 'bg_color': '#FCD5B4'})

    # Key queries.
    root = project
    parts = (Part.all_available_to_user(user) if user is not None else Part.objects.all()).order_by('reference')
    assemblies = project.children.all().order_by('id')

    def _generate_statistics():
        """ Write the stats worksheet. """
        sheet_stats.set_column(0, 2, 20)
        sheet_stats.write('A1', 'Name', fmt_bold)
        sheet_stats.write('A2', 'Assemblies', fmt_bold)
        sheet_stats.write('A3', 'Parts', fmt_bold)
        sheet_stats.write('A4', 'Explosion', fmt_bold)
        sheet_stats.write('A5', 'Generated', fmt_bold)

        sheet_stats.write('B1', root.reference, fmt_cell)
        sheet_stats.write('B2', assemblies.count(), fmt_cell)
        sheet_stats.write('B3', parts.count(), fmt_cell)
        sheet_stats.write('B4', datetime.datetime.now().strftime('%yW%V'))
        sheet_stats.write('B5', datetime.datetime.now(), fmt_cell_date)

    def _generate_parts():
        """ Write the parts worksheet. """

        # Write title.
        sheet_parts.write('A1', 'Parts', fmt_bold)

        # Write column heading.
        col_id = ExcelColumn(sheet_parts, 0, 5.0, 'PK', fmt_cell, fmt_heading)
        col_image = ExcelColumn(sheet_parts, 1, 4.0, '', fmt_cell, fmt_heading)
        col_qty = ExcelColumn(sheet_parts, 2, 8.0, 'Qty', fmt_cell, fmt_heading)
        col_ref = ExcelColumn(sheet_parts, 3, 30.0, 'Reference', fmt_pbsref, fmt_heading)
        col_name = ExcelColumn(sheet_parts, 4, 50.0, 'Name', fmt_cell, fmt_heading)
        col_supplier = ExcelColumn(sheet_parts, 5, 20.0, 'Supplier Code', fmt_cell, fmt_heading)
        col_dimensions = ExcelColumn(sheet_parts, 6, 20.0, 'Dimensions LWH (mm)', fmt_cell, fmt_heading)
        col_weight = ExcelColumn(sheet_parts, 7, 20.0, 'Weight (kg)', fmt_cell, fmt_heading)
        col_colour = ExcelColumn(sheet_parts, 8, 20.0, 'Colour', fmt_cell, fmt_heading)
        col_sales = ExcelColumn(sheet_parts, 9, 20.0, 'Sales Code', fmt_cell, fmt_heading)
        col_hs = ExcelColumn(sheet_parts, 10, 20.0, 'HS Code', fmt_cell, fmt_heading)
        col_usedby = ExcelColumn(sheet_parts, 11, 18.0, 'Assemblies', fmt_cell_sm, fmt_heading)
        col_spec = ExcelColumn(sheet_parts, 12, 40.0, 'Spec', fmt_cell_sm, fmt_heading)

        # For each part, write a record.
        for idx, part in enumerate(parts):
            cheapest = part.cheapest()

            col_id.number(idx, part.id)
            path = part.picture.path if part.picture else None
            col_image.image(idx, path, part)
            col_qty.number(idx, part.count_usage())
            col_ref.text(idx, part.reference)
            col_name.text(idx, part.name)
            col_dimensions.text(idx, part.dimensions)
            col_weight.number(idx, part.kgs or 0)
            col_colour.text(idx, part.colour)
            col_sales.text(idx, part.sale_code)
            col_hs.text(idx, part.hs_code)
            col_spec.text(idx, part.spec)
            if cheapest and cheapest.url:
                col_supplier.url(idx, cheapest.url, str(cheapest.partcode or cheapest.supplier), fmt_link)
            elif cheapest:
                col_supplier.text(idx, str(cheapest.partcode or cheapest.supplier))
            col_usedby.text(idx, ', '.join([assy.reference for assy in part.find_using_assemblies() if assy]))

        # Apply the auto filter range. RC, R1,C1
        sheet_parts.autofilter(1, 0, len(parts) + 1, 12)
        sheet_parts.freeze_panes(2, 0)

    def _generate_pbs():
        """ Write the PBS worksheet. """

        # Write title.
        sheet_pbs.write('A1', 'Product Breakdown Structure', fmt_bold)

        # Write column heading.
        col_level = ExcelColumn(sheet_pbs, 0, 5.0, 'Level', fmt_cell_sm, fmt_heading)
        col_address = ExcelColumn(sheet_pbs, 1, 38.0, 'Address', fmt_pbsref, fmt_heading)
        col_image = ExcelColumn(sheet_pbs, 2, 2.50, 'I', fmt_cell, fmt_heading)
        col_qty = ExcelColumn(sheet_pbs, 3, 5, 'Qty', fmt_cell, fmt_heading)
        col_is_sold = ExcelColumn(sheet_pbs, 4, 3.70, 'Sell', fmt_orange, fmt_heading)
        col_name = ExcelColumn(sheet_pbs, 5, 50.0, 'Name', fmt_cell_sm, fmt_heading)
        col_version = ExcelColumn(sheet_pbs, 6, 10, 'Version', fmt_cell, fmt_heading)

        used_assys = set([root])
        used_parts = set()

        row = 0

        def write(item, line, level):
            """ Write a row into the excel. """
            nonlocal row
            location = ('   ' * level) + '├─' + item.reference
            col_level.number(row, level)
            col_address.text(row, location)
            path = item.picture.path if hasattr(item, 'picture') and item.picture else None
            col_image.image(row, path, item)
            col_qty.number(row, line.quantity if hasattr(line, 'quantity') else 1)
            if item.sale_code:
                col_is_sold.text(row, 'Y')
            col_name.text(row, item.name)
            col_version.text(row, item.revision if hasattr(item, 'revision') else '')
            row += 1

        def write_orphan(item):
            """ Write a row into the excel as an orphan. """
            nonlocal row
            col_level.text(row, 'ORPHAN')
            col_address.text(row, item.reference)
            path = item.picture.path if hasattr(item, 'picture') and item.picture else None
            col_image.image(row, path, item)
            col_qty.number(row, 0)
            if item.sale_code:
                col_is_sold.text(row, 'Y')
            col_name.text(row, item.name)
            col_version.text(row, item.revision if hasattr(item, 'revision') else '')
            row += 1

        def traverse(assembly, line, level):
            """ Traverse the assembly tree. """
            sub_lines = SubAssemblyLineItem.objects.filter(subassembly=assembly)
            used_assys.add(assembly)
            write(assembly, line, level)
            for line in sub_lines:
                if line.child_part:
                    write(line.child_part, line, level + 1)
                    used_parts.add(line.child_part)
                if line.child_subassembly:
                    traverse(line.child_subassembly, line, level + 1)

        def write_orphans():
            orphan_subs = project.children.exclude(
                id=project.id).exclude(reference__in=[s.reference for s in used_assys])
            orphan_parts = [p for p in parts if p.is_orphan]

            for assy in orphan_subs:
                write_orphan(assy)

            for part in orphan_parts:
                write_orphan(part)

        # Traverse from the root.
        traverse(root, None, 0)

        # Skip 2 rows then write out the orphans not used.
        row += 2
        write_orphans()

    sheet_pbs.freeze_panes(2, 0)
    for sheet, colour in ((sheet_pbs, '#2563EB'), (sheet_parts, '#334155'), (sheet_stats, '#94A3B8')):
        sheet.set_tab_color(colour)
    workbook.set_properties({'title': f'{root.reference} BOM', 'company': 'Bomnado',
                             'comments': 'Generated by Bomnado.'})
    _generate_parts()
    _generate_statistics()
    _generate_pbs()
    return workbook


class Supplier:
    """ Helper class for reasoning about suppliers in the Purchasing sheet. """

    def __init__(self, source, required):
        """
        :param source: The PartSource to represent.
        :param required: The number required by this build.
        """
        self.source = source
        self.required = required
        if source.rrp is None:
            self.cost, self.recieved, self.deal = None, None, None       # no price: sorts last, says so
        else:
            self.cost, self.recieved = self.source.cost_quantity_for(self.required, include_shipping=False)
            self.deal = self.cost / self.recieved

    def relative_deal(self, best):
        """ A coefficient for how good (0.x) or bad (1.x) this deal is relative
        to another supplier given by `best`. """
        if not best:
            return 1.0
        if not best.deal:
            return 1.0
        return self.deal / best.deal

    @property
    def total_cost(self):
        """ The total spend required to purchase from this supplier.
        return The value of ((max(min_order, requied) * rrp) + shipping)
        """
        if self.source.rrp is None:
            return None
        cost, recieved = self.source.cost_quantity_for(self.required, include_shipping=True)
        return cost

    def text(self, best):
        """ A three-line cell summarising this supplier: what you get, who it is, how it compares. """
        if self.deal is None:
            return f'no price · {self.source.lead_time} days\n{self.source.partcode} @ {self.source.source}'
        relative = 'best price' if best is None or best is self else f'{self.relative_deal(best):.1f} × best'
        return f'{self.recieved} for £{self.cost:.2f} · {self.source.lead_time} days · ship £{self.source.shipping}\n' \
               f'{self.source.partcode} @ {self.source.source}\n' \
               f'{relative}'


class Row:
    """ Represent a part row in the purchasing sheet. """

    def __init__(self, part, required):
        """
        :param source: The Part to represent.
        :param required: The number required by this build.
        """
        self.part = part
        self.required = required

        # Represent the suppliers and sort by cheapest deal.
        self.suppliers = [Supplier(src, required) for src in part.sources.all()]
        self.suppliers = sorted(self.suppliers, key=lambda s: (s.deal is None, s.deal or 0))

    @property
    def cheapest(self):
        """ The cheapest supplier or `None` if no suppliers. """
        return self.suppliers[0] if self.suppliers else None

    @property
    def lead_of_cheapest(self):
        """ The lead time of the cheapest priced supplier, or `None` if none is priced. """
        return self.suppliers[0].source.lead_time if self.suppliers and self.suppliers[0].deal is not None else None


class DealRow:
    """ Represent a deal row in the purchasing sheet. """

    def __init__(self, deal, required):
        """
        :param source: The Deal to represent.
        :param required: The number required by this build.
        """
        self.deal = deal
        self.required = required


def export_purchasing_spreadsheet(project, output, user, base_url=None):
    """ Generate a purchasing spreadsheet as an excel file.
    :param project: Root Assembly
    :param output The BytesIO object to write into.
    :param user If user object is passed, apply relevant deals
    Note - you must call `workbook.close()` on the returned workbook.
    """
    # Create a workbook.
    workbook = xlsxwriter.Workbook(output, {'in_memory': True, 'remove_timezone': True})

    # Create the worksheets.
    sheet_purchasing = workbook.add_worksheet('Purchasing')
    sheet_bulk = workbook.add_worksheet('Bulk Deals')

    # Setup Formatting Styles
    fmt_heading = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'valign': 'vcenter'})
    fmt_heading_user = workbook.add_format({'bold': True, 'bg_color': '#C4D79B', 'valign': 'vcenter'})

    fmt_cell = workbook.add_format({'valign': 'vcenter', 'shrink': False})
    fmt_cell_ha = workbook.add_format({'valign': 'vcenter', 'align': 'center', 'shrink': False})
    fmt_cell_sm = workbook.add_format({'valign': 'vcenter', 'shrink': True, 'font_size': '9'})  # 'align': 'hcenter'
    fmt_pbsref = workbook.add_format({'valign': 'vcenter', 'shrink': True, 'font': 'Consolas', 'font_size': '9'})
    fmt_currency = workbook.add_format({'num_format': '£#,###.00', 'align': 'center', 'valign': 'vcenter'})

    fmt_user_notes = workbook.add_format(
        {'valign': 'vcenter', 'shrink': False, 'font_size': '9', 'text_wrap': True, 'align': 'left'})
    fmt_cell_wrap = workbook.add_format(
        {'font_color': '#1F497D', 'valign': 'top', 'align': 'left', 'font': 'Consolas', 'font_size': '9',
         'text_wrap': True})
    fmt_ref_link = workbook.add_format({'valign': 'vcenter', 'shrink': True, 'font': 'Consolas', 'font_size': '9',
                                        'font_color': '#2563EB', 'underline': True})
    fmt_currency_bold = workbook.add_format({'num_format': '£#,##0.00', 'align': 'center', 'valign': 'vcenter',
                                             'bold': True, 'top': 1})
    fmt_total_label = workbook.add_format({'bold': True, 'align': 'right', 'valign': 'vcenter', 'top': 1})

    # The branding band: who made this, for what, when.
    fmt_brand = workbook.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#0F172A',
                                     'valign': 'vcenter', 'font_size': 13, 'indent': 1})
    generated = datetime.datetime.now().strftime('%d %b %Y')
    who = getattr(user, 'email', '') or getattr(user, 'username', '') or ''
    banner = f'Bomnado  ·  {project.reference}  ·  purchasing list  ·  {generated}' + (f'  ·  {who}' if who else '')
    for sheet in (sheet_purchasing, sheet_bulk):
        sheet.set_row(0, 26)
        sheet.merge_range(0, 0, 0, 14, banner, fmt_brand)
    sheet_purchasing.set_tab_color('#2563EB')
    sheet_bulk.set_tab_color('#64748B')
    workbook.set_properties({'title': f'{project.reference} purchasing', 'company': 'Bomnado',
                             'comments': 'Generated by Bomnado.'})

    # Create a counter for each part that is used (not assembly).
    root = project
    parts = Counter()
    assemblies = Counter()
    root.collect_and_count_parts(parts, assemblies)

    # For each part, produced a ranked supplier list.
    rows = [Row(part, qty) for part, qty in parts.items()]
    # Parts with no priced supplier have no lead time: they sort last, not crash the export.
    rows.sort(key=lambda r: (r.lead_of_cheapest is None, r.lead_of_cheapest or 0, r.part.reference))

    # Find the part with the largest number of suppliers.
    supplier_max = max(part.sources.count() for part, qty in parts.items()) if parts else 0
    supplier_text_columns = []
    supplier_total_columns = []

    # Write column headings
    # Bits to fill out.
    col_paid = ExcelColumn(sheet_purchasing, 0, 10.0, 'Paid Ex.', fmt_currency, fmt_heading_user)
    col_arrived = ExcelColumn(sheet_purchasing, 1, 10.0, 'Arrived', fmt_cell, fmt_heading_user)
    col_notes = ExcelColumn(sheet_purchasing, 2, 30.0, 'Invoice / Stock / Notes', fmt_user_notes, fmt_heading_user)
    # =IF(A5="STOCK", "STOCK", Q5-A5)
    gap_1 = ExcelColumn(sheet_purchasing, 3, 1, '', fmt_heading, fmt_heading)

    # Part headings.
    col_id = ExcelColumn(sheet_purchasing, 4, 5.0, 'PK', fmt_cell, fmt_heading, column_hidden=True)
    col_image = ExcelColumn(sheet_purchasing, 5, 6.43, '', fmt_cell, fmt_heading)  # 4.0
    col_qty = ExcelColumn(sheet_purchasing, 6, 8.0, 'Qty', fmt_cell_ha, fmt_heading)
    col_ref = ExcelColumn(sheet_purchasing, 7, 30.0, 'Reference', fmt_pbsref, fmt_heading)
    col_name = ExcelColumn(sheet_purchasing, 8, 24.0, 'Name', fmt_cell_sm, fmt_heading)
    col_type = ExcelColumn(sheet_purchasing, 9, 6.5, 'Type', fmt_cell_ha, fmt_heading)
    gap_2 = ExcelColumn(sheet_purchasing, 10, 1, '', fmt_heading, fmt_heading)

    # Supplier summary.
    col_lead_c = ExcelColumn(sheet_purchasing, 11, 8.0, 'Lead days', fmt_cell_ha, fmt_heading)
    col_cheapest = ExcelColumn(sheet_purchasing, 12, 12.0, 'Preference', fmt_cell_sm, fmt_heading)  # Hidden?
    col_bulk = ExcelColumn(sheet_purchasing, 13, 8.0, 'Bulk', fmt_cell_ha, fmt_heading)
    col_line = ExcelColumn(sheet_purchasing, 14, 10.0, 'Line Ex.', fmt_currency, fmt_heading)
    gap_3 = ExcelColumn(sheet_purchasing, 15, 1, '', fmt_heading, fmt_heading)

    # How the sheet is meant to be used, on the columns the buyer fills in.
    sheet_purchasing.write_comment(1, 0, 'What you actually paid, ex VAT, once ordered.')
    sheet_purchasing.write_comment(1, 1, 'When the parts arrived. Any note makes the cell green.')
    sheet_purchasing.write_comment(1, 2, 'Go down the list part by part: check the shelf first and write STOCK '
                                         'if there is enough; otherwise order from a supplier column, then put '
                                         'the invoice number here and the spend in Paid Ex.')

    # Bulk Deal Column Info
    colbd_paid = ExcelColumn(sheet_bulk, 0, 10.0, 'Paid Ex.', fmt_currency, fmt_heading_user)
    colbd_arrived = ExcelColumn(sheet_bulk, 1, 10.0, 'Arrived', fmt_cell, fmt_heading_user)
    colbd_notes = ExcelColumn(sheet_bulk, 2, 30.0, 'Invoice / Stock / Notes', fmt_user_notes, fmt_heading_user)
    gapbd_1 = ExcelColumn(sheet_bulk, 3, 1, '', fmt_heading, fmt_heading)
    colbd_id = ExcelColumn(sheet_bulk, 4, 5.0, 'PK', fmt_cell, fmt_heading, column_hidden=True)
    colbd_name = ExcelColumn(sheet_bulk, 5, 14.0, 'Deal Name', fmt_cell_sm, fmt_heading)
    gapbd_2 = ExcelColumn(sheet_bulk, 6, 1, '', fmt_heading, fmt_heading)
    colbd_lead_c = ExcelColumn(sheet_bulk, 7, 7.0, '⏰ Days', fmt_cell_ha, fmt_heading)
    colbd_cost = ExcelColumn(sheet_bulk, 8, 7.0, 'Cost Ex.', fmt_currency, fmt_heading)
    colbd_shipping = ExcelColumn(sheet_bulk, 9, 7.0, 'Shipping', fmt_currency, fmt_heading)

    # Gap 10
    offset = 16

    # Write suppliers.
    for number in range(supplier_max):
        supplier_text_columns.append(
            ExcelColumn(sheet_purchasing, offset + number, 40.0, f'Supplier Option {number + 1}', fmt_cell_wrap,
                        fmt_heading))
        offset += 1
        supplier_total_columns.append(
            ExcelColumn(sheet_purchasing, offset + number, 10.0, '', fmt_currency, fmt_heading))
    offset += 1

    deals_in_purchase = set()

    # Write each Part row.
    for idx, row in enumerate(rows):

        part = row.part
        # User fields.
        col_paid.text(idx, '')
        col_notes.text(idx, '')
        col_arrived.text(idx, '')

        # Basic fields.
        used_in = ', '.join([assy.reference for assy in set(part.find_using_assemblies()) if assy])

        col_id.number(idx, part.id)
        path = part.picture.path if part.picture else None
        col_image.image(idx, path, part)
        col_qty.number(idx, row.required)
        if base_url:
            col_ref.url(idx, f'{base_url.rstrip("/")}/part/{part.id}', part.reference, fmt_ref_link)
        else:
            col_ref.text(idx, part.reference)
        col_ref.comment(idx, f'Used in: {used_in}')
        col_name.text(idx, part.name)
        col_type.text(idx, part.nature)

        # Gaps.
        gap_1.text(idx, '')
        gap_2.text(idx, '')
        gap_3.text(idx, '')

        # Computed fields.
        if row.suppliers:

            # Populate based on cheapest suppliers.
            cheapest = row.suppliers[0]
            if row.lead_of_cheapest is not None:
                col_lead_c.number(idx, cheapest.source.lead_time)
            col_cheapest.text(idx, cheapest.source.source)
            if cheapest.cost is not None:
                col_line.number(idx, cheapest.cost)

            # Deals
            deals = []
            for deal in Deal.all_available_to_user(user):
                if part in deal.parts.all():
                    deals.append(deal.name)
                    deals_in_purchase.add(deal)
            col_bulk.text(idx, ",".join(deals))

            for n, supplier in enumerate(row.suppliers):
                if supplier.source.url:
                    supplier_text_columns[n].url(idx, supplier.source.url, supplier.text(best=cheapest))
                else:
                    supplier_text_columns[n].text(idx, supplier.text(best=cheapest))
                if supplier.total_cost is not None:
                    supplier_total_columns[n].number(idx, supplier.total_cost)
                if supplier.source.order_notes:
                    supplier_text_columns[n].comment(idx, supplier.source.order_notes)

    # Add relevant deals for this order unto the purchasing sheet as a seperate tab
    for idx, deal in enumerate(deals_in_purchase):
        colbd_paid.text(idx, '')
        colbd_arrived.text(idx, '')
        colbd_notes.text(idx, '')
        gapbd_1.text(idx, '')
        colbd_id.number(idx, deal.id)
        colbd_name.text(idx, deal.name)
        gapbd_2.text(idx, '')
        colbd_lead_c.number(idx, deal.lead_time)
        colbd_cost.number(idx, deal.rrp)
        colbd_shipping.number(idx, deal.shipping)

    # The build total, under the line column.
    if rows:
        line_letter = col_line.col_letter()
        total_row = len(rows)
        col_line.formula(total_row, f'=SUM({line_letter}3:{line_letter}{len(rows) + 2})', fmt_currency_bold)
        col_bulk.text(total_row, '', fmt_total_label)
        sheet_purchasing.write(total_row + 2, col_cheapest.col, 'Estimated parts Ex.', fmt_total_label)

    # Setup the filter, and keep the headings and the part identity on screen while scrolling.
    sheet_purchasing.autofilter(1, 0, len(rows) + 1, offset + 1)
    sheet_purchasing.freeze_panes(2, 9)
    sheet_bulk.freeze_panes(2, 0)

    # The buyer's traffic lights: amber rows are still to do, STOCK is yellow, anything paid or
    # noted goes green, and a part with no priced supplier is red where its lead time would be.
    fmt_todo = workbook.add_format({'bg_color': '#FDF6E3'})
    fmt_stock = workbook.add_format({'bg_color': '#FFEB9C'})
    fmt_done = workbook.add_format({'bg_color': '#C6EFCE'})
    fmt_missing = workbook.add_format({'bg_color': '#FFC7CE'})
    last = len(rows) + 1
    # first_row, first_col, last_row, last_col
    sheet_purchasing.conditional_format(2, 0, last, 2, {
        'type': 'formula', 'criteria': '=UPPER(TRIM($C3))="STOCK"', 'format': fmt_stock})
    sheet_purchasing.conditional_format(2, 0, last, 2, {
        'type': 'formula', 'criteria': '=OR($A3<>"", $B3<>"", TRIM($C3)<>"")', 'format': fmt_done})
    sheet_purchasing.conditional_format(2, 0, last, 2, {
        'type': 'formula', 'criteria': '=AND($A3="", $B3="", TRIM($C3)="")', 'format': fmt_todo})
    sheet_purchasing.conditional_format(2, 11, last, 11, {
        'type': 'formula', 'criteria': '=AND($L3="", $E3<>"")', 'format': fmt_missing})
    sheet_bulk.conditional_format(2, 0, len(deals_in_purchase) + 1, 2, {
        'type': 'formula', 'criteria': '=AND($A3="", $B3="", TRIM($C3)="")', 'format': fmt_todo})
    sheet_bulk.conditional_format(2, 0, len(deals_in_purchase) + 1, 2, {
        'type': 'formula', 'criteria': '=OR($A3<>"", $B3<>"", TRIM($C3)<>"")', 'format': fmt_done})

    # Final details.
    sheet_purchasing.set_default_row(hide_unused_rows=True)
    sheet_bulk.set_default_row(hide_unused_rows=True)

    sheet_purchasing.set_column(offset + 1, 16384, None, None, {'hidden': True})
    sheet_bulk.set_column(11, 16384, None, None, {'hidden': True})  # 10 Columns in bulk deals

    return workbook
