"""Render the established company invoice grid without a reference workbook."""
import base64
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, LongTable

from backend.orders.pi_layout import layout,terms


def asset(doc,name):
    return BytesIO(base64.b64decode(doc['assets'][name]))


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
    header=image('header.png',usable);footer=image('address.png',usable)
    def page(canvas,document):
        canvas.saveState();header.drawOn(canvas,margin,height-margin-header.drawHeight)
        footer.drawOn(canvas,margin,18)
        canvas.setFont(regular,6);canvas.drawRightString(width-margin,9,f'{doc["reference"]} | Page {document.page}')
        canvas.restoreState()
    document=SimpleDocTemplate(output,pagesize=A4,leftMargin=margin,rightMargin=margin,
        topMargin=margin+header.drawHeight+4,bottomMargin=max(65,footer.drawHeight+28),
        title='Proforma Invoice '+doc['reference'],author=doc['company']['seller'][0])
    story=[]
    symbol='₹' if doc['currency']=='INR' else '$'
    for section in model['sections']:
        rows=[];commands=[];heights=[]
        for index,source in enumerate(section['rows']):
            row=['']*11;min_height=12
            for cell in source:
                col,span=cell['col'],cell['span'];kind=cell['style'];text=cell['text']
                is_bold=kind in ('bold','head','bank_title','warning','final_term','title','bold_amount')
                size=14 if kind=='title' else 7 if kind in ('terms','final_term') else 8
                alignment=2 if 'amount' in kind else 1 if kind in ('title','head','center') else 0
                style=ParagraphStyle('cell',fontName=bold if is_bold else regular,fontSize=size,
                    leading=size+2,alignment=alignment,textColor=colors.red if kind=='warning' else colors.black)
                if cell.get('sku'):text=cell['sku']+'\n'+text
                if 'uom' in cell:text+=' '+cell['uom']
                if 'amount' in kind:text=symbol+' '+text
                content=escape(text).replace('\n','<br/>')
                if kind=='bank_title':content='<u>'+content+'</u>'
                paragraph=Paragraph(content,style);row[col]=paragraph
                if span>1:commands.append(('SPAN',(col,index),(col+span-1,index)))
                commands.extend([('LINEBEFORE',(col,index),(col,index),.45,colors.black),
                    ('LINEAFTER',(col+span-1,index),(col+span-1,index),.45,colors.black)])
                if kind=='warning':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.yellow))
                if kind=='final_term':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.HexColor('#FFF2CC')))
                _,h=paragraph.wrap(sum(columns[col:col+span])-6,10000)
                min_height=max(min_height,h+4)
            if section['name']=='parties' and index==1:min_height=max(min_height,62)
            if section['name']=='parties' and index==3:min_height=max(min_height,46)
            if section['name']=='items' and index>0:min_height=max(min_height,19)
            rows.append(row);heights.append(min_height)
        table=LongTable(rows,colWidths=columns,rowHeights=heights,
            repeatRows=1 if section['name']=='items' else 0,splitInRow=1,hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
            ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),
            ('LINEBELOW',(0,0),(-1,-1),.2,colors.HexColor('#D0D0D0')),
            ('BOX',(0,0),(-1,-1),.5,colors.black),*commands]))
        story.append(table)
    signatures=Table([[image('payment_options.png',usable*.48),image('signature.png',usable*.42)]],colWidths=[usable*.55,usable*.45])
    signatures.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    story.extend([Spacer(1,6),signatures])
    document.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()


def xlsx(doc):
    output=BytesIO();book=xlsxwriter.Workbook(output,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
    sheet=book.add_worksheet('Proforma Invoice');sheet.hide_gridlines(2)
    sheet.set_paper(9);sheet.set_portrait();sheet.fit_to_pages(1,0);sheet.set_margins(.47,.47,.47,.47)
    model=layout(doc)
    for index,width in enumerate(model['widths']):sheet.set_column(index,index,width)
    formats={}
    symbol='₹' if doc['currency']=='INR' else '$'
    for kind in ('','bold','head','bank_title','warning','final_term','title','center','amount','bold_amount','terms'):
        values={'font_name':'Cambria','font_size':20 if kind=='title' else 10 if kind in ('terms','final_term') else 12,
            'font_color':'#FF0000' if kind=='warning' else '#000000','text_wrap':True,'valign':'top',
            'left':1,'right':1,'top':1,'bottom':1,'top_color':'#D0D0D0','bottom_color':'#D0D0D0',
            'bold':kind in ('bold','head','bank_title','warning','final_term','title','bold_amount')}
        if kind=='bank_title':values['underline']=1
        if kind=='warning':values['bg_color']='#FFFF00'
        if kind=='final_term':values['bg_color']='#FFF2CC'
        if kind in ('title','head','center'):values['align']='center'
        if 'amount' in kind:values.update(align='right',num_format='"'+symbol+'" #,##0.00')
        formats[kind]=book.add_format(values)
    def image(name,row,col,w,h):
        data=asset(doc,name)
        with PILImage.open(data) as im:
            scale=min(w/im.width,h/im.height);dpi=im.info.get('dpi',(96,96))
        data.seek(0);sheet.insert_image(row,col,name,{'image_data':data,'x_scale':scale*dpi[0]/96,'y_scale':scale*dpi[1]/96,'object_position':1})
    for row in range(5):sheet.set_row(row,24)
    image('header.png',0,0,950,170)
    row_index=5
    import textwrap
    for section in model['sections']:
        for index,row in enumerate(section['rows']):
            # Split very long cell contents over physical rows: Excel caps row
            # height at 409pt. Every character remains printable and editable.
            chunks=[]
            for cell in row:
                value=cell['text']
                if cell.get('sku'):value=cell['sku']+'\n'+value
                if 'uom' in cell:value+=' '+cell['uom']
                chars=max(4,int(sum(model['widths'][cell['col']:cell['col']+cell['span']])*.9))
                wrapped=[part for line in value.split('\n') for part in (textwrap.wrap(line,chars) or [''])]
                chunks.append([wrapped[offset:offset+20] for offset in range(0,len(wrapped),20)])
            for chunk_index in range(max(map(len,chunks))):
                height=18
                for cell,parts in zip(row,chunks):
                    lines=parts[chunk_index] if chunk_index<len(parts) else ['']
                    value='\n'.join(lines);col=cell['col'];end=col+cell['span']-1;fmt=formats[cell['style']]
                    number=(cell.get('numeric') or cell['field']=='shipping_charges' or (cell['field'] or '').endswith('.unit_price')) and chunk_index==0
                    if cell['span']>1:sheet.merge_range(row_index,col,row_index,end,'',fmt)
                    if number:
                        decimal=Decimal(cell['text'])
                        if len(decimal.as_tuple().digits)<=15:sheet.write_number(row_index,col,float(decimal),fmt)
                        else:sheet.write_string(row_index,col,symbol+' '+cell['text'],fmt)
                    else:sheet.write_string(row_index,col,value,fmt)
                    height=max(height,len(lines)*(13 if cell['style'] in ('terms','final_term') else 16))
                if section['name']=='parties' and index==1:height=max(height,90)
                if section['name']=='parties' and index==3:height=max(height,65)
                if section['name']=='header' and index==0:height=max(height,30)
                sheet.set_row(row_index,min(409,height));row_index+=1
    image('payment_options.png',row_index,0,440,90);image('signature.png',row_index,7,330,100)
    for _ in range(5):sheet.set_row(row_index,22);row_index+=1
    image('address.png',row_index,0,950,100);row_index+=4
    sheet.print_area(0,0,row_index,10);sheet.repeat_rows(0,5);sheet.set_footer('&CPage &P of &N')
    book.close();return output.getvalue()
