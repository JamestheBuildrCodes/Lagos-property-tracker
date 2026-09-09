"""Build the three client-facing intelligence layers from one normalized snapshot.

Layer 1: concise executive HTML email.
Layer 2: polished XLSX mirrored into the existing Google Sheet.
Layer 3: concise analyst DOCX; docs_writer.py can publish the same content to Google Docs.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from market_analysis import build_summary, fmt_naira, load_csv

TODAY=datetime.now(timezone.utc).strftime("%Y-%m-%d")

def esc(v):
    return (str(v if v is not None else "").replace("&","&amp;").replace("<","&lt;")
            .replace(">","&gt;").replace('"',"&quot;"))

def _load_inputs(listings_path,changes_path="none",research_path=None):
    listings=load_csv(listings_path)
    changes=load_csv(changes_path) if changes_path and changes_path.lower()!="none" and os.path.exists(changes_path) else []
    research=load_csv(research_path) if research_path and research_path.lower()!="none" and os.path.exists(research_path) else []
    summary=build_summary(listings,changes,listings_path)
    research_sources={"Estate Intel"} if research else set()
    if research_sources:
        summary["sources"]=len(set(summary.get("source_names",[])) | research_sources)
        summary["source_names"]=sorted(set(summary.get("source_names",[])) | research_sources)
    return listings,changes,research,summary

def _wow_text(metric):
    p=metric.get("pct_change")
    if p is None:return "No prior snapshot"
    if p>0:return f"↑ {p:.1f}%"
    if p<0:return f"↓ {abs(p):.1f}%"
    return "→ 0.0%"

def build_executive_html_from_summary(s,date=None):
    date=date or datetime.now(timezone.utc).strftime("%d %b %Y")
    h=["""<!doctype html><html><body style="font-family:Arial,sans-serif;color:#172033;line-height:1.5;max-width:760px;margin:auto">"""]
    h.append(f"<div style='padding:24px;background:#0d2340;color:white'><div style='font-size:12px;letter-spacing:1.5px'>MASTER BUILDER • MARKET INTELLIGENCE</div><h1 style='margin:8px 0'>Lagos Property Market — Weekly Intelligence Brief</h1><div>{esc(date)}</div></div>")
    h.append("<h2>Market snapshot</h2><table style='width:100%;border-collapse:collapse'>")
    h.append("<tr style='background:#e8eef5'><th align='left' style='padding:9px'>Metric</th><th align='left' style='padding:9px'>Current</th><th align='left' style='padding:9px'>WoW</th></tr>")
    wow=s.get("week_on_week",{})
    metric_map=[("Listings tracked","listings",s["listings_tracked"]),
                ("Areas monitored",None,s["areas_monitored"]),("Sources",None,s["sources"]),
                ("New listings",None,s["changes"]["new_listings"]),("Price reductions",None,s["changes"]["price_reductions"]),
                ("Price increases",None,s["changes"]["price_increases"]),
                ("Median apartment sale", "sale",fmt_naira(s["median_apartment_sale"])),
                ("Median annual rent","rent",fmt_naira(s["median_annual_rent"])),
                ("Median land ₦/sqm","land_ppsqm",fmt_naira(s["median_land_ppsqm"]))]
    for label,key,current in metric_map:
        w=_wow_text(wow.get("metrics",{}).get(key,{})) if key and wow.get("available") else "—"
        h.append(f"<tr><td style='padding:8px;border-bottom:1px solid #ddd'>{esc(label)}</td><td style='padding:8px;border-bottom:1px solid #ddd'><b>{esc(current)}</b></td><td style='padding:8px;border-bottom:1px solid #ddd'>{esc(w)}</td></tr>")
    h.append("</table>")
    h.append("<h2>What changed this week?</h2>")
    notes=s.get("analysis_notes",[])
    for n in notes[:5]: h.append(f"<p>{esc(n)}</p>")
    h.append("<h2>Decision signals</h2><ul>")
    sig=s["signals"]
    pairs=[("Most expensive",sig.get("most_expensive")),("Rental / investment screen",sig.get("investment")),
           ("Best buyer value screen",sig.get("buyer_value")),("Lowest observed land ₦/sqm",sig.get("land_opportunity"))]
    for label,obj in pairs:
        h.append(f"<li><b>{esc(label)}:</b> {esc(obj['market_node'] if obj else 'N/A')}</li>")
    monitors=", ".join(x["market_node"] for x in sig.get("monitoring",[])) or "N/A"
    h.append(f"<li><b>Watch closely:</b> {esc(monitors)}</li></ul>")
    h.append("<h2>Why it matters</h2>")
    if wow.get("available"):
        h.append("<p>The week-on-week view shows whether the market is moving, while the area scorecard shows where the movement and relative pricing are concentrated. Use the Sheet for the underlying comparables and the analyst report for context.</p>")
    else:
        h.append("<p>This is the first comparable snapshot available to the reporting layer. Future weekly runs will establish the week-on-week baseline.</p>")
    h.append("<p style='font-size:12px;color:#667085;border-top:1px solid #ddd;padding-top:12px'>Data is based on current asking prices from Nigeria Property Centre and PropertyPro Nigeria. Asking prices are not confirmed closed transactions. Estate Intel is public research only; premium/login-gated data is never collected or bypassed.</p></body></html>")
    return "".join(h)

def build_executive_html(listings_path,changes_path="none"):
    return build_executive_html_from_summary(_load_inputs(listings_path,changes_path)[-1])

def _xlsx_lib():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment,Border,Side
        from openpyxl.utils import get_column_letter
        from openpyxl.formatting.rule import CellIsRule
        return Workbook,Font,PatternFill,Alignment,Border,Side,get_column_letter,CellIsRule
    except ImportError as exc: raise RuntimeError("XLSX reporting requires openpyxl.") from exc

def build_xlsx_from_data(listings,changes,research,s,output=None):
    Workbook,Font,PatternFill,Alignment,Border,Side,get_column_letter,CellIsRule=_xlsx_lib()
    output=output or f"market_intelligence_{TODAY}.xlsx"
    wb=Workbook()
    navy="0D2340"; light="E8EEF5"; pale="F6F8FB"; green="E7F6EC"; red="FDECEC"; grey="667085"
    thin=Side(style="thin",color="D9E1EA")
    def title(sheet,text):
        sheet.merge_cells(start_row=1,start_column=1,end_row=1,end_column=3)
        c=sheet.cell(1,1,text); c.font=Font(size=16,bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor=navy); c.alignment=Alignment(vertical="center")
        sheet.row_dimensions[1].height=30
    def headers(sheet,row=3):
        for c in sheet[row]:
            c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor=navy); c.alignment=Alignment(wrap_text=True,vertical="center")
            c.border=Border(bottom=thin)
        sheet.freeze_panes=f"A{row+1}"
    def polish(sheet,start=1):
        for col in sheet.columns:
            letter=get_column_letter(col[0].column)
            maxlen=max((len(str(c.value or "")) for c in col),default=0)
            sheet.column_dimensions[letter].width=min(max(maxlen+2,12),38)
        for row in sheet.iter_rows(min_row=start):
            for c in row:
                c.alignment=Alignment(vertical="top",wrap_text=True)
        sheet.sheet_view.showGridLines=False
    ws=wb.active; ws.title="Executive Summary"
    title(ws,"Lagos Property Market — Weekly Intelligence Brief")
    ws["A2"]=datetime.now(timezone.utc).strftime("%d %B %Y"); ws["A2"].font=Font(italic=True,color=grey)
    ws.append(["Metric","Current","Week-on-week"])
    rows=[("Listings tracked",s["listings_tracked"],"listings"),("Areas monitored",s["areas_monitored"],None),("Sources",s["sources"],None),
          ("New listings",s["changes"]["new_listings"],None),("Price reductions",s["changes"]["price_reductions"],None),("Price increases",s["changes"]["price_increases"],None),
          ("Median apartment sale",s["median_apartment_sale"],"sale"),("Median annual rent",s["median_annual_rent"],"rent"),("Median land ₦/sqm",s["median_land_ppsqm"],"land_ppsqm")]
    wow=s.get("week_on_week",{})
    for label,val,key in rows:
        w=_wow_text(wow.get("metrics",{}).get(key,{})) if key and wow.get("available") else "—"
        ws.append([label,val,w])
    headers(ws,3)
    ws["A14"]="Decision Signals"; ws["A14"].font=Font(size=13,bold=True,color=navy)
    for label,obj in [("Most expensive",s["signals"].get("most_expensive")),("Rental / investment screen",s["signals"].get("investment")),
                      ("Best buyer value screen",s["signals"].get("buyer_value")),("Lowest observed land ₦/sqm",s["signals"].get("land_opportunity"))]:
        ws.append([label,obj["market_node"] if obj else "N/A",""])
    ws.append(["Watch closely",", ".join(x["market_node"] for x in s["signals"].get("monitoring",[])) or "N/A",""])
    ws.append([]); ws.append(["Market interpretation"]); ws["A20"].font=Font(size=13,bold=True,color=navy)
    for note in s.get("analysis_notes",[]): ws.append([note])
    polish(ws)
    # Scorecard
    ws=wb.create_sheet("Area Scorecard"); ws.append(["Area","Listings","3BR Sale","3BR Rent","Yield Proxy","Sale ₦/sqm","Rent ₦/sqm","Land ₦/sqm","6-mo Sale","6-mo Rent","6-mo Land ₦/sqm","Sale Data","Rent Data","Land Data"])
    for x in s["scorecard"]:
        tr=s.get("trends",{}).get(x["market_node"],{})
        ws.append([x["market_node"],x["listing_count"],x["sale_3br_median"],x["rent_3br_median"],x["gross_rent_yield_proxy_pct"],x["sale_ppsqm_median"],x["rent_ppsqm_median"],x["land_ppsqm_median"],tr.get("sale_pct"),tr.get("rent_pct"),tr.get("land_ppsqm_pct"),x["sale_count"],x["rent_count"],x["land_count"]])
    headers(ws,1); polish(ws)
    # Data tabs
    def add_data(name,data):
        sh=wb.create_sheet(name)
        if data:
            sh.append(list(data[0].keys()))
            for r in data: sh.append([r.get(k) for k in data[0].keys()])
            headers(sh,1)
        else: sh.append(["No data returned"])
        polish(sh)
    add_data("Current Listings",listings); add_data("Weekly Changes",changes); add_data("Estate Intel Public",research)
    ws=wb.create_sheet("Methodology")
    for row in [["Purpose","Decision-ready property market intelligence"],["Approved sources","Nigeria Property Centre; PropertyPro Nigeria; Estate Intel"],
                ["Freshness","Current listing data targeted to 31 days; weekly refresh"],["Coverage","9 nodes: Banana Island, Old Ikoyi, Lekki Phase 1, Victoria Island, Eko Atlantic, Ikeja GRA, Asokoro, Maitama, Wuse"],
                ["Assets","Apartment sales/rentals 1–5BR; residential land; Estate Intel public research"],["Pricing","Asking prices; not confirmed closed transactions"],
                ["Estate Intel","Public research only; premium/login-gated values excluded"],["Transport","NPC direct; PropertyPro and Estate Intel via Zyte browser HTML"],
                ["History","Six-month directional comparison from archived weekly snapshots"],["Decision use","Executive Summary for decisions; Area Scorecard for comparison; Current Listings for audit"]]: ws.append(row)
    headers(ws,1); polish(ws)
    for sh in wb.worksheets:
        sh.auto_filter.ref=sh.dimensions if sh.max_row>1 else None
        for row in sh.iter_rows():
            for c in row:
                if isinstance(c.value,(int,float)) and c.column>1: c.number_format='#,##0.00'
    wb.save(output); return output

def build_xlsx(listings_path,changes_path="none",research_path=None,output=None):
    return build_xlsx_from_data(*_load_inputs(listings_path,changes_path,research_path),output)

def build_docx_from_data(listings,changes,research,s,output=None):
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches,Pt
    except ImportError as exc: raise RuntimeError("DOCX reporting requires python-docx.") from exc
    output=output or f"Lagos_Property_Market_Intelligence_{TODAY}.docx"
    doc=Document(); sec=doc.sections[0]
    sec.top_margin=sec.bottom_margin=Inches(.6); sec.left_margin=sec.right_margin=Inches(.7)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run("LAGOS PROPERTY MARKET\nWEEKLY INTELLIGENCE REPORT"); r.bold=True; r.font.size=Pt(20)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.add_run(datetime.now(timezone.utc).strftime("%d %B %Y")).italic=True
    doc.add_heading("1. Executive Decision Brief",1)
    t=doc.add_table(rows=1,cols=3); t.style="Light Shading Accent 1"
    for i,h in enumerate(["Metric","Current","WoW"]): t.rows[0].cells[i].text=h
    wow=s.get("week_on_week",{})
    for label,val,key in [("Listings tracked",s["listings_tracked"],"listings"),("Areas monitored",s["areas_monitored"],None),("Sources",s["sources"],None),
                          ("New listings",s["changes"]["new_listings"],None),("Price reductions",s["changes"]["price_reductions"],None),("Price increases",s["changes"]["price_increases"],None),
                          ("Median apartment sale",fmt_naira(s["median_apartment_sale"]),"sale"),("Median annual rent",fmt_naira(s["median_annual_rent"]),"rent"),("Median land ₦/sqm",fmt_naira(s["median_land_ppsqm"]),"land_ppsqm")]:
        c=t.add_row().cells; c[0].text=label; c[1].text=str(val); c[2].text=_wow_text(wow.get("metrics",{}).get(key,{})) if key and wow.get("available") else "—"
    doc.add_heading("2. What Happened This Week",1)
    for n in s.get("analysis_notes",[]): doc.add_paragraph(n)
    doc.add_heading("3. Where the Opportunity Is",1)
    sig=s["signals"]
    for label,obj in [("Most expensive",sig.get("most_expensive")),("Strongest rental pricing / yield proxy",sig.get("strongest_rental")),("Best relative value",sig.get("best_relative_value")),("Lowest observed land ₦/sqm",sig.get("land_opportunity"))]:
        doc.add_paragraph(f"{label}: {obj['market_node'] if obj else 'N/A'}",style="List Bullet")
    doc.add_paragraph("Watch closely: "+(", ".join(x["market_node"] for x in sig.get("monitoring",[])) or "N/A"))
    doc.add_heading("4. Sales, Rentals & Land",1)
    for x in [z for z in s["scorecard"] if z["listing_count"]]:
        doc.add_paragraph(f"{x['market_node']}: {x['listing_count']} comparables; 3BR sale {fmt_naira(x['sale_3br_median'])}; 3BR rent {fmt_naira(x['rent_3br_median'])}; sale ₦/sqm {fmt_naira(x['sale_ppsqm_median'])}; land ₦/sqm {fmt_naira(x['land_ppsqm_median'])}.")
    doc.add_heading("5. Six-Month Trend View",1)
    trend_rows=[(n,tr) for n,tr in s.get("trends",{}).items() if any(tr.get(k) is not None for k in ("sale_pct","rent_pct","land_ppsqm_pct"))]
    if trend_rows:
        for n,tr in trend_rows:
            vals=[]
            for key,label in (("sale_pct","sale"),("rent_pct","rent"),("land_ppsqm_pct","land ₦/sqm")):
                if tr.get(key) is not None: vals.append(f"{label} {tr[key]:+.1f}%")
            doc.add_paragraph(f"{n}: "+", ".join(vals),style="List Bullet")
    else: doc.add_paragraph("Trend baseline is being established; future weekly runs will extend the six-month archive.")
    doc.add_heading("6. Recommended Actions",1)
    doc.add_paragraph("Use relative pricing and weekly movement to prioritise negotiations and areas for deeper diligence. Do not treat a thinly sampled area as a definitive market index.")
    doc.add_paragraph("All prices are asking prices. Estate Intel data is limited to public research; no premium or authentication controls are bypassed.")
    doc.save(output); return output

def build_docx(listings_path,changes_path="none",research_path=None,output=None):
    return build_docx_from_data(*_load_inputs(listings_path,changes_path,research_path),output)

def build_bundle(listings_path,changes_path="none",research_path=None):
    listings,changes,research,s=_load_inputs(listings_path,changes_path,research_path)
    html=build_executive_html_from_summary(s); html_path=f"executive_brief_{TODAY}.html"; Path(html_path).write_text(html,encoding="utf-8")
    xlsx=build_xlsx_from_data(listings,changes,research,s); docx=build_docx_from_data(listings,changes,research,s)
    analysis={"generated_at":datetime.now(timezone.utc).isoformat(),"summary":s,"outputs":{"html":html_path,"xlsx":xlsx,"docx":docx}}
    Path("market_intelligence.json").write_text(json.dumps(analysis,indent=2,ensure_ascii=False),encoding="utf-8")
    Path("report_outputs.json").write_text(json.dumps(analysis["outputs"],indent=2),encoding="utf-8")
    return analysis

def main():
    if len(sys.argv)<2: raise SystemExit("Usage: python report_builder.py <listings.csv> [changes.csv] [research.csv]")
    result=build_bundle(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else "none",sys.argv[3] if len(sys.argv)>3 else "none")
    for k,v in result["outputs"].items(): print(f"Created {k}: {v}")

if __name__=="__main__": main()
