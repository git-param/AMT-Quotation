"""Render the established company invoice grid without a reference workbook."""
import base64
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from xml.sax.saxutils import escape

from PIL import Image as PILImage
import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, Image, LongTable, PageBreak, NextPageTemplate

from backend.orders.bulk_pi.layout import layout, terms, quantity_summary


def asset(doc,name):
    return BytesIO(base64.b64decode(doc['assets'][name]))


def clip_workbook_header(raw):
    """Crop only the drawing viewport, retaining the original embedded image.

    Excel honors image cropping in DrawingML. This matches the PDF/browser
    viewport without shrinking the logo or changing the source PNG.
    """
    drawing='{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'
    art='{http://schemas.openxmlformats.org/drawingml/2006/main}'
    output=BytesIO()
    with ZipFile(BytesIO(raw)) as source,ZipFile(output,'w') as target:
        for entry in source.infolist():
            data=source.read(entry.filename)
            if entry.filename.startswith('xl/drawings/drawing') and entry.filename.endswith('.xml'):
                root=ET.fromstring(data)
                for anchor in root:
                    pic=anchor.find(drawing+'pic')
                    name=pic.find(drawing+'nvPicPr/'+drawing+'cNvPr') if pic is not None else None
                    if name is None or name.get('descr')!='header.png':continue
                    extent=pic.find(drawing+'spPr/'+art+'xfrm/'+art+'ext')
                    full_height=int(extent.get('cy'));visible=125*9525
                    fill=pic.find(drawing+'blipFill')
                    fill.insert(1,ET.Element(art+'srcRect',b=str(round((1-visible/full_height)*100000))))
                    extent.set('cy',str(visible))
                    endpoint=anchor.find(drawing+'to')
                    endpoint.find(drawing+'row').text='3'
                    endpoint.find(drawing+'rowOff').text=str(29*9525)
                data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            target.writestr(entry,data)
    return output.getvalue()


def fonts():
    for regular,bold in ((Path('C:/Windows/Fonts/cambria.ttc'),Path('C:/Windows/Fonts/cambriab.ttf')),
            (Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'))):
        if regular.is_file() and bold.is_file():
            if 'PICompany' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('PICompany',str(regular)))
                pdfmetrics.registerFont(TTFont('PICompanyBold',str(bold)))
            return 'PICompany','PICompanyBold'
    return 'Times-Roman','Times-Bold'


def pdf(doc):
    regular,bold=fonts()
    output=BytesIO();width,height=A4;margin=12*mm;usable=width-2*margin
    model=layout(doc);weights=model['widths'];columns=[usable*w/sum(weights) for w in weights]
    def image(name,w):
        data=asset(doc,name)
        with PILImage.open(data) as im:h=w*im.height/im.width
        data.seek(0);return Image(data,width=w,height=h)
    header=image('header.png',usable)
    header_height=min(header.drawHeight,70)
    def first_page(canvas,document):
        canvas.saveState()
        clip=canvas.beginPath();clip.rect(margin,height-margin-header_height,usable,header_height)
        canvas.clipPath(clip,stroke=0)
        header.drawOn(canvas,margin,height-margin-header.drawHeight)
        canvas.restoreState()
        canvas.saveState();canvas.setLineWidth(.9)
        top=height-margin;bottom=top-header_height-2
        canvas.line(margin,top,width-margin,top)
        canvas.line(margin,top,margin,bottom);canvas.line(width-margin,top,width-margin,bottom)
        canvas.restoreState()
    bottom=margin
    document=BaseDocTemplate(output,pagesize=A4,
        title='Proforma Invoice '+doc['reference'],author=doc['company']['seller'][0])
    def frame(top,name):
        return Frame(margin,bottom,usable,top-bottom,id=name,
                     leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    document.addPageTemplates([
        PageTemplate(id='First',frames=frame(height-margin-header_height-2,'first'),onPage=first_page,autoNextPageTemplate='Later'),
        PageTemplate(id='Later',frames=frame(height-margin,'later')),
        PageTemplate(id='Annexure',frames=frame(height-margin-header_height-2,'annexure'),onPage=first_page)])
    story=[]
    symbol='₹' if doc['currency']=='INR' else '$'
    def paragraph(cell):
        kind=cell['style'];text=cell.get('display_text',cell['text'])
        is_bold=kind in ('bold','head','bank_title','warning','final_term','title','bold_amount')
        size=14 if kind=='title' else 7 if kind in ('terms','final_term') else 8
        alignment=2 if 'amount' in kind else 1 if kind in ('title','head','center') else 0
        style=ParagraphStyle('cell',fontName=bold if is_bold else regular,fontSize=size,
            leading=size+2,alignment=alignment,textColor=colors.red if kind=='warning' else colors.black)
        if 'uom' in cell:text+=' '+cell['uom']
        if 'amount' in kind and not cell.get('free'):text=symbol+' '+text
        content=escape(text).replace('\n','<br/>')
        if kind=='bank_title':content='<u>'+content+'</u>'
        return Paragraph(content,style)
    def physical_rows(rows):
        # ReportLab cannot split a very tall cell across merged columns. Split
        # its paragraph first, keeping the original text, style and column grid.
        result=[]
        for row in rows:
            chunks=[]
            for cell in row:
                w=sum(columns[cell['col']:cell['col']+cell['span']])-6
                pending=[paragraph(cell)];parts=[]
                while pending:
                    part=pending.pop(0)
                    if part.wrap(w,10000)[1]>160:
                        split=part.split(w,160)
                        if len(split)>1:pending=split+pending;continue
                    parts.append(part)
                chunks.append(parts)
            for index in range(max(map(len,chunks))):
                result.append([{**cell,'_paragraph':parts[index] if index<len(parts) else Paragraph('',ParagraphStyle('blank',fontName=regular,fontSize=8))}
                    for cell,parts in zip(row,chunks)])
        return result
    def append_sections(sections):
        for section in sections:
            rows=[];commands=[];heights=[]
            for index,source in enumerate(physical_rows(section['rows'])):
                row=['']*11;min_height=12
                for cell in source:
                    col,span=cell['col'],cell['span'];kind=cell['style']
                    content=cell['_paragraph'];row[col]=content
                    if span>1:commands.append(('SPAN',(col,index),(col+span-1,index)))
                    if cell.get('bottom_aligned'):commands.append(('VALIGN',(col,index),(col+span-1,index),'BOTTOM'))
                    if not cell.get('open_left'):commands.append(('LINEBEFORE',(col,index),(col,index),.8,colors.black))
                    if not cell.get('open_right'):commands.append(('LINEAFTER',(col+span-1,index),(col+span-1,index),.8,colors.black))
                    if kind=='warning':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.yellow))
                    if kind=='final_term':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.HexColor('#FFF2CC')))
                    if cell.get('line_top'):commands.append(('LINEABOVE',(col,index),(col+span-1,index),.8,colors.black))
                    if cell.get('line_bottom'):commands.append(('LINEBELOW',(col,index),(col+span-1,index),.8,colors.black))
                    _,h=content.wrap(sum(columns[col:col+span])-6,10000)
                    min_height=max(min_height,h+3)
                    if cell.get('header_metadata'):min_height=max(min_height,h+3)
                if section['name']=='parties' and index==1:min_height=max(min_height,30)
                if section['name']=='parties' and index==3:min_height=max(min_height,30)
                if section['name']=='items' and index>0:min_height=max(min_height,19)
                if section['name']=='annexure':
                    commands.append(('LINEBELOW',(0,index),(-1,index),.45,colors.black))
                rows.append(row);heights.append(min_height)
            table=LongTable(rows,colWidths=columns,rowHeights=heights,
                repeatRows=2 if section['name']=='annexure' else 1 if section['name']=='items' else 0,splitInRow=1,hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
                ('TOPPADDING',(0,0),(-1,-1),1.5),('BOTTOMPADDING',(0,0),(-1,-1),1.5),
                *([('LINEBEFORE',(0,0),(0,-1),.9,colors.black),('LINEAFTER',(-1,0),(-1,-1),.9,colors.black),
                   ('LINEBELOW',(0,-1),(-1,-1),.9,colors.black)] if section['name']=='header' else [('BOX',(0,0),(-1,-1),.9,colors.black)]),*commands,
                *([('LINEBELOW',(0,0),(-1,0),.8,colors.black)] if section['name']=='items' else []),
                *([('LINEABOVE',(0,-1),(-1,-1),.8,colors.black)] if section['name']=='bank' else [])]))
            story.append(table)
    append_sections([section for section in model['sections'] if not section.get('annexure')])
    footer_block=Table([
        [image('payment_options.png',usable*.46),image('signature.png',usable*.44)],
        [image('address.png',usable-12),'']],colWidths=[usable*.5]*2,splitByRow=0)
    footer_block.setStyle(TableStyle([
        ('SPAN',(0,1),(1,1)),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('BOX',(0,0),(-1,-1),.9,colors.black),
        ('LINEABOVE',(0,1),(-1,1),.9,colors.black)]))
    story.append(footer_block)
    story.extend([NextPageTemplate('Annexure'), PageBreak()])
    append_sections([section for section in model['sections'] if section.get('annexure')])
    annexure_footer=Table([[image('payment_options.png',usable*.46),image('signature.png',usable*.44)]],
                         colWidths=[usable*.5]*2,splitByRow=0)
    annexure_footer.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOX',(0,0),(-1,-1),.9,colors.black),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story.append(annexure_footer)
    document.build(story)
    return output.getvalue()


def xlsx(doc):
    output=BytesIO();book=xlsxwriter.Workbook(output,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
    sheet=book.add_worksheet('Proforma Invoice');sheet.hide_gridlines(2)
    sheet.set_paper(9);sheet.set_portrait();sheet.fit_to_pages(1,1);sheet.set_margins(.47,.47,.47,.47)
    model=layout(doc)
    for index,width in enumerate(model['widths']):sheet.set_column(index,index,width)
    formats={};format_values={}
    symbol='₹' if doc['currency']=='INR' else '$'
    for kind in ('','bold','head','bank_title','warning','final_term','title','center','amount','bold_amount','terms'):
        values={'font_name':'Cambria','font_size':20 if kind=='title' else 10 if kind in ('terms','final_term') else 12,
            'font_color':'#FF0000' if kind=='warning' else '#000000','text_wrap':True,'valign':'top',
            'left':2,'right':2,'top':0,'bottom':0,'border_color':'#000000',
            'bold':kind in ('bold','head','bank_title','warning','final_term','title','bold_amount')}
        if kind=='bank_title':values['underline']=1
        if kind=='warning':values['bg_color']='#FFFF00'
        if kind=='final_term':values['bg_color']='#FFF2CC'
        if kind in ('title','head','center'):values['align']='center'
        if 'amount' in kind:values.update(align='right',num_format='"'+symbol+'" #,##0.00')
        format_values[kind]=values
        formats[kind]=book.add_format(values)
    def image(name,row,col,w,h):
        data=asset(doc,name)
        with PILImage.open(data) as im:
            scale=w/im.width if name=='header.png' else min(w/im.width,h/im.height)
            dpi=im.info.get('dpi',(96,96))
        data.seek(0);sheet.insert_image(row,col,name,{'image_data':data,'x_scale':scale*dpi[0]/96,'y_scale':scale*dpi[1]/96,'object_position':1})
    border_left=book.add_format({'left':2,'left_color':'#000000'})
    border_right=book.add_format({'right':2,'right_color':'#000000'})
    border_top=book.add_format({'top':2,'top_color':'#000000'})
    border_corner_left=book.add_format({'left':2,'top':2,'border_color':'#000000'})
    border_corner_right=book.add_format({'right':2,'top':2,'border_color':'#000000'})
    for row in range(4):
        sheet.set_row(row,24)
        sheet.write_blank(row,0,None,border_corner_left if row==0 else border_left)
        sheet.write_blank(row,10,None,border_corner_right if row==0 else border_right)
    for col in range(1,10):sheet.write_blank(0,col,None,border_top)
    image('header.png',0,0,950,125)
    row_index=4
    coordinates={};formula_cells=[]
    import textwrap
    for section in (section for section in model['sections'] if not section.get('annexure')):
        for index,row in enumerate(section['rows']):
            # Split very long cell contents over physical rows: Excel caps row
            # height at 409pt. Every character remains printable and editable.
            chunks=[]
            for cell in row:
                value=cell.get('display_text',cell['text'])
                if 'uom' in cell:value+=' '+cell['uom']
                chars=max(4,int(sum(model['widths'][cell['col']:cell['col']+cell['span']])*.9))
                wrapped=[part for line in value.split('\n') for part in (textwrap.wrap(line,chars) or [''])]
                chunks.append([wrapped[offset:offset+20] for offset in range(0,len(wrapped),20)])
            for chunk_index in range(max(map(len,chunks))):
                height=16 if section['name']=='header' else 18
                for cell,parts in zip(row,chunks):
                    lines=parts[chunk_index] if chunk_index<len(parts) else ['']
                    value='\n'.join(lines);col=cell['col'];end=col+cell['span']-1
                    top=((index==0 and chunk_index==0 and section['name']!='header') or (section['name']=='bank' and index==len(section['rows'])-1 and chunk_index==0)
                         or (cell.get('line_top') and chunk_index==0))
                    bottom=((index==len(section['rows'])-1 and chunk_index==max(map(len,chunks))-1) or cell['style']=='head'
                            or (cell.get('line_bottom') and chunk_index==len(parts)-1))
                    key=(cell['style'],top,bottom,cell.get('open_left',False),cell.get('open_right',False),cell.get('bottom_aligned',False))
                    if key not in formats:
                        formats[key]=book.add_format({**format_values[cell['style']],'top':2 if top else 0,'bottom':2 if bottom else 0,
                            'left':0 if cell.get('open_left') else 2,'right':0 if cell.get('open_right') else 2,
                            'valign':'bottom' if cell.get('bottom_aligned') else 'top'})
                    fmt=formats[key]
                    path=cell.get('calculated') or cell.get('field')
                    if chunk_index==0 and path:coordinates[path]=xl_rowcol_to_cell(row_index,col)
                    quantity=(cell.get('field') or '').endswith('.quantity')
                    if quantity:
                        fmt=book.add_format({**format_values[cell['style']],'num_format':'0 "'+cell.get('uom','PCs')+'"','top':2 if top else 0,'bottom':2 if bottom else 0})
                    number=(cell.get('numeric') or cell['field']=='shipping_charges' or quantity or (cell['field'] or '').endswith('.unit_price')) and chunk_index==0 and not cell.get('free')
                    if cell['span']>1:sheet.merge_range(row_index,col,row_index,end,'',fmt)
                    if number:
                        decimal=Decimal(cell['text'])
                        if len(decimal.as_tuple().digits)<=15:sheet.write_number(row_index,col,float(decimal),fmt)
                        else:sheet.write_string(row_index,col,symbol+' '+cell['text'],fmt)
                    else:sheet.write_string(row_index,col,value,fmt)
                    if chunk_index==0 and (cell.get('calculated') in ('subtotal','tax','grand_total') or (cell.get('calculated') or '').endswith('.line_total')):
                        formula_cells.append((row_index,col,fmt,cell['calculated'],cell['text']))
                    height=max(height,len(lines)*(13 if cell['style'] in ('terms','final_term') else 16))
                    if cell.get('header_metadata'):height=max(height,len(lines)*16+2)
                if section['name']=='parties' and index==1:height=max(height,45)
                if section['name']=='parties' and index==3:height=max(height,40)
                if section['name']=='header' and index==0:height=max(height,30)
                sheet.set_row(row_index,min(409,height));row_index+=1
    image('payment_options.png',row_index,0,440,90);image('signature.png',row_index,5,440,90)
    for part in range(2):
        for offset in range(4):
            top=offset==0;bottom_edge=offset==3
            left=book.add_format({'left':2,'top':2 if top else 0,'bottom':2 if bottom_edge else 0,'border_color':'#000000'})
            right=book.add_format({'right':2,'top':2 if top else 0,'bottom':2 if bottom_edge else 0,'border_color':'#000000'})
            edge=book.add_format({'top':2 if top else 0,'bottom':2 if bottom_edge else 0,'border_color':'#000000'})
            sheet.set_row(row_index,20 if part==0 else 18)
            for col in range(11):sheet.write_blank(row_index,col,None,left if col==0 else right if col==10 else edge)
            row_index+=1
        if part==0:image('address.png',row_index,0,950,92)
    sheet.print_area(0,0,row_index-1,10);sheet.set_footer('&CPage &P of &N')
    annexure_subtotal = write_annexure(book, doc)
    for row,col,fmt,path,cached in formula_cells:
        if path.endswith('.line_total'):
            prefix=path.rsplit('.',1)[0]
            formula=f'=ROUND({coordinates[prefix+".quantity"]}*{coordinates[prefix+".unit_price"]},2)'
        elif path=='subtotal':
            formula=f"='Annexure-1'!G{annexure_subtotal+1}"
        elif path=='tax':formula=f'=ROUND(({coordinates["subtotal"]}+N({coordinates["shipping_charges"]}))*{doc["totals"]["tax_rate"]},2)'
        else:formula=f'=ROUND({coordinates["subtotal"]}+N({coordinates["shipping_charges"]})+{coordinates.get("tax","0")},2)'
        sheet.write_formula(row,col,formula,fmt,float(Decimal(cached)))
    book.set_calc_mode('auto')
    book.close();return clip_workbook_header(output.getvalue())


def write_annexure(book, doc):
    """An independently printable list; formulas link back to the summary PI."""
    import textwrap
    sheet = book.add_worksheet('Annexure-1')
    sheet.hide_gridlines(2)
    sheet.set_paper(9)
    sheet.set_portrait()
    sheet.fit_to_pages(1, 0)
    sheet.set_margins(.47, .47, .47, .47)
    widths = [7, 49, 13, 18, 13, 20, 23]
    for col, width in enumerate(widths):
        sheet.set_column(col, col, width)
    base = {'font_name': 'Cambria', 'font_size': 11, 'border': 1,
            'text_wrap': True, 'valign': 'top'}
    normal = book.add_format(base)
    heading = book.add_format({**base, 'bold': True, 'align': 'center'})
    symbol = '\u20b9' if doc['currency'] == 'INR' else '$'
    money = book.add_format({**base, 'num_format': '"'+symbol+'" #,##0.00', 'align': 'right'})
    final = book.add_format({**base, 'bold': True, 'num_format': '"'+symbol+'" #,##0.00'})

    def image(name, row, col, width, height):
        data = asset(doc, name)
        with PILImage.open(data) as im:
            scale = width/im.width if name == 'header.png' else min(width/im.width, height/im.height)
            dpi = im.info.get('dpi', (96, 96))
        data.seek(0)
        sheet.insert_image(row, col, name, {'image_data': data,
            'x_scale': scale*dpi[0]/96, 'y_scale': scale*dpi[1]/96, 'object_position': 1})

    for row in range(4):
        sheet.set_row(row, 24)
    image('header.png', 0, 0, 950, 125)
    sheet.merge_range(4, 0, 4, 6, 'Annexure-1 | '+doc['reference'], heading)
    sheet.set_row(4, 26)
    for col, title in enumerate(['Sr No.', 'Item Description', 'HSN Code', 'Condition',
                                  'Qty / UOM', 'Unit Price ('+doc['currency']+')',
                                  'Total Price ('+doc['currency']+')']):
        sheet.write_string(5, col, title, heading)
    sheet.set_row(5, 32)
    sheet.repeat_rows(0, 5)
    row = 6
    amount_cells = []
    for index, line in enumerate(doc['totals']['lines']):
        chunks = [part for raw in line['description'].splitlines()
                  for part in (textwrap.wrap(raw, 45) or [''])] or ['']
        start = row
        for offset in range(0, len(chunks), 15):
            part = chunks[offset:offset+15]
            for col in range(7):
                sheet.write_blank(row, col, None, normal)
            sheet.write_string(row, 1, '\n'.join(part), normal)
            sheet.set_row(row, max(26, len(part)*14))
            row += 1
        qty = book.add_format({**base, 'num_format': '0 "'+line['uom']+'"'})
        sheet.write_number(start, 0, index+1, normal)
        sheet.write_string(start, 2, line['hsn_code'], normal)
        sheet.write_string(start, 3, line['item_condition'], normal)
        sheet.write_number(start, 4, float(Decimal(line['quantity'])), qty)
        sheet.write_number(start, 5, float(Decimal(line['unit_price'])), money)
        sheet.write_formula(start, 6, f'=ROUND(E{start+1}*F{start+1},2)', money,
                            float(Decimal(line['line_total'])))
        amount_cells.append('G'+str(start+1))
    subtotal = row
    sheet.merge_range(row, 0, row, 4, 'Total quantity: '+quantity_summary(doc), normal)
    sheet.write_string(row, 5, 'Subtotal', heading)
    sheet.write_formula(row, 6, '=ROUND(SUM('+','.join(amount_cells)+'),2)', money,
                        float(Decimal(doc['totals']['subtotal'])))
    row += 1
    shipping = row
    sheet.merge_range(row, 0, row, 4, '', normal)
    sheet.write_string(row, 5, 'Shipping', heading)
    sheet.write_number(row, 6, float(Decimal(doc['totals']['shipping'])), money)
    row += 1
    tax_cell = '0'
    if Decimal(doc['totals']['tax_rate']):
        tax_cell = 'G'+str(row+1)
        sheet.merge_range(row, 0, row, 4, '', normal)
        sheet.write_string(row, 5, f'GST {Decimal(doc["totals"]["tax_rate"])*100:g}%', heading)
        sheet.write_formula(row, 6, f'=ROUND((G{subtotal+1}+G{shipping+1})*{doc["totals"]["tax_rate"]},2)',
                            money, float(Decimal(doc['totals']['tax'])))
        row += 1
    sheet.merge_range(row, 0, row, 4, 'Amount in words: '+doc['totals']['amount_in_words'], heading)
    sheet.write_string(row, 5, 'Grand Total', heading)
    sheet.write_formula(row, 6, f'=ROUND(G{subtotal+1}+G{shipping+1}+{tax_cell},2)', final,
                        float(Decimal(doc['totals']['grand_total'])))
    sheet.set_row(row, 42)
    row += 1
    image('payment_options.png', row, 0, 440, 90)
    image('signature.png', row, 4, 440, 90)
    for offset in range(5):
        sheet.set_row(row+offset, 20)
    sheet.print_area(0, 0, row+4, 6)
    sheet.set_footer('&CAnnexure-1 | Page &P of &N')
    return subtotal
