"""Render the established company invoice grid without a reference workbook."""
from backend.common.currencies import currency_symbol
import base64
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from threading import Lock
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
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, Image, LongTable, KeepInFrame

from backend.orders.normal_pi.layout import layout,terms

_font_lock = Lock()


class FullWidthKeepInFrame(KeepInFrame):
    """Fit a short invoice vertically without pulling its outer rule inward."""

    def drawOn(self, canv, x, y, _sW=0):
        scale = getattr(self, '_scale', 1.0)
        if scale == 1.0:
            return super().drawOn(canv, x, y, _sW=_sW)
        canv.saveState()
        try:
            canv.translate(x, y)
            canv.scale(1.0, 1.0 / scale)
            super(KeepInFrame, self).drawOn(canv, 0, 0, _sW=_sW, scale=scale)
        finally:
            canv.restoreState()


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
            with _font_lock:
                if 'PICompany' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('PICompany',str(regular)))
                    pdfmetrics.registerFont(TTFont('PICompanyBold',str(bold)))
            return 'PICompany','PICompanyBold'
    return 'Times-Roman','Times-Bold'


def section_borders(name):
    """Keep the summary open above its first amount and between labels and amounts."""
    if name not in ('header', 'items', 'bank'):
        return [('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
                ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black),
                ('LINEABOVE',(0,0),(-1,0),.6,colors.black),
                ('LINEBELOW',(0,-1),(-1,-1),.6,colors.black)]
    edges = [('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
             ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black)]
    edges.append(('LINEBELOW',(0,-1),(7 if name == 'items' else -1,-1),.6,colors.black))
    if name == 'items':
        edges.append(('LINEABOVE',(0,0),(-1,0),.6,colors.black))
    elif name == 'bank':
        edges.append(('LINEABOVE',(0,0),(7,0),.6,colors.black))
    return edges


def rich_required(sheet,row,col,value,cell_format,required_format):
    """Write required-field prompts with their marker in red in Excel."""
    parts=value.split('*required')
    if len(parts)==1:
        sheet.write_string(row,col,value,cell_format)
        return
    rich=[]
    for index,part in enumerate(parts):
        if part:rich.append(part)
        if index<len(parts)-1:rich.extend((required_format,'*required'))
    sheet.write_rich_string(row,col,*rich,cell_format)


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
        PageTemplate(id='Later',frames=frame(height-margin,'later'))])
    story=[]
    item_table=None
    symbol=currency_symbol(doc['currency'])
    def paragraph(cell,available_width):
        kind=cell['style'];text=cell.get('display_text',cell['text'])
        is_bold=kind in ('bold','head','bank_title','warning','final_term','title','bold_amount')
        size=14 if kind=='title' else 7 if kind in ('terms','final_term') else 8
        alignment=2 if 'amount' in kind else 1 if kind in ('title','head','center') else 0
        style=ParagraphStyle('cell',fontName=bold if is_bold else regular,fontSize=size,
            leading=size+2,alignment=alignment,textColor=colors.red if kind=='warning' else colors.black)
        if 'amount' in kind and not cell.get('free'):
            amount=format(Decimal(cell['text']),',.2f')
            face=bold if is_bold else regular
            gap=4
            text_width=pdfmetrics.stringWidth(symbol,face,size)+pdfmetrics.stringWidth(amount,face,size)
            money_size=size*min(1,max(available_width-gap-1,1)/max(text_width,1))
            symbol_width=pdfmetrics.stringWidth(symbol,face,money_size)+gap
            left=Paragraph(escape(symbol),ParagraphStyle('currency',parent=style,
                alignment=0,fontSize=money_size,leading=money_size+2,splitLongWords=0))
            right=Paragraph(escape(amount),ParagraphStyle('money',parent=style,
                alignment=2,fontSize=money_size,leading=money_size+2,splitLongWords=0))
            money=Table([[left,right]],colWidths=[symbol_width,available_width-symbol_width])
            money.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),
                ('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),
                ('BOTTOMPADDING',(0,0),(-1,-1),0)]))
            return money
        if 'uom' in cell:text+=' '+cell['uom']
        content=escape(text).replace('\n','<br/>')
        if cell.get('party') and cell.get('field')=='delivery.consignee_text':
            content=content.replace('*required','<font color="#dc2626">*required</font>')
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
    for section in model['sections']:
        rows=[];commands=[];heights=[]
        for index,source in enumerate(physical_rows(section['rows'])):
            row=['']*11;min_height=12
            for cell in source:
                col,span=cell['col'],cell['span'];kind=cell['style']
                content=cell['_paragraph'];row[col]=content
                if span>1:commands.append(('SPAN',(col,index),(col+span-1,index)))
                if cell.get('bottom_aligned'):commands.append(('VALIGN',(col,index),(col+span-1,index),'BOTTOM'))
                if not cell.get('open_left'):commands.append(('LINEBEFORE',(col,index),(col,index),1.2 if col==0 else .6,colors.black))
                if not cell.get('open_right'):commands.append(('LINEAFTER',(col+span-1,index),(col+span-1,index),1.2 if col+span==11 else .6,colors.black))
                if kind=='warning':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.yellow))
                if kind=='final_term':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.HexColor('#FFF2CC')))
                if cell.get('line_top'):commands.append(('LINEABOVE',(col,index),(col+span-1,index),.6,colors.black))
                if cell.get('line_bottom'):commands.append(('LINEBELOW',(col,index),(col+span-1,index),.6,colors.black))
                _,h=content.wrap(sum(columns[col:col+span])-6,10000)
                min_height=max(min_height,h+3)
                if cell.get('header_metadata'):min_height=max(min_height,h+3)
            if section['name']=='parties' and index==1:min_height=max(min_height,30)
            if section['name']=='parties' and index==3:min_height=max(min_height,30)
            if section['name']=='items' and index>0:
                single_sku=len(doc['totals']['lines'])==1
                min_height=max(min_height,(22 if index==1 else 63 if index==2 else 19) if single_sku else 19)
            rows.append(row);heights.append(min_height)
        table=LongTable(rows,colWidths=columns,rowHeights=heights,
            repeatRows=1 if section['name']=='items' else 0,splitInRow=1,hAlign='LEFT')
        table_style=TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),3),
            ('RIGHTPADDING',(0,0),(-1,-1),3),
            ('TOPPADDING',(0,0),(-1,-1),1.5),
            ('BOTTOMPADDING',(0,0),(-1,-1),1.5),
            *section_borders(section['name']),*commands,
            *([('LINEBELOW',(0,0),(-1,0),.6,colors.black)] if section['name']=='items' else []),
            *([('LINEABOVE',(0,-1),(-1,-1),.6,colors.black)] if section['name']=='bank' else [])])
        table.setStyle(table_style)
        if section['name']=='items' and doc.get('pi_format','normal')=='normal' and len(doc['totals']['lines'])<=4:
            item_table=(len(story),rows,heights,table_style)
        story.append(table)
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
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
        ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black),
        ('LINEABOVE',(0,0),(-1,0),.6,colors.black),
        ('LINEBELOW',(0,-1),(-1,-1),1.2,colors.black),
        ('LINEABOVE',(0,address_row),(-1,address_row),.6,colors.black),
        *([('LINEABOVE',(0,1),(-1,1),.6,colors.black)] if model['shipping_notice'] else [])]))
    story.append(footer_block)
    if item_table:
        table_index,rows,heights,table_style=item_table
        first_frame_height=height-2*margin-header_height-2
        used_height=sum(flowable.wrap(usable,first_frame_height)[1] for flowable in story)
        # Let the products use spare page space while retaining a little room
        # above the bottom margin for ReportLab's frame rounding.
        spare_height=max(0,min(120,first_frame_height-used_height-12))
        product_rows=len(heights)-1
        if spare_height and product_rows:
            roomier=heights.copy()
            if len(doc['totals']['lines'])==1:
                roomier[2]+=min(spare_height,30)
            else:
                extra=min(spare_height/product_rows,30)
                roomier[1:]=[row_height+extra for row_height in heights[1:]]
            table=LongTable(rows,colWidths=columns,rowHeights=roomier,
                repeatRows=1,splitInRow=1,hAlign='LEFT')
            table.setStyle(table_style)
            story[table_index]=table
    if item_table:
        first_frame_height=height-2*margin-header_height-2
        used_height=sum(flowable.wrap(usable,first_frame_height)[1] for flowable in story)
        # Keep ordinary one-to-four item invoices together; retain pagination
        # for unusually large text rather than making it unreadably small.
        if first_frame_height-8 < used_height <= first_frame_height*1.4:
            story=[FullWidthKeepInFrame(usable,first_frame_height-4,story,mode='shrink',hAlign='LEFT',vAlign='TOP')]
    document.build(story)
    return output.getvalue()


def xlsx(doc):
    output=BytesIO();book=xlsxwriter.Workbook(output,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
    sheet=book.add_worksheet('Proforma Invoice');sheet.hide_gridlines(2)
    sheet.set_paper(9);sheet.set_portrait();sheet.fit_to_pages(1,1 if len(doc['totals']['lines'])<=4 else 0);sheet.set_margins(.47,.47,.47,.47)
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
        if 'amount' in kind:values.update(align='right',num_format='"'+symbol+'"* #,##0.00')
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
    for section in model['sections']:
        for index,row in enumerate(section['rows']):
            # Split very long cell contents over physical rows: Excel caps row
            # height at 409pt. Every character remains printable and editable.
            chunks=[]
            for cell in row:
                value=cell.get('display_text',cell['text'])
                if 'uom' in cell:value+=' '+cell['uom']
                chars=max(4,int(sum(model['widths'][cell['col']:cell['col']+cell['span']])*.9))
                wrapped=[part for line in value.split('\n') for part in
                         (([line] if cell.get('aria')=='Proforma Invoice Date' or
                           value=='Proforma Invoice Date:' else textwrap.wrap(line,chars)) or [''])]
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
                    left=0 if cell.get('open_left') else 2 if col==0 else 1
                    right=0 if cell.get('open_right') else 2 if end==10 else 1
                    key=(cell['style'],top,bottom,left,right,cell.get('bottom_aligned',False))
                    if key not in formats:
                        formats[key]=book.add_format({**format_values[cell['style']],'top':1 if top else 0,'bottom':1 if bottom else 0,
                            'left':left,'right':right,
                            'valign':'bottom' if cell.get('bottom_aligned') else 'top'})
                    fmt=formats[key]
                    path=cell.get('calculated') or cell.get('field')
                    if chunk_index==0 and path:coordinates[path]=xl_rowcol_to_cell(row_index,col)
                    quantity=(cell.get('field') or '').endswith('.quantity')
                    if quantity:
                        fmt=book.add_format({**format_values[cell['style']],'num_format':'0 "'+cell.get('uom','PCs')+'"','top':1 if top else 0,'bottom':1 if bottom else 0,'left':left,'right':right})
                    number=(cell.get('numeric') or cell['field']=='shipping_charges' or quantity or (cell['field'] or '').endswith('.unit_price')) and chunk_index==0 and not cell.get('free')
                    if cell['span']>1:sheet.merge_range(row_index,col,row_index,end,'',fmt)
                    if number:
                        decimal=Decimal(cell['text'])
                        if len(decimal.as_tuple().digits)<=15:sheet.write_number(row_index,col,float(decimal),fmt)
                        else:sheet.write_string(row_index,col,symbol+' '+cell['text'],fmt)
                    elif cell.get('party') and cell.get('field')=='delivery.consignee_text':
                        rich_required(sheet,row_index,col,value,fmt,required_format)
                    else:sheet.write_string(row_index,col,value,fmt)
                    if chunk_index==0 and (cell.get('calculated') in ('goods_total','subtotal','tax','grand_total') or (cell.get('calculated') or '').endswith('.line_total')):
                        formula_cells.append((row_index,col,fmt,cell['calculated'],cell['text']))
                    height=max(height,len(lines)*(13 if cell['style'] in ('terms','final_term') else 16))
                    if cell.get('header_metadata'):height=max(height,len(lines)*16+2)
                if section['name']=='parties' and index==1:height=max(height,45)
                if section['name']=='parties' and index==3:height=max(height,40)
                if section['name']=='items' and index>0:
                    height=max(height,(22 if index==1 else 63 if index==2 else 18) if len(doc['totals']['lines'])==1 else 36 if len(doc['totals']['lines'])<=4 else 18)
                if section['name']=='header' and index==0:height=max(height,30)
                sheet.set_row(row_index,min(409,height));row_index+=1
    image('payment_options.png',row_index,0,440,90);image('signature.png',row_index,5,440,90)
    for part in range(2):
        for offset in range(4):
            top=offset==0;bottom_edge=offset==3
            left=book.add_format({'left':2,'top':1 if top else 0,'bottom':2 if bottom_edge else 0,'border_color':'#000000'})
            right=book.add_format({'right':2,'top':1 if top else 0,'bottom':2 if bottom_edge else 0,'border_color':'#000000'})
            edge=book.add_format({'top':1 if top else 0,'bottom':2 if bottom_edge else 0,'border_color':'#000000'})
            sheet.set_row(row_index,20 if part==0 else 18)
            for col in range(11):sheet.write_blank(row_index,col,None,left if col==0 else right if col==10 else edge)
            row_index+=1
        if part==0:
            if model['shipping_notice']:
                notice_format=book.add_format({'font_name':'Cambria','font_size':10,'bold':True,
                'font_color':'#FF0000','bg_color':'#FFFF00','text_wrap':True,
                'valign':'vcenter','left':2,'right':2,'top':1,'bottom':1,'border_color':'#000000'})
                sheet.merge_range(row_index,0,row_index,10,model['shipping_notice'],notice_format)
                sheet.set_row(row_index,36)
                row_index+=1
            image('address.png',row_index,0,950,92)
    sheet.print_area(0,0,row_index-1,10);sheet.set_footer('&CPage &P of &N')
    for row,col,fmt,path,cached in formula_cells:
        if path.endswith('.line_total'):
            prefix=path.rsplit('.',1)[0]
            formula=f'=ROUND({coordinates[prefix+".quantity"]}*{coordinates[prefix+".unit_price"]},2)'
            line=doc['totals']['lines'][int(prefix.split('.')[1])]
            if not line.get('net_unit_price'):
                formula+='-'+line.get('discount_amount','0.00')
        elif path in ('subtotal','goods_total'):
            refs=','.join(value for key,value in coordinates.items() if key.endswith('.line_total')) or '0'
            formula=f'=ROUND(SUM({refs}),2)'
            if path=='subtotal':formula+='-'+doc['totals'].get('summary_discount','0.00')
        elif path=='tax':formula=f'=ROUND(({coordinates["subtotal"]}+N({coordinates["shipping_charges"]}))*{doc["totals"]["tax_rate"]},2)'
        else:formula=f'=ROUND({coordinates["subtotal"]}+N({coordinates["shipping_charges"]})+{coordinates.get("tax","0")},2)'
        sheet.write_formula(row,col,formula,fmt,float(Decimal(cached)))
    book.set_calc_mode('auto')
    book.close();return clip_workbook_header(output.getvalue())
