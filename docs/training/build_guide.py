#!/usr/bin/env python3
"""Build learning artwork and PDF, retaining the reviewed Billing illustration.

Maintainer-only tool. No accelerator runtime imports, network requests or execution.
The deliberate Markdown subset fails on unsupported block markup.
"""
from __future__ import annotations

import argparse
import html
import io
import re
from pathlib import Path
from urllib.parse import quote, urlparse

from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, XPreformatted,
)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
FILES = sorted(ROOT.glob("0[1-6]-*.md"))
REVISION = "fcec34fb8e83bf7b663ab5ed0e1e945224dd03fd"
DOC_DATE = "October 28, 2026"
GITHUB = "https://github.com/exploreomni/Data-Model-Accelerator/blob/"
PINK, DEEP, INK, WHITE = "#FF5FA2", "#4D122C", "#220411", "#FCFCF7"
FONT_FILES = {"Cal": "CalSans-Latin-400.ttf", "Body": "IBMPlexSans-Latin-400.ttf",
              "Medium": "IBMPlexSans-Latin-500.ttf", "Mono": "IBMPlexMono-Latin-500.ttf"}
ARTWORK = {}
WIDTH = 504


def font(size, face="Body"):
    return ImageFont.truetype(str(FONTS / FONT_FILES[face]), size)


def drawing(height, title, subtitle):
    im = PILImage.new("RGB", (1600, height), WHITE)
    d = ImageDraw.Draw(im)
    d.text((48, 36), title, font=font(66, "Cal"), fill=INK)
    d.text((48, 124), subtitle, font=font(33), fill=DEEP)
    return im, d


def card(d, box, title, lines, dark=False, pink=False, mono=False):
    x, y, r, b = box
    fill = DEEP if dark else PINK if pink else WHITE
    fg = WHITE if dark else INK
    d.rounded_rectangle(box, radius=24, fill=fill, outline=None if dark or pink else DEEP, width=3)
    d.text((x + 24, y + 20), title, fill=fg, font=font(28, "Mono"))
    for n, line in enumerate(lines):
        d.text((x + 24, y + 64 + n * 42), line, fill=fg, font=font(29 if mono else 34, "Mono" if mono else "Medium"))


def arrow(d, points, fill=DEEP, width=5):
    d.line(points, fill=fill, width=width, joint="curve")
    x, y = points[-1]
    px, py = points[-2]
    if x == px:
        direction = 1 if y > py else -1
        triangle = [(x, y), (x-11, y-18*direction), (x+11, y-18*direction)]
    else:
        direction = 1 if x > px else -1
        triangle = [(x, y), (x-18*direction, y-11), (x-18*direction, y+11)]
    d.polygon(triangle, fill=fill)


def store_image(name, image):
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    ARTWORK["assets/" + name] = out.getvalue()


def make_artwork():
    im, d = drawing(1040, "One migration. Complete domains.", "Inventory the whole scope, then deliver one business area at a time.")
    xs = [48, 570, 1092]
    titles = [("01 / INVENTORY", ["Sources, reports", "and shared rules"]),
              ("02 / CHOOSE", ["Select a complete", "business domain"]),
              ("03 / DESIGN", ["Tables, meanings", "and relationships"]),
              ("06 / VALIDATE", ["Compare results;", "authorize release"]),
              ("05 / GENERATE", ["Warehouse code", "and Omni files"]),
              ("04 / REVIEW", ["Resolve questions;", "approve the design"])]
    for i, (title, lines) in enumerate(titles):
        x, y = xs[i % 3], 226 if i < 3 else 558
        card(d, (x, y, x + 460, y + 206), title, lines, dark=i == 5, pink=i == 1)
    arrow(d, [(508,329),(566,329)])
    arrow(d, [(1030,329),(1088,329)])
    arrow(d, [(1322,432),(1322,554)])
    arrow(d, [(1092,661),(1034,661)])
    arrow(d, [(570,661),(512,661)])
    d.rounded_rectangle((48, 830, 1552, 970), radius=24, fill=PINK)
    d.text((80,855), "Continue to the next domain with saved progress.", font=font(38,"Medium"), fill=INK)
    d.text((80,911), "A domain supports many reports, metrics and business questions.", font=font(32), fill=INK)
    store_image("workflow.png", im)

    # Reviewed source illustration: preserve the topic composition rather than
    # regenerating the previous single-view pipeline during a PDF rebuild.
    ARTWORK["assets/billing-pipeline.png"] = (ASSETS / "billing-pipeline.png").read_bytes()

    im, d = drawing(870, "Know where to look", "An illustrated reading map for your delivery's START_HERE.html")
    cards = [("01 / DATA MODEL", ["Meaning and grain", "Columns, keys, joins", "New or reused work"]),
             ("02 / CODE & FILES", ["Selected deliverables", "Warehouse + Omni", "Setup instructions"]),
             ("03 / VALIDATION", ["Checks that ran", "Results and evidence", "What is still missing"])]
    for i, (title, lines) in enumerate(cards):
        x=48+i*522
        card(d,(x,226,x+460,515),title,lines,dark=i==0,pink=i==1)
    d.rounded_rectangle((48,578,1552,790),radius=24,fill=DEEP)
    d.text((82,608), "Return one clear correction", font=font(46,"Cal"),fill=WHITE)
    d.text((82,676), "Name the table, explain the issue and provide the intended rule.", font=font(34),fill=WHITE)
    d.text((82,728), "Send feedback to the agent or the person who shared the package.", font=font(32),fill=WHITE)
    store_image("review-route.png", im)


def destination(target):
    if urlparse(target).scheme in {"https", "http"}:
        return target
    path, _, fragment = target.partition("#")
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(REPO):
        raise ValueError(f"Link escapes repository: {target}")
    if not resolved.exists():
        raise ValueError(f"Missing linked file: {target}")
    if resolved in FILES and not fragment:
        return "#" + resolved.stem
    if resolved == ROOT / "README.md" and not fragment:
        return "#contents"
    revision = "atx/self-guided-training" if resolved.is_relative_to(ROOT) else REVISION
    return GITHUB + revision + "/" + quote(resolved.relative_to(REPO).as_posix()) + ("#" + fragment if fragment else "")


INLINE = re.compile(r"`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*")


def inline(text):
    parts, start = [], 0
    for m in INLINE.finditer(text):
        parts.append(html.escape(text[start:m.start()]))
        if m[1] is not None:
            parts.append('<font name="Mono" size="9">'+html.escape(m[1])+'</font>')
        elif m[2] is not None:
            parts.append('<a href="'+html.escape(destination(m[3]), quote=True)+'" color="'+DEEP+'"><u>'+inline(m[2])+'</u></a>')
        elif m[4] is not None:
            parts.append('<b>'+inline(m[4])+'</b>')
        else:
            parts.append(inline(m[5]))  # Caption emphasis uses spacing/color, not a faux italic font.
        start=m.end()
    return ''.join(parts)+html.escape(text[start:])


def styles():
    for name, filename in FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, str(FONTS/filename)))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Medium", italic="Body", boldItalic="Medium")
    base=dict(fontName="Body", fontSize=10.5, leading=14, textColor=colors.HexColor(INK), spaceAfter=6, bulletFontName="Body")
    result={"body":ParagraphStyle("body", **base)}
    def add(name, **kw):
        result[name]=ParagraphStyle(name,parent=result["body"],**kw)
    add("h1",fontName="Cal",fontSize=27,leading=29,spaceAfter=20,keepWithNext=True)
    add("h2",fontName="Medium",fontSize=16,leading=19,spaceBefore=10,spaceAfter=6,keepWithNext=True)
    add("h3",fontName="Medium",fontSize=12.5,leading=16,spaceBefore=10,spaceAfter=6,keepWithNext=True)
    add("cell",fontSize=10,leading=13,spaceAfter=0)
    add("headcell",fontName="Medium",fontSize=10,leading=13,spaceAfter=0,textColor=colors.HexColor(WHITE))
    add("caption",fontSize=9,leading=12,textColor=colors.HexColor(DEEP),spaceAfter=12)
    add("code",fontName="Mono",fontSize=8.4,leading=11.5,spaceBefore=0,spaceAfter=0)
    add("quote",leftIndent=14,rightIndent=12,spaceBefore=4,spaceAfter=12,borderPadding=8)
    add("cover",fontName="Cal",fontSize=40,leading=42,spaceAfter=24)
    add("sub",fontSize=17,leading=23,spaceAfter=22)
    add("label",fontName="Mono",fontSize=9,leading=13,spaceAfter=10)
    return result


def parse_lesson(path, st):
    lines=path.read_text().splitlines()
    result=[]
    i=0
    while i<len(lines):
        s=lines[i].strip()
        if not s or (s.startswith("[Learning") and " · " in s):
            i+=1; continue
        if s.startswith("# "):
            heading=Paragraph(inline(s[2:]),st["h1"])
            heading.bookmark=path.stem
            result.append(heading);i+=1;continue
        if s.startswith("## ") or s.startswith("### "):
            level=3 if s.startswith("###") else 2
            result.append(Paragraph(inline(s[level+1:]),st["h"+str(level)]));i+=1;continue
        if s.startswith("```"):
            code=[];i+=1
            while i<len(lines) and not lines[i].startswith("```"):
                code.append(lines[i]);i+=1
            if i==len(lines):raise ValueError(f"Unclosed code fence: {path}")
            for line in code:
                if pdfmetrics.stringWidth(line,"Mono",8.4)>WIDTH-22:
                    raise ValueError(f"Wrap code line for print in {path.name}: {line}")
            panel=Table([[XPreformatted(html.escape('\n'.join(code)),st["code"])]],colWidths=[WIDTH],hAlign="LEFT")
            panel.setStyle(TableStyle([("BOX",(0,0),(-1,-1),.6,colors.HexColor(DEEP)),
                ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),
                ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
            result.extend([panel,Spacer(1,10)]);i+=1;continue
        if s.startswith("!["):
            m=re.fullmatch(r"!\[([^\]]+)\]\(([^)]+)\)",s)
            if not m or m[2] not in ARTWORK:raise ValueError(f"Unknown illustration: {s}")
            image=PILImage.open(io.BytesIO(ARTWORK[m[2]]))
            result.append(Image(io.BytesIO(ARTWORK[m[2]]),width=WIDTH,height=WIDTH*image.height/image.width))
            result.append(Spacer(1,8));i+=1;continue
        if s.startswith("|"):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith("|"):
                cells=[x.strip() for x in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r":?-+:?",c) for c in cells):rows.append(cells)
                i+=1
            n=len(rows[0])
            if any(len(row)!=n for row in rows):raise ValueError(f"Uneven table: {path}")
            widths={2:[190,314],3:[155,180,169],4:[100,162,120,122]}[n]
            data=[[Paragraph(inline(c),st["headcell" if r==0 else "cell"]) for c in row] for r,row in enumerate(rows)]
            table=Table(data,colWidths=widths,repeatRows=1,hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor(DEEP)),
                ("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),7),
                ("BOTTOMPADDING",(0,0),(-1,-1),7),("LEFTPADDING",(0,0),(-1,-1),10),
                ("RIGHTPADDING",(0,0),(-1,-1),10),
                ("LINEBELOW",(0,1),(-1,-1),.35,colors.HexColor(DEEP))]))
            result.extend([table,Spacer(1,12)]);continue
        if s.startswith("<") or s.startswith("#"):
            raise ValueError(f"Unsupported Markdown block: {path.name}: {s}")
        bullet=re.match(r"^(?:- |(\d+)\. )(.+)",s)
        if bullet:
            label=(bullet[1]+".") if bullet[1] else "•"
            result.append(Paragraph(inline(bullet[2]),st["body"],bulletText=label));i+=1;continue
        if s.startswith("> "):
            result.append(KeepTogether([Paragraph(inline(s[2:]),st["quote"])]));i+=1;continue
        text=[s];i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r"^(#|\||```|!\[|> |- |\d+\. )",lines[i].strip()):
            text.append(lines[i].strip());i+=1
        caption=s.startswith("*") and not s.startswith("**")
        result.append(Paragraph(inline(' '.join(text)),st["caption" if caption else "body"]))
    return result


class Guide(BaseDocTemplate):
    def afterFlowable(self, item):
        if hasattr(item,"bookmark"):
            self.canv.bookmarkPage(item.bookmark)
            self.canv.addOutlineEntry(item.getPlainText(),item.bookmark,level=0)


def draw_page(canvas, doc):
    canvas.setFillColor(colors.HexColor(WHITE));canvas.rect(0,0,612,792,fill=1,stroke=0)
    if doc.page==1:
        canvas.setFillColor(colors.HexColor(PINK));canvas.rect(0,594,612,198,fill=1,stroke=0)
        canvas.drawImage(str(ASSETS/"omni-wordmark.png"),54,682,width=106,height=106*223/539,mask="auto")
    else:
        canvas.setFont("Mono",8);canvas.setFillColor(colors.HexColor(DEEP))
        canvas.drawString(54,757,"DATA MODEL ACCELERATOR / LEARNING GUIDE")
    canvas.setFont("Mono",8);canvas.setFillColor(colors.HexColor(DEEP))
    canvas.drawString(54,29,"DRAFT · SE/AE review required before customer use")
    canvas.drawRightString(558,29,str(doc.page))


def build_pdf():
    if len(FILES)!=6:raise ValueError("Expected exactly six numbered lessons")
    st=styles();rl_config.invariant=1
    out=io.BytesIO()
    doc=Guide(out,pagesize=letter,leftMargin=54,rightMargin=54,topMargin=64,bottomMargin=55,
              title="Data Model Accelerator — Learning Guide",author="Omni",pageCompression=1)
    doc.addPageTemplates(PageTemplate(id="learning",frames=[Frame(54,55,504,673,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=draw_page))
    story=[Spacer(1,156),Paragraph("Turn scattered reporting<br/>into shared data models.",st["cover"]),
           Paragraph("Your self-guided introduction to the<br/>Data Model Accelerator",st["sub"]),
           Spacer(1,14),Paragraph("Plan the whole migration.<br/>Deliver complete business domains.",st["h2"]),
           Paragraph("Learn what the tool does, explore a fictional Billing domain, review a delivery, and install it in your approved assistant.",st["body"]),
           Spacer(1,22),Paragraph("DRAFT — requires explicit SE/AE review before sending to customer.",st["label"]),
           Paragraph("Documentation checked "+DOC_DATE+"<br/>Workflow baseline "+REVISION[:7]+" · Six lessons · Synthetic examples",st["caption"]),PageBreak()]
    title=Paragraph("Choose your starting point",st["h1"]);title.bookmark="contents";story.append(title)
    story.append(Paragraph("Read the lessons in order, or jump to the task in front of you. You can learn and review a delivery before installing anything.",st["body"]))
    for f in FILES:
        name=f.read_text().splitlines()[0][2:]
        story.extend([Paragraph('<a href="#'+f.stem+'" color="'+DEEP+'"><u>'+html.escape(name)+'</u></a>',st["h2"]),Spacer(1,5)])
    story.extend([Spacer(1,10),Paragraph("Have a delivery ZIP? Start with lesson 4. Already installed? Verify the selected copy in lesson 5, then launch in lesson 6.",st["body"]),
        Paragraph("These six lessons match the editable Markdown guide in the repository. Underlined references open source files or official documentation. The optional commerce practice is a separate, smaller review exercise.",st["body"]),
        Paragraph("Illustrations explain the workflow; they are not UI screenshots. Synthetic files and local checks do not establish native-host, warehouse or business acceptance.",st["caption"])])
    for f in FILES:
        story.append(PageBreak());story.extend(parse_lesson(f,st))
    doc.build(story)
    return out.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",help="Fail if generated assets or PDF differ; write nothing.")
    args=parser.parse_args()
    make_artwork()
    generated={**ARTWORK,"data-model-accelerator-guide.pdf":build_pdf()}
    for name,data in generated.items():
        path=ROOT/name
        if args.check:
            if not path.exists() or path.read_bytes()!=data:
                raise SystemExit(f"Outdated training artifact: {name}; rebuild and visually review.")
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    print(("Verified" if args.check else "Built")+" two drawn illustrations and the PDF with the checked-in Billing illustration.")


if __name__=="__main__":
    main()
