"""Render the established company invoice grid without a reference workbook."""
from backend.common.currencies import currency_symbol
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

from backend.orders.normal_pi.exports import section_borders, rich_required, fonts, _font_lock
from backend.orders.bulk_pi.layout import layout, terms, quantity_summary, annexure_section, ANNEXURE_WIDTHS, annexure_words, WIDTHS


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
                    start_row=int(anchor.find(drawing+'from/'+drawing+'row').text)
                    endpoint.find(drawing+'row').text=str(start_row+3)
                    endpoint.find(drawing+'rowOff').text=str(29*9525)
                data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            target.writestr(entry,data)
    return output.getvalue()


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
        canvas.saveState();canvas.setLineWidth(1.2)
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
    symbol=currency_symbol(doc['currency'])
    annexure_scale=usable/(sum(w*7+5 for w in ANNEXURE_WIDTHS)*.75)
    annex_regular,annex_bold=regular,bold
    for font_path,bold_path in [(Path('C:/Windows/Fonts/times.ttf'),Path('C:/Windows/Fonts/timesbd.ttf'))]:
        if font_path.is_file() and bold_path.is_file():
            with _font_lock:
                if 'PIAnnexure' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('PIAnnexure',str(font_path)))
                    pdfmetrics.registerFont(TTFont('PIAnnexureBold',str(bold_path)))
            annex_regular,annex_bold='PIAnnexure','PIAnnexureBold'
    def paragraph(cell,available_width):
        kind=cell['style'];text=cell.get('display_text',cell['text'])
        is_bold=kind in ('bold','head','bank_title','warning','final_term','title','bold_amount','bold_center','annexure_title')
        size=14 if kind=='title' else 7 if kind in ('terms','final_term') else 8
        alignment=2 if 'amount' in kind else 1 if kind in ('title','head','center','bold_center','annexure_title') else 0
        face=bold if is_bold else regular
        if cell.get('annexure'):
            face=annex_bold if is_bold else annex_regular
            size=(8 if kind=='annexure_title' else 12)*annexure_scale
            if kind=='annexure_title':face='Helvetica-Bold'
        if cell.get('total_cell'):alignment=1
        if cell.get('nowrap'):
            size=min(size,available_width/max(pdfmetrics.stringWidth(line,face,1) for line in text.splitlines()))
        style=ParagraphStyle('cell',fontName=face,fontSize=size,
            leading=size+2,alignment=alignment,textColor=colors.red if kind=='warning' else colors.black)
        if cell.get('accounting') and not cell.get('total_cell'):
            amount=format(Decimal(text),',.2f')
            # Currency codes such as AED need more room than a one-character
            # symbol. Measure both parts and fit them on the same baseline.
            gap=4
            text_width=pdfmetrics.stringWidth(symbol,face,size)+pdfmetrics.stringWidth(amount,face,size)
            money_size=size*min(1,max(available_width-gap-1,1)/max(text_width,1))
            currency_width=pdfmetrics.stringWidth(symbol,face,money_size)+gap
            left=Paragraph(escape(symbol),ParagraphStyle('currency',parent=style,alignment=0,
                fontSize=money_size,leading=money_size+2,splitLongWords=0))
            right=Paragraph(amount,ParagraphStyle('money',parent=style,alignment=2,
                fontSize=money_size,leading=money_size+2,splitLongWords=0))
            money=Table([[left,right]],colWidths=[currency_width,available_width-currency_width])
            money.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
            return money
        if cell.get('accounting'):
            text=format(Decimal(text),',.2f')
        if 'uom' in cell:text+=' '+cell['uom']
        if 'amount' in kind and not cell.get('free'):text=symbol+' '+text
        content=escape(text).replace('\n','<br/>')
        if cell.get('party') and cell.get('field')=='delivery.consignee_text':
            content=content.replace('*required','<font color="#dc2626">*required</font>')
        if kind=='bank_title':content='<u>'+content+'</u>'
        return Paragraph(content,style)
    def physical_rows(rows,section_columns):
        # ReportLab cannot split a very tall cell across merged columns. Split
        # its paragraph first, keeping the original text, style and column grid.
        result=[]
        for row in rows:
            chunks=[]
            for cell in row:
                w=sum(section_columns[cell['col']:cell['col']+cell['span']])-6
                pending=[paragraph(cell,w)];parts=[]
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
            section_weights=section.get('widths',weights)
            section_columns=[usable*w/sum(section_weights) for w in section_weights]
            rows=[];commands=[];heights=[];total_commands=[]
            for index,source in enumerate(physical_rows(section['rows'],section_columns)):
                row=['']*len(section_columns);min_height=12
                for cell in source:
                    col,span=cell['col'],cell['span'];kind=cell['style']
                    content=cell['_paragraph'];row[col]=content
                    end_row=index+cell.get('rowspan',1)-1
                    if span>1 or end_row>index:commands.append(('SPAN',(col,index),(col+span-1,end_row)))
                    if section.get('annexure'):
                        commands.append(('LINEBELOW',(col,end_row),(col+span-1,end_row),.6,colors.black))
                    if cell.get('total_cell'):
                        total_commands.extend([('BOX',(col,index),(col+span-1,end_row),.6,colors.black),
                                               ('VALIGN',(col,index),(col+span-1,end_row),'MIDDLE')])
                    if cell.get('bottom_aligned'):commands.append(('VALIGN',(col,index),(col+span-1,index),'BOTTOM'))
                    if not cell.get('open_left'):commands.append(('LINEBEFORE',(col,index),(col,index),1.2 if col==0 else .6,colors.black))
                    if not cell.get('open_right'):commands.append(('LINEAFTER',(col+span-1,index),(col+span-1,index),1.2 if col+span==len(section_columns) else .6,colors.black))
                    if kind=='warning':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.yellow))
                    if kind=='final_term':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.HexColor('#FFF2CC')))
                    if cell.get('line_top'):commands.append(('LINEABOVE',(col,index),(col+span-1,index),.6,colors.black))
                    if cell.get('line_bottom'):commands.append(('LINEBELOW',(col,index),(col+span-1,index),.6,colors.black))
                    _,h=content.wrap(sum(section_columns[col:col+span])-6,10000)
                    min_height=max(min_height,h+3)
                    if cell.get('header_metadata'):min_height=max(min_height,h+3)
                if section['name']=='parties' and index==1:min_height=max(min_height,30)
                if section['name']=='parties' and index==3:min_height=max(min_height,30)
                if section['name']=='items' and index>0:
                    min_height=max(min_height,85 if len(section['rows'])==2 else 19)
                    if len(section['rows'])==2:commands.append(('VALIGN',(0,index),(-1,index),'MIDDLE'))
                if section['name']=='annexure':
                    reference_height=22.5 if index==0 else 36 if index==1 else 40.9 if any(c.get('calculated')=='annexure_amount_in_words' for c in source) else 21.95 if any((c.get('field') or '').startswith('lines.') for c in source) else 14.1
                    min_height=max(min_height,reference_height*annexure_scale)
                    commands.append(('VALIGN',(0,index),(-1,index),'MIDDLE'))
                rows.append(row);heights.append(min_height)
            table=LongTable(rows,colWidths=section_columns,rowHeights=heights,
                repeatRows=2 if section['name']=='annexure' else 1 if section['name']=='items' else 0,splitInRow=1,hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
                ('TOPPADDING',(0,0),(-1,-1),1.5),('BOTTOMPADDING',(0,0),(-1,-1),1.5),
                *section_borders(section['name']),*commands,*total_commands,
                *([('LINEBELOW',(0,0),(-1,0),.6,colors.black)] if section['name']=='items' else []),
                *([('LINEABOVE',(0,-1),(-1,-1),.6,colors.black)] if section['name']=='bank' else []),
                *([('LINEABOVE',(0,0),(-1,0),1.2,colors.black),
                   ('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
                   ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black)] if section['name']=='annexure' else [])]))
            story.append(table)
    append_sections([section for section in model['sections'] if not section.get('annexure')])
    footer_rows=[[image('payment_options.png',usable*.46),image('signature.png',usable*.44)]]
    if model['shipping_notice']:
        footer_rows.append([Paragraph(escape(model['shipping_notice']),ParagraphStyle(
            'shipping_notice',fontName=bold,fontSize=10,leading=13,
            textColor=colors.red)),''])
    address_row=len(footer_rows)
    footer_rows.append([image('address.png',usable-12),''])
    footer_block=Table(footer_rows,colWidths=[usable*.5]*2,splitByRow=0)
    footer_block.setStyle(TableStyle([
        *([('SPAN',(0,1),(1,1)),('BACKGROUND',(0,1),(-1,1),colors.yellow)]
          if model['shipping_notice'] else []),
        ('SPAN',(0,address_row),(1,address_row)),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),6),
        ('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
        ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black),
        ('LINEABOVE',(0,0),(-1,0),.6,colors.black),
        ('LINEBELOW',(0,-1),(-1,-1),1.2,colors.black),
        ('LINEABOVE',(0,address_row),(-1,address_row),.6,colors.black),
        *([('LINEABOVE',(0,1),(-1,1),.6,colors.black)] if model['shipping_notice'] else [])]))
    story.append(footer_block)
    story.extend([NextPageTemplate('Annexure'), PageBreak()])
    append_sections([section for section in model['sections'] if section.get('annexure')])
    annexure_footer=Table([[image('payment_options.png',usable*.46),image('signature.png',usable*.44)]],
                         colWidths=[usable*.5]*2,splitByRow=0)
    annexure_footer.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
        ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black),
        ('LINEABOVE',(0,0),(-1,0),.6,colors.black),
        ('LINEBELOW',(0,-1),(-1,-1),1.2,colors.black),
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
    symbol=currency_symbol(doc['currency'])
    for kind in ('','bold','head','bank_title','warning','final_term','title','center','amount','bold_amount','terms','date_label'):
        values={'font_name':'Cambria','font_size':20 if kind=='title' else 10 if kind in ('terms','final_term') else 12,
            'font_color':'#FF0000' if kind=='warning' else '#000000','text_wrap':True,'valign':'top',
            'left':1,'right':1,'top':0,'bottom':0,'border_color':'#000000',
            'bold':kind in ('bold','head','bank_title','warning','final_term','title','bold_amount')}
        if kind=='bank_title':values['underline']=1
        if kind=='warning':values['bg_color']='#FFFF00'
        if kind=='final_term':values['bg_color']='#FFF2CC'
        if kind=='date_label':values['text_wrap']=False
        if kind in ('title','head','center'):values['align']='center'
        if 'amount' in kind:values.update(align='right',num_format='"'+symbol+'" #,##0.00')
        format_values[kind]=values
        formats[kind]=book.add_format(values)
    required_format=book.add_format({'font_color':'#dc2626'})
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
                    top=((index==0 and chunk_index==0 and section['name']!='header' and not (section['name']=='bank' and col>=8)) or (section['name']=='bank' and index==len(section['rows'])-1 and chunk_index==0)
                         or (cell.get('line_top') and chunk_index==0))
                    bottom=((index==len(section['rows'])-1 and chunk_index==max(map(len,chunks))-1 and not (section['name']=='items' and col>=8)) or cell['style']=='head'
                            or (cell.get('line_bottom') and chunk_index==len(parts)-1))
                    single_item_cell=section['name']=='items' and index>0 and len(section['rows'])==2
                    key=(cell['style'],top,bottom,cell.get('open_left',False),cell.get('open_right',False),cell.get('bottom_aligned',False),single_item_cell)
                    if key not in formats:
                        formats[key]=book.add_format({**format_values[cell['style']],'top':1 if top else 0,'bottom':1 if bottom else 0,
                            'left':0 if cell.get('open_left') else 2 if col==0 else 1,
                            'right':0 if cell.get('open_right') else 2 if end==10 else 1,
                            'valign':'bottom' if cell.get('bottom_aligned') else 'vcenter' if single_item_cell else 'top'})
                    fmt=formats[key]
                    path=cell.get('calculated') or cell.get('field')
                    if chunk_index==0 and path:coordinates[path]=xl_rowcol_to_cell(row_index,col)
                    quantity=(cell.get('field') or '').endswith('.quantity')
                    if quantity:
                        fmt=book.add_format({**format_values[cell['style']],'num_format':'0 "'+cell.get('uom','PCs')+'"',
                            'top':1 if top else 0,'bottom':1 if bottom else 0,
                            'left':0 if cell.get('open_left') else 2 if col==0 else 1,
                            'right':0 if cell.get('open_right') else 2 if end==10 else 1,
                            'valign':'vcenter' if single_item_cell else 'top'})
                    number=(cell.get('numeric') or cell['field'] in ('shipping_charges','bank_charges') or quantity or (cell['field'] or '').endswith('.unit_price')) and chunk_index==0 and not cell.get('free')
                    if cell['span']>1:sheet.merge_range(row_index,col,row_index,end,'',fmt)
                    if number:
                        decimal=Decimal(cell['text'])
                        if len(decimal.as_tuple().digits)<=15:sheet.write_number(row_index,col,float(decimal),fmt)
                        else:sheet.write_string(row_index,col,symbol+' '+cell['text'],fmt)
                    elif cell.get('party') and cell.get('field')=='delivery.consignee_text':
                        rich_required(sheet,row_index,col,value,fmt,required_format)
                    else:sheet.write_string(row_index,col,value,fmt)
                    if chunk_index==0 and (cell.get('calculated') in ('subtotal','goods_total','tax','grand_total') or (cell.get('calculated') or '').endswith('.line_total')):
                        formula_cells.append((row_index,col,fmt,cell['calculated'],cell['text']))
                    height=max(height,len(lines)*(13 if cell['style'] in ('terms','final_term') else 16))
                    if cell.get('header_metadata'):height=max(height,len(lines)*16+2)
                if section['name']=='parties' and index==1:height=max(height,45)
                if section['name']=='parties' and index==3:height=max(height,40)
                if section['name']=='items' and index>0 and len(section['rows'])==2:height=max(height,85)
                if section['name']=='header' and index==0:height=max(height,30)
                sheet.set_row(row_index,min(409,height));row_index+=1
    image('payment_options.png',row_index,0,440,90);image('signature.png',row_index,5,440,90)
    for part in range(2):
        for offset in range(4):
            top=offset==0;bottom_edge=offset==3
            lower=2 if part==1 else 1
            left=book.add_format({'left':2,'top':1 if top else 0,'bottom':lower if bottom_edge else 0,'border_color':'#000000'})
            right=book.add_format({'right':2,'top':1 if top else 0,'bottom':lower if bottom_edge else 0,'border_color':'#000000'})
            edge=book.add_format({'top':1 if top else 0,'bottom':lower if bottom_edge else 0,'border_color':'#000000'})
            sheet.set_row(row_index,20 if part==0 else 18)
            for col in range(11):sheet.write_blank(row_index,col,None,left if col==0 else right if col==10 else edge)
            row_index+=1
        if part==0:
            if model['shipping_notice']:
                notice_format=book.add_format({'font_name':'Cambria','font_size':11,'bold':True,
                'font_color':'#FF0000','bg_color':'#FFFF00','text_wrap':True,
                'valign':'vcenter','left':2,'right':2,'top':1,'bottom':1,'border_color':'#000000'})
                sheet.merge_range(row_index,0,row_index,10,model['shipping_notice'],notice_format)
                sheet.set_row(row_index,36)
                row_index+=1
            image('address.png',row_index,0,950,92)
    sheet.print_area(0,0,row_index-1,10);sheet.set_footer('&CPage &P of &N')
    annexure_start = row_index + 3
    for gap_row in range(row_index, annexure_start):
        sheet.set_row(gap_row, 15)
    sheet.set_print_scale(70)
    sheet.set_h_pagebreaks([annexure_start])
    annexure_subtotal = write_annexure(book, doc, coordinates, sheet, annexure_start)
    for row,col,fmt,path,cached in formula_cells:
        if path.endswith('.line_total'):
            prefix=path.rsplit('.',1)[0]
            formula=f'=ROUND({coordinates[prefix+".quantity"]}*{coordinates[prefix+".unit_price"]},2)'
            line=doc['totals']['lines'][int(prefix.split('.')[1])]
            if not line.get('net_unit_price'):
                formula+='-'+line.get('discount_amount','0.00')
        elif path in ('subtotal','goods_total'):
            formula='='+annexure_subtotal
            if path=='goods_total':formula+='+'+doc['totals'].get('summary_discount','0.00')
        elif path=='tax':formula=f'=ROUND(({coordinates["subtotal"]}+N({coordinates["shipping_charges"]})+{coordinates.get("bank_charges","0")})*{doc["totals"]["tax_rate"]},2)'
        else:formula=f'=ROUND({coordinates["subtotal"]}+N({coordinates["shipping_charges"]})+{coordinates.get("bank_charges","0")}+{coordinates.get("tax","0")},2)'
        sheet.write_formula(row,col,formula,fmt,float(Decimal(cached)))
    book.set_calc_mode('auto')
    book.close();return clip_workbook_header(output.getvalue())




def write_annexure(book, doc, cover_coordinates, sheet, start_row):
    """Append the six-column annexure below the cover on the same sheet."""
    import textwrap
    model = annexure_section(doc)
    # Merge existing cover columns to retain both grids' column boundaries.
    columns = [0, 1, 5, 6, 8, 9, 11]
    base = {'font_name':'Times New Roman','font_size':12,'border':1,
            'text_wrap':True,'valign':'vcenter','border_color':'#000000'}
    symbol = currency_symbol(doc['currency'])
    formats = {}
    def fmt(cell):
        kind = cell['style']
        key = (kind,cell['col'],cell.get('accounting',False),cell.get('total_cell',False),cell.get('nowrap',False),cell.get('uom'))
        if key not in formats:
            options = {**base,'left':2 if cell['col']==0 else 1,
                       'right':2 if cell['col']==5 or cell['span']==6 else 1}
            if kind in ('bold','bold_center','bold_amount','head','annexure_title'):
                options['bold']=True
            if kind in ('head','center','bold_center','annexure_title'):
                options['align']='center'
            if kind=='annexure_title':
                options.update(font_name='Arial',font_size=8,valign='bottom')
            if cell.get('accounting'):
                options.update(num_format='"'+symbol+'"* #,##0.00',align='right')
            if cell.get('total_cell'):
                options.update(align='center')
                if cell.get('accounting'):
                    options['num_format']='"'+symbol+'" #,##0.00'
            if cell.get('nowrap'):
                options.update(text_wrap=True,font_size=8)
            if cell.get('uom'):
                options['num_format'] = '0 "'+cell['uom']+'"'
            formats[key]=book.add_format(options)
        return formats[key]
    def image(name,row,col,width,height):
        data=asset(doc,name)
        with PILImage.open(data) as im:
            scale=width/im.width if name=='header.png' else min(width/im.width,height/im.height)
            dpi=im.info.get('dpi',(96,96))
        data.seek(0)
        sheet.insert_image(row,col,name,{'image_data':data,'x_scale':scale*dpi[0]/96,
            'y_scale':scale*dpi[1]/96,'object_position':1,'x_offset':6,'y_offset':4})
    header_width=sum(width*7+5 for width in WIDTHS)
    for row in range(start_row, start_row+4):
        sheet.set_row(row,24)
        for col in range(11):
            edge=book.add_format({'top':2 if row==start_row else 0,'left':2 if col==0 else 0,
                                 'right':2 if col==10 else 0})
            sheet.write_blank(row,col,None,edge)
    image('header.png',start_row,0,header_width-12,125)
    row=start_row+4
    item_rows=[]
    summary=None
    for index,source in enumerate(model['rows']):
        if source[0]['span']==6:
            sheet.merge_range(row,0,row,10,source[0]['text'],fmt(source[0]))
            sheet.set_row(row,model['row_heights'][index]);row+=1;continue
        description=next((cell for cell in source if cell.get('field','') and cell['field'].endswith('.description')),None)
        if description:
            wrapped=[part for raw in description['text'].splitlines() for part in (textwrap.wrap(raw,53) or [''])] or ['']
            chunks=[wrapped[i:i+20] for i in range(0,len(wrapped),20)]
        else:
            chunks=[None]
        for chunk_index,chunk in enumerate(chunks):
            for cell in source:
                logical_col=cell['col'];col=columns[logical_col]
                end_col=columns[logical_col+1]-1
                value=cell['text'];style=fmt(cell)
                if cell.get('rowspan',1)>1 or end_col>col:
                    sheet.merge_range(row,col,row+cell.get('rowspan',1)-1,end_col,'',style)
                if chunk_index:
                    sheet.write_string(row,col,'\n'.join(chunk) if logical_col==1 else '',style)
                    continue
                if description and logical_col==1:value='\n'.join(chunk)
                if cell.get('field') and cell['field'].endswith('.quantity'):
                    sheet.write_number(row,col,float(Decimal(value)),style)
                elif cell.get('accounting'):
                    if cell.get('field') and cell['field'].endswith('.unit_price'):
                        sheet.write_number(row,col,float(Decimal(value)),style)
                    elif cell.get('field') and cell['field'].endswith('.line_total'):
                        quantity=xl_rowcol_to_cell(row,columns[3])
                        price=xl_rowcol_to_cell(row,columns[4])
                        line=doc['totals']['lines'][int(cell['field'].split('.')[1])]
                        deduction='0.00' if line.get('net_unit_price') else line.get('discount_amount','0.00')
                        sheet.write_formula(row,col,f'=ROUND({quantity}*{price},2)-{deduction}',style,float(Decimal(value)))
                        item_rows.append(row)
                    elif cell.get('calculated')=='subtotal':
                        summary=xl_rowcol_to_cell(row,col)
                        refs=','.join(xl_rowcol_to_cell(r,columns[5]) for r in item_rows)
                        sheet.write_formula(row,col,'=ROUND(SUM('+refs+'),2)-'+doc['totals'].get('summary_discount','0.00'),style,float(Decimal(value)))
                    elif cell.get('calculated')=='grand_total':
                        sheet.write_formula(row,col,"='Proforma Invoice'!"+cover_coordinates['grand_total'],style,float(Decimal(value)))
                    else:
                        path=cell.get('calculated')
                        if path in ('shipping','tax','bank_charges'):
                            key='shipping_charges' if path=='shipping' else path
                            sheet.write_formula(row,col,"='Proforma Invoice'!"+cover_coordinates[key],style,float(Decimal(value)))
                        else:sheet.write_number(row,col,float(Decimal(value)),style)
                else:
                    sheet.write_string(row,col,value,style)
            sheet.set_row(row,max(model['row_heights'][index],len(chunk)*14 if chunk else 0))
            row+=1
    # One undivided payment/signature box, exactly beneath the final blank row.
    footer=book.add_format({'left':2,'right':2,'top':1,'bottom':2,'border_color':'#000000'})
    sheet.merge_range(row,0,row+4,10,'',footer)
    for offset in range(5):sheet.set_row(row+offset,18)
    image('payment_options.png',row,0,header_width*.5,110)
    image('signature.png',row,6,header_width*.47-10,110)
    sheet.print_area(0,0,row+4,10)
    return summary
