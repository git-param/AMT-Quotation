"""Render the established company invoice grid without a reference workbook."""
from backend.common.currencies import currency_symbol
import base64
import math
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from PIL import Image as PILImage, ImageDraw, ImageFont
import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, Image, LongTable, KeepInFrame, Flowable

from backend.orders.normal_pi.layout import layout,terms
from backend.orders.company_profile import COMPANY_PI_PROFILE
from backend.orders.terms_config import RETURN_POLICY_LABEL, RETURN_POLICY_URL

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


def merge_export_words(model):
    """Combine the wording label and value while keeping adjacent totals fixed."""
    for section in model['sections']:
        for row in section['rows']:
            for index,cell in enumerate(row):
                if cell.get('calculated') in ('amount_in_words','annexure_amount_in_words') and index:
                    label=row[index-1]
                    combined={**cell,'col':label['col'],
                              'span':cell['col']+cell['span']-label['col'],
                              'text':'Amount in words: '+cell['text']}
                    combined['display_text']=combined['text']
                    combined.pop('nowrap',None)
                    row[index-1:index+1]=[combined]
                    break
    return model


def asset(doc,name):
    return BytesIO(base64.b64decode(doc['assets'][name]))


class OfficeLocationPin(Flowable):
    """Match the office pin silhouette used in the editable PI preview."""
    def __init__(self):
        super().__init__()
        self.width=27*.75
        self.height=31*.75
        self.hAlign='CENTER'

    def draw(self):
        red=colors.HexColor('#852020')
        self.canv.setFillColor(red)
        scale_x=self.width/36
        scale_y=self.height/42
        def point(x,y):
            return x*scale_x,(42-y)*scale_y
        path=self.canv.beginPath()
        path.moveTo(*point(18,1.5))
        path.curveTo(*point(8.9,1.5),*point(2,8.4),*point(2,17.1))
        path.curveTo(*point(2,28.2),*point(18,40.5),*point(18,40.5))
        path.curveTo(*point(18,40.5),*point(34,28.2),*point(34,17.1))
        path.curveTo(*point(34,8.4),*point(27.1,1.5),*point(18,1.5))
        path.close()
        self.canv.drawPath(path,stroke=0,fill=1)
        self.canv.setFillColor(colors.white)
        self.canv.circle(*point(18,16.8),6.1*(scale_x+scale_y)/2,stroke=0,fill=1)


class OfficeAddressTable(Table):
    """Three address cells styled like the reference office-address strip."""
    divider_height=40*.75
    minimum_height=140*.75

    def wrap(self, availWidth, availHeight):
        width,height=super().wrap(availWidth,availHeight)
        if height < self.minimum_height:
            extra=self.minimum_height-height
            for cell in self._cellvalues[0]:
                if isinstance(cell,(list,tuple)) and cell and isinstance(cell[-1],Spacer):
                    cell[-1].height=extra
            width,height=super().wrap(availWidth,availHeight)
        return width,height

    def drawOn(self, canv, x, y, _sW=0):
        # A KeepInFrame can offer extra width while drawing its children.
        # Keep the footer anchored to the invoice frame instead of centering
        # it again inside that larger temporary width.
        return super().drawOn(canv,x,y,_sW=0)

    def draw(self):
        super().draw()
        self.canv.saveState()
        try:
            self.canv.setFillColor(colors.HexColor('#852020'))
            top_offset=(8+(140-16-100)/2+39)*.75
            top_y=self._height-top_offset
            bottom_y=max(0,top_y-self.divider_height)
            for x in (self._width*.3125,self._width*.6875):
                # A narrow lens has pointed ends and a wider middle, matching
                # the reference separator rather than a constant-width stroke.
                height=top_y-bottom_y
                half_width=1.5*.75
                tilt=math.tan(math.radians(1))*height
                path=self.canv.beginPath()
                path.moveTo(x,bottom_y)
                path.curveTo(x-half_width,bottom_y+height*.25,
                             x+tilt-half_width,bottom_y+height*.75,x+tilt,top_y)
                path.curveTo(x+tilt+half_width,bottom_y+height*.75,
                             x+half_width,bottom_y+height*.25,x,bottom_y)
                path.close()
                self.canv.drawPath(path,stroke=0,fill=1)
        finally:
            self.canv.restoreState()


def legal_notice_pdf(text, usable, style):
    """Center the notice within the invoice width, including inside KeepInFrame."""
    table=Table([[Paragraph(escape(text).replace('\n','<br/>'),style)]],
                colWidths=[usable],hAlign='LEFT')
    table.setStyle(TableStyle([
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    return table


def office_address_font():
    for path in (Path('C:/Windows/Fonts/arialbd.ttf'),
                 Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')):
        if path.is_file():
            with _font_lock:
                if 'PIOfficeBold' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('PIOfficeBold',str(path)))
            return 'PIOfficeBold'
    return 'Helvetica-Bold'


def office_address_pdf(addresses, usable):
    style = ParagraphStyle('office_address', fontName=office_address_font(), fontSize=7.5,
                           leading=8.1, alignment=1, textColor=colors.HexColor('#171717'),
                           wordWrap='CJK')
    cells = [[OfficeLocationPin(), Spacer(1, 6.75), Paragraph(escape(address).replace('\n', '<br/>'), style), Spacer(1, 0)]
             for address in (addresses or [])[:3]]
    while len(cells) < 3:
        cells.append([Spacer(1,0)])
    # Use the complete available width so the addresses and dividers share
    # the reference's evenly spaced 12.5%, 50%, and 87.5% address centers.
    widths=[usable*.25,usable*.125,usable*.25,usable*.125,usable*.25]
    cells=[cells[0],[Spacer(1,0)],cells[1],[Spacer(1,0)],cells[2]]
    table = OfficeAddressTable([cells], colWidths=widths, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 8*.75+9), ('BOTTOMPADDING', (0, 0), (-1, -1), 8*.75),
    ]))
    return table


def office_address_png(addresses, width_px, height_px=140):
    """Build the Excel office strip, using address.png for its exact default design."""
    scale=2
    width=max(3,int(width_px))*scale;height=max(1,int(height_px))*scale
    default_addresses=COMPANY_PI_PROFILE['office_addresses']
    if list(addresses or [])[:3]==default_addresses and len(list(addresses or []))==3:
        reference=Path(__file__).resolve().parents[3]/'assets'/'PI-img'/'address.png'
        if reference.is_file():
            with PILImage.open(reference) as source:
                target_height=max(1,round(width*source.height/source.width))
                image=source.convert('RGBA').resize((width,target_height),PILImage.Resampling.LANCZOS)
            output=BytesIO();image.save(output,format='PNG');output.seek(0)
            return output
    canvas=PILImage.new('RGB',(width,height),'white');draw=ImageDraw.Draw(canvas)
    font_path=Path('C:/Windows/Fonts/arialbd.ttf')
    font_px=max(12,min(int(width_px)*.0112,15))
    try:font=ImageFont.truetype(str(font_path),round(font_px*scale))
    except OSError:font=ImageFont.load_default()
    red=(133,32,32);column=width*.25;center_start=width*.125;center_step=width*.375
    def bezier(start,control1,control2,end,steps=12):
        points=[]
        for step in range(1,steps+1):
            t=step/steps;u=1-t
            points.append((u**3*start[0]+3*u**2*t*control1[0]+3*u*t**2*control2[0]+t**3*end[0],
                           u**3*start[1]+3*u**2*t*control1[1]+3*u*t**2*control2[1]+t**3*end[1]))
        return points
    # Use token-based wrapping so long address lines never cross a divider.
    for index,address in enumerate((addresses or [])[:3]):
        center=round(center_start+index*center_step)
        left=round(center-column/2);right=round(center+column/2)
        max_width=right-left-44*scale
        lines=[]
        for source_line in str(address).replace('\\n','\n').splitlines():
            words=source_line.split();current=''
            for word in words:
                if draw.textbbox((0,0),word,font=font)[2] > max_width:
                    if current:lines.append(current);current=''
                    fragment=''
                    for character in word:
                        candidate=fragment+character
                        if fragment and draw.textbbox((0,0),candidate,font=font)[2] > max_width:
                            lines.append(fragment);fragment=character
                        else:fragment=candidate
                    current=fragment
                    continue
                candidate=(current+' '+word).strip()
                if current and draw.textbbox((0,0),candidate,font=font)[2] > max_width:
                    lines.append(current);current=word
                else:current=candidate
            lines.append(current)
        # Match the browser SVG pin and its 27 x 31 CSS-pixel size.
        pin_y=20*scale;pin_scale_x=27*scale/36;pin_scale_y=31*scale/42;pin_left=center-18*pin_scale_x
        def pin_point(x,y):return pin_left+x*pin_scale_x,pin_y+y*pin_scale_y
        pin=[pin_point(18,1.5)]
        pin+=bezier(pin_point(18,1.5),pin_point(8.9,1.5),pin_point(2,8.4),pin_point(2,17.1))
        pin+=bezier(pin_point(2,17.1),pin_point(2,28.2),pin_point(18,40.5),pin_point(18,40.5))
        pin+=bezier(pin_point(18,40.5),pin_point(18,40.5),pin_point(34,28.2),pin_point(34,17.1))
        pin+=bezier(pin_point(34,17.1),pin_point(34,8.4),pin_point(27.1,1.5),pin_point(18,1.5))
        draw.polygon(pin,fill=red)
        hole_x=6.1*pin_scale_x;hole_y=6.1*pin_scale_y
        hole_cx,hole_cy=pin_point(18,16.8)
        draw.ellipse((hole_cx-hole_x,hole_cy-hole_y,hole_cx+hole_x,hole_cy+hole_y),fill='white')
        line_height=font_px*1.08*scale
        y=pin_y+31*scale+9*scale
        for line in lines:
            box=draw.textbbox((0,0),line,font=font)
            x=center-(box[2]-box[0])//2
            draw.text((x,y),line,font=font,fill=(23,23,23));y+=line_height
    for x in (round(width*.3125),round(width*.6875)):
        divider_top=(8+((140-16-100)/2)+39)*scale;divider_bottom=divider_top+40*scale
        top_x=round(x+math.sin(math.radians(1))*20*scale)
        bottom_x=round(x-math.sin(math.radians(1))*20*scale)
        draw.line((top_x,divider_top,bottom_x,divider_bottom),fill=red,width=3*scale)
        radius=3*scale/2
        draw.ellipse((top_x-radius,divider_top-radius,top_x+radius,divider_top+radius),fill=red)
        draw.ellipse((bottom_x-radius,divider_bottom-radius,bottom_x+radius,divider_bottom+radius),fill=red)
    output=BytesIO();canvas.save(output,format='PNG');output.seek(0)
    return output


def clip_workbook_header(raw):
    """Keep the complete header artwork in the workbook."""
    return raw

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
    if name == 'title':
        return []
    if name not in ('header', 'items', 'bank'):
        return [('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
                ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black),
                ('LINEABOVE',(0,0),(-1,0),.6,colors.black),
                ('LINEBELOW',(0,-1),(-1,-1),.6,colors.black)]
    edges = [('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
             ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black)]
    edges.append(('LINEBELOW',(0,-1),(7 if name == 'items' else -1,-1),.6,colors.black))
    if name == 'header':
        edges.append(('LINEABOVE',(0,0),(-1,0),1.2,colors.black))
    elif name == 'items':
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
    model=merge_export_words(layout(doc));weights=model['widths'];columns=[usable*w/sum(weights) for w in weights]
    def image(name,w):
        data=asset(doc,name)
        with PILImage.open(data) as im:h=w*im.height/im.width
        data.seek(0);return Image(data,width=w,height=h)
    header=image('header.png',usable)
    header_height=header.drawHeight
    def first_page(canvas,document):
        canvas.saveState()
        header.drawOn(canvas,margin,height-margin-header.drawHeight)
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
        alignment=1 if cell.get('center') or cell.get('free') or 'amount' in kind or kind in ('title','head','center') else 0
        style=ParagraphStyle('cell',fontName=bold if is_bold else regular,fontSize=size,
            leading=size+2,alignment=alignment,textColor=colors.red if kind=='warning' else colors.black)
        if 'amount' in kind and not cell.get('free'):
            amount=format(Decimal(cell['text']),',.2f')
            return Paragraph(escape(symbol+' '+amount),style)
        if 'uom' in cell:text+=' '+cell['uom']
        content=escape(text).replace('\n','<br/>')
        if kind in ('terms','final_term') and RETURN_POLICY_LABEL in text:
            content=content.replace(RETURN_POLICY_LABEL, f'<link href="{RETURN_POLICY_URL}" color="#0563C1">{RETURN_POLICY_LABEL}</link>')
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
                if section['name']!='title' and not cell.get('open_left'):commands.append(('LINEBEFORE',(col,index),(col,index),1.2 if col==0 else .6,colors.black))
                if section['name']!='title' and not cell.get('open_right'):commands.append(('LINEAFTER',(col+span-1,index),(col+span-1,index),1.2 if col+span==11 else .6,colors.black))
                if kind=='warning':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.yellow))
                if kind=='final_term':commands.append(('BACKGROUND',(col,index),(col+span-1,index),colors.HexColor('#FFF2CC')))
                if section['name']!='title' and cell.get('line_top'):commands.append(('LINEABOVE',(col,index),(col+span-1,index),.6,colors.black))
                if section['name']!='title' and cell.get('line_bottom'):commands.append(('LINEBELOW',(col,index),(col+span-1,index),.6,colors.black))
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
    footer_rows=[[image('payment_options.jpg',usable*.43),image('signature.png',usable*.43)]]
    if model['shipping_notice']:
        footer_rows.append([Paragraph(escape(model['shipping_notice']),ParagraphStyle(
            'shipping_notice',fontName=bold,fontSize=10,leading=13,
            textColor=colors.red)),''])
    footer_block=Table(footer_rows,colWidths=[usable*.5]*2,splitByRow=0,hAlign='LEFT')
    footer_block.setStyle(TableStyle([
        *([('SPAN',(0,1),(1,1)),('BACKGROUND',(0,1),(-1,1),colors.yellow)]
          if model['shipping_notice'] else []),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LINEBEFORE',(0,0),(0,-1),1.2,colors.black),
        ('LINEAFTER',(-1,0),(-1,-1),1.2,colors.black),
        ('LINEABOVE',(0,0),(-1,0),.6,colors.black),
        ('LINEBELOW',(0,-1),(-1,-1),1.2,colors.black),
        *([('LINEABOVE',(0,1),(-1,1),.6,colors.black)] if model['shipping_notice'] else [])]))
    story.append(footer_block)
    story.append(Spacer(1, 6))
    story.append(office_address_pdf(model['office_addresses'], usable))
    story.append(Spacer(1, 8))
    legal_style=ParagraphStyle('legal_notice',fontName=regular,fontSize=8,leading=10,
        alignment=1,textColor=colors.HexColor('#333333'))
    story.append(legal_notice_pdf(model['legal_notice'],usable,legal_style))
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
    sheet.ignore_errors({'number_stored_as_text':'A1:K1048576'})
    sheet.set_paper(9);sheet.set_portrait();sheet.fit_to_pages(1,1 if len(doc['totals']['lines'])<=4 else 0);sheet.set_margins(.47,.47,.47,.47)
    model=merge_export_words(layout(doc))
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
        if 'amount' in kind:values.update(align='center',num_format='"'+symbol+'" #,##0.00')
        format_values[kind]=values
        formats[kind]=book.add_format(values)
    required_format=book.add_format({'font_color':'#dc2626'})
    def image(name,row,col,w,h):
        data=asset(doc,name)
        with PILImage.open(data) as im:
            scale=w/im.width if name=='header.png' else min(w/im.width,h/im.height)
            dpi=im.info.get('dpi',(96,96))
        data.seek(0);sheet.insert_image(row,col,name,{'image_data':data,'x_scale':scale*dpi[0]/96,'y_scale':scale*dpi[1]/96,'object_position':1})
    def office_address_image(row):
        data=office_address_png(model['office_addresses'],sum(int(width*7+5) for width in model['widths']))
        with PILImage.open(data) as address_image:
            row_height=address_image.height*.375/5
        data.seek(0)
        sheet.insert_image(row,0,'office-addresses.png',{'image_data':data,'x_scale':.5,'y_scale':.5,'object_position':1})
        return row_height
    for row in range(7):sheet.set_row(row,24)
    image('header.png',0,0,950,125)
    row_index=7
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
                chars=max(4,int(sum(model['widths'][cell['col']:cell['col']+cell['span']])*1.1))
                wrapped=[part for line in value.split('\n') for part in
                         (([line] if cell.get('aria')=='Proforma Invoice Date' or
                           value=='Proforma Invoice Date:' else textwrap.wrap(line,chars)) or [''])]
                chunks.append([wrapped[offset:offset+20] for offset in range(0,len(wrapped),20)])
            for chunk_index in range(max(map(len,chunks))):
                height=16 if section['name']=='header' else 18
                for cell,parts in zip(row,chunks):
                    lines=parts[chunk_index] if chunk_index<len(parts) else ['']
                    value='\n'.join(lines);col=cell['col'];end=col+cell['span']-1
                    top=(section['name']!='title' and ((index==0 and chunk_index==0 and not (section['name']=='bank' and col>=8)) or (section['name']=='bank' and index==len(section['rows'])-1 and chunk_index==0)
                         or (cell.get('line_top') and chunk_index==0)))
                    bottom=(section['name']!='title' and ((index==len(section['rows'])-1 and chunk_index==max(map(len,chunks))-1 and not (section['name']=='items' and col>=8)) or cell['style']=='head'
                            or (cell.get('line_bottom') and chunk_index==len(parts)-1)))
                    left=0 if section['name']=='title' or cell.get('open_left') else 2 if col==0 else 1
                    right=0 if section['name']=='title' or cell.get('open_right') else 2 if end==10 else 1
                    center_money='amount' in cell['style']
                    center_cell=bool(cell.get('center') or cell.get('free'))
                    key=(cell['style'],top,bottom,left,right,cell.get('bottom_aligned',False),center_money,center_cell)
                    if key not in formats:
                        style_values={**format_values[cell['style']],'top':(2 if section['name']=='header' and index==0 else 1) if top else 0,'bottom':1 if bottom else 0,
                            'left':left,'right':right}
                        if center_money:
                            style_values.update(align='center',num_format='"'+symbol+'" #,##0.00')
                        if center_cell:style_values['align']='center'
                        formats[key]=book.add_format({**style_values,
                            'valign':'bottom' if cell.get('bottom_aligned') else 'top'})
                    fmt=formats[key]
                    path=cell.get('calculated') or cell.get('field')
                    if chunk_index==0 and path:coordinates[path]=xl_rowcol_to_cell(row_index,col)
                    quantity=(cell.get('field') or '').endswith('.quantity')
                    if quantity:
                        fmt=book.add_format({**format_values[cell['style']],'num_format':'0 "'+cell.get('uom','PCs')+'"','top':(2 if section['name']=='header' and index==0 else 1) if top else 0,'bottom':1 if bottom else 0,'left':left,'right':right})
                    number=(cell.get('numeric') or cell['field'] in ('shipping_charges','bank_charges') or quantity or (cell['field'] or '').endswith('.unit_price')) and chunk_index==0 and not cell.get('free')
                    if cell['span']>1:sheet.merge_range(row_index,col,row_index,end,'',fmt)
                    if number:
                        decimal=Decimal(cell['text'])
                        if len(decimal.as_tuple().digits)<=15:sheet.write_number(row_index,col,float(decimal),fmt)
                        else:sheet.write_string(row_index,col,symbol+' '+cell['text'],fmt)
                    elif cell.get('party') and cell.get('field')=='delivery.consignee_text':
                        rich_required(sheet,row_index,col,value,fmt,required_format)
                    elif cell['style'] in ('terms','final_term') and RETURN_POLICY_LABEL in value:
                        link_fmt=book.add_format({**style_values,'font_color':'#0563C1','underline':0})
                        sheet.write_url(row_index,col,RETURN_POLICY_URL,link_fmt,value)
                    elif section['name']=='items' and col==0 and value.isdecimal():sheet.write_number(row_index,col,int(value),fmt)
                    else:sheet.write_string(row_index,col,value,fmt)
                    if chunk_index==0 and (cell.get('calculated') in ('goods_total','subtotal','tax','grand_total') or (cell.get('calculated') or '').endswith('.line_total')):
                        formula_cells.append((row_index,col,fmt,cell['calculated'],cell['text']))
                    height=max(height,len(lines)*(13 if cell['style'] in ('terms','final_term') else 16)+3)
                    if cell.get('header_metadata'):height=max(height,len(lines)*16+2)
                if section['name']=='parties' and index==1:height=max(height,45)
                if section['name']=='parties' and index==3:height=max(height,40)
                if section['name']=='items' and index>0:
                    height=max(height,(22 if index==1 else 63 if index==2 else 18) if len(doc['totals']['lines'])==1 else 36 if len(doc['totals']['lines'])<=4 else 18)
                if section['name']=='title':height=max(height,32)
                sheet.set_row(row_index,min(409,height));row_index+=1
    footer_start=row_index
    image('payment_options.jpg',footer_start,0,440,90);image('signature.png',footer_start,5,440,90)
    for offset in range(4):
        row=footer_start+offset;top=offset==0;bottom_edge=(1 if model['shipping_notice'] else 2) if offset==3 else 0
        left=book.add_format({'left':2,'top':1 if top else 0,'bottom':bottom_edge,'border_color':'#000000'})
        right=book.add_format({'right':2,'top':1 if top else 0,'bottom':bottom_edge,'border_color':'#000000'})
        edge=book.add_format({'top':1 if top else 0,'bottom':bottom_edge,'border_color':'#000000'})
        sheet.set_row(row,20)
        for col in range(11):sheet.write_blank(row,col,None,left if col==0 else right if col==10 else edge)
    row_index=footer_start+4
    if model['shipping_notice']:
        notice_format=book.add_format({'font_name':'Cambria','font_size':10,'bold':True,
            'font_color':'#FF0000','bg_color':'#FFFF00','text_wrap':True,'valign':'vcenter',
            'left':2,'right':2,'top':1,'bottom':2,'border_color':'#000000'})
        sheet.merge_range(row_index,0,row_index,10,model['shipping_notice'],notice_format);sheet.set_row(row_index,36);row_index+=1
    address_row=row_index
    row_height=office_address_image(address_row)
    for offset in range(5):sheet.set_row(address_row+offset,row_height)
    row_index=address_row+5
    legal_format=book.add_format({'font_name':'Cambria','font_size':8,'align':'center','valign':'vcenter','text_wrap':True})
    sheet.merge_range(row_index,0,row_index,10,model['legal_notice'],legal_format)
    sheet.set_row(row_index,28)
    sheet.print_area(0,0,row_index,10);sheet.set_footer('&CPage &P of &N')
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
        elif path=='tax':formula=f'=ROUND(({coordinates["subtotal"]}+N({coordinates["shipping_charges"]})+{coordinates.get("bank_charges","0")})*{doc["totals"]["tax_rate"]},2)'
        else:formula=f'=ROUND({coordinates["subtotal"]}+N({coordinates["shipping_charges"]})+{coordinates.get("bank_charges","0")}+{coordinates.get("tax","0")},2)'
        sheet.write_formula(row,col,formula,fmt,float(Decimal(cached)))
    book.set_calc_mode('auto')
    book.close();return clip_workbook_header(output.getvalue())
